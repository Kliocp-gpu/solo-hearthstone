// 单机炉石 · macOS 外壳
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
    private var warnings: [String] = []        // 启动时要说给用户听的话（端口被占、另开了一个窗口）
    private var occupiedPorts: [Int] = []      // 探测过程中被别人占着的端口，只用于提示，不据此杀进程

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

        let otherInstance = cleanupOwnedOrphans()
        writeLock(server: nil, port: nil)
        guard let chosen = pickPort() else {
            showError("端口 8765–8800 全部被占用，无法启动本地服务。\n\n请先关掉占用这些端口的程序，或重启电脑后再试。")
            return
        }
        port = chosen
        if otherInstance {
            warnings.append("另一个「单机炉石」窗口正在运行，这一窗口改用端口 \(port)。两边的对局互不影响。")
        }
        if !occupiedPorts.isEmpty {
            let list = occupiedPorts.map(String.init).joined(separator: "、")
            warnings.append("端口 \(list) 已被其他进程占用，这一窗口改用 \(port)。没有结束任何不是本程序启动的进程。")
        }
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
        window.title = "单机炉石"
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
        appMenu.addItem(withTitle: "关于单机炉石",
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
        var comps = URLComponents(string: "http://127.0.0.1:\(port)/")!
        if !warnings.isEmpty {
            // 端口被占/另开窗口这类情况，页面上给一句可读的提示，而不是只写日志
            comps.queryItems = [URLQueryItem(name: "warn", value: warnings.joined(separator: " "))]
        }
        let url = comps.url!
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
        var candidates = [
            "/opt/homebrew/bin/python3",
            "/usr/local/bin/python3",
            "/usr/bin/python3",
            "\(NSHomeDirectory())/.workbuddy/binaries/python/versions/3.13.12/bin/python3",
        ]
        // 指定解释器时不再走回落链（测试「找不到 python3」这条路径也用它）
        if let forced = ProcessInfo.processInfo.environment["HS_APP_PYTHON"] {
            candidates = [forced]
        }
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

    /// 找第一个真正空闲的端口。占着的端口只记下来用于提示，不试图清掉占用者——
    /// 那些进程是谁的没法证明，宁可换端口也不能误杀。
    private func pickPort() -> Int? {
        occupiedPorts = []
        for candidate in 8765..<8800 {
            if portIsFree(candidate) { return candidate }
            occupiedPorts.append(candidate)
        }
        return nil
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
                if self.restartAttempts < 2, let next = self.pickPort() {
                    self.restartAttempts += 1
                    plog("restarting server (attempt \(self.restartAttempts)) on port \(next)")
                    self.port = next
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
            // 把服务 pid 和端口一起写进锁，下次异常退出后才有据可查
            writeLock(server: task.processIdentifier, port: port)
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
    // 原则：只结束「能证明是自己启动的」进程，证明不了一律不碰，改用别的端口。
    //
    // 锁文件记录三样东西：本次 App 的 pid、本次拉起的服务进程 pid、服务所在的端口。
    // 判定孤儿需要两条同时成立：
    //   1. 锁里的 App pid 已经不存在（说明上次是崩溃或被 kill 掉，没走正常退出）
    //   2. 锁里的服务 pid 还活着，**并且确实还在锁里记录的那个端口上监听**
    // 只要有任何一条不满足，就认为「无法确认归属」，不发出任何信号。
    //
    // 旧实现按端口范围（8765-8800）无差别 kill，会误杀另一个还在运行的实例的服务，
    // 甚至误杀别的程序 —— 已经去掉。

    private let LOCK = "/tmp/hearthstone-app.lock"

    private struct LockInfo: Codable {
        var app: Int32
        var server: Int32?
        var port: Int?
    }

    private func readLock() -> LockInfo? {
        guard let data = FileManager.default.contents(atPath: LOCK) else { return nil }
        if let info = try? JSONDecoder().decode(LockInfo.self, from: data), info.app > 1 {
            return info
        }
        // 兼容旧格式：文件里只有一个 pid
        if let text = String(data: data, encoding: .utf8),
           let pid = Int32(text.trimmingCharacters(in: .whitespacesAndNewlines)), pid > 1 {
            return LockInfo(app: pid, server: nil, port: nil)
        }
        return nil
    }

    private func writeLock(server: Int32?, port: Int?) {
        let info = LockInfo(app: getpid(), server: server, port: port)
        guard let data = try? JSONEncoder().encode(info) else { return }
        try? data.write(to: URL(fileURLWithPath: LOCK), options: .atomic)
    }

    private func clearLock() {
        // 只有锁还属于自己才删：两个实例共用一个锁文件，别替别人清
        if let info = readLock(), info.app == getpid() {
            try? FileManager.default.removeItem(atPath: LOCK)
        }
    }

    /// 返回 true 表示「另一个实例正在运行」，调用方据此只做提示、不清理。
    private func cleanupOwnedOrphans() -> Bool {
        guard let old = readLock() else {
            plog("reap: 没有锁文件，不清理任何进程")
            return false
        }
        if old.app != getpid(), kill(old.app, 0) == 0 {
            plog("reap: 另一个实例正在运行 (pid \(old.app), port \(old.port.map(String.init) ?? "-"))，不动任何监听者")
            return true
        }
        guard let sp = old.server, let spPort = old.port, sp > 1 else {
            plog("reap: 锁文件是异常退出留下的，但没有记录服务进程，无需清理")
            return false
        }
        guard kill(sp, 0) == 0 else {
            plog("reap: 记录的服务进程 \(sp) 已不存在")
            return false
        }
        guard listensOn(pid: sp, port: spPort) else {
            plog("reap: pid \(sp) 还活着但不在端口 \(spPort) 上监听，疑似 pid 复用，不动它")
            return false
        }
        plog("reap: 清理上次残留的服务进程 pid=\(sp)（端口 \(spPort)，已确认归属）")
        kill(sp, SIGTERM)
        usleep(300_000)
        if kill(sp, 0) == 0 { kill(sp, SIGKILL) }
        return false
    }

    /// 归属校验：该 pid 是否真的在这个端口上 LISTEN。lsof 不可用时返回 false（保守）。
    private func listensOn(pid: Int32, port: Int) -> Bool {
        let task = Process()
        task.executableURL = URL(fileURLWithPath: "/usr/sbin/lsof")
        task.arguments = ["-ti", "tcp:\(port)", "-sTCP:LISTEN"]
        let pipe = Pipe()
        task.standardOutput = pipe
        task.standardError = FileHandle.nullDevice
        do { try task.run() } catch { return false }
        let data = pipe.fileHandleForReading.readDataToEndOfFile()
        task.waitUntilExit()
        let out = String(data: data, encoding: .utf8) ?? ""
        return out.split(separator: "\n").contains {
            Int32($0.trimmingCharacters(in: .whitespaces)) == pid
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
