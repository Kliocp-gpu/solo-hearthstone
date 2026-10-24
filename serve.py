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

    # ---------- 统一响应 ----------
    def _ok(self, g, **kw):
        """成功：始终带上 state，前端一律据此重绘"""
        return self._json(dict(ok=True,
                               state=g.state(0) if g else None,
                               hp_used=g.players[0].hero_power_used if g else False,
                               **kw))

    def _err(self, code, message, g=None, status=400):
        """失败：带错误码 + 人话原因，并尽量附上当前局面，让前端保持原样

        错误码分三类，前端据此区分处理：
          * no_game / not_your_turn / game_over —— 局面状态不对
          * bad_* / illegal_* —— 这次操作不合法（可恢复，保留选择状态）
          * server_error —— 服务端异常（前端提示重开或刷新）
        """
        body = dict(ok=False, error=dict(code=code, message=message))
        if g is not None:
            body["state"] = g.state(0)
            body["hp_used"] = g.players[0].hero_power_used
        return self._json(body, status)

    def _act_failed(self, g, code, default_msg):
        """动作返回 False 时，用引擎记录的原因回话"""
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
            classes = [dict(id=c, name=CLASS_CN.get(c, c)) for c in CLASSES]
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
            if cls not in CLASSES:
                return self._err("bad_request", f"未知职业：{cls}")
            if deck is not None and not isinstance(deck, list):
                return self._err("bad_request", "deck 必须是卡牌 id 的数组")
            seed = body.get("seed")
            rng = random.Random(seed)
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
            return self._ok(g, msg="开局", seed=seed)

        if path == "/api/random_deck":
            rng = random.Random()
            cls = body.get("cls")
            return self._json(dict(deck=random_deck(rng, cls)))

        # 下面这些都需要一个进行中的对局
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
                    # AI 崩了不能让局面卡在对手回合里：把回合交回玩家，并明确报告
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
