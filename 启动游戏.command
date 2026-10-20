#!/bin/bash
# 双击本文件即可开玩：自动起服务 + 自动开浏览器
cd "$(dirname "$0")" || exit 1

PY="$(command -v python3 || echo /usr/bin/python3)"
PORT=8765
URL="http://127.0.0.1:$PORT"

# 已经在跑就直接开浏览器，不重复启动
if curl -s --noproxy '*' -o /dev/null --max-time 2 "$URL"; then
  echo "服务已在运行，直接打开浏览器…"
else
  echo "启动服务中…"
  NO_PROXY='*' no_proxy='*' "$PY" serve.py > /tmp/hs_server.log 2>&1 &
  for i in $(seq 1 20); do
    sleep 0.5
    curl -s --noproxy '*' -o /dev/null --max-time 2 "$URL" && break
  done
fi

open "$URL"
echo "已打开 $URL （关掉这个窗口不会关掉游戏，要退出请运行 停止游戏.command）"
sleep 1
