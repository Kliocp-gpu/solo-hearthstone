"""Minimal local server: Python standard library only, zero dependencies.

Run: python3 serve.py   then open http://localhost:8765
"""
import json, os, random, sys
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse

import engine
import cards  # noqa: F401
import ai

PORT = int(os.environ.get("PORT", 8765))
STATIC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
CARDS = engine.CARDS
CLASSES = ["MAGE", "PRIEST", "WARLOCK", "PALADIN", "WARRIOR", "DRUID",
           "ROGUE", "HUNTER", "SHAMAN", "DEMONHUNTER", "DEATHKNIGHT"]

CLASS_CN = {
    "MAGE": "法师", "PRIEST": "牧师", "WARLOCK": "术士", "PALADIN": "圣骑士",
    "WARRIOR": "战士", "DRUID": "德鲁伊", "ROGUE": "潜行者", "HUNTER": "猎人",
    "SHAMAN": "萨满祭司", "DEMONHUNTER": "恶魔猎手", "DEATHKNIGHT": "死亡骑士",
    "NEUTRAL": "中立",
}

# Actual behaviour of each hero power in this simplified engine.
# The text describes what the code really does, not the official card name.
HERO_POWER_CN = {
    "MAGE": "火焰冲击：造成1点伤害",
    "PRIEST": "次级治疗术：恢复2点生命",
    "WARRIOR": "护甲值：获得2点护甲",
    "DRUID": "变形：本回合+1攻击力，并获得1点护甲",
    "WARLOCK": "简化技能：造成1点伤害",
    "PALADIN": "简化技能：造成1点伤害",
    "ROGUE": "简化技能：造成1点伤害",
    "HUNTER": "简化技能：造成1点伤害",
    "SHAMAN": "简化技能：造成1点伤害",
    "DEMONHUNTER": "简化技能：造成1点伤害",
    "DEATHKNIGHT": "简化技能：造成1点伤害",
}

STATE = {"game": None, "deck": None}
DECK_SIZE = 30


def playable():
    return [cid for cid, d in CARDS.items()
            if d.get("type") in ("MINION", "SPELL", "WEAPON") and not d.get("token")]


def collectible_classes():
    """Classes that actually have cards in this pool.

    Only 9 of the 11 class ids have class cards here; Death Knight and Demon
    Hunter have none, so offering them would give a deck of neutrals plus a
    bogus hero power.
    """
    out = []
    for c in CLASSES:
        n = sum(1 for cid, d in CARDS.items()
                if d.get("cls") == c and not d.get("token"))
        if n >= 20:
            out.append(c)
    return out


def deck_error(deck, cls):
    """Validate a deck on the server; returns (code, message), or (None, None).

    Front-end limits are UX only. Legality is decided here: exact size, card
    ids exist, no tokens, class ownership, 1 copy per legendary, 2 otherwise.
    """
    if not isinstance(deck, list):
        return "bad_request", "deck 必须是卡牌 id 的数组"
    if len(deck) != DECK_SIZE:
        return "invalid_deck", f"卡组必须正好 {DECK_SIZE} 张，现在是 {len(deck)} 张"
    cnt = {}
    for cid in deck:
        if not isinstance(cid, str) or cid not in CARDS:
            return "invalid_deck", f"卡组里有不存在的卡牌：{cid!r}"
        d = CARDS[cid]
        name = d.get("name", cid)
        if d.get("token"):
            return "invalid_deck", f"「{name}」是衍生牌，不能放进卡组"
        if d.get("type") not in ("MINION", "SPELL", "WEAPON"):
            return "invalid_deck", f"「{name}」不是可收集卡牌"
        if d.get("cls") not in (cls, "NEUTRAL"):
            own = CLASS_CN.get(d.get("cls"), d.get("cls"))
            return "invalid_deck", f"「{name}」是{own}职业牌，不能放进{CLASS_CN.get(cls, cls)}卡组"
        cnt[cid] = cnt.get(cid, 0) + 1
        limit = 1 if d.get("rarity") == "LEGENDARY" else 2
        if cnt[cid] > limit:
            return "invalid_deck", f"「{name}」最多带 {limit} 张"
    return None, None


