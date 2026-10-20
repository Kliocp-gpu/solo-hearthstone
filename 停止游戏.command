#!/bin/bash
# 双击本文件：关掉游戏服务
PID=$(lsof -ti tcp:8765 2>/dev/null)
if [ -z "$PID" ]; then
  echo "游戏服务没有在运行。"
else
  kill $PID && echo "已关闭游戏服务 (PID $PID)。"
fi
sleep 1
