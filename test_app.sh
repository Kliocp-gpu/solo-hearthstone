#!/bin/bash
# 应用外壳冒烟测试：能启动 → 服务能起来 → 自动退出 → 服务进程被收掉
# 需要 GUI 会话（会真的创建一个窗口），所以不放进 Python 测试套件里。
set -uo pipefail
cd "$(dirname "$0")"

APP="build/单机炉石.app"
BIN="$APP/Contents/MacOS/Hearthstone"
LOG="/tmp/hearthstone-app-test.log"
export HS_APP_LOG="$LOG"

if [ ! -x "$BIN" ]; then
  echo "先运行 ./build_app.sh 生成应用"
  exit 1
fi

fail=0
rm -f "$LOG"

BEFORE=$(pgrep -f "Resources/game/serve.py" 2>/dev/null | sort | tr "\n" " ")

HS_APP_QUIT_AFTER=5 "$BIN" >/dev/null 2>&1 &
APP_PID=$!
sleep 8

if ! grep -q "server started" "$LOG" 2>/dev/null; then
  echo "✗ 服务没有启动"; fail=1
else
  echo "✓ 服务已随应用启动"
fi

if ! grep -q "load http://127.0.0.1" "$LOG" 2>/dev/null; then
  echo "✗ 没有加载页面"; fail=1
else
  echo "✓ 页面已加载"
fi

if ! grep -q "stopping server" "$LOG" 2>/dev/null; then
  echo "✗ 退出时没有停服务"; fail=1
else
  echo "✓ 退出时停掉了服务"
fi

LEFT=""
for pid in $(pgrep -f "Resources/game/serve.py" 2>/dev/null); do
  case " $BEFORE " in *" $pid "*) ;; *) LEFT="$LEFT $pid" ;; esac
done
if [ -n "$LEFT" ]; then
  echo "✗ 本次启动的服务进程没有退出:$LEFT"; fail=1
  kill -9 $LEFT 2>/dev/null
else
  echo "✓ 本次启动的服务进程已退出"
fi

kill "$APP_PID" 2>/dev/null

if [ "$fail" -eq 0 ]; then
  echo "结果：应用外壳冒烟通过"
else
  echo "结果：失败，日志见 $LOG"
fi
exit "$fail"
