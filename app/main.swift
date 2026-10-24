// 网页炉石 · macOS 外壳
//
// 作用：双击即开。启动时拉起内置的 Python 服务、等它就绪、用 WKWebView 显示；
// 关窗即退，同时把服务进程收掉。不需要终端，也不需要手动启停。
//
// 设计取舍：只依赖 Cocoa + WebKit，不引入任何第三方库，也不打包 Python 解释器
// （体积从 60MB+ 降到几百 KB），代价是运行时需要一个可用的 python3。

import Cocoa
import WebKit
import Darwin

// 日志路径可用 HS_APP_LOG 覆盖，方便测试脚本与日常使用分开记录
let LOG_PATH = ProcessInfo.processInfo.environment["HS_APP_LOG"] ?? "/tmp/hearthstone-app.log"

func plog(_ line: String) {
    let stamp = ISO8601DateFormatter().string(from: Date())
    let text = "[\(stamp)] \(line)\n"
    if let fh = FileHandle(forWritingAtPath: LOG_PATH) {
        fh.seekToEndOfFile()
        fh.write(text.data(using: .utf8)!)
        fh.closeFile()
    } else {
        FileManager.default.createFile(atPath: LOG_PATH, contents: text.data(using: .utf8))
    }
}

final class AppDelegate: NSObject, NSApplicationDelegate, WKNavigationDelegate {
    private var window: NSWindow!
    private var web: WKWebView!
    private var server: Process?
    private var port = 8765
    private var gameDir: URL?
    private var quitting = false
    private var restartAttempts = 0

    // MARK: - 生命周期

