#!/bin/bash
# 把网页版打包成 macOS 应用：build/Hearthstone.app
# 依赖：Xcode 命令行工具（swiftc）。不打包 Python 解释器，运行时用系统自带的 python3。
set -euo pipefail
cd "$(dirname "$0")"

APP="build/Hearthstone.app"
GAME="$APP/Contents/Resources/game"
BIN="$APP/Contents/MacOS/Hearthstone"

echo "清理旧产物 …"
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$GAME/static"

echo "编译 Swift 外壳 …"
swiftc -O -swift-version 5 \
    -o "$BIN" \
    app/main.swift \
    -framework Cocoa -framework WebKit

echo "打包资源 …"
cp app/Info.plist "$APP/Contents/Info.plist"
printf 'APPL????' > "$APP/Contents/PkgInfo"
cp engine.py cards.py ai.py serve.py "$GAME/"
cp static/index.html "$GAME/static/"

echo "本地签名（ad-hoc）…"
codesign --force --sign - "$APP" >/dev/null 2>&1 || echo "  签名失败，不影响本机运行"

SIZE=$(du -sh "$APP" | cut -f1)
echo "完成：${APP}（${SIZE}）"
echo "双击即可运行；也可以拖进「应用程序」文件夹。"
