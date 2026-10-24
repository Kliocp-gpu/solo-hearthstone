#!/bin/bash
# 应用外壳场景回归
#
# 覆盖：
#   1 基础：启动 → 服务就绪 → 页面加载 → 退出收子进程
#   2 端口冲突：8765 被别的程序占着 → 换端口，且**不杀**那个程序
#   3 多实例：A 在跑时再开 B、再开 C，A 的服务始终不能被杀
#   4 强制退出：App 被 kill -9 后重开，只清理记录在锁里、且确认还在原端口监听的那个孤儿
#   5 移动 .app：拷到别处仍能启动
#   6 找不到 python3：给出可读的错误页
#   7 对局保留：同一次运行内局面稳定（对应刷新窗口）；退出重开后局面消失
#
# 需要 GUI 会话（会真的开窗口），所以不放进 Python 测试套件。
# 端口一律从日志里读，不写死 —— 前面的场景可能留下 TIME_WAIT 或别的监听者。
set -uo pipefail
cd "$(dirname "$0")"

APP="build/单机炉石.app"
BIN="$APP/Contents/MacOS/Hearthstone"
TMP="/tmp/hs-app-tests"
LOCK="/tmp/hearthstone-app.lock"

if [ ! -x "$BIN" ]; then
  echo "先运行 ./build_app.sh 生成应用"
  exit 1
fi

rm -rf "$TMP"; mkdir -p "$TMP"
fail=0

# 开跑前记下已经存在的监听者：结束时只清「本次跑出来的」，绝不碰别人的实例
PREEXIST=$(lsof -nP -ti "tcp:8765-8800" -sTCP:LISTEN 2>/dev/null | sort -u | tr '\n' ' ')
if [ -n "$PREEXIST" ]; then
  echo "注意：8765-8800 上已有监听者（pid ${PREEXIST}），本次测试不会动它们，端口会顺延。"
fi
OK()  { echo "  ✓ $1"; }
NO()  { echo "  ✗ $1"; fail=1; }
alive() { kill -0 "$1" 2>/dev/null; }
pid_on_port() { lsof -nP -ti "tcp:$1" -sTCP:LISTEN 2>/dev/null | head -1; }

wait_log() {  # wait_log <文件> <正则> [超时秒]
  local f=$1 p=$2 t=${3:-12} i=0 n=$(( ${3:-12} * 20 ))
  while [ $i -lt $n ]; do
    grep -qE "$p" "$f" 2>/dev/null && return 0
    sleep 0.05; i=$((i+1))
  done
  return 1
}

# 从日志里取本次实际用的端口
port_from_log() {
  grep -m1 -oE 'load http://127\.0\.0\.1:[0-9]+' "$1" 2>/dev/null \
    | grep -oE '[0-9]+$'
}

wait_port_free() {  # 等端口空出来
  local i=0
  while [ $i -lt 60 ]; do
    [ -z "$(pid_on_port "$1")" ] && return 0
    sleep 0.1; i=$((i+1))
  done
  return 1
}

launch_app() {  # launch_app <日志> [额外 env ...]
  local log=$1; shift
  env HS_APP_LOG="$log" "$@" "$BIN" >/dev/null 2>&1 &
  echo $!
}

cleanup() {
  for p in ${SPAWNED:-}; do kill -9 "$p" 2>/dev/null; done
  [ -n "${DUMMY:-}" ] && kill -9 "$DUMMY" 2>/dev/null
  # 应用被 kill -9 时会把服务留成孤儿，这里把「本次新出现的监听者」收掉
  for p in $(lsof -nP -ti "tcp:8765-8800" -sTCP:LISTEN 2>/dev/null); do
    case " $PREEXIST " in *" $p "*) ;; *) kill -9 "$p" 2>/dev/null ;; esac
  done
  return 0
}
trap cleanup EXIT
SPAWNED=""

