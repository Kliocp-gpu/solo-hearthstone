"""极简本地服务器：Python 标准库，零第三方依赖
启动：python3 serve.py  然后浏览器打开 http://localhost:8765
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

# 英雄技能按职业简化后的实际效果（写实际行为，不套官方名以免误导）
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


def playable():
    return [cid for cid, d in CARDS.items()
            if d.get("type") in ("MINION", "SPELL", "WEAPON") and not d.get("token")]


def random_deck(rng, cls=None, n=30):
    pool = playable()
    if cls:
        sub = [c for c in pool if CARDS[c].get("cls") in (cls, "NEUTRAL")]
        if len(sub) >= 20:
            pool = sub
    deck, cnt = [], {}
    for _ in range(600):                      # 传说限 1 张、其余限 2 张
        if len(deck) >= n:
            break
        cid = rng.choice(pool)
        lim = 1 if CARDS.get(cid, {}).get("rarity") == "LEGENDARY" else 2
        if cnt.get(cid, 0) >= lim:
            continue
        cnt[cid] = cnt.get(cid, 0) + 1
        deck.append(cid)
    while len(deck) < n:                      # 卡池太窄时兜底
        deck.append(rng.choice(pool))
    return deck


def resolve_target(g, t):
    """把前端传来的 {side, i} 解析成实体；i=-1 表示英雄"""
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
            classes = [dict(id=c, name=CLASS_CN.get(c, c)) for c in CLASSES]
            return self._json(dict(cards=out, classes=classes, hero_powers=HERO_POWER_CN))

        if path == "/api/state":
            g = STATE["game"]
            if not g:
                return self._json(dict(error="no game"), 400)
            return self._json(dict(state=g.state(0), hp_used=g.players[0].hero_power_used))

        return self._send(404, "not found", "text/plain")

    # ---------- POST ----------
    def do_POST(self):
        path = urlparse(self.path).path
        try:
            n = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(n) or b"{}")
        except Exception:
            body = {}
        g = STATE["game"]

        def ok(**kw):
            return self._json(dict(ok=True, state=g.state(0) if g else None,
                                   hp_used=g.players[0].hero_power_used if g else False, **kw))

        if path == "/api/start":
            deck = body.get("deck")
            cls = body.get("cls") or "MAGE"
            rng = random.Random(body.get("seed"))
            if not deck or len(deck) < 30:
                deck = random_deck(rng, cls)
            ai_deck = random_deck(rng, rng.choice(CLASSES))
            ai_cls = rng.choice(CLASSES)
            g = engine.Game(("你", f"AI（{CLASS_CN.get(ai_cls, ai_cls)}）"),
                            (deck, ai_deck), seed=rng.randrange(1 << 30))
            g.players[0].cls = cls
            g.players[1].cls = ai_cls
            g.start_turn()
            STATE["game"], STATE["deck"] = g, deck
            return ok(msg="开局")

        if path == "/api/random_deck":
            rng = random.Random()
            cls = body.get("cls")
            return self._json(dict(deck=random_deck(rng, cls)))

        if not g:
            return self._json(dict(error="no game"), 400)

        if path == "/api/play":
            tgt = resolve_target(g, body.get("target"))
            ch = body.get("choice")
            r = g.play_card(g.players[0], int(body.get("idx", -1)), tgt,
                            choice=int(ch) if ch is not None else None)
            return ok(msg="出牌" if r else "打不出")

        if path == "/api/heropower":
            tgt = resolve_target(g, body.get("target"))
            r = g.hero_power(g.players[0], tgt)
            return ok(msg="技能" if r else "用不了")

        if path == "/api/heroattack":
            tgt = resolve_target(g, body.get("target")) or g.players[1]
            r = g.hero_attack(g.players[0], tgt)
            return ok(msg="英雄攻击" if r else "不能攻击")

        if path == "/api/attack":
            i = int(body.get("src", -1))
            me = g.players[0]
            if i < 0 or i >= len(me.board):
                return ok(msg="无效")
            tgt = resolve_target(g, body.get("target")) or g.players[1]
            r = g.attack(me.board[i], tgt)
            return ok(msg="攻击" if r else "不能攻击")

        if path == "/api/end":
            g.end_turn()                 # 切到 AI
            if not g.over:
                ai.ai_turn(g)            # AI 走完（内部会切回玩家）
            return ok(msg="结束回合")

        return self._send(404, "not found", "text/plain")


def main():
    print(f"卡池 {len(CARDS)} 张 | 启动 http://localhost:{PORT}")
    print("Ctrl-C 退出")
    HTTPServer(("127.0.0.1", PORT), H).serve_forever()


if __name__ == "__main__":
    main()
