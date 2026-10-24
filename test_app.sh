#!/bin/bash
# 应用外壳场景回归
#
# 覆盖：
#   1 基础：启动 → 服务就绪 → 页面加载 → 退出收子进程
#   2 端口冲突：8765 被别的程序占着 → 换端口，且**不杀**那个程序
#   3 多实例：A 在跑时再开 B、再开 C，A 的服务始终不能被杀
#   4 强制退出：App 被 kill -9 后重开，只清理记录在案且校验通过的孤儿
#   5 移动 .app：拷到别处仍能启动
#   6 找不到 python3：给出可读的错误页
#   7 对局保留：同一次运行内局面稳定（对应刷新窗口）；退出重开后局面消失
#   8 一人一份记录：A 崩溃前 B 已经退出，A 的孤儿仍能被后来的实例认领
#
# 安全约定：本脚本只杀「自己启动并记录下来的 pid」——
#   SPAWNED    = 本脚本拉起的 App 进程
#   OWNED_SRV  = 从这些 App 的日志/记录里读到的服务进程
#   DUMMY      = 为制造端口冲突而起的占位进程
# 绝不按端口段扫杀，也不碰开跑前就存在的监听者。
#
# 需要 GUI 会话（会真的开窗口），所以不放进 Python 测试套件。
set -uo pipefail
cd "$(dirname "$0")"

APP="build/单机炉石.app"
BIN="$APP/Contents/MacOS/Hearthstone"
TMP="${HS_TEST_TMP:-/tmp/hs-app-tests}"
LOCK_DIR="/tmp/hearthstone-app.d"

if [ ! -x "$BIN" ]; then
  echo "先运行 ./build_app.sh 生成应用"
  exit 1
fi

rm -rf "$TMP"; mkdir -p "$TMP"
fail=0
OWNED_SRV=""
DUMMY=""
# 拉起的 App pid 记在文件里，不用变量：launch_app 常被 $(...) 调用，
# 命令替换在子 Shell 里跑，函数内对变量的赋值回不到主 Shell。
SPAWN_FILE="$TMP/.spawned"
: > "$SPAWN_FILE"

PREEXIST=$(lsof -nP -ti "tcp:8765-8800" -sTCP:LISTEN 2>/dev/null | sort -u | tr '\n' ' ')
if [ -n "$PREEXIST" ]; then
  echo "注意：8765-8800 上已有监听者（pid ${PREEXIST}），本次不会动它们，端口会顺延。"
fi

OK()  { echo "  ✓ $1"; }
NO()  { echo "  ✗ $1"; fail=1; }
alive() { kill -0 "$1" 2>/dev/null; }
pid_on_port() { lsof -nP -ti "tcp:$1" -sTCP:LISTEN 2>/dev/null | head -1; }

wait_log() {  # wait_log <文件> <正则> [超时秒]
  local f=$1 p=$2 i=0 n=$(( ${3:-12} * 20 ))
  while [ $i -lt $n ]; do
    grep -qE "$p" "$f" 2>/dev/null && return 0
    sleep 0.05; i=$((i+1))
  done
  return 1
}

port_from_log() {  # 本次实际用的端口：从日志读，不写死
  grep -m1 -oE 'load http://127\.0\.0\.1:[0-9]+' "$1" 2>/dev/null | grep -oE '[0-9]+$'
}

srv_from_log() {   # 本次拉起的服务 pid
  grep -m1 -oE 'server started, pid=[0-9]+' "$1" 2>/dev/null | grep -oE '[0-9]+$'
}

wait_port_free() {
  local i=0
  while [ $i -lt 60 ]; do
    [ -z "$(pid_on_port "$1")" ] && return 0
    sleep 0.1; i=$((i+1))
  done
  return 1
}

launch_app() {  # launch_app <日志> [额外 env ...]；pid 写进 SPAWN_FILE 并回显
  local log=$1; shift
  env HS_APP_LOG="$log" "$@" "$BIN" >/dev/null 2>&1 &
  local pid=$!
  echo "$pid" >> "$SPAWN_FILE"
  echo "$pid"
}

record_srv() {  # record_srv <日志>：服务 pid 记进 OWNED_SRV
  local sp; sp=$(srv_from_log "$1")
  [ -n "$sp" ] && OWNED_SRV="$OWNED_SRV $sp"
  return 0
}