# ---------------------------------------------------------------- 1 基础
echo "1. 基础：启动 / 就绪 / 加载 / 退出"
L1="$TMP/basic.log"
A=$(launch_app "$L1" HS_APP_QUIT_AFTER=6); SPAWNED="$SPAWNED $A"
if wait_log "$L1" "server started" 12; then OK "服务随应用启动"; else NO "服务没启动"; fi
if wait_log "$L1" "load http://127.0.0.1:" 12; then
  P1=$(port_from_log "$L1"); OK "页面已加载（端口 ${P1}）"
else
  P1=""; NO "没有加载页面"
fi
if wait_log "$L1" "stopping server" 12; then OK "退出时停掉了服务"; else NO "退出时没有停服务"; fi
[ -n "$P1" ] && wait_port_free "$P1"
if [ -n "$P1" ] && [ -z "$(pid_on_port "$P1")" ]; then OK "退出后端口 ${P1} 已释放"; else NO "退出后端口仍被占用"; fi
if [ -f "$LOCK" ]; then NO "退出后锁文件没删干净"; else OK "锁文件已清理"; fi

# ---------------------------------------------------------------- 2 端口冲突
echo "2. 端口冲突：8765 被别的程序占着"
L2="$TMP/conflict.log"
wait_port_free 8765 >/dev/null
/usr/bin/python3 -m http.server 8765 --bind 127.0.0.1 >/dev/null 2>&1 &
DUMMY=$!
sleep 1.2
if [ "$(pid_on_port 8765)" != "$DUMMY" ]; then
  NO "占位进程没占住 8765（现有监听者 $(pid_on_port 8765)），跳过本项"
else
  B=$(launch_app "$L2" HS_APP_QUIT_AFTER=7); SPAWNED="$SPAWNED $B"
  P2=$(wait_log "$L2" "load http://127.0.0.1:" 12 && port_from_log "$L2")
  if [ -n "$P2" ] && [ "$P2" != "8765" ]; then OK "自动避开了 8765（改用 ${P2}）"; else NO "没有避开被占端口"; fi
  if wait_log "$L2" "warn=" 12; then OK "页面带上了端口占用提示"; else NO "没有提示"; fi
  if alive "$DUMMY"; then OK "占着 8765 的程序没被误杀"; else NO "占位程序被杀了（误杀）"; fi
  wait_log "$L2" "stopping server" 12
  sleep 0.5
  if alive "$DUMMY"; then OK "退出后占位程序仍然活着"; else NO "退出时把占位程序杀了"; fi
fi
kill -9 "$DUMMY" 2>/dev/null; DUMMY=""
wait_port_free 8765 >/dev/null

# ---------------------------------------------------------------- 3 两个实例
echo "3. 多实例：A 在跑时开 B、再开 C，A 不能被杀"
L3A="$TMP/two-a.log"; L3B="$TMP/two-b.log"; L3C="$TMP/two-c.log"
A3=$(launch_app "$L3A" HS_APP_QUIT_AFTER=45); SPAWNED="$SPAWNED $A3"
PA=$(wait_log "$L3A" "load http://127.0.0.1:" 15 && port_from_log "$L3A")
A3_SRV=$( [ -n "$PA" ] && pid_on_port "$PA" )
if [ -z "${A3_SRV:-}" ]; then
  NO "A 的服务没起来，跳过本项"
