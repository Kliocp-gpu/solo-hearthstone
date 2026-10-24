"""接口层回归：错误码、失败原因、失败时局面不变

为什么单独有这一层：test_cards.py 验的是「规则对不对」，selftest 验的是「会不会崩」，
但网页对战走的是 HTTP —— 动作失败时到底给用户什么反馈、局面有没有被悄悄改掉，
这两件事只有从接口这一层才测得出来。每修一个交互问题，就在这里留一条能复现的检查。

用法：python3 test_api.py
"""
import json
import threading
import urllib.error
import urllib.request
from http.server import HTTPServer

import serve  # 会在导入时加载卡池

ok = fail = 0


def check(name, cond, detail=""):
    global ok, fail
    if cond:
        ok += 1
        print(f"  ✓ {name}")
    else:
        fail += 1
        print(f"  ✗ {name}  {detail}")


def start_server():
    srv = HTTPServer(("127.0.0.1", 0), serve.H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, srv.server_address[1]


def api(port, path, body=None):
    """返回 (http_code, json)。body 为 None 时发 GET。"""
    url = f"http://127.0.0.1:{port}{path}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"},
        method="POST" if body is not None else "GET")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(req, timeout=10) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            return e.code, json.loads(raw or b"{}")
        except Exception:
            return e.code, {"raw": raw.decode("utf-8", "replace")}


def signature(st):
    """局面指纹：拿它比对「失败之后局面有没有被改动」"""
    if not st:
        return None
    me = st["me"]
    return (me["hp"], me["mana"], me["max_mana"], len(me["hand"]),
            len(me["board"]), me["deck"], len(st.get("log") or []))


def fresh(port, cls="MAGE"):
    """固定种子 + 固定卡组开局，方便复现"""
    return api(port, "/api/start", {
        "cls": cls,
        "seed": 12345,
        "deck": ["VAN_CS2_182"] * 30,      # 全是 4 费雪人：法力不够 / 手牌位置都好构造
    })