cleanup() {
  local p f srv apps
  apps=$(tr '\n' ' ' < "$SPAWN_FILE" 2>/dev/null)
  # 1) 先 SIGKILL 本次拉起的 App：别让它们在收服务时又自动重启一个
  for p in $apps; do kill -9 "$p" 2>/dev/null; done
  sleep 0.2
  # 2) 按每个 App 自己的记录收服务（只碰记录在案的 pid）
  for p in $apps; do
    f="$LOCK_DIR/$p.json"
    [ -f "$f" ] || continue
    srv=$(/usr/bin/python3 -c "import json;print(json.load(open('$f')).get('server') or '')" 2>/dev/null)
    [ -n "$srv" ] && kill -9 "$srv" 2>/dev/null
    rm -f "$f"
  done
  # 3) 日志/记录里读到过的服务 pid 也一并收掉
  for srv in ${OWNED_SRV:-}; do kill -9 "$srv" 2>/dev/null; done
  [ -n "${DUMMY:-}" ] && kill -9 "$DUMMY" 2>/dev/null
  return 0
}
trap cleanup EXIT

# 供第 10 组自测用：启动一个长寿命实例，然后立刻以失败退出，验证 trap 真能收干净
if [ "${HS_TEST_ABORT_MODE:-}" = "1" ]; then
  L="$TMP/abort.log"
  launch_app "$L" HS_APP_QUIT_AFTER=60 >/dev/null
  APID=$(tail -1 "$SPAWN_FILE")
  wait_log "$L" "load http://127.0.0.1:" 15
  PS=$(port_from_log "$L")
  echo "APP=$APID SRV=$(pid_on_port "$PS")" > "$TMP/abort.pids"
  echo "self-test: 立刻以失败退出，清理交给 trap"
  exit 1
fi

# ---------------------------------------------------------------- 1 基础
echo "1. 基础：启动 / 就绪 / 加载 / 退出"
L1="$TMP/basic.log"
A=$(launch_app "$L1" HS_APP_QUIT_AFTER=6)
if wait_log "$L1" "server started" 12; then OK "服务随应用启动"; else NO "服务没启动"; fi
record_srv "$L1"
if wait_log "$L1" "load http://127.0.0.1:" 12; then
  P1=$(port_from_log "$L1"); OK "页面已加载（端口 ${P1}）"
else
  P1=""; NO "没有加载页面"
fi
if wait_log "$L1" "stopping server" 12; then OK "退出时停掉了服务"; else NO "退出时没有停服务"; fi
[ -n "$P1" ] && wait_port_free "$P1"
if [ -n "$P1" ] && [ -z "$(pid_on_port "$P1")" ]; then OK "退出后端口 ${P1} 已释放"; else NO "退出后端口仍被占用"; fi
if [ -f "$LOCK_DIR/$A.json" ]; then NO "退出后本实例的记录没删"; else OK "本实例的记录已清理"; fi

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
  B=$(launch_app "$L2" HS_APP_QUIT_AFTER=7)
  record_srv "$L2"
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
A3=$(launch_app "$L3A" HS_APP_QUIT_AFTER=45); record_srv "$L3A"
PA=$(wait_log "$L3A" "load http://127.0.0.1:" 15 && port_from_log "$L3A")
A3_SRV=$( [ -n "$PA" ] && pid_on_port "$PA" )
if [ -z "${A3_SRV:-}" ]; then
  NO "A 的服务没起来，跳过本项"