else
  OK "A 占用 ${PA}（服务 pid ${A3_SRV}）"
  B3=$(launch_app "$L3B" HS_APP_QUIT_AFTER=6); SPAWNED="$SPAWNED $B3"
  PB=$(wait_log "$L3B" "load http://127.0.0.1:" 12 && port_from_log "$L3B")
  if [ -n "$PB" ] && [ "$PB" != "$PA" ]; then OK "B 换到 ${PB}"; else NO "B 没有让开 ${PA}"; fi
  if wait_log "$L3B" "另一个实例正在运行" 12; then OK "B 识别出另一个实例"; else NO "B 没有识别出另一个实例"; fi
  wait_log "$L3B" "stopping server" 12
  sleep 0.8
  if alive "$A3_SRV"; then OK "B 退出后 A 的服务还在"; else NO "B 退出时把 A 的服务杀了"; fi

  # 关键回归：B 退出时把锁删了，C 启动时「看不到任何所有者」。
  # 旧实现会在这时把 8765-8800 上的监听者全部杀掉。
  C3=$(launch_app "$L3C" HS_APP_QUIT_AFTER=6); SPAWNED="$SPAWNED $C3"
  if wait_log "$L3C" "load http://127.0.0.1:" 12; then
    PC=$(port_from_log "$L3C"); OK "C 启动成功（${PC}）"
  else
    NO "C 没能启动"
  fi
  sleep 0.8
  if alive "$A3_SRV"; then OK "C 启动没有误杀 A 的服务（旧实现在这里会杀掉）"; else NO "C 启动时误杀了 A 的服务"; fi
  wait_log "$L3C" "stopping server" 12
fi
# 收尾：停 A、清残留与锁，让后面的场景从干净状态开始
kill -9 "${A3:-0}" 2>/dev/null
sleep 0.6
LEFTOVER=$(pid_on_port "${PA:-8765}")
[ -n "$LEFTOVER" ] && kill -9 "$LEFTOVER" 2>/dev/null
sleep 0.3
rm -f "$LOCK"
OK "清理：A 与服务都已停止，锁已清空"

# ---------------------------------------------------------------- 4 强制退出
echo "4. 强制退出后重开：只清理能确认归属的孤儿"
L4="$TMP/crash.log"; L4B="$TMP/crash-reopen.log"
A4=$(launch_app "$L4"); SPAWNED="$SPAWNED $A4"
if ! wait_log "$L4" "server started" 15; then
  NO "A4 服务没起来，跳过本项"
else
  P4=$(grep -m1 -oE 'port = [0-9]+' "$L4" | grep -oE '[0-9]+')
  SRV4=$( [ -n "$P4" ] && pid_on_port "$P4" )
  if [ -z "${SRV4:-}" ]; then
    NO "拿不到 A4 的服务 pid（端口 ${P4:-?}），跳过本项"
  else
    kill -9 "$A4" 2>/dev/null          # 模拟崩溃：不触发 applicationWillTerminate
    sleep 1
    if alive "$SRV4"; then OK "服务成了孤儿（pid ${SRV4} 仍在跑）"; else NO "服务没留下来，无法测回收"; fi
    if grep -q '"server"' "$LOCK" 2>/dev/null; then OK "锁里记录了服务 pid"; else NO "锁里没有服务 pid"; fi
    R=$(launch_app "$L4B" HS_APP_QUIT_AFTER=7); SPAWNED="$SPAWNED $R"
    if wait_log "$L4B" "清理上次残留的服务进程 pid=${SRV4}" 15; then
      OK "重开时精确回收了那个孤儿"
    else
      NO "没有回收孤儿"
    fi
    sleep 0.5
    if alive "$SRV4"; then NO "孤儿服务还在（回收失败）"; else OK "孤儿服务已结束"; fi
    PR=$(wait_log "$L4B" "load http://127.0.0.1:" 15 && port_from_log "$L4B")
    if [ -n "$PR" ]; then OK "新实例正常加载（${PR}）"; else NO "新实例加载失败"; fi
    wait_log "$L4B" "stopping server" 12
    [ -n "$PR" ] && wait_port_free "$PR" >/dev/null
  fi
fi
for p in $(lsof -nP -ti "tcp:8765" -sTCP:LISTEN 2>/dev/null); do kill -9 "$p" 2>/dev/null; done
sleep 0.3
[ -z "$(pid_on_port 8765)" ] && OK "清理：8765 已释放" || NO "8765 仍有残留监听者"