def main():
    srv, port = start_server()
    try:
        print("=== 没有对局时的错误 ===")
        code, r = api(port, "/api/state")
        check("未开局时 /api/state 返回 400 + no_game",
              code == 400 and r.get("error", {}).get("code") == "no_game", f"{code} {r}")
        code, r = api(port, "/api/play", {"idx": 0})
        check("未开局时出牌返回 no_game 而不是静默失败",
              code == 400 and r["error"]["code"] == "no_game", f"{code} {r}")
        check("错误响应里有可读原因",
              isinstance(r["error"].get("message"), str) and r["error"]["message"],
              r)

        print("=== 开局参数校验 ===")
        code, r = api(port, "/api/start", {"cls": "NOT_A_CLASS"})
        check("未知职业 → 400 bad_request",
              code == 400 and r["error"]["code"] == "bad_request", f"{code} {r}")
        code, r = api(port, "/api/start", {"deck": "not-a-list"})
        check("deck 不是数组 → 400 bad_request",
              code == 400 and r["error"]["code"] == "bad_request", f"{code} {r}")

        code, r = fresh(port)
        check("合法开局返回 ok + state",
              code == 200 and r.get("ok") and r.get("state"), f"{code} {r}")
        g = serve.STATE["game"]

        print("=== 出牌失败：给原因，且局面不变 ===")
        before = signature(api(port, "/api/state")[1]["state"])
        code, r = api(port, "/api/play", {"idx": 99})
        check("手牌位置越界 → 400",
              code == 400 and r["error"]["code"] == "illegal_play", f"{code} {r}")
        check("原因明确（手牌位置无效）", "手牌位置" in r["error"]["message"],
              r["error"]["message"])
        check("失败响应带回 state（前端才能保持原样）", bool(r.get("state")), r)
        check("越界出牌后局面没有任何变化",
              signature(r["state"]) == before, f"{before} → {signature(r['state'])}")

        # 0 费幸运币不在手（先手没有），手上全是 4 费雪人，起始 1 费 → 必定打不出
        code, r = api(port, "/api/play", {"idx": 0})
        check("法力不够 → 400 且说明差多少",
              code == 400 and "法力水晶" in r["error"]["message"], f"{code} {r}")
        check("法力不够时局面不变（不扣费、不掉牌）",
              signature(r["state"]) == before, f"{before} → {signature(r['state'])}")

        print("=== 攻击失败：给原因 ===")
        code, r = api(port, "/api/attack", {"src": 3, "target": {"side": "foe", "i": 0}})
        check("随从位置越界 → 400 bad_source",
              code == 400 and r["error"]["code"] == "bad_source", f"{code} {r}")
        # 手上只有雪人，先给场上放一个随从再测「本回合不能攻击」
        g.players[0].mana = 10
        code, r = api(port, "/api/play", {"idx": 0})
        code, r = api(port, "/api/attack", {"src": 0, "target": {"side": "foe", "i": -1}})
        check("刚出的随从攻击英雄 → 400 且说明原因",
              code == 400 and ("攻击" in r["error"]["message"]
                               or "嘲讽" in r["error"]["message"]), f"{code} {r}")
        check("攻击失败时局面不变",
              signature(r["state"]) == signature(api(port, "/api/state")[1]["state"]), r)

        print("=== 英雄技能：用过一次后拒绝 ===")
        g.players[0].mana = 10
        g.players[0].hero_power_used = False
        code, r1 = api(port, "/api/heropower", {"target": {"side": "foe", "i": -1}})
        code2, r2 = api(port, "/api/heropower", {"target": {"side": "foe", "i": -1}})
        check("第一次英雄技能成功", code == 200 and r1.get("ok"), f"{code} {r1}")
        check("第二次 → 400 且说明「已经用过」",
              code2 == 400 and "已经用过" in r2["error"]["message"], f"{code2} {r2}")

        print("=== 不是你的回合 ===")
        g.turn = 1
        code, r = api(port, "/api/play", {"idx": 0})
        check("对手回合出牌 → 400 not_your_turn",
              code == 400 and r["error"]["code"] == "not_your_turn", f"{code} {r}")
        check("对手回合的拒绝也带回 state", bool(r.get("state")), r)
        g.turn = 0

        print("=== 对局结束 ===")
        g.over, g.winner = True, "你"
        code, r = api(port, "/api/play", {"idx": 0})
        check("结束后操作 → 400 game_over",
              code == 400 and r["error"]["code"] == "game_over", f"{code} {r}")
        g.over, g.winner = False, None

        print("=== AI 崩了也不能把局面卡死 ===")
        real = serve.ai.ai_turn
        serve.ai.ai_turn = lambda _g: (_ for _ in ()).throw(RuntimeError("boom"))
        try:
            code, r = api(port, "/api/end", {})
            check("AI 抛异常 → 500 且错误码是 ai_error",
                  code == 500 and r["error"]["code"] == "ai_error", f"{code} {r}")
            check("异常信息可读", "boom" in r["error"]["message"], r["error"]["message"])
            check("回合被交回玩家（不卡在对手回合）",
                  r.get("state") and r["state"]["cur"] == 0, r.get("state", {}).get("cur"))
            code2, r2 = api(port, "/api/play", {"idx": 0})
            check("报错之后玩家仍然能继续操作",
                  code2 in (200, 400) and r2["error"]["code"] != "not_your_turn"
                  if code2 == 400 else True, f"{code2} {r2.get('error')}")
        finally:
            serve.ai.ai_turn = real

        print("=== 未知接口 ===")
        code, r = api(port, "/api/nope", {})
        check("未知接口 → 404 not_found",
              code == 404 and r["error"]["code"] == "not_found", f"{code} {r}")
        code, r = api(port, "/api/nope")
        check("未知 GET 接口也返回 JSON 错误",
              code == 404 and r["error"]["code"] == "not_found", f"{code} {r}")

        print("=== 正常流程仍然通 ===")
        fresh(port)
        code, r = api(port, "/api/end", {})
        check("结束回合返回 ok 且带回 state",
              code == 200 and r.get("ok") and r.get("state"), f"{code} {r}")
        check("AI 走完后轮到玩家",
              r["state"]["cur"] == 0, r["state"].get("cur"))
    finally:
        srv.shutdown()

    print(f"\n结果：{ok} 通过 / {fail} 失败")
    return 1 if fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