else
  OK "A 占用 ${PA}（服务 pid ${A3_SRV}）"
  B3=$(launch_app "$L3B" HS_APP_QUIT_AFTER=6); record_srv "$L3B"
  PB=$(wait_log "$L3B" "load http://127.0.0.1:" 12 && port_from_log "$L3B")
  if [ -n "$PB" ] && [ "$PB" != "$PA" ]; then OK "B 换到 ${PB}"; else NO "B 没有让开 ${PA}"; fi
  if wait_log "$L3B" "实例 [0-9]+ 仍在运行" 12; then OK "B 识别出另一个实例"; else NO "B 没有识别出另一个实例"; fi
  wait_log "$L3B" "stopping server" 12
  sleep 0.8
  if alive "$A3_SRV"; then OK "B 退出后 A 的服务还在"; else NO "B 退出时把 A 的服务杀了"; fi

  # 关键回归：B 退出后它自己的记录已删，A 的记录还在（A 还活着）→ 不能动 A。
  # 旧实现按端口段扫杀，会在这里把 A 的服务杀掉。
  C3=$(launch_app "$L3C" HS_APP_QUIT_AFTER=6); record_srv "$L3C"
  if wait_log "$L3C" "load http://127.0.0.1:" 12; then
    PC=$(port_from_log "$L3C"); OK "C 启动成功（${PC}）"
  else
    NO "C 没能启动"
  fi
  sleep 0.8
  if alive "$A3_SRV"; then OK "C 启动没有误杀 A 的服务（旧实现在这里会杀掉）"; else NO "C 启动时误杀了 A 的服务"; fi
  wait_log "$L3C" "stopping server" 12
fi
kill -9 "${A3:-0}" 2>/dev/null
[ -n "${A3_SRV:-}" ] && { sleep 0.3; kill -9 "$A3_SRV" 2>/dev/null; }
rm -f "$LOCK_DIR/${A3:-0}.json"
sleep 0.2

# ---------------------------------------------------------------- 4 强制退出
echo "4. 强制退出后重开：只清理校验通过的孤儿"
L4="$TMP/crash.log"; L4B="$TMP/crash-reopen.log"
A4=$(launch_app "$L4")
if ! wait_log "$L4" "server started" 15; then
  NO "A4 服务没起来，跳过本项"
else
  record_srv "$L4"
  P4=$(grep -m1 -oE 'port = [0-9]+' "$L4" | grep -oE '[0-9]+')
  SRV4=$( [ -n "$P4" ] && pid_on_port "$P4" )
  if [ -z "${SRV4:-}" ]; then
    NO "拿不到 A4 的服务 pid（端口 ${P4:-?}），跳过本项"
  else
    kill -9 "$A4" 2>/dev/null          # 模拟崩溃：不触发 applicationWillTerminate
    sleep 1
    if alive "$SRV4"; then OK "服务成了孤儿（pid ${SRV4} 仍在跑）"; else NO "服务没留下来，无法测回收"; fi
    if grep -q '"server"' "$LOCK_DIR/$A4.json" 2>/dev/null; then OK "记录里保存了服务 pid"; else NO "记录里没有服务 pid"; fi
    if grep -q '"started"' "$LOCK_DIR/$A4.json" 2>/dev/null; then OK "记录里保存了启动时刻"; else NO "记录里没有启动时刻"; fi
    R=$(launch_app "$L4B" HS_APP_QUIT_AFTER=7); record_srv "$L4B"
    if wait_log "$L4B" "回收残留服务 pid=${SRV4}" 15; then
      OK "重开时精确回收了那个孤儿"
    else
      NO "没有回收孤儿"
    fi
    sleep 0.5
    if alive "$SRV4"; then NO "孤儿服务还在（回收失败）"; else OK "孤儿服务已结束"; fi
    if [ -f "$LOCK_DIR/$A4.json" ]; then NO "孤儿记录没删"; else OK "孤儿记录已删"; fi
    PR=$(wait_log "$L4B" "load http://127.0.0.1:" 15 && port_from_log "$L4B")
    if [ -n "$PR" ]; then OK "新实例正常加载（${PR}）"; else NO "新实例加载失败"; fi
    wait_log "$L4B" "stopping server" 12
  fi
fi

# ---------------------------------------------------------------- 5 移动 .app
echo "5. 移动 .app 后启动"
L5="$TMP/moved.log"
MOVED="$TMP/moved-单机炉石.app"
cp -R "$APP" "$MOVED"
env HS_APP_LOG="$L5" HS_APP_QUIT_AFTER=6 "$MOVED/Contents/MacOS/Hearthstone" >/dev/null 2>&1 &
echo $! >> "$SPAWN_FILE"
record_srv "$L5"
if wait_log "$L5" "game dir = $MOVED/Contents/Resources/game" 12; then OK "从新位置找到了 game 目录"; else NO "移动后找不到 game 目录"; fi
if wait_log "$L5" "load http://127.0.0.1:" 12; then OK "移动后仍能正常加载"; else NO "移动后加载失败"; fi
wait_log "$L5" "stopping server" 12