    func applicationDidFinishLaunching(_ notification: Notification) {
        plog("launch, bundle=\(Bundle.main.bundlePath)")
        buildMenu()
        buildWindow()

        guard let dir = locateGameDir() else {
            showError("找不到游戏文件（serve.py）。\n\n如果移动过工程目录，请重新运行 build_app.sh 打包。")
            return
        }
        gameDir = dir
        plog("game dir = \(dir.path)")

        guard let python = findPython() else {
            showError("没有找到可用的 python3（需要 3.9 或更高）。")
            return
        }
        plog("python = \(python)")

        reapStaleListeners()
        writeLock()
        port = pickPort()
        plog("port = \(port)")
        startServer(python: python, dir: dir)

        // 自测钩子：给自动化测试用，正常使用不会触发
        if let secs = ProcessInfo.processInfo.environment["HS_APP_QUIT_AFTER"],
           let delay = Double(secs) {
            plog("self-test: will quit in \(delay)s")
            DispatchQueue.main.asyncAfter(deadline: .now() + delay) { NSApp.terminate(nil) }
        }
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { true }

    func applicationWillTerminate(_ notification: Notification) {
        stopServer()
        plog("terminated")
    }

    // MARK: - 界面

    private func buildWindow() {
        let rect = NSRect(x: 0, y: 0, width: 1180, height: 820)
        window = NSWindow(contentRect: rect,
                          styleMask: [.titled, .closable, .miniaturizable, .resizable],
                          backing: .buffered, defer: false)
        window.title = "网页炉石"
        window.minSize = NSSize(width: 900, height: 640)
        window.center()
        window.setFrameAutosaveName("MainWindow")

        let config = WKWebViewConfiguration()
        config.preferences.setValue(true, forKey: "developerExtrasEnabled")
        web = WKWebView(frame: rect, configuration: config)
        web.navigationDelegate = self
        web.setValue(false, forKey: "drawsBackground")   // 避免白底闪一下
        window.contentView = web

        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
        loadLoadingPage()
    }

    private func buildMenu() {
        let mainMenu = NSMenu()

        let appItem = NSMenuItem()
        mainMenu.addItem(appItem)
        let appMenu = NSMenu()
        appMenu.addItem(withTitle: "关于网页炉石",
                        action: #selector(NSApplication.orderFrontStandardAboutPanel(_:)),
                        keyEquivalent: "")
        appMenu.addItem(.separator())
        appMenu.addItem(withTitle: "重新加载", action: #selector(reload), keyEquivalent: "r")
        appMenu.addItem(withTitle: "退出", action: #selector(NSApplication.terminate(_:)),
                        keyEquivalent: "q")
        appItem.submenu = appMenu

        let editItem = NSMenuItem()
        mainMenu.addItem(editItem)
        let editMenu = NSMenu(title: "编辑")
        editMenu.addItem(withTitle: "撤销", action: Selector(("undo:")), keyEquivalent: "z")
        editMenu.addItem(withTitle: "重做", action: Selector(("redo:")), keyEquivalent: "Z")
        editMenu.addItem(.separator())
        editMenu.addItem(withTitle: "剪切", action: #selector(NSText.cut(_:)), keyEquivalent: "x")
        editMenu.addItem(withTitle: "拷贝", action: #selector(NSText.copy(_:)), keyEquivalent: "c")
        editMenu.addItem(withTitle: "粘贴", action: #selector(NSText.paste(_:)), keyEquivalent: "v")
        editMenu.addItem(withTitle: "全选", action: #selector(NSText.selectAll(_:)), keyEquivalent: "a")
        editItem.submenu = editMenu

        NSApp.mainMenu = mainMenu
    }

    @objc private func reload() {
        if web.url == nil { loadGame(); return }
        web.reload()
    }

    // MARK: - 页面

    private func loadLoadingPage() {
        let html = """
        <html><body style="background:#161618;color:#ccc;font:14px -apple-system;
        display:flex;align-items:center;justify-content:center;height:100vh;margin:0">
        <div>正在启动本地服务…</div></body></html>
        """
        web.loadHTMLString(html, baseURL: nil)
    }

    private func loadGame() {
        let url = URL(string: "http://127.0.0.1:\(port)/")!
        plog("load \(url.absoluteString)")
        web.load(URLRequest(url: url))
    }

    private func showError(_ message: String) {
        plog("ERROR: \(message)")
        let html = """
        <html><body style="background:#161618;color:#e8b;font:14px -apple-system;padding:40px;line-height:1.7">
        <h2 style="color:#f88">启动失败</h2>
        <p style="white-space:pre-wrap">\(message)</p>
        <p style="color:#888">诊断日志：\(LOG_PATH)</p>
        </body></html>
        """
        web.loadHTMLString(html, baseURL: nil)
    }

    func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!,
                 withError error: Error) {
        if (error as NSError).code == NSURLErrorCancelled { return }
        if restartAttempts > 0 {                       // 正在自动重启，等它就绪即可
            plog("navigation failed while restarting, waiting for the new server")
            return
        }
        showError("连接本地服务失败：\(error.localizedDescription)\n端口 \(port)")
    }

    // MARK: - 服务进程

    private func locateGameDir() -> URL? {
        let fm = FileManager.default
        var candidates: [URL] = []
        if let res = Bundle.main.resourceURL {
            candidates.append(res.appendingPathComponent("game"))
        }
        // 开发模式：.app 就放在工程目录里
        candidates.append(Bundle.main.bundleURL.deletingLastPathComponent())
        for dir in candidates {
            if fm.fileExists(atPath: dir.appendingPathComponent("serve.py").path) {
                return dir
            }
        }
        return nil
    }

    private func findPython() -> String? {
        let candidates = [
            "/opt/homebrew/bin/python3",
            "/usr/local/bin/python3",
            "/usr/bin/python3",
            "\(NSHomeDirectory())/.workbuddy/binaries/python/versions/3.13.12/bin/python3",
        ]
        for path in candidates {
            guard FileManager.default.isExecutableFile(atPath: path) else { continue }
            let p = Process()
            p.executableURL = URL(fileURLWithPath: path)
            p.arguments = ["-c", "import sys; sys.exit(0 if sys.version_info >= (3,9) else 1)"]
            p.standardOutput = FileHandle.nullDevice
            p.standardError = FileHandle.nullDevice
            do {
                try p.run()
                p.waitUntilExit()
                if p.terminationStatus == 0 { return path }
            } catch { continue }
        }
        return nil
    }

    private func portIsFree(_ candidate: Int) -> Bool {
        let fd = socket(AF_INET, SOCK_STREAM, 0)
        guard fd >= 0 else { return false }
        defer { close(fd) }
        // TIME_WAIT 的端口仍然可以复用；服务器端也开了 allow_reuse_address，保持一致
        var yes: Int32 = 1
        setsockopt(fd, SOL_SOCKET, SO_REUSEADDR, &yes, socklen_t(MemoryLayout<Int32>.size))
        var addr = sockaddr_in()
        addr.sin_family = sa_family_t(AF_INET)
        addr.sin_port = in_port_t(UInt16(candidate).bigEndian)
        addr.sin_addr.s_addr = inet_addr("127.0.0.1")
        addr.sin_len = UInt8(MemoryLayout<sockaddr_in>.size)
        let result = withUnsafePointer(to: &addr) {
            $0.withMemoryRebound(to: sockaddr.self, capacity: 1) {
                Darwin.bind(fd, $0, socklen_t(MemoryLayout<sockaddr_in>.size))
            }
        }
        return result == 0
    }

    private func pickPort() -> Int {
        for candidate in 8765..<8800 where portIsFree(candidate) { return candidate }
        return 8765
    }

    private func startServer(python: String, dir: URL) {
        let task = Process()
        task.executableURL = URL(fileURLWithPath: python)
        task.arguments = [dir.appendingPathComponent("serve.py").path]
        task.currentDirectoryURL = dir
        var env = ProcessInfo.processInfo.environment
        env["PORT"] = String(port)
        env["PYTHONUNBUFFERED"] = "1"
        env["NO_PROXY"] = "*"
        env["no_proxy"] = "*"
        task.environment = env

        let pipe = Pipe()
        task.standardOutput = pipe
        task.standardError = pipe
        pipe.fileHandleForReading.readabilityHandler = { handle in
            let data = handle.availableData
            if data.isEmpty { return }
            if let text = String(data: data, encoding: .utf8) {
                plog("server: \(text.trimmingCharacters(in: .whitespacesAndNewlines))")
            }
        }

        task.terminationHandler = { [weak self] proc in
            DispatchQueue.main.async {
                guard let self = self, !self.quitting else { return }
                self.server = nil
                plog("server exited unexpectedly, status=\(proc.terminationStatus)")
                if self.restartAttempts < 2 {
                    self.restartAttempts += 1
                    plog("restarting server (attempt \(self.restartAttempts))")
                    self.port = self.pickPort()
                    if let dir = self.gameDir, let py = self.findPython() {
                        self.startServer(python: py, dir: dir)
                        return
                    }
                }
                self.showError("本地服务异常退出，自动重启也失败了。\n\n诊断日志：\(LOG_PATH)")
            }
        }

        do {
            try task.run()
            server = task
            plog("server started, pid=\(task.processIdentifier)")
        } catch {
            showError("无法启动 Python 服务：\(error.localizedDescription)")
            return
        }

        waitReady(attempts: 0)
    }

    private func waitReady(attempts: Int) {
        guard attempts < 80 else {
            showError("本地服务 12 秒内没有响应。\n\n诊断日志：\(LOG_PATH)")
            return
        }
        var request = URLRequest(url: URL(string: "http://127.0.0.1:\(port)/api/state")!)
        request.timeoutInterval = 1
        request.cachePolicy = .reloadIgnoringLocalCacheData
        URLSession.shared.dataTask(with: request) { [weak self] _, response, _ in
            DispatchQueue.main.async {
                guard let self = self else { return }
                if response is HTTPURLResponse {
                    self.restartAttempts = 0
                    self.loadGame()
                } else {
                    DispatchQueue.main.asyncAfter(deadline: .now() + 0.15) {
                        self.waitReady(attempts: attempts + 1)
                    }
                }
            }
        }.resume()
    }

    // MARK: - 上一次运行留下的进程
    //
    // 判断谁占着端口需要 ps，而 ps 在某些环境下不可用；改用锁文件：
    // 启动时写下自己的 pid，退出时删掉。锁文件存在但 pid 已经不在，
    // 就说明上一次是强制退出或崩溃，端口上的监听者可以安全收掉。

    private let LOCK = "/tmp/hearthstone-app.lock"

    private func previousInstancePid() -> Int32? {
        guard let text = try? String(contentsOfFile: LOCK, encoding: .utf8),
              let pid = Int32(text.trimmingCharacters(in: .whitespacesAndNewlines)),
              pid > 1 else { return nil }
        return pid
    }

    private func writeLock() {
        try? "\(getpid())".write(toFile: LOCK, atomically: true, encoding: .utf8)
    }

    private func clearLock() {
        if let pid = previousInstancePid(), pid == getpid() {
            try? FileManager.default.removeItem(atPath: LOCK)
        }
    }

    private func reapStaleListeners() {
        if let other = previousInstancePid(), kill(other, 0) == 0 {
            plog("another instance is running (pid \(other)), leaving listeners alone")
            return
        }
        let pids = pidsListening(inPortRange: "8765-8800")
        guard !pids.isEmpty else { plog("reap: nothing listening in 8765-8800"); return }
        for pid in pids {
            plog("reap: cleaning listener pid=\(pid) left by a previous run")
            kill(pid, SIGTERM)
            usleep(300_000)
            if kill(pid, 0) == 0 { kill(pid, SIGKILL) }
        }
    }

    private func pidsListening(inPortRange range: String) -> [Int32] {
        let task = Process()
        task.executableURL = URL(fileURLWithPath: "/usr/sbin/lsof")
        task.arguments = ["-ti", "tcp:\(range)", "-sTCP:LISTEN"]
        let pipe = Pipe()
        task.standardOutput = pipe
        task.standardError = FileHandle.nullDevice
        do { try task.run() } catch { return [] }
        let data = pipe.fileHandleForReading.readDataToEndOfFile()
        task.waitUntilExit()
        let out = String(data: data, encoding: .utf8) ?? ""
        // 只接受有效的正整数：kill(0, ...) 会把信号发给整个进程组，必须挡住
        return out.split(separator: "\n").compactMap { line -> Int32? in
            guard let pid = Int32(line.trimmingCharacters(in: .whitespaces)), pid > 1 else { return nil }
            return pid
        }
    }

    private func stopServer() {
        quitting = true
        clearLock()
        guard let task = server, task.isRunning else { return }
        plog("stopping server pid=\(task.processIdentifier)")
        task.terminate()
        // SIGTERM 后最多等 1 秒，避免卡在退出流程
        let deadline = Date().addingTimeInterval(1.0)
        while task.isRunning && Date() < deadline {
            usleep(50_000)
        }
        if task.isRunning { kill(task.processIdentifier, SIGKILL) }
    }
}

let app = NSApplication.shared
let delegate = AppDelegate()
app.delegate = delegate
app.setActivationPolicy(.regular)
app.run()
