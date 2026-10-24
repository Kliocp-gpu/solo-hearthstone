"""Static checks for the single-file front end.

There is no browser in the test loop, so the cheapest useful guard is a static
one: every element the script looks up must exist in the markup, and every
handler referenced from markup must be defined. This catches the most common
breakage when editing index.html by hand (renamed or newly added ids).

Usage: python3 test_ui.py
"""
import re

ok = fail = 0
HTML = "static/index.html"


def check(name, cond, detail=""):
    global ok, fail
    if cond:
        ok += 1
        print(f"  ✓ {name}")
    else:
        fail += 1
        print(f"  ✗ {name}  {detail}")


def main():
    src = open(HTML, encoding="utf-8").read()
    js = re.search(r"<script>([\s\S]*)</script>", src).group(1)

    ids_defined = set(re.findall(r'id="([^"]+)"', src))
    ids_used = set(re.findall(r"getElementById\(['\"]([^'\"]+)['\"]\)", js))
    missing = sorted(ids_used - ids_defined)
    check("脚本里用到的每个 id 都在页面里存在", not missing, missing)

    handlers_used = set(re.findall(r'on(?:click|input|change)="([A-Za-z_$][\w$]*)\(', src))
    funcs_defined = set(re.findall(r"function\s+([A-Za-z_$][\w$]*)\s*\(", js))
    funcs_defined |= set(re.findall(r"(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?\(", js))
    undefined = sorted(h for h in handlers_used if h not in funcs_defined)
    check("markup 里引用的每个事件处理函数都有定义", not undefined, undefined)

    check("关键交互函数齐全",
          {"pick", "selHand", "selHero", "startGame", "backToDeck", "endTurn",
           "usePower", "add", "remove", "clearDeck", "drawPool",
           "pickChoice", "closeChoose"} <= funcs_defined,
          sorted({"pick", "selHand", "selHero", "startGame", "backToDeck", "endTurn",
                  "usePower", "add", "remove", "clearDeck", "drawPool",
                  "pickChoice", "closeChoose"} - funcs_defined))

    # 组卡筛选器：三个控件都在，且 drawPool 会读取它们
    for eid in ("q", "fcost", "frar", "poolCount", "cntHint", "again"):
        check(f"筛选/结算相关元素存在：#{eid}", eid in ids_defined)

    check("drawPool 读取了搜索框与两个筛选器",
          all(k in js for k in ("getElementById('q')", "getElementById('fcost')",
                                "getElementById('frar')")))

    # 卡牌 tile 的 onclick 只在可加入时才拼接，避免生成空 onclick
    check("卡牌 tile 的可点击性由 click 变量决定",
          "const click = full ? '' :" in js and "${click}" in js)

    # 刷新页面接回对局 / App 外壳的端口占用提示 / 对局保留说明
    check("页面加载时会查询 /api/state 接回对局",
          "async function resumeGame" in js and "api('/api/state')" in js
          and "resumeGame()" in js)
    check("组卡视图说明了「对局只保留在本次运行内」",
          "persistNote" in ids_defined and "退出 App 会丢" in src)
    check("卡牌都带职业色标（中立=灰标，职业=职业色）",
          "function clsTag" in js and "clsTag(c)" in js
          and "'中立'" in js and "k-${c.cls" in js)
    check("卡组列表的每一行也带职业色标",
          "clsTag(c)" in js and "${c.cost} 费${clsTag(c)}" in js)
    check("App 外壳传来的 ?warn= 会被显示成提示条",
          "URLSearchParams(location.search)" in js and "get('warn')" in js)

    print(f"\n结果：{ok} 通过 / {fail} 失败")
    return 1 if fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