# ---------------------------------------------------------------- 6 没有 python3
echo "6. 找不到 python3"
L6="$TMP/nopython.log"
N=$(launch_app "$L6" HS_APP_PYTHON=/nonexistent/python3 HS_APP_QUIT_AFTER=3)
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
A7=$(launch_app "$L7" HS_APP_QUIT_AFTER=9); record_srv "$L7"
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
  R7=$(launch_app "$L7B" HS_APP_QUIT_AFTER=7); record_srv "$L7B"
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

# ---------------------------------------------------------------- 8 一人一份记录
echo "8. 一人一份记录：A 崩溃前 B 已退出，A 的孤儿仍能被认领"
L8A="$TMP/lock-a.log"; L8B="$TMP/lock-b.log"; L8C="$TMP/lock-c.log"
A8=$(launch_app "$L8A" HS_APP_QUIT_AFTER=60); record_srv "$L8A"
PA8=$(wait_log "$L8A" "load http://127.0.0.1:" 15 && port_from_log "$L8A")
A8_SRV=$( [ -n "$PA8" ] && pid_on_port "$PA8" )
if [ -z "${A8_SRV:-}" ]; then
  NO "A8 的服务没起来，跳过本项"
else
  OK "A8 占用 ${PA8}（服务 pid ${A8_SRV}）"
  B8=$(launch_app "$L8B" HS_APP_QUIT_AFTER=6); record_srv "$L8B"
  wait_log "$L8B" "load http://127.0.0.1:" 12
  wait_log "$L8B" "stopping server" 12
  sleep 0.8
  if [ -f "$LOCK_DIR/$A8.json" ]; then
    OK "B 退出后 A 的记录仍在（共用一个锁文件时会在这里被删掉）"
  else
    NO "B 退出时把 A 的记录也删了"
  fi
  kill -9 "$A8" 2>/dev/null                      # A 崩溃，记录留下
  sleep 1
  if alive "$A8_SRV"; then OK "A 的服务成了孤儿（pid ${A8_SRV}）"; else NO "A 的服务没留下来"; fi
  C8=$(launch_app "$L8C" HS_APP_QUIT_AFTER=8); record_srv "$L8C"
  if wait_log "$L8C" "回收残留服务 pid=${A8_SRV}" 15; then
    OK "后来的实例凭记录认领并回收了这个孤儿"
  else
    NO "孤儿没被认领（记录丢失或校验没通过）"
  fi
  sleep 0.5
  if alive "$A8_SRV"; then NO "孤儿服务还在"; else OK "孤儿服务已结束"; fi
  if [ -f "$LOCK_DIR/$A8.json" ]; then NO "A 的记录没删"; else OK "A 的记录已删"; fi
  wait_log "$L8C" "stopping server" 14
fi

# ---------------------------------------------------------------- 9 启动时刻校验
echo "9. 启动时刻不符：拒绝回收（防 pid 被复用后误杀）"
L9A="$TMP/stale-a.log"; L9B="$TMP/stale-b.log"
A9=$(launch_app "$L9A" HS_APP_QUIT_AFTER=60); record_srv "$L9A"
PA9=$(wait_log "$L9A" "load http://127.0.0.1:" 15 && port_from_log "$L9A")
SRV9=$( [ -n "$PA9" ] && pid_on_port "$PA9" )
if [ -z "${SRV9:-}" ]; then
  NO "A9 的服务没起来，跳过本项"
else
  # 把记录里的启动时刻改早 100 秒，模拟「pid 已经被别的进程接手」
  /usr/bin/python3 - "$LOCK_DIR/$A9.json" <<'PY'
