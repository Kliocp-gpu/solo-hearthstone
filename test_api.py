"""HTTP-layer regression: error codes, failure reasons, and state preserved on failure.

为什么单独有这一层：test_cards.py 验的是「规则对不对」，selftest 验的是「会不会崩」，
但网页对战走的是 HTTP —— 动作失败时到底给用户什么反馈、局面有没有被悄悄改掉，
这两件事只有从接口这一层才测得出来。每修一个交互问题，就在这里留一条能复现的检查。

用法：python3 test_api.py
"""
import json
import random
import socket
import threading
import time
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

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
    # 必须和 serve.main() 用同一种服务器：单线程版本会被一条挂着的连接卡死
    srv = ThreadingHTTPServer(("127.0.0.1", 0), serve.H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, srv.server_address[1]


def api(port, path, body=None):
    """Return (http_code, json). A None body sends a GET."""
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
    """State fingerprint: used to prove a failed action changed nothing."""
    if not st:
        return None
    me = st["me"]
    return (me["hp"], me["mana"], me["max_mana"], len(me["hand"]),
            len(me["board"]), me["deck"], len(st.get("log") or []))


def legal_deck(cls="MAGE", n=30):
    """Build a legal deck: 15 non-legendary cards, two copies each."""
    pool = [cid for cid, d in serve.CARDS.items()
            if not d.get("token")
            and d.get("type") in ("MINION", "SPELL", "WEAPON")
            and d.get("cls") in (cls, "NEUTRAL")
            and d.get("rarity") != "LEGENDARY"]
    deck = []
    for cid in pool:
        deck.extend([cid, cid])
        if len(deck) >= n:
            break
    return deck[:n]


def fresh(port, cls="MAGE", seed=12345):
    """Start a game with a fixed seed and a legal deck so runs are reproducible."""
    return api(port, "/api/start", {"cls": cls, "seed": seed, "deck": legal_deck(cls)})


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
        code, r = api(port, "/api/start", {"cls": "DEATHKNIGHT",
                                           "deck": legal_deck("MAGE")})
        check("当前卡池没有职业牌的职业被拒绝",
              code == 400 and r["error"]["code"] == "bad_request", f"{code} {r}")
        code, r = api(port, "/api/start", {"deck": "not-a-list"})
        check("deck 不是数组 → 400 bad_request",
              code == 400 and r["error"]["code"] == "bad_request", f"{code} {r}")

        print("=== 牌组合法性（服务端校验）===")
        base = legal_deck("MAGE")
        code, r = api(port, "/api/start", {"cls": "MAGE", "deck": base + [base[0]]})
        check("31 张 → invalid_deck 且说明张数",
              code == 400 and r["error"]["code"] == "invalid_deck"
              and "30" in r["error"]["message"], f"{code} {r.get('error')}")
        code, r = api(port, "/api/start", {"cls": "MAGE", "deck": base[:27]})
        check("27 张 → invalid_deck", code == 400
              and r["error"]["code"] == "invalid_deck", f"{code} {r.get('error')}")

        d3 = base[:27] + [base[0]] * 3
        code, r = api(port, "/api/start", {"cls": "MAGE", "deck": d3})
        check("同一张卡 3 张 → invalid_deck 且提示上限 2",
              code == 400 and "2 张" in r["error"]["message"], f"{code} {r.get('error')}")

        legend = next(cid for cid, d in serve.CARDS.items()
                      if d.get("rarity") == "LEGENDARY" and d.get("cls") in ("MAGE", "NEUTRAL"))
        dleg = base[:28] + [legend, legend]
        code, r = api(port, "/api/start", {"cls": "MAGE", "deck": dleg})
        check("传说带 2 张 → invalid_deck 且提示上限 1",
              code == 400 and "1 张" in r["error"]["message"], f"{code} {r.get('error')}")

        priest = next(cid for cid, d in serve.CARDS.items()
                      if d.get("cls") == "PRIEST" and not d.get("token"))
        dcls = base[:29] + [priest]
        code, r = api(port, "/api/start", {"cls": "MAGE", "deck": dcls})
        check("别职业的卡 → invalid_deck 且点名职业",
              code == 400 and "不能放进" in r["error"]["message"], f"{code} {r.get('error')}")

        dno = base[:29] + ["NOT_A_CARD"]
        code, r = api(port, "/api/start", {"cls": "MAGE", "deck": dno})
        check("不存在的卡 id → invalid_deck",
              code == 400 and "不存在" in r["error"]["message"], f"{code} {r.get('error')}")

        dtok = base[:29] + ["TOKEN_BANANA"]
        code, r = api(port, "/api/start", {"cls": "MAGE", "deck": dtok})
        check("衍生牌进卡组 → invalid_deck",
              code == 400 and "衍生牌" in r["error"]["message"], f"{code} {r.get('error')}")

        code, r = fresh(port)
        check("合法卡组开局成功", code == 200 and r.get("ok") and r.get("state"),
              f"{code} {r}")
        check("开局回传 seed（可复现）", "seed" in r and r["seed"] == 12345, r.get("seed"))

        print("=== AI 卡组与职业必须一致 ===")
        g = serve.STATE["game"]
        check("AI 职业与响应里的 ai_cls 一致",
              r.get("ai_cls") == g.players[1].cls, f"{r.get('ai_cls')} vs {g.players[1].cls}")
        bad = [cid for cid in g.players[1].deck
               if serve.CARDS.get(cid, {}).get("cls") not in (g.players[1].cls, "NEUTRAL")]
        check("AI 牌库里没有别职业的牌", not bad, bad[:3])
        cnt = {}
        for cid in g.players[1].deck:
            cnt[cid] = cnt.get(cid, 0) + 1
        over = [cid for cid, n in cnt.items()
                if n > (1 if serve.CARDS[cid].get("rarity") == "LEGENDARY" else 2)]
        check("AI 牌库没有超出张数上限", not over, over[:3])
        check("AI 牌库总数没被打乱（30 = 剩余牌库 + 起手 - 幸运币）",
              len(g.players[1].deck) + len(g.players[1].hand) - 1 == 30,
              f"{len(g.players[1].deck)} + {len(g.players[1].hand)} - 1")

        # Verify the generator itself: every class x 8 seeds must yield a legal 30
        bad_gen = []
        for c in serve.collectible_classes():
            for s in range(8):
                d = serve.random_deck(random.Random(s), c)
                err = serve.deck_error(d, c)
                if err != (None, None):
                    bad_gen.append((c, s, err))
        check("随机卡组生成器对每个职业都给出合法 30 张", not bad_gen, bad_gen[:2])

        print("=== 同种子可复现 ===")
        _, r1 = fresh(port, seed=777)
        hand1 = [c["cid"] for c in r1["state"]["me"]["hand"]]
        ai_cls1 = r1["ai_cls"]
        _, r2 = fresh(port, seed=777)
        hand2 = [c["cid"] for c in r2["state"]["me"]["hand"]]
        check("同 seed 同卡组 → 起手完全一致", hand1 == hand2, f"{hand1} vs {hand2}")
        check("同 seed → AI 职业一致", ai_cls1 == r2["ai_cls"], f"{ai_cls1} vs {r2['ai_cls']}")

        print("=== 出牌失败：给原因，且局面不变 ===")
        fresh(port)                       # 换一局干净的，后面手动调法力
        g = serve.STATE["game"]
        before = signature(api(port, "/api/state")[1]["state"])
        code, r = api(port, "/api/play", {"idx": 99})
        check("手牌位置越界 → 400",
              code == 400 and r["error"]["code"] == "illegal_play", f"{code} {r}")
        check("原因明确（手牌位置无效）", "手牌位置" in r["error"]["message"],
              r["error"]["message"])
        check("失败响应带回 state（前端才能保持原样）", bool(r.get("state")), r)
        check("越界出牌后局面没有任何变化",
              signature(r["state"]) == before, f"{before} → {signature(r['state'])}")

        # Drop mana to zero so any card with cost >= 1 is unplayable
        g.players[0].mana = 0
        st = api(port, "/api/state")[1]["state"]
        idx = next(i for i, c in enumerate(st["me"]["hand"]) if c["cost"] > 0)
        before = signature(st)
        code, r = api(port, "/api/play", {"idx": idx})
        check("法力不够 → 400 且说明差多少",
              code == 400 and "法力水晶" in r["error"]["message"], f"{code} {r}")
        check("法力不够时局面不变（不扣费、不掉牌）",
              signature(r["state"]) == before, f"{before} → {signature(r['state'])}")

        print("=== 攻击失败：给原因 ===")
        code, r = api(port, "/api/attack", {"src": 3, "target": {"side": "foe", "i": 0}})
        check("随从位置越界 → 400 bad_source",
              code == 400 and r["error"]["code"] == "bad_source", f"{code} {r}")

        # Play a minion without charge to test "cannot attack the turn it is played"
        g.players[0].mana = 10
        st = api(port, "/api/state")[1]["state"]
        midx = next(i for i, c in enumerate(st["me"]["hand"])
                    if c["type"] == "MINION"
                    and not serve.CARDS[c["cid"]].get("charge"))
        code, r = api(port, "/api/play", {"idx": midx})
        check("先打出一个随从", code == 200, f"{code} {r.get('error')}")
        code, r = api(port, "/api/attack", {"src": 0, "target": {"side": "foe", "i": -1}})
        check("当回合刚出的随从攻击英雄 → 400 且说明原因",
              code == 400 and "攻击" in r["error"]["message"], f"{code} {r}")
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

        print("=== 组卡池：职业页与通用页分离 ===")
        code, r = api(port, "/api/cards?cls=MAGE")
        classes = {c["cls"] for c in r["cards"]}
        check("职业页只回本职业牌（不再混入中立）",
              code == 200 and classes == {"MAGE"}, f"{code} {classes}")
        code, r = api(port, "/api/cards?cls=NEUTRAL")
        classes = {c["cls"] for c in r["cards"]}
        check("通用页只回中立牌",
              code == 200 and classes == {"NEUTRAL"}, f"{code} {classes}")

        print("=== 正常流程仍然通 ===")
        fresh(port)
        code, r = api(port, "/api/end", {})
        check("结束回合返回 ok 且带回 state",
              code == 200 and r.get("ok") and r.get("state"), f"{code} {r}")
        check("AI 走完后轮到玩家",
              r["state"]["cur"] == 0, r["state"].get("cur"))

        print("=== 并发：一条空闲连接不该挡住别的请求 ===")
        # 起因：WKWebView 会挂着一条 keep-alive 连接，单线程 HTTPServer 会因此
        # 让所有其它客户端一直等到超时。换个多线程服务器 + 全局锁才是对的。
        idle = socket.create_connection(("127.0.0.1", port), timeout=5)
        try:
            t0 = time.time()
            code, r = api(port, "/api/state")
            dt = time.time() - t0
            check("有连接挂着不发请求时，API 仍能及时响应",
                  code in (200, 400) and dt < 3, f"code={code} 耗时 {dt:.2f}s")
        finally:
            idle.close()
    finally:
        srv.shutdown()

    print(f"\n结果：{ok} 通过 / {fail} 失败")
    return 1 if fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