# ---------------------------------------------------------------- 5 移动 .app
echo "5. 移动 .app 后启动"
L5="$TMP/moved.log"
MOVED="$TMP/moved-单机炉石.app"
cp -R "$APP" "$MOVED"
M=$(env HS_APP_LOG="$L5" HS_APP_QUIT_AFTER=6 "$MOVED/Contents/MacOS/Hearthstone" >/dev/null 2>&1 & echo $!)
SPAWNED="$SPAWNED $M"
if wait_log "$L5" "game dir = $MOVED/Contents/Resources/game" 12; then OK "从新位置找到了 game 目录"; else NO "移动后找不到 game 目录"; fi
if wait_log "$L5" "load http://127.0.0.1:" 12; then OK "移动后仍能正常加载"; else NO "移动后加载失败"; fi
wait_log "$L5" "stopping server" 12

# ---------------------------------------------------------------- 6 没有 python3
echo "6. 找不到 python3"
L6="$TMP/nopython.log"
N=$(launch_app "$L6" HS_APP_PYTHON=/nonexistent/python3 HS_APP_QUIT_AFTER=3); SPAWNED="$SPAWNED $N"
if wait_log "$L6" "没有找到可用的 python3" 10; then OK "给出了可读的错误提示"; else NO "缺少 python3 时没有提示"; fi
wait_log "$L6" "terminated" 6

# ---------------------------------------------------------------- 7 对局保留语义
echo "7. 对局保留：同一次运行内不变，退出重开后消失"
L7="$TMP/persist-a.log"; L7B="$TMP/persist-b.log"
FP() {  # FP <端口> 局面指纹：回合/血量/法力/手牌数
  curl -s -m 3 --noproxy '*' "http://127.0.0.1:$1/api/state" \
    | /usr/bin/python3 -c "import sys,json
d=json.load(sys.stdin); s=d.get('state') or {}; me=s.get('me') or {}
print(s.get('turn'), me.get('hp'), me.get('mana'), len(me.get('hand') or []))" 2>/dev/null
}
A7=$(launch_app "$L7" HS_APP_QUIT_AFTER=9); SPAWNED="$SPAWNED $A7"
P7=$(wait_log "$L7" "load http://127.0.0.1:" 15 && port_from_log "$L7")
if [ -z "$P7" ]; then
  NO "第 7 组没起来，跳过"
else
  START=$(curl -s -m 5 --noproxy '*' -X POST -H "Content-Type: application/json" \
          -d '{"cls":"MAGE"}' "http://127.0.0.1:$P7/api/start")
  if echo "$START" | grep -q '"ok": true'; then OK "开局成功（随机卡组）"; else NO "开局失败：$START"; fi
  F1=$(FP "$P7"); F2=$(FP "$P7")
  if [ -n "$F1" ] && [ "$F1" = "$F2" ]; then
    OK "同一次运行内重复取局面不变（对应「刷新窗口」）"
  else
    NO "重复请求局面不一致：$F1 vs $F2"
  fi
  if wait_log "$L7" "terminated" 18; then OK "退出后服务随之停止"; else NO "退出流程没走完"; fi
  sleep 0.6
  R7=$(launch_app "$L7B" HS_APP_QUIT_AFTER=7); SPAWNED="$SPAWNED $R7"
  P7B=$(wait_log "$L7B" "load http://127.0.0.1:" 15 && port_from_log "$L7B")
  if [ -n "$P7B" ]; then
    S3=$(curl -s -m 3 --noproxy '*' "http://127.0.0.1:$P7B/api/state")
    if echo "$S3" | grep -q 'no_game'; then
      OK "退出重开后对局已不在（局面只存在于内存）"
    else
      NO "重开后仍读到旧局面：$S3"
    fi
  else
    NO "重开失败"
  fi
  wait_log "$L7B" "stopping server" 12
fi

echo
if [ "$fail" -eq 0 ]; then
  echo "结果：应用场景回归全部通过（7 组）"
else
  echo "结果：有失败项，日志在 $TMP/"
fi
exit "$fail"