def random_deck(rng, cls=None, n=30):
    pool = playable()
    if cls:
        sub = [c for c in pool if CARDS[c].get("cls") in (cls, "NEUTRAL")]
        if len(sub) >= 20:
            pool = sub
    deck, cnt = [], {}
    for _ in range(600):                      # 1 copy per legendary, 2 otherwise
        if len(deck) >= n:
            break
        cid = rng.choice(pool)
        lim = 1 if CARDS.get(cid, {}).get("rarity") == "LEGENDARY" else 2
        if cnt.get(cid, 0) >= lim:
            continue
        cnt[cid] = cnt.get(cid, 0) + 1
        deck.append(cid)
    while len(deck) < n:                      # fallback for a narrow pool; limits still apply
        added = False
        for cid in pool:
            lim = 1 if CARDS.get(cid, {}).get("rarity") == "LEGENDARY" else 2
            while cnt.get(cid, 0) < lim and len(deck) < n:
                cnt[cid] = cnt.get(cid, 0) + 1
                deck.append(cid)
                added = True
            if len(deck) >= n:
                break
        if not added:                         # unreachable: the pool holds far more than 30
            break
    return deck


def resolve_target(g, t):
    """Resolve the front-end {side, i} reference into an entity; i=-1 means the hero."""
    if not t:
        return None
    p = g.players[0] if t.get("side") == "me" else g.players[1]
    i = t.get("i", -1)
    if i < 0:
        return p
    if i < len(p.board):
        return p.board[i]
    return None


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        data = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _json(self, obj, code=200):
        self._send(code, json.dumps(obj, ensure_ascii=False))

    # ---------- Uniform responses ----------
    def _ok(self, g, **kw):
        """Success: always carry state back so the client can redraw."""
        return self._json(dict(ok=True,
                               state=g.state(0) if g else None,
                               hp_used=g.players[0].hero_power_used if g else False,
                               **kw))

    def _err(self, code, message, g=None, status=400):
        """Failure: error code + human-readable reason, plus the current state.

        Codes fall into three groups so the client can react differently:
          * no_game / not_your_turn / game_over - the session is not playable
          * bad_* / illegal_* - this action is invalid (recoverable, keep selection)
          * server_error / ai_error - the server broke (offer restart / refresh)
        """
        body = dict(ok=False, error=dict(code=code, message=message))
        if g is not None:
            body["state"] = g.state(0)
            body["hp_used"] = g.players[0].hero_power_used
        return self._json(body, status)

    def _act_failed(self, g, code, default_msg):
        """Talk back with the reason the engine recorded when an action returned False."""
        return self._err(code, g.last_error or default_msg, g)

    # ---------- GET ----------
    def do_GET(self):
        u = urlparse(self.path)
        path = u.path

        if path in ("/", "/index.html"):
            html = open(os.path.join(STATIC, "index.html"), encoding="utf-8").read()
            return self._send(200, html, "text/html; charset=utf-8")

        if path == "/api/cards":
            cls = None
            for kv in u.query.split("&"):
                if kv.startswith("cls="):
                    cls = kv[4:]
            out = []
            for cid, d in CARDS.items():
                if d.get("token"):          # 衍生牌不进组卡池
                    continue
                if cls and d.get("cls") not in (cls, "NEUTRAL"):
                    continue
                out.append(dict(cid=cid, name=d.get("name"), cost=d.get("cost", 0),
                                atk=d.get("atk"), hp=d.get("hp"),
                                type=d.get("type"), cls=d.get("cls"),
                                text=d.get("text", ""),
                                rarity=d.get("rarity", "COMMON"),
                                races=d.get("races") or [],
                                ok=d.get("implemented", True),
                                partial=d.get("partial", False)))
            out.sort(key=lambda x: (x["cost"], x["name"] or ""))
            classes = [dict(id=c, name=CLASS_CN.get(c, c)) for c in collectible_classes()]
            return self._json(dict(cards=out, classes=classes, hero_powers=HERO_POWER_CN))

        if path == "/api/state":
            g = STATE["game"]
            if not g:
                return self._err("no_game", "还没有开始对局")
            return self._json(dict(state=g.state(0), hp_used=g.players[0].hero_power_used))

        if path.startswith("/api/"):
            return self._err("not_found", f"没有这个接口：{path}", STATE["game"], status=404)
        return self._send(404, "not found", "text/plain")

    # ---------- POST ----------
    def do_POST(self):
        path = urlparse(self.path).path
        try:
            n = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(n) or b"{}")
        except Exception:
            return self._err("bad_request", "请求体不是合法 JSON")
        if not isinstance(body, dict):
            return self._err("bad_request", "请求体必须是 JSON 对象")

        try:
            return self._route(path, body)
        except Exception as ex:                    # 任何没预料到的异常都不能变成空响应
            import traceback
            traceback.print_exc()
            return self._err("server_error", f"服务端异常：{type(ex).__name__}: {ex}",
                             STATE["game"], status=500)

    def _route(self, path, body):
        g = STATE["game"]

        if path == "/api/start":
            deck = body.get("deck")
            cls = body.get("cls") or "MAGE"
            if cls not in collectible_classes():
                return self._err("bad_request",
                                 f"未知或没有卡牌的职业：{cls}")
            if deck is not None:
                code, why = deck_error(deck, cls)
                if code:
                    return self._err(code, why)
            # The seed drives shuffling, the AI deck and the AI class.
            # Returning it lets the same game be reproduced exactly.
            seed = body.get("seed")
            if seed is None:
                seed = random.randrange(1 << 30)
            rng = random.Random(seed)
            if not deck:
                deck = random_deck(rng, cls)
            ai_cls = rng.choice(collectible_classes())      # 先定职业，再按职业发牌
            ai_deck = random_deck(rng, ai_cls)
            g = engine.Game(("你", f"AI（{CLASS_CN.get(ai_cls, ai_cls)}）"),
                            (deck, ai_deck), seed=seed)
            g.players[0].cls = cls
            g.players[1].cls = ai_cls
            g.start_turn()
            STATE["game"], STATE["deck"] = g, deck
            return self._ok(g, msg="开局", seed=seed, ai_cls=ai_cls)

        if path == "/api/random_deck":
            rng = random.Random()
            cls = body.get("cls")
            return self._json(dict(deck=random_deck(rng, cls)))

        # Everything below needs a game in progress
        if path not in ("/api/play", "/api/heropower", "/api/heroattack",
                        "/api/attack", "/api/end"):
            return self._err("not_found", f"没有这个接口：{path}", g, status=404)
        if not g:
            return self._err("no_game", "还没有开始对局")
        if g.over:
            return self._err("game_over", "对局已经结束，请点「返回组卡」重新开局", g)
        if g.cur is not g.players[0]:
            return self._err("not_your_turn", "现在是对手的回合", g)

        if path == "/api/play":
            try:
                idx = int(body.get("idx", -1))
            except (TypeError, ValueError):
                return self._err("bad_request", "idx 必须是整数", g)
            tgt = resolve_target(g, body.get("target"))
            if body.get("target") and tgt is None:
                return self._err("bad_target", "目标已不在场上", g)
            ch = body.get("choice")
            r = g.play_card(g.players[0], idx, tgt,
                            choice=int(ch) if ch is not None else None)
            if not r:
                return self._act_failed(g, "illegal_play", "这张牌现在打不出去")
            return self._ok(g, msg="出牌")

        if path == "/api/heropower":
            tgt = resolve_target(g, body.get("target"))
            if body.get("target") and tgt is None:
                return self._err("bad_target", "目标已不在场上", g)
            r = g.hero_power(g.players[0], tgt)
            if not r:
                return self._act_failed(g, "illegal_power", "英雄技能现在用不了")
            return self._ok(g, msg="技能")

        if path == "/api/heroattack":
            tgt = resolve_target(g, body.get("target")) or g.players[1]
            r = g.hero_attack(g.players[0], tgt)
            if not r:
                return self._act_failed(g, "illegal_attack", "英雄现在不能攻击")
            return self._ok(g, msg="英雄攻击")

        if path == "/api/attack":
            try:
                i = int(body.get("src", -1))
            except (TypeError, ValueError):
                return self._err("bad_request", "src 必须是整数", g)
            me = g.players[0]
            if i < 0 or i >= len(me.board):
                return self._err("bad_source", "发起攻击的随从已不在场上", g)
            tgt = resolve_target(g, body.get("target")) or g.players[1]
            r = g.attack(me.board[i], tgt)
            if not r:
                return self._act_failed(g, "illegal_attack", "这个随从现在不能攻击")
            return self._ok(g, msg="攻击")

        if path == "/api/end":
            g.end_turn()                 # 切到 AI
            if not g.over:
                try:
                    ai.ai_turn(g)        # AI 走完（内部会切回玩家）
                except Exception as ex:
                    # Never leave the game stuck in the AI's turn:
                    # hand the turn back and report the failure.
                    import traceback
                    traceback.print_exc()
                    if not g.over and g.cur is not g.players[0]:
                        g.turn += 1
                    return self._err("ai_error",
                                     f"AI 回合出错（{type(ex).__name__}: {ex}），已把回合交回，可以继续操作",
                                     g, status=500)
            return self._ok(g, msg="结束回合")

        return self._err("not_found", f"没有这个接口：{path}", g, status=404)


def main():
    print(f"卡池 {len(CARDS)} 张 | 启动 http://localhost:{PORT}")
    print("Ctrl-C 退出")
    HTTPServer(("127.0.0.1", PORT), H).serve_forever()


if __name__ == "__main__":
    main()