import json, sys
p = sys.argv[1]
d = json.load(open(p))
d["started"] = (d.get("started") or 0) - 100
json.dump(d, open(p, "w"))
PY
  kill -9 "$A9" 2>/dev/null
  sleep 1
  B9=$(launch_app "$L9B" HS_APP_QUIT_AFTER=6); record_srv "$L9B"
  if wait_log "$L9B" "疑似 pid 复用" 15; then OK "识别出启动时刻对不上"; else NO "没有做启动时刻校验"; fi
  sleep 0.5
  if alive "$SRV9"; then OK "校验不通过 → 没有杀掉那个进程"; else NO "仍然把它杀了（校验没生效）"; fi
  if [ -f "$LOCK_DIR/$A9.json" ]; then OK "校验不通过的记录被保留（便于事后排查）"; else NO "把取证用的记录删了"; fi
  wait_log "$L9B" "stopping server" 14
  kill -9 "$SRV9" 2>/dev/null
  rm -f "$LOCK_DIR/$A9.json"
fi

# ---------------------------------------------------------------- 10 失败退出清理
echo "10. 失败退出时的清理：子脚本以 exit 1 结束，trap 必须收干净"
CHILD_TMP="/tmp/hs-abort-child"
CHILD_OUT="/tmp/hs-abort-child.out"
rm -rf "$CHILD_TMP"
HS_TEST_TMP="$CHILD_TMP" HS_TEST_ABORT_MODE=1 bash "$0" >"$CHILD_OUT" 2>&1
RC=$?
if [ "$RC" -ne 0 ]; then OK "子脚本按预期以非零状态退出（rc=${RC}）"; else NO "子脚本没有按预期失败"; fi
APP10=$(grep -o 'APP=[0-9]*' "$CHILD_TMP/abort.pids" 2>/dev/null | cut -d= -f2)
SRV10=$(grep -o 'SRV=[0-9]*' "$CHILD_TMP/abort.pids" 2>/dev/null | cut -d= -f2)
if [ -z "${APP10:-}" ] || [ -z "${SRV10:-}" ]; then
  NO "没拿到子脚本的 pid 记录（见 ${CHILD_OUT}）"
else
  sleep 0.5
  if alive "$APP10"; then NO "失败退出后 App 进程还在（pid ${APP10}）"; else OK "App 进程已被 trap 清理"; fi
  if alive "$SRV10"; then
    NO "失败退出后服务进程还在（pid ${SRV10}）"
    kill -9 "$SRV10" 2>/dev/null
  else
    OK "服务进程已被 trap 清理"
  fi
fi

# ---------------------------------------------------------------- 11 缺启动时刻
echo "11. 记录里没有启动时刻：拒绝回收（不再靠 pid+端口硬杀）"
L11A="$TMP/nostart-a.log"; L11B="$TMP/nostart-b.log"
A11=$(launch_app "$L11A" HS_APP_QUIT_AFTER=60); record_srv "$L11A"
PA11=$(wait_log "$L11A" "load http://127.0.0.1:" 15 && port_from_log "$L11A")
SRV11=$( [ -n "$PA11" ] && pid_on_port "$PA11" )
if [ -z "${SRV11:-}" ]; then
  NO "A11 的服务没起来，跳过本项"
else
  # 删掉 started 字段，模拟「取不到启动时刻」的记录
  /usr/bin/python3 - "$LOCK_DIR/$A11.json" <<'PY'
import json, sys
p = sys.argv[1]
d = json.load(open(p))
d.pop("started", None)
json.dump(d, open(p, "w"))
PY
  kill -9 "$A11" 2>/dev/null
  sleep 1
  B11=$(launch_app "$L11B" HS_APP_QUIT_AFTER=6); record_srv "$L11B"
  if wait_log "$L11B" "没有启动时刻" 15; then OK "识别出记录缺少启动时刻"; else NO "没有对缺失启动时刻做拦截"; fi
  sleep 0.5
  if alive "$SRV11"; then OK "缺启动时刻 → 没有杀掉那个进程"; else NO "仍然把它杀了（拦截没生效）"; fi
  if [ -f "$LOCK_DIR/$A11.json" ]; then OK "记录被保留（便于事后排查）"; else NO "把取证用的记录删了"; fi
  wait_log "$L11B" "stopping server" 14
  kill -9 "$SRV11" 2>/dev/null
  rm -f "$LOCK_DIR/$A11.json"
fi

echo
if [ "$fail" -eq 0 ]; then
  echo "结果：应用场景回归全部通过（11 组）"
else
  echo "结果：有失败项，日志在 $TMP/"
fi
exit "$fail"
