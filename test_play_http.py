"""Full-game regression over the HTTP API.

Why this exists: test_cards.py calls the engine directly, selftest.py calls
ai_turn directly, and test_api.py checks error contracts on hand-made states.
None of them plays a whole game the way the browser does -- JSON in, JSON out,
targets resolved by index, turn guard in between. This file drives complete
games through /api/* until someone wins and asserts the invariants hold the
whole way.

Usage: python3 test_play_http.py
"""
import json
import random
import threading
import urllib.error
import urllib.request
from http.server import HTTPServer

import serve

ok = fail = 0
MAX_ACTIONS = 400
MAX_HAND = 10
MAX_BOARD = 7


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
    url = f"http://127.0.0.1:{port}{path}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"},
        method="POST" if body is not None else "GET")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(req, timeout=15) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            return e.code, json.loads(raw or b"{}")
        except Exception:
            return e.code, {"raw": raw.decode("utf-8", "replace")}


def next_action(resp):
    """A deliberately simple player: spend mana, attack, use the power, end turn."""
    st = resp["state"]
    me = st["me"]

    playable = [i for i, c in enumerate(me["hand"]) if c.get("playable")]
    if playable:
        i = max(playable, key=lambda j: me["hand"][j]["cost"])
        card = me["hand"][i]
        body = {"idx": i, "target": None}
        if card.get("choose"):
            body["choice"] = 0
        return "/api/play", body

    ready = [i for i, m in enumerate(me["board"])
             if m.get("attackable") and m.get("atk", 0) > 0]
    if ready:
        board = st["foe"]["board"]
        # Prefer a visible taunt, otherwise the first minion, otherwise the hero.
        # Stealthed taunts cannot be chosen, so they are skipped.
        taunts = [i for i, m in enumerate(board)
                  if m.get("taunt") and not m.get("stealth")]
        if taunts:
            tgt = {"side": "foe", "i": taunts[0]}
        elif board:
            tgt = {"side": "foe", "i": 0}
        else:
            tgt = {"side": "foe", "i": -1}
        return "/api/attack", {"src": ready[0], "target": tgt}

    if not resp.get("hp_used") and me["mana"] >= 2:
        return "/api/heropower", {"target": {"side": "foe", "i": -1}}

    return "/api/end", {}


def play_one(port, seed, verbose=False):
    """Play a full game over HTTP; returns a dict of findings."""
    deck = serve.random_deck(random.Random(seed), "MAGE")
    code, resp = api(port, "/api/start", {"cls": "MAGE", "deck": deck, "seed": seed})
    if code != 200:
        return {"start_failed": (code, resp)}

    errors = []          # 5xx responses
    rejected = []        # 4xx responses (expected sometimes: taunt, stealth, mana)
    violations = []      # broken invariants
    actions = 0
    last_turn = resp["state"]["turn"]

    while not resp["state"]["over"] and actions < MAX_ACTIONS:
        path, body = next_action(resp)
        code, r2 = api(port, path, body)
        actions += 1

        st = r2.get("state") or resp["state"]
        me = st["me"]
        if len(me["hand"]) > MAX_HAND:
            violations.append(f"hand={len(me['hand'])}")
        if len(me["board"]) > MAX_BOARD:
            violations.append(f"board={len(me['board'])}")
        if me["mana"] > 10 or me["max_mana"] > 10:
            violations.append(f"mana={me['mana']}/{me['max_mana']}")
        if code >= 500:
            errors.append((path, body, code, (r2.get("error") or {}).get("code")))
            break
        if code == 400:
            rejected.append(((r2.get("error") or {}).get("code"), path))
            # Do not spin on the same rejected action: end the turn instead
            if path != "/api/end":
                code, r2 = api(port, "/api/end", {})
                st = r2.get("state") or st
                if code >= 500:
                    errors.append(("/api/end", {}, code, "after-400"))
                    break
        resp = r2 if "state" in r2 else resp

        if st["turn"] != last_turn and st["cur"] not in (0, None) and not st["over"]:
            violations.append(f"turn={st['turn']} cur={st['cur']}")
        last_turn = st["turn"]

    st = resp["state"]
    card_errors = [l for l in (st.get("log") or [])
                   if "[card-error]" in l or "[dr-error]" in l]
    return {
        "over": st["over"],
        "winner": st.get("winner"),
        "turn": st["turn"],
        "actions": actions,
        "errors": errors,
        "rejected": rejected,
        "violations": violations,
        "card_errors": card_errors,
        "log_tail": (st.get("log") or [])[-3:],
    }


def main():
    srv, port = start_server()
    try:
        for seed in (1, 7, 42):
            print(f"=== 完整对局 seed={seed} ===")
            r = play_one(port, seed)
            if "start_failed" in r:
                check(f"seed={seed} 开局成功", False, r["start_failed"])
                continue
            check(f"seed={seed}：整局没有任何 5xx",
                  not r["errors"], r["errors"][:2])
            check(f"seed={seed}：没有卡效果或亡语报错",
                  not r["card_errors"], r["card_errors"][:2])
            check(f"seed={seed}：局面不变量始终成立（手牌/场上/法力）",
                  not r["violations"], r["violations"][:3])
            check(f"seed={seed}：对局在 {MAX_ACTIONS} 步内结束",
                  r["over"], f"actions={r['actions']} turn={r['turn']}")
            check(f"seed={seed}：产生了明确的胜者",
                  r["winner"] in ("你",) or bool(r["winner"]), r["winner"])
            if r["rejected"]:
                codes = sorted({c for c, _ in r["rejected"]})
                print(f"      （过程中有 {len(r['rejected'])} 次合法拒绝：{codes}）")

        print("=== 对局结束后接口的行为 ===")
        code, r = api(port, "/api/play", {"idx": 0})
        check("对局结束后出牌 → 400 game_over",
              code == 400 and r["error"]["code"] == "game_over", f"{code} {r.get('error')}")
        code, r = api(port, "/api/state")
        check("对局结束后仍能读到最终局面",
              code == 200 and r["state"]["over"], code)
    finally:
        srv.shutdown()

    print(f"\n结果：{ok} 通过 / {fail} 失败")
    return 1 if fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
