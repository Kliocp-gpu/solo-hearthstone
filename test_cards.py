"""逐条验证关键卡的行为（不是数量统计，而是真跑一遍看结果）"""
import cards, engine
from engine import Game, Ctx, Minion, Player, CARDS, make_minion
import ai

ok = fail = 0


def check(name, cond, detail=""):
    global ok, fail
    if cond:
        ok += 1
        print(f"  ✓ {name}")
    else:
        fail += 1
        print(f"  ✗ {name}  {detail}")


def newgame(seed=1):
    filler = ["VAN_CS2_182"] * 20          # 雪人当牌库填充
    g = Game(("A", "B"), (list(filler), list(filler)), seed=seed)
    for p in g.players:
        p.hand = []
        p.board = []
        p.mana = p.max_mana = 10
    return g


def put(g, p, cid, **kw):
    m = make_minion(cid, CARDS[cid], p.pid)
    for k, v in kw.items():
        setattr(m, k, v)
    m.summoned_this_turn = False
    m.attacks_left = 1
    p.board.append(m)
    g.recalc()
    return m


def by_name(n):
    for cid, d in CARDS.items():
        if d["name"] == n:
            return cid
    raise KeyError(n)


print("=== 光环 / 种族 ===")
g = newgame()
p, f = g.players
wolf = put(g, p, by_name("森林狼"))
beast = put(g, p, by_name("石牙野猪"))
human = put(g, p, by_name("闪金镇步兵"))
check("森林狼让其他野兽 +1 攻", beast.atk == 2, f"atk={beast.atk}")
check("森林狼不给非野兽加成", human.atk == 1, f"atk={human.atk}")

g = newgame()
p = g.players[0]
rhino = put(g, p, by_name("苔原犀牛"))
b = put(g, p, by_name("石牙野猪"), charge=False, attacks_left=0)
check("苔原犀牛给野兽冲锋（可攻击）", b.charge and b.attacks_left > 0,
      f"charge={b.charge} left={b.attacks_left}")

g = newgame()
p = g.players[0]
put(g, p, by_name("鱼人领军"))
m1 = put(g, p, by_name("鱼人袭击者") if "鱼人袭击者" in [d["name"] for d in CARDS.values()] else by_name("暗鳞先知"))
check("鱼人领军给其他鱼人 +2 攻", m1.atk >= 3, f"atk={m1.atk} ({m1.name})")

print("=== 过载 ===")
g = newgame()
p, f = g.players
p.hand = [by_name("闪电箭")]
g.play_card(p, 0, target=f)
check("闪电箭打过载 1", p.overload == 1, f"overload={p.overload}")
g.end_turn()
p2 = g.cur
while p2 is not p:
    g.end_turn()
    p2 = g.cur
check("过载下回合锁 1 水晶", p.locked_mana == 1 and p.mana == p.max_mana - 1,
      f"locked={p.locked_mana} mana={p.mana}/{p.max_mana}")

print("=== 连击 ===")
g = newgame()
p = g.players[0]
p.hand = [by_name("迪菲亚头目")]
g.play_card(p, 0)
check("无连击时不召唤", len(p.board) == 1, f"board={len(p.board)}")
g = newgame()
p = g.players[0]
p.cards_played = 1
p.hand = [by_name("迪菲亚头目")]
g.play_card(p, 0)
check("连击时召唤 2/1", len(p.board) == 2, f"board={len(p.board)}")

print("=== 奥秘 ===")
g = newgame()
p, f = g.players
p.hand = [by_name("法术反制")]
g.play_card(p, 0)
check("奥秘挂上而不是立即生效", len(p.secrets) == 1 and p.armor == 0, f"{p.secrets}")
f.hand = [by_name("火球术")]
hp = p.hp
g.turn = 1
g.play_card(f, 0, target=p)
check("法术反制挡掉对手法术", p.hp == hp and not f.secrets, f"hp={p.hp}")

g = newgame()
p, f = g.players
p.hand = [by_name("寒冰屏障")]
g.play_card(p, 0)
p.hp = 5
g.turn = 1
f.hand = [by_name("火球术")]
g.play_card(f, 0, target=p)
check("寒冰屏障挡住致命伤害", p.hp > 0, f"hp={p.hp}")

g = newgame()
p, f = g.players
p.hand = [by_name("镜像实体")]
g.play_card(p, 0)
g.turn = 1
f.hand = [by_name("冰风雪人")]
g.play_card(f, 0)
check("镜像实体复制对手随从", len(p.board) == 1, f"board={len(p.board)}")

print("=== 亡语 / 战吼 ===")
g = newgame()
p, f = g.players
put(g, f, by_name("冰风雪人"))
f.board[0].hp = 1
syl = put(g, p, by_name("希尔瓦娜斯·风行者"))
syl.hp = 0
g.check_deaths()
check("希尔瓦娜斯偷随从", len(p.board) == 1 and len(f.board) == 0,
      f"own={len(p.board)} foe={len(f.board)}")

g = newgame()
p, f = g.players
for _ in range(2):
    put(g, f, by_name("冰风雪人"))
p.hand = [by_name("死亡之翼")]
p.hand.append(by_name("冰风雪人"))
g.play_card(p, 0)
check("死亡之翼清场", len(f.board) == 0 and len(p.board) == 1, f"foe={len(f.board)}")
check("死亡之翼弃手牌", len(p.hand) == 0, f"hand={len(p.hand)}")

g = newgame()
p = g.players[0]
p.hand = [by_name("冰风雪人"), by_name("冰风雪人"), by_name("冰风雪人")]
p.mana = 10
cid = by_name("暮光幼龙")
p.hand.append(cid)
g.play_card(p, len(p.hand) - 1)
drake = [m for m in p.board if m.name == "暮光幼龙"][0]
check("暮光幼龙按手牌数加血", drake.max_hp == 1 + 3, f"max_hp={drake.max_hp}（基础 4/1）")

g = newgame()
p = g.players[0]
p.hp = 12
p.hand = [by_name("阿莱克丝塔萨")]
g.play_card(p, 0)
check("红龙把英雄血设成 15", p.hp == 15, f"hp={p.hp}")

print("=== 武器 ===")
g = newgame()
p, f = g.players
p.hand = [by_name("真银圣剑")]
g.play_card(p, 0)
check("武器耐久来自 health 字段", p.weapon and p.weapon["durability"] == 2,
      f"{p.weapon}")
put(g, f, by_name("冰风雪人"))
p.hp = 20
g.hero_attack(p, f.board[0])
check("真银圣剑攻击后回血", p.hp == 20 - 4 + 2, f"hp={p.hp}（应 20-4+2）")

g = newgame()
p, f = g.players
p.hand = [by_name("血吼")]
g.play_card(p, 0)
put(g, f, by_name("冰风雪人"))
d0 = p.weapon["durability"]
g.hero_attack(p, f.board[0])
check("血吼打随从不掉耐久", p.weapon and p.weapon["durability"] == d0,
      f"dura={p.weapon and p.weapon['durability']}")

print("=== 触发 ===")
g = newgame()
p = g.players[0]
put(g, p, by_name("紫罗兰教师"))
p.hand = [by_name("火球术")]
p.mana = 10
g.play_card(p, 0, target=g.players[1])
check("紫罗兰教师施法召唤 1/1", len(p.board) == 2, f"board={len(p.board)}")

g = newgame()
p = g.players[0]
put(g, p, by_name("加基森拍卖师"))
before = len(p.hand)
p.hand.append(by_name("火球术"))
before = len(p.hand)
p.mana = 10
g.play_card(p, len(p.hand) - 1, target=g.players[1])
check("加基森拍卖师施法抽牌", len(p.hand) == before, f"hand={len(p.hand)} (打出-1 抽+1)")

g = newgame()
p, f = g.players
put(g, p, by_name("古拉巴什狂暴者"))
gb = [m for m in p.board if m.name == "古拉巴什狂暴者"][0]
c = Ctx(g, f, p, src=f)
engine.damage(c, gb, 2)
check("古拉巴什狂暴者受伤 +3 攻", gb.atk == 2 + 3, f"atk={gb.atk}（基础 2 攻）")

g = newgame()
p, f = g.players
put(g, p, by_name("铸甲师"))
put(g, p, by_name("冰风雪人"))
c = Ctx(g, f, p, src=f)
engine.damage(c, p.board[1], 1)
check("铸甲师受伤给护甲", p.armor == 1, f"armor={p.armor}")

print("=== 老瞎眼 / 光耀之子 ===")
g = newgame()
p = g.players[0]
eye = put(g, p, by_name("老瞎眼"))
for _ in range(2):
    put(g, p, by_name("暗鳞先知"))
check("老瞎眼按其他鱼人加攻", eye.atk == 2 + 2 + 2, f"atk={eye.atk}（基础2 + 2鱼人 + 2个暗鳞先知光环）")

g = newgame()
p = g.players[0]
sp = put(g, p, by_name("光耀之子"))
sp.hp = 4
g.recalc()
check("光耀之子攻击力=生命值", sp.atk == 4, f"atk={sp.atk} hp={sp.hp}")

print("=== 复合句 ===")
g = newgame()
p, f = g.players
put(g, f, by_name("冰风雪人"))
put(g, f, by_name("冰风雪人"))
p.hand = [by_name("暴风雪")]
g.play_card(p, 0)
check("暴风雪 2 伤 + 冻结", all(m.hp == 3 and m.frozen for m in f.board),
      [(m.hp, m.frozen) for m in f.board])

g = newgame()
p, f = g.players
big = put(g, f, by_name("冰风雪人"))
engine.buff(Ctx(g, f, p), big, 4, 0)
p.hand = [by_name("大地震击")]
g.play_card(p, 0, target=big)
check("大地震击 沉默 + 1 伤", big.silenced and big.hp == 4, f"sil={big.silenced} hp={big.hp}")

g = newgame()
p, f = g.players
p.hand = [by_name("神圣愤怒")]
p.deck = p.deck + [by_name("山岭巨人")]      # 牌库末尾是 12 费 → 12 点伤害
g.play_card(p, 0, target=f)
check("神圣愤怒按抽到牌的费用造成伤害", f.hp == 30 - 12, f"hp={f.hp}")

g = newgame()
p, f = g.players
p.hand = [by_name("自然之力")]
g.play_card(p, 0)
check("自然之力召唤三个冲锋树人", len(p.board) == 3 and all(m.charge for m in p.board),
      len(p.board))

g = newgame()
p, f = g.players
put(g, f, by_name("暗鳞先知"))          # 鱼人
p.hand = [by_name("鱼人杀手蟹")]
g.play_card(p, 0, target=f.board[0])
crab = [m for m in p.board if m.name == "鱼人杀手蟹"][0]
check("鱼人杀手蟹吃鱼人并 +2/+2", len(f.board) == 0 and crab.atk == 3 and crab.hp == 4,
      f"foe={len(f.board)} {crab.atk}/{crab.hp}")

print("=== 常规法术回归 ===")
g = newgame()
p, f = g.players
put(g, f, by_name("冰风雪人"))
p.hand = [by_name("火球术")]
g.play_card(p, 0, target=f.board[0])
check("火球术 6 伤打死 4/5", len(f.board) == 0, f"board={len(f.board)}")

g = newgame()
p, f = g.players
put(g, f, by_name("冰风雪人"))
p.hand = [by_name("寒冰箭")]
g.play_card(p, 0, target=f.board[0])
check("寒冰箭 3 伤 + 冻结", f.board[0].hp == 2 and f.board[0].frozen,
      f"hp={f.board[0].hp} frozen={f.board[0].frozen}")

g = newgame()
p, f = g.players
put(g, f, by_name("冰风雪人"))
p.hand = [by_name("变形术")]
g.play_card(p, 0, target=f.board[0])
check("变形术变 1/1", f.board[0].atk == 1 and f.board[0].max_hp == 1,
      f"{f.board[0].atk}/{f.board[0].max_hp}")

g = newgame()
p = g.players[0]
p.hand = [by_name("生而平等")]
p.hand += [by_name("冰风雪人")]
for _ in range(2):
    put(g, p, by_name("冰风雪人"))
g.play_card(p, 0)
check("生而平等全场血=1", all(m.hp == 1 for m in p.board), [m.hp for m in p.board])

print("=== 抉择（Choose One）===")
g = newgame()
p, f = g.players
put(g, f, by_name("冰风雪人"))
p.hand = [by_name("丛林守护者")]
g.play_card(p, 0, target=f.board[0], choice=0)          # 造成2点伤害
check("丛林守护者① 造成2点伤害", f.board[0].hp == 3, f"hp={f.board[0].hp}")

g = newgame()
p, f = g.players
t = put(g, f, by_name("森金持盾卫士"))
check("（前置）森金持盾卫士带嘲讽", t.taunt, f"taunt={t.taunt}")
p.hand = [by_name("丛林守护者")]
g.play_card(p, 0, target=t, choice=1)                   # 沉默一个随从
check("丛林守护者② 沉默（嘲讽被消掉）", not t.taunt, f"taunt={t.taunt}")

g = newgame()
p = g.players[0]
p.hand = [by_name("利爪德鲁伊")]
g.play_card(p, 0, choice=0)                             # 冲锋
m = [x for x in p.board if x.name == "利爪德鲁伊"][0]
check("利爪德鲁伊① 冲锋可立即攻击", m.charge and m.attacks_left > 0,
      f"charge={m.charge} left={m.attacks_left}")

g = newgame()
p = g.players[0]
p.hand = [by_name("利爪德鲁伊")]
g.play_card(p, 0, choice=1)                             # +2生命值并嘲讽
m = [x for x in p.board if x.name == "利爪德鲁伊"][0]
check("利爪德鲁伊② +2血且嘲讽", m.taunt and m.hp == 6 and m.max_hp == 6,
      f"{m.atk}/{m.hp}/{m.max_hp} taunt={m.taunt}")

g = newgame()
p = g.players[0]
p.hand = [by_name("战争古树")]
g.play_card(p, 0, choice=0)                             # +5攻击力
m = [x for x in p.board if x.name == "战争古树"][0]
check("战争古树① +5 攻击（5/5 → 10/5）", m.atk == 10 and m.hp == 5, f"{m.atk}/{m.hp}")

g = newgame()
p = g.players[0]
p.hand = [by_name("塞纳留斯")]
g.play_card(p, 0, choice=1)                             # 两个 2/2 嘲讽树人
treants = [x for x in p.board if x.name == "树人"]
check("塞纳留斯② 召唤两个 2/2 嘲讽树人",
      len(treants) == 2 and all(x.atk == 2 and x.hp == 2 and x.taunt for x in treants),
      [(x.atk, x.hp, x.taunt) for x in treants])

g = newgame()
p = g.players[0]
p.hand = [by_name("塞纳留斯")]
put(g, p, by_name("冰风雪人"))
g.play_card(p, 0, choice=0)                             # 其他随从 +2/+2
check("塞纳留斯① 其他随从 +2/+2", p.board[0].atk == 6 and p.board[0].hp == 7,
      f"{p.board[0].atk}/{p.board[0].hp}")

g = newgame()
p = g.players[0]
p.hand = [by_name("知识古树")]
g.play_card(p, 0, choice=0)                             # 抽两张
check("知识古树① 抽两张", len(p.hand) == 2, f"hand={len(p.hand)}")

g = newgame()
p = g.players[0]
p.hp = 20
p.hand = [by_name("知识古树")]
g.play_card(p, 0, choice=1)                             # 恢复5点
check("知识古树② 恢复5点生命", p.hp == 25, f"hp={p.hp}")

g = newgame()
p, f = g.players
put(g, f, by_name("冰风雪人"))
p.hand = [by_name("愤怒")]
g.play_card(p, 0, target=f.board[0], choice=1)          # 1伤 + 抽牌
check("愤怒② 1点伤害并抽一张", f.board[0].hp == 4 and len(p.hand) == 1,
      f"hp={f.board[0].hp} hand={len(p.hand)}")

g = newgame()
p, f = g.players
put(g, f, by_name("冰风雪人"))
put(g, f, by_name("冰风雪人"))
p.hand = [by_name("星辰坠落")]
g.play_card(p, 0, choice=1)                             # 所有敌方随从 2 伤
check("星辰坠落② 全场敌方随从 2 伤", all(x.hp == 3 for x in f.board),
      [x.hp for x in f.board])

g = newgame()
p = g.players[0]
put(g, p, by_name("冰风雪人"))
p.hand = [by_name("野性之力")]
g.play_card(p, 0, choice=1)                             # 召唤 3/2 猎豹
pan = [x for x in p.board if x.name == "猎豹"]
check("野性之力② 召唤 3/2 猎豹",
      len(pan) == 1 and pan[0].atk == 3 and pan[0].hp == 2,
      [(x.name, x.atk, x.hp) for x in p.board])

g = newgame()
p = g.players[0]
put(g, p, by_name("冰风雪人"))
p.hand = [by_name("自然印记")]
g.play_card(p, 0, target=p.board[0], choice=1)          # +4生命值和嘲讽
check("自然印记② +4血且嘲讽", p.board[0].hp == 9 and p.board[0].taunt,
      f"hp={p.board[0].hp} taunt={p.board[0].taunt}")

print("=== 动态费用 ===")
g = newgame()
p = g.players[0]
p.hand = [by_name("山岭巨人")] + [by_name("冰风雪人")] * 4      # 手里 5 张，其他 4 张
check("山岭巨人 12 费 - 手牌其他 4 张 = 8", g.cost(p, by_name("山岭巨人")) == 8,
      f"cost={g.cost(p, by_name('山岭巨人'))}")

g = newgame()
p = g.players[0]
p.hp = 22                                                      # 已受 8 伤
p.hand = [by_name("熔核巨人")]
check("熔核巨人 20 费 - 已受 8 伤 = 12", g.cost(p, by_name("熔核巨人")) == 12,
      f"cost={g.cost(p, by_name('熔核巨人'))}")

g = newgame()
p, f = g.players
for _ in range(3):
    put(g, p, by_name("冰风雪人"))
for _ in range(2):
    put(g, f, by_name("冰风雪人"))
p.hand = [by_name("海巨人")]
check("海巨人 10 费 - 场上 5 个随从 = 5", g.cost(p, by_name("海巨人")) == 5,
      f"cost={g.cost(p, by_name('海巨人'))}")

g = newgame()
p = g.players[0]
p.weapon = {"name": "奥金斧", "atk": 5, "durability": 2}
p.hand = [by_name("恐怖海盗")]
check("恐怖海盗 4 费 - 武器 5 攻 = 0", g.cost(p, by_name("恐怖海盗")) == 0,
      f"cost={g.cost(p, by_name('恐怖海盗'))}")

g = newgame()
p = g.players[0]
put(g, p, by_name("巫师学徒"))
p.hand = [by_name("火球术")]
check("巫师学徒让火球术 4 → 3 费", g.cost(p, by_name("火球术")) == 3,
      f"cost={g.cost(p, by_name('火球术'))}")

g = newgame()
p = g.players[0]
put(g, p, by_name("召唤传送门"))
p.hand = [by_name("冰风雪人"), by_name("精灵龙")]
check("召唤传送门 4 费随从 → 2，2 费随从 → 1（下限 1）",
      g.cost(p, by_name("冰风雪人")) == 2 and g.cost(p, by_name("精灵龙")) == 1,
      f"雪人={g.cost(p, by_name('冰风雪人'))} 精灵龙={g.cost(p, by_name('精灵龙'))}")

g = newgame()
p, f = g.players
put(g, p, by_name("法力怨魂"))
p.hand = [by_name("冰风雪人")]
check("法力怨魂让双方随从 +1 费（我方 4 → 5）", g.cost(p, by_name("冰风雪人")) == 5,
      f"cost={g.cost(p, by_name('冰风雪人'))}")
check("法力怨魂对对手也生效", g.cost(f, by_name("冰风雪人")) == 5,
      f"cost={g.cost(f, by_name('冰风雪人'))}")

g = newgame()
p = g.players[0]
put(g, p, by_name("小个子召唤师"))
p.hand = [by_name("冰风雪人")]
check("小个子召唤师：本回合第一个随从 4 → 3", g.cost(p, by_name("冰风雪人")) == 3,
      f"cost={g.cost(p, by_name('冰风雪人'))}")
g.play_card(p, 0)                                              # 打出第一个随从
p.hand = [by_name("冰风雪人")]
check("小个子召唤师：第二个随从不再减费", g.cost(p, by_name("冰风雪人")) == 4,
      f"cost={g.cost(p, by_name('冰风雪人'))}")

g = newgame()
p = g.players[0]
p.hand = [by_name("伺机待发"), by_name("火球术")]
g.play_card(p, 0)                                              # 伺机待发
check("伺机待发：火球术 4 → 1 费", g.cost(p, by_name("火球术")) == 1,
      f"cost={g.cost(p, by_name('火球术'))}")
g.play_card(p, 0)                                              # 打掉火球术
p.hand = [by_name("火球术")]
check("伺机待发只减一张（第二张回到 4 费）", g.cost(p, by_name("火球术")) == 4,
      f"cost={g.cost(p, by_name('火球术'))}")

g = newgame()
p = g.players[0]
p.mana = p.max_mana = 3
p.hand = [by_name("巫师学徒"), by_name("火球术")]
g.play_card(p, 0)                                              # 学徒 2 费
check("实战：学徒站场后 1 点法力打不出火球术", not g.can_play(p, by_name("火球术")),
      f"mana={p.mana} cost={g.cost(p, by_name('火球术'))}")

print("=== 法术伤害 / 治疗管线 ===")
g = newgame()
p, f = g.players
put(g, p, by_name("狗头人地卜师"))
put(g, f, by_name("山岭巨人"))                      # 8/8，挨 7 点还能活着
p.hand = [by_name("火球术")]
g.play_card(p, 0, target=f.board[0])
check("法强+1 的火球造成 7 伤（6+1）", f.board[0].hp == 1, f"hp={f.board[0].hp}")

g = newgame()
p, f = g.players
put(g, p, by_name("狗头人地卜师"))
put(g, f, by_name("冰风雪人"))
put(g, f, by_name("冰风雪人"))
p.hand = [by_name("奉献")]
g.play_card(p, 0)
check("法强+1 的奉献对每个随从打 3", all(m.hp == 2 for m in f.board),
      [m.hp for m in f.board])

g = newgame()
p, f = g.players
put(g, p, by_name("先知维伦"))
f.hp = 30
p.hand = [by_name("火球术")]
g.play_card(p, 0, target=f)
check("先知维伦让火球伤害翻倍（12 伤）", f.hp == 18, f"hp={f.hp}")

g = newgame()
p, f = g.players
put(g, p, by_name("先知维伦"))
p.hp = 20
p.hand = [by_name("圣光术")]
g.play_card(p, 0, target=p)
check("先知维伦让治疗也翻倍（+6 → +12，封顶 30）", p.hp == 30, f"hp={p.hp}")

g = newgame()
p, f = g.players
put(g, p, by_name("奥金尼灵魂祭司"))
p.hp = 20
p.hand = [by_name("圣光术")]
g.play_card(p, 0, target=p)
check("奥金尼：治疗变伤害（+6 变 -6）", p.hp == 14, f"hp={p.hp}")

g = newgame()
p, f = g.players
p.cls = "MAGE"
put(g, p, by_name("狗头人地卜师"))
f.hp = 30
g.hero_power(p, f)
check("法强让英雄技能的 1 伤变 2", f.hp == 28, f"hp={f.hp}")

print("=== 英雄技能：术士 生命分流 ===")
g = newgame()
p, f = g.players
p.cls = "WARLOCK"
p.hp = 20
deck0 = len(p.deck)
res = g.hero_power(p)
check("生命分流：消耗 2 费", res and p.mana == 8, f"mana={p.mana}")
check("生命分流：抽一张牌", len(p.hand) == 1 and len(p.deck) == deck0 - 1,
      f"hand={len(p.hand)} deck={len(p.deck)}")
check("生命分流：对自己造成 2 点伤害", p.hp == 18, f"hp={p.hp}")
check("生命分流：一回合只能用一次", not g.hero_power(p) and p.hp == 18, f"hp={p.hp}")

# 法强 / 维伦只加成对外伤害，自伤固定 2
g = newgame()
p, f = g.players
p.cls = "WARLOCK"
p.hp = 20
put(g, p, by_name("狗头人地卜师"))          # 法术伤害 +1
g.hero_power(p)
check("生命分流：法强不放大自伤", p.hp == 18, f"hp={p.hp}（法强 {p.spell_power}）")

# 护甲照常吸收自伤
g = newgame()
p, f = g.players
p.cls = "WARLOCK"
p.hp = 20
p.armor = 5
g.hero_power(p)
check("生命分流：护甲先吸收自伤", p.armor == 3 and p.hp == 20,
      f"armor={p.armor} hp={p.hp}")

# 牌库空时先吃疲劳，再挨 2 点
g = newgame()
p, f = g.players
p.cls = "WARLOCK"
p.hp = 20
p.deck = []
p.fatigue = 0
g.hero_power(p)
check("生命分流：空牌库先吃疲劳 1 再受 2 伤", p.hp == 17, f"hp={p.hp}")

# 2 血时用技能会把自己打死（与正式规则一致）
g = newgame()
p, f = g.players
p.cls = "WARLOCK"
p.hp = 2
g.hero_power(p)
check("生命分流：2 血使用会自杀、判定对手胜",
      p.hp <= 0 and g.over and g.winner == "B", f"hp={p.hp} over={g.over} winner={g.winner}")

print("=== 英雄技能：其余六职业 ===")
g = newgame()
p, f = g.players
p.cls = "PALADIN"
g.hero_power(p)
check("援军：召唤一个 1/1 白银之手新兵",
      [(m.name, m.atk, m.hp) for m in p.board] == [("白银之手新兵", 1, 1)],
      [(m.name, m.atk, m.hp) for m in p.board])

g = newgame()
p, f = g.players
p.cls = "ROGUE"
g.hero_power(p)
w1 = dict(p.weapon) if p.weapon else None
p.weapon["durability"] = 1                      # 先磨损
p.hero_power_used = False
g.hero_power(p)
check("匕首精通：装备 1/2 匕首，重复使用顶掉旧的并回满耐久",
      w1 == {"name": "匕首", "atk": 1, "durability": 2}
      and p.weapon == {"name": "匕首", "atk": 1, "durability": 2},
      f"首次={w1} 现在={p.weapon}")

g = newgame()
p, f = g.players
p.cls = "HUNTER"
f.hp = 30
mm = put(g, f, by_name("银背族长"))
hp0 = mm.hp
g.hero_power(p, target=mm)                      # 就算指了随从，也只打脸
check("稳固射击：对敌方英雄 2 点，随从不受影响",
      f.hp == 28 and mm.hp == hp0, f"foe_hp={f.hp} 随从={mm.hp}/{hp0}")

g = newgame()
p, f = g.players
p.cls = "SHAMAN"
for _ in range(4):
    p.hero_power_used = False
    g.hero_power(p)
names = [m.name for m in p.board]
check("图腾召唤：四个图腾互不重复",
      len(names) == 4 and len(set(names)) == 4, names)

g = newgame()
p, f = g.players
p.cls = "DEMONHUNTER"
g.hero_power(p)
check("恶魔之咬：本回合 +1 攻击力", p.hero_atk == 1, f"hero_atk={p.hero_atk}")

g = newgame()
p, f = g.players
p.cls = "DEATHKNIGHT"
g.hero_power(p)
check("亡灵大军：召唤一个 1/1 食尸鬼",
      [(m.name, m.atk, m.hp) for m in p.board] == [("食尸鬼", 1, 1)],
      [(m.name, m.atk, m.hp) for m in p.board])

g = newgame()
p, f = g.players
p.cls = "PALADIN"
p.mana = p.max_mana = 10
for _ in range(7):
    put(g, p, by_name("闪金镇步兵"))
res = g.hero_power(p)
check("场上满 7 个：召唤类技能被拒，且不扣法力",
      (not res) and p.mana == 10 and len(p.board) == 7,
      f"res={res} mana={p.mana} board={len(p.board)}")

print("=== 图腾：四种都要有真实效果 ===")
g = newgame()
p, f = g.players
big = put(g, p, by_name("冰风雪人"))
big.hp = 3
p.hp = 20
heal_t = engine.summon(engine.Ctx(g, p, f), "TOKEN_TOTEM_HEAL")
check("治疗图腾：0/2", bool(heal_t) and (heal_t.atk, heal_t.hp) == (0, 2),
      f"{heal_t.atk if heal_t else '?'}/{heal_t.hp if heal_t else '?'}")
g.end_turn()
check("治疗图腾：回合结束为友方随从与英雄各回 1 点",
      big.hp == 4 and p.hp == 21, f"随从={big.hp} 英雄={p.hp}")

g = newgame()
p, f = g.players
f.hp = 30
engine.summon(engine.Ctx(g, p, f), "TOKEN_TOTEM_SEARING")
g.end_turn()
check("灼热图腾：回合结束对一个随机敌人造成 1 点", f.hp == 29, f"hp={f.hp}")

g = newgame()
p, f = g.players
stone = engine.summon(engine.Ctx(g, p, f), "TOKEN_TOTEM_STONECLAW")
check("石爪图腾：0/2 嘲讽",
      bool(stone) and stone.taunt and (stone.atk, stone.hp) == (0, 2),
      f"{stone.atk if stone else '?'}/{stone.hp if stone else '?'} 嘲讽={stone.taunt if stone else '?'}")

g = newgame()
p, f = g.players
engine.summon(engine.Ctx(g, p, f), "TOKEN_TOTEM_WRATH")
check("风语图腾：法术伤害 +1", p.spell_power == 1, f"spell_power={p.spell_power}")
p.hand = [by_name("寒冰箭")]
f.hp = 30
g.play_card(p, 0, target=f)
check("风语图腾：寒冰箭由 3 伤变 4 伤", f.hp == 26, f"hp={f.hp}")

g = newgame()
p, f = g.players
p.cls = "SHAMAN"
for _ in range(4):
    p.hero_power_used = False
    g.hero_power(p)
board = {m.name: m for m in p.board}
check("萨满技能召唤的四个图腾都带卡表数据（不是数值白板）",
      set(board) == {"治疗图腾", "灼热图腾", "石爪图腾", "风语图腾"}
      and all(m.cid in engine.CARDS and engine.CARDS[m.cid].get("token") for m in p.board),
      f"{[(m.name, m.cid) for m in p.board]}")
check("其中石爪有嘲讽、风语加法强",
      board["石爪图腾"].taunt and board["风语图腾"].spell_power == 1
      and p.spell_power == 1,
      f"嘲讽={board['石爪图腾'].taunt} 法强={p.spell_power}")

print("=== 费用修正 / 武器战吼 ===")
g = newgame()
p = g.players[0]
put(g, p, by_name("风险投资公司雇佣兵"))
p.hand = [by_name("冰风雪人")]
check("风险投资公司雇佣兵让随从 +3 费（4 → 7）", g.cost(p, by_name("冰风雪人")) == 7,
      f"cost={g.cost(p, by_name('冰风雪人'))}")

g = newgame()
p, f = g.players
p.mana = p.max_mana = 10
p.hand = [by_name("肯瑞托法师"), by_name("法术反制")]
g.play_card(p, 0)                                  # 先下肯瑞托法师
check("肯瑞托法师：下一个奥秘 0 费", g.cost(p, by_name("法术反制")) == 0,
      f"cost={g.cost(p, by_name('法术反制'))}")
g.play_card(p, 0)                                  # 挂上奥秘
check("肯瑞托法师只顶一个（第二张恢复 3 费）",
      g.cost(p, by_name("法术反制")) == 3, f"cost={g.cost(p, by_name('法术反制'))}")

g = newgame()
p, f = g.players
p.hand = [by_name("米尔豪斯·法力风暴")]
g.play_card(p, 0)
check("米尔豪斯让对手法术 0 费", g.cost(f, by_name("火球术")) == 0,
      f"cost={g.cost(f, by_name('火球术'))}")
g.end_turn()                                       # AI 回合结束后，效果失效
check("米尔豪斯只持续对手一个回合", g.cost(g.players[0], by_name("火球术")) == 4,
      f"cost={g.cost(g.players[0], by_name('火球术'))}")

g = newgame()
p, f = g.players
p.weapon = {"name": "奥金斧", "atk": 5, "durability": 2}
p.hand = [by_name("血帆袭击者")]
g.play_card(p, 0)
m = [x for x in p.board if x.name == "血帆袭击者"][0]
check("血帆袭击者获得等同于武器攻击力的攻击（2+5=7）", m.atk == 7, f"atk={m.atk}")

g = newgame()
p, f = g.players
p.weapon = {"name": "奥金斧", "atk": 5, "durability": 2}
p.hand = [by_name("恶毒铁匠")]
m = put(g, p, by_name("恶毒铁匠"), hp=2)           # 已受伤 → 激怒
g.recalc()
check("恶毒铁匠激怒时英雄攻击力 +2（5 → 7）", p.attack == 7, f"attack={p.attack}")

print("=== 控制 / 吞噬 / 变形 ===")
g = newgame()
p = g.players[0]
put(g, p, by_name("冰风雪人"))                       # 左邻：4/5
p.hand = [by_name("虚空恐魔")]                       # 战吼吃相邻随从
g.play_card(p, 0)
vt = [x for x in p.board if x.name == "虚空恐魔"][0]
check("虚空恐魔吃掉相邻的 4/5（3/3 → 7/8）",
      vt.atk == 7 and vt.max_hp == 8 and len(p.board) == 1,
      f"{vt.atk}/{vt.max_hp} board={len(p.board)}")

g = newgame()
p, f = g.players
for _ in range(4):
    put(g, f, by_name("冰风雪人"))
p.hand = [by_name("精神控制技师")]
g.play_card(p, 0)
check("精神控制技师：对手满 4 个随从时抢一个",
      len(p.board) == 2 and len(f.board) == 3,
      f"我={len(p.board)} 敌={len(f.board)}")

g = newgame()
p, f = g.players
for _ in range(3):
    put(g, f, by_name("冰风雪人"))
p.hand = [by_name("精神控制技师")]
g.play_card(p, 0)
check("精神控制技师：对手只有 3 个时不触发",
      len(p.board) == 1 and len(f.board) == 3,
      f"我={len(p.board)} 敌={len(f.board)}")

g = newgame()
p, f = g.players
put(g, f, by_name("冰风雪人"))
p.hand = [by_name("工匠大师欧沃斯巴克")]
g.play_card(p, 0)
m = f.board[0]
check("工匠大师把敌方随从变成 5/5 或 1/1",
      (m.atk, m.hp) in ((5, 5), (1, 1)) and m.name in ("暴掠龙", "松鼠"),
      f"{m.name} {m.atk}/{m.hp}")

g = newgame()
p, f = g.players
t = put(g, f, by_name("森金持盾卫士"))                # 3/5，攻击力符合条件
p.hand = [by_name("暗影狂乱")]
g.play_card(p, 0, target=t)
check("暗影狂乱抢过来（本回合能打）", t in p.board and t.attacks_left == 1,
      f"在我方={t in p.board} left={t.attacks_left}")
g.end_turn()
check("暗影狂乱：回合结束还回去", t in f.board and t not in p.board,
      f"在敌方={t in f.board}")

g = newgame()
p, f = g.players
t = put(g, f, by_name("冰风雪人"))                    # 4/5，攻击力超标
p.hand = [by_name("暗影狂乱")]
g.play_card(p, 0, target=t)
check("暗影狂乱对 4 攻随从无效（还留在对面）", t in f.board, f"在敌方={t in f.board}")

print("=== 跨句触发 / 挂钩子 ===")
g = newgame()
p, f = g.players
m = put(g, p, by_name("冰风雪人"))
p.hand = [by_name("智慧祝福")]
g.play_card(p, 0, target=m)
p.hand = []
g.attack(m, f)
check("智慧祝福：随从攻击后抽一张", len(p.hand) == 1, f"hand={len(p.hand)}")

g = newgame()
p, f = g.players
m = put(g, p, by_name("冰风雪人"))
p.hand = [by_name("先祖之魂")]
g.play_card(p, 0, target=m)
m.hp = 0
g.check_deaths()
alive = [x for x in p.board if x.name == "冰风雪人"]
check("先祖之魂：随从死后原样复活", len(alive) == 1 and alive[0].hp == 5,
      f"count={len(alive)} hp={alive[0].hp if alive else '-'}")

g = newgame()
p, f = g.players
t = put(g, f, by_name("冰风雪人"))
p.hand = [by_name("腐蚀术")]
g.play_card(p, 0, target=t)
check("腐蚀术：当回合还不死", t in f.board, f"在敌方={t in f.board}")
g.end_turn()                       # 交给 AI
g.end_turn()                       # AI 结束 → 回到我的回合，触发腐蚀
check("腐蚀术：我的下回合开始时摧毁", t not in f.board, f"在敌方={t in f.board}")

g = newgame()
p, f = g.players
put(g, p, by_name("报警机器人"))
p.hand = [by_name("冰风雪人")]
p.deck = [by_name("冰风雪人")] * 5
g.start_turn()
check("报警机器人：回合开始和手牌随从交换",
      any(x.name == "冰风雪人" for x in p.board) and by_name("报警机器人") in p.hand,
      [x.name for x in p.board])

g = newgame()
p, f = g.players
put(g, p, by_name("游学者周卓"))
p.hand = [by_name("火球术")]
g.play_card(p, 0, target=f)
check("游学者周卓：施法后给对方一张复制", len(f.hand) == 1, f"敌方手牌={len(f.hand)}")

print("=== 衍生牌 ===")
g = newgame()
p, f = g.players
p.hand = [by_name("穆克拉")]
g.play_card(p, 0)
check("穆克拉给对手两张香蕉",
      len(f.hand) == 2 and all(CARDS[c]["name"] == "香蕉" for c in f.hand),
      [CARDS[c]["name"] for c in f.hand])

g = newgame()
p = g.players[0]
put(g, p, by_name("伊瑟拉"))
p.hand = []
g.end_turn()                                     # 我的回合结束 → 触发
check("伊瑟拉回合结束给一张梦境牌",
      len(p.hand) == 1 and CARDS[p.hand[0]].get("token"),
      [CARDS[c]["name"] for c in p.hand])

g = newgame()
p, f = g.players
p.hand = [by_name("精英牛头人酋长")]
g.play_card(p, 0)
check("精英牛头人酋长给双方同一张和弦牌",
      len(p.hand) == 1 and len(f.hand) == 1 and p.hand[0] == f.hand[0],
      f"我={[CARDS[c]['name'] for c in p.hand]} 敌={[CARDS[c]['name'] for c in f.hand]}")

# 和弦牌「我是鱼人」：官方是 3~5 个 1/1（以前写成 3 或 4）
g = newgame()
p = g.players[0]
counts = set()
for i in range(60):
    g = newgame(seed=100 + i)
    p = g.players[0]
    p.hand = ["TOKEN_MURLOC"]
    g.play_card(p, 0)
    counts.add(len([m for m in p.board if m.name == "鱼人"]))
check("我是鱼人：召唤 3~5 个 1/1 鱼人", counts and counts.issubset({3, 4, 5}),
      f"实际出现过 {sorted(counts)} 个")

# 和弦牌「部落的力量」：官方是固定六名部落勇士，不是随机传说
g = newgame()
p = g.players[0]
got = set()
for i in range(80):
    g = newgame(seed=200 + i)
    p = g.players[0]
    p.hand = ["TOKEN_HORDE"]
    g.play_card(p, 0)
    got |= {m.name for m in p.board}
champions = {"霜狼步兵", "森金持盾卫士", "萨尔玛先知", "银月城卫兵", "凯恩·血蹄", "牛头人战士"}
check("部落的力量：只从六名部落勇士里召唤", got == champions,
      f"召唤过 {sorted(got)}")
legends = [n for n in got if CARDS[by_name(n)].get("rarity") == "LEGENDARY"
           and n != "凯恩·血蹄"]
check("部落的力量：不会召出其它传说", not legends, f"误召 {legends}")

g = newgame()
p = g.players[0]
m = put(g, p, by_name("冰风雪人"))
p.hand = ["TOKEN_BANANA"]
g.play_card(p, 0, target=m)
check("香蕉 +1/+1", m.atk == 5 and m.max_hp == 6, f"{m.atk}/{m.max_hp}")

g = newgame()
p, f = g.players
t = put(g, f, by_name("冰风雪人"))
p.hand = ["TOKEN_DREAM"]
g.play_card(p, 0, target=t)
check("梦境把敌方随从弹回手牌", not f.board and len(f.hand) == 1,
      f"board={len(f.board)} hand={len(f.hand)}")

g = newgame()
p, f = g.players
put(g, p, by_name("冰风雪人"))
put(g, f, by_name("冰风雪人"))
p.hand = ["TOKEN_AWAKEN"]
g.play_card(p, 0)
check("伊瑟拉的苏醒：全场打 5（随从全死、双方英雄各掉 5）",
      not p.board and not f.board and p.hp == 25 and f.hp == 25,
      f"我={p.hp} 敌={f.hp} 我场={len(p.board)} 敌场={len(f.board)}")

g = newgame()
p, f = g.players
put(g, f, "TOKEN_SISTER")
p.hand = [by_name("火球术")]
played = g.play_card(p, 0, target=f.board[0])
check("欢笑姐妹不能被法术指定（打出被拒绝，费用不扣）",
      not played and p.mana == 10 and f.board[0].hp == 5,
      f"played={played} mana={p.mana} hp={f.board[0].hp}")

g = newgame()
p = g.players[0]
p.hand = ["TOKEN_DRAKE"]
g.play_card(p, 0)
check("翡翠幼龙是 7/6", p.board[0].atk == 7 and p.board[0].hp == 6,
      f"{p.board[0].atk}/{p.board[0].hp}")

print("=== 换英雄 / 限时 ===")
g = newgame()
p = g.players[0]
p.cls = "WARLOCK"
p.hand = [by_name("加拉克苏斯大王")]
g.play_card(p, 0)
check("加拉克苏斯：英雄变 15 血上限、装备血怒 3/8",
      p.hp == 15 and p.hero_max_hp == 15 and p.weapon
      and p.weapon["atk"] == 3 and p.weapon["durability"] == 8,
      f"hp={p.hp} max={p.hero_max_hp} weapon={p.weapon}")
p.hp = 10
p.mana = 10
p.hand = [by_name("圣光术")]
g.play_card(p, 0, target=p)
check("加拉克苏斯形态下治疗不会超过 15", p.hp == 15, f"hp={p.hp}")
p.hero_power_used = False
p.mana = 10
g.hero_power(p)
infernals = [m for m in p.board if m.name == "地狱火"]
check("加拉克苏斯技能召唤 6/6 地狱火",
      len(infernals) == 1 and infernals[0].atk == 6 and infernals[0].hp == 6,
      [(m.name, m.atk, m.hp) for m in p.board])

g = newgame()
p = g.players[0]
put(g, p, by_name("诺兹多姆"))
check("诺兹多姆在场时 state 带 15 秒限时", g.state(0)["timer"] == 15,
      f"timer={g.state(0)['timer']}")

print("=== 交战结算（同时掉血）===")

# 4/4 打死 2/2，自己必须照样吃 2 点反击伤害
g = newgame()
p, f = g.players
a = put(g, p, by_name("碧蓝幼龙"))          # 4/4
d = put(g, f, by_name("铁炉堡火枪手"))       # 2/2
g.attack(a, d)
check("4/4 打死 2/2 后自己掉 2（不能白嫖）",
      not f.board and a.hp == 2, f"攻方={a.atk}/{a.hp} 敌场={len(f.board)}")

# 双方都活着 → 互相掉血
g = newgame()
p, f = g.players
a = put(g, p, by_name("冰风雪人"))           # 4/5
d = put(g, f, by_name("森金持盾卫士"))        # 3/5
g.attack(a, d)
check("4/5 打 3/5：攻方 4/2、守方 3/1",
      a.hp == 2 and d.hp == 1, f"攻方 {a.atk}/{a.hp} 守方 {d.atk}/{d.hp}")

# 同归于尽
g = newgame()
p, f = g.players
a = put(g, p, by_name("铁炉堡火枪手"))
b = put(g, f, by_name("铁炉堡火枪手"))
g.attack(a, b)
check("2/2 打 2/2：双方同归于尽", not p.board and not f.board,
      f"我场={len(p.board)} 敌场={len(f.board)}")

# 英雄用武器打随从：随从死了英雄也要吃反击
g = newgame()
p, f = g.players
p.hand = [by_name("血吼")]                   # 7/1，打随从不掉耐久
g.play_card(p, 0)
t = put(g, f, by_name("铁炉堡火枪手"))
g.hero_attack(p, t)
check("血吼打随从：随从死、英雄掉 2、武器 -1 攻且不掉耐久",
      not f.board and p.hp == 28 and p.weapon["atk"] == 6
      and p.weapon["durability"] == 1,
      f"hp={p.hp} weapon={p.weapon} 敌场={len(f.board)}")

# 角斗士的长弓：攻击时免疫，英雄不掉血
g = newgame()
p, f = g.players
p.hand = [by_name("角斗士的长弓")]
g.play_card(p, 0)
t = put(g, f, by_name("铁炉堡火枪手"))
g.hero_attack(p, t)
check("角斗士的长弓攻击随从时英雄免疫反击",
      not f.board and p.hp == 30, f"hp={p.hp} 敌场={len(f.board)}")

print("=== 带条件的单张效果（23 张）===")

# 冰枪术
g = newgame()
p, f = g.players
t = put(g, f, by_name("冰风雪人"))
p.hand = [by_name("冰枪术")]
g.play_card(p, 0, target=t)
check("冰枪术：未冻结的目标改为冻结", t.frozen and t.hp == 5, f"frozen={t.frozen} hp={t.hp}")
p.hand = [by_name("冰枪术")]
g.play_card(p, 0, target=t)
check("冰枪术：已冻结的目标吃 4 点伤害", t.hp == 1, f"hp={t.hp}")

# 视界术
g = newgame()
p = g.players[0]
p.hand = [by_name("视界术")]
g.play_card(p, 0)
drawn = p.hand[0]
check("视界术：抽到的那张降 3 费", g.cost(p, drawn) == max(0, CARDS[drawn]["cost"] - 3),
      f"{CARDS[drawn]['name']} cost={g.cost(p, drawn)}")

# 冷血
g = newgame()
p = g.players[0]
m = put(g, p, by_name("冰风雪人"))
p.hand = [by_name("冷血")]
g.play_card(p, 0, target=m)
check("冷血：+2 攻击力", m.atk == 6, f"atk={m.atk}")
g = newgame()
p = g.players[0]
m = put(g, p, by_name("冰风雪人"))
p.cards_played = 1
p.hand = [by_name("冷血")]
g.play_card(p, 0, target=m)
check("冷血连击：改为 +4 攻击力", m.atk == 8, f"atk={m.atk}")

# 追踪术
g = newgame()
p = g.players[0]
before = len(p.deck)
p.hand = [by_name("追踪术")]
g.play_card(p, 0)
check("追踪术：从牌库顶三张里留一张、弃两张",
      len(p.hand) == 1 and len(p.deck) == before - 3,
      f"hand={len(p.hand)} deck={len(p.deck)}/{before}")

# 刺骨
g = newgame()
p, f = g.players
t = put(g, f, by_name("森金持盾卫士"))          # 3/5
p.hand = [by_name("刺骨")]
g.play_card(p, 0, target=t)
check("刺骨：2 点伤害", t.hp == 3, f"hp={t.hp}")
g = newgame()
p, f = g.players
t = put(g, f, by_name("森金持盾卫士"))
p.cards_played = 1
p.hand = [by_name("刺骨")]
g.play_card(p, 0, target=t)
check("刺骨连击：改为 4 点伤害", t.hp == 1, f"hp={t.hp}")

# 隐藏
g = newgame()
p, f = g.players
m = put(g, p, by_name("冰风雪人"))
p.hand = [by_name("隐藏")]
g.play_card(p, 0)
check("隐藏：己方随从获得潜行", m.stealth, f"stealth={m.stealth}")
g.end_turn()
g.end_turn()
check("隐藏：到自己下个回合开始潜行消失", not m.stealth, f"stealth={m.stealth}")

# 毁灭之刃
g = newgame()
p, f = g.players
t = put(g, f, by_name("冰风雪人"))
p.hand = [by_name("毁灭之刃")]
g.play_card(p, 0, target=t)
check("毁灭之刃：装备 2/2 武器并造成 1 点伤害",
      p.weapon["atk"] == 2 and p.weapon["durability"] == 2 and t.hp == 4,
      f"weapon={p.weapon} hp={t.hp}")
g = newgame()
p, f = g.players
t = put(g, f, by_name("冰风雪人"))
p.cards_played = 1
p.hand = [by_name("毁灭之刃")]
g.play_card(p, 0, target=t)
check("毁灭之刃连击：改为 2 点伤害", t.hp == 3, f"hp={t.hp}")

# 裂颅之击
g = newgame()
p, f = g.players
p.cards_played = 1
p.hand = [by_name("裂颅之击")]
g.play_card(p, 0)
check("裂颅之击：对敌方英雄造成 2 点", f.hp == 28, f"hp={f.hp}")
g.end_turn()
g.end_turn()
check("裂颅之击连击：下个回合回到手牌", by_name("裂颅之击") in p.hand,
      [CARDS[c]["name"] for c in p.hand])

# 暗影步
g = newgame()
p = g.players[0]
m = put(g, p, by_name("冰风雪人"))
p.hand = [by_name("暗影步")]
g.play_card(p, 0, target=m)
cid = by_name("冰风雪人")
check("暗影步：随从回手并降 2 费",
      cid in p.hand and g.cost(p, cid) == 2 and not p.board,
      f"hand={'冰风雪人' in [CARDS[c]['name'] for c in p.hand]} cost={g.cost(p, cid)}")

# 丛林之魂
g = newgame()
p = g.players[0]
m = put(g, p, by_name("冰风雪人"))
p.hand = [by_name("丛林之魂")]
g.play_card(p, 0)
m.hp = 0
g.check_deaths()
treants = [x for x in p.board if x.name == "树人"]
check("丛林之魂：随从死亡后召唤 2/2 树人",
      len(treants) == 1 and treants[0].atk == 2 and treants[0].hp == 2,
      [(x.name, x.atk, x.hp) for x in p.board])

# 死亡缠绕
g = newgame()
p, f = g.players
t = put(g, f, by_name("冰风雪人"))
t.hp = 1
p.hand = [by_name("死亡缠绕")]
g.play_card(p, 0, target=t)
check("死亡缠绕：目标死亡则抽一张", len(p.hand) == 1 and not f.board,
      f"hand={len(p.hand)} 敌场={len(f.board)}")
g = newgame()
p, f = g.players
t = put(g, f, by_name("冰风雪人"))
p.hand = [by_name("死亡缠绕")]
g.play_card(p, 0, target=t)
check("死亡缠绕：目标没死就不抽", len(p.hand) == 0 and t.hp == 4,
      f"hand={len(p.hand)} hp={t.hp}")

# 力量的代价
g = newgame()
p = g.players[0]
m = put(g, p, by_name("冰风雪人"))
p.hand = [by_name("力量的代价")]
g.play_card(p, 0, target=m)
check("力量的代价：+4/+4", m.atk == 8 and m.max_hp == 9, f"{m.atk}/{m.max_hp}")
g.end_turn()
check("力量的代价：回合结束时死亡", not p.board, [(x.name, x.hp) for x in p.board])

# 末日灾祸
g = newgame()
p, f = g.players
t = put(g, f, by_name("冰风雪人"))
t.hp = 2
p.hand = [by_name("末日灾祸")]
g.play_card(p, 0, target=t)
demons = [x for x in p.board if "DEMON" in x.races]
check("末日灾祸：目标死亡则随机召唤恶魔", len(demons) == 1,
      [(x.name, x.races) for x in p.board])

# 猛击
g = newgame()
p, f = g.players
t = put(g, f, by_name("冰风雪人"))
p.hand = [by_name("猛击")]
g.play_card(p, 0, target=t)
check("猛击：目标存活则抽一张", t.hp == 3 and len(p.hand) == 1,
      f"hp={t.hp} hand={len(p.hand)}")

# 致死打击
g = newgame()
p, f = g.players
p.hand = [by_name("致死打击")]
g.play_card(p, 0, target=f)
check("致死打击：正常 4 点", f.hp == 26, f"hp={f.hp}")
g = newgame()
p, f = g.players
p.hp = 12
p.hand = [by_name("致死打击")]
g.play_card(p, 0, target=f)
check("致死打击：自己 ≤12 血时改为 6 点", f.hp == 24, f"hp={f.hp}")

# 升级
g = newgame()
p = g.players[0]
p.hand = [by_name("升级")]
g.play_card(p, 0)
check("升级：没武器就装备 1/3",
      p.weapon and p.weapon["atk"] == 1 and p.weapon["durability"] == 3,
      f"weapon={p.weapon}")
p.hand = [by_name("升级")]
g.play_card(p, 0)
check("升级：有武器就 +1/+1",
      p.weapon["atk"] == 2 and p.weapon["durability"] == 4, f"weapon={p.weapon}")

# 杀戮命令
g = newgame()
p, f = g.players
p.hand = [by_name("杀戮命令")]
g.play_card(p, 0, target=f)
check("杀戮命令：没有野兽时 3 点", f.hp == 27, f"hp={f.hp}")
g = newgame()
p, f = g.players
put(g, p, by_name("森林狼"))                   # 野兽
p.hand = [by_name("杀戮命令")]
g.play_card(p, 0, target=f)
check("杀戮命令：控制野兽时 5 点", f.hp == 25, f"hp={f.hp}")

# 照明弹
g = newgame()
p, f = g.players
put(g, p, by_name("冰风雪人"), stealth=True)
f.mana = 10
f.hand = [by_name("寒冰屏障")]
g.turn = 1
g.play_card(f, 0)
g.turn = 0
p.hand = [by_name("照明弹")]
g.play_card(p, 0)
check("照明弹：清潜行 + 摧毁敌方奥秘 + 抽一张",
      not p.board[0].stealth and not f.secrets and len(p.hand) == 1,
      f"stealth={p.board[0].stealth} 奥秘={f.secrets} hand={len(p.hand)}")

# 自然之力
g = newgame()
p = g.players[0]
p.hand = [by_name("自然之力")]
g.play_card(p, 0)
treants = [x for x in p.board if x.name == "树人"]
check("自然之力：三个 2/2 冲锋树人",
      len(treants) == 3 and all(x.atk == 2 and x.charge and x.attacks_left > 0
                                for x in treants),
      [(x.name, x.atk, x.charge, x.attacks_left) for x in p.board])
g.end_turn()
check("自然之力：回合结束树人消失", not [x for x in p.board if x.name == "树人"],
      [x.name for x in p.board])

# 血骑士
g = newgame()
p, f = g.players
a = put(g, p, by_name("银色侍从"))             # 1/1 圣盾
b = put(g, f, by_name("银色侍从"))
p.hand = [by_name("血骑士")]
g.play_card(p, 0)
bk = [x for x in p.board if x.name == "血骑士"][0]
check("血骑士：吃掉两个圣盾变 9/9",
      bk.atk == 9 and bk.max_hp == 9 and not a.shield and not b.shield,
      f"{bk.atk}/{bk.max_hp} 我方盾={a.shield} 敌方盾={b.shield}")

# 恶魔之火
g = newgame()
p = g.players[0]
d = put(g, p, by_name("虚空行者"))             # 1/3 恶魔
p.hand = [by_name("恶魔之火")]
g.play_card(p, 0, target=d)
check("恶魔之火：友方恶魔改为 +2/+2", d.atk == 3 and d.max_hp == 5,
      f"{d.atk}/{d.max_hp}")
g = newgame()
p, f = g.players
t = put(g, f, by_name("冰风雪人"))
p.hand = [by_name("恶魔之火")]
g.play_card(p, 0, target=t)
check("恶魔之火：其它目标吃 2 点伤害", t.hp == 3, f"hp={t.hp}")

# 暗影形态
g = newgame()
p, f = g.players
p.cls = "PRIEST"
p.hand = [by_name("暗影形态")]
g.play_card(p, 0)
check("暗影形态：英雄技能变为 2 点伤害", p.hero_power_key == "SHADOW",
      p.hero_power_key)
p.hero_power_used = False
p.mana = 10
g.hero_power(p, target=f)
check("暗影形态技能：打 2 点", f.hp == 28, f"hp={f.hp}")
p.hand = [by_name("暗影形态")]
g.play_card(p, 0)
p.hero_power_used = False
p.mana = 10
g.hero_power(p, target=f)
check("暗影形态再放一次：技能变 3 点", f.hp == 25 and p.hero_power_key == "SHADOW2",
      f"hp={f.hp} key={p.hero_power_key}")

# 命令怒吼
g = newgame()
p, f = g.players
m = put(g, p, by_name("冰风雪人"))
p.hand = [by_name("命令怒吼")]
g.play_card(p, 0)
engine.damage(g.ctx(target=m), m, 9)
check("命令怒吼：本回合随从不会低于 1 血并抽一张",
      m.alive and m.hp == 1 and len(p.hand) == 1,
      f"hp={m.hp} alive={m.alive} hand={len(p.hand)}")
g.end_turn()
check("命令怒吼：效果只持续本回合", not p.minions_survive, f"flag={p.minions_survive}")

# 英雄冻结
g = newgame()
p, f = g.players
p.hand = [by_name("升级")]
g.play_card(p, 0)                             # 装备 1/3
engine.freeze(g.ctx(), p)
check("英雄被冻结时不能攻击",
      not g.hero_attack(p, f) and f.hp == 30, f"hp={f.hp}")
g.end_turn()
check("英雄冻结在自己的回合结束时解除", not p.frozen, f"frozen={p.frozen}")

print("=== 潜行规则 / 后手补偿 ===")

# 潜行不能被攻击
g = newgame()
p, f = g.players
st = put(g, f, by_name("冰风雪人"), stealth=True)
atk = put(g, p, by_name("冰风雪人"))
ok_attack = g.attack(atk, st)
check("潜行随从不能被攻击", not ok_attack and st.hp == 5, f"返回={ok_attack} hp={st.hp}")

# 潜行嘲讽不挡打脸
g = newgame()
p, f = g.players
put(g, f, by_name("森金持盾卫士"), stealth=True)          # 潜行 + 嘲讽
p.weapon = {"name": "测试刀", "atk": 5, "durability": 2}
check("只有潜行嘲讽时仍然可以打脸", g.hero_attack(p, f) and f.hp == 25,
      f"hp={f.hp}")

# 可见嘲讽照旧挡脸（防止改过头）
g = newgame()
p, f = g.players
put(g, f, by_name("森金持盾卫士"))
p.weapon = {"name": "测试刀", "atk": 5, "durability": 2}
check("可见嘲讽仍然挡住英雄攻击", not g.hero_attack(p, f) and f.hp == 30,
      f"hp={f.hp}")

# 法术不能指定敌方潜行随从，且不扣费
g = newgame()
p, f = g.players
st = put(g, f, by_name("冰风雪人"), stealth=True)
p.hand = [by_name("火球术")]
r = g.play_card(p, 0, target=st)
check("法术不能指定敌方潜行随从（不扣费）",
      not r and st.hp == 5 and p.mana == 10,
      f"返回={r} hp={st.hp} mana={p.mana}")

# 自己的法术可以指定自己的潜行随从
g = newgame()
p = g.players[0]
mine = put(g, p, by_name("冰风雪人"), stealth=True)
p.hand = [by_name("火球术")]
check("自己的法术可以指定自己的潜行随从", g.play_card(p, 0, target=mine),
      f"hp={mine.hp}")

# 英雄技能同样不能指定敌方潜行随从
g = newgame()
p, f = g.players
st = put(g, f, by_name("冰风雪人"), stealth=True)
p.cls = "HUNTER"
check("英雄技能不能指定敌方潜行随从",
      not g.hero_power(p, target=st) and st.hp == 5,
      f"hp={st.hp}")

# 扰魔（无法被法术指定）：敌我双方的法术都不行，但战吼/光环不受影响
g = newgame()
p, f = g.players
fd = put(g, f, by_name("精灵龙"))
p.hand = [by_name("火球术")]
check("法术不能指定敌方精灵龙（扰魔）",
      not g.play_card(p, 0, target=fd) and fd.hp == 2, f"hp={fd.hp}")
g = newgame()
p = g.players[0]
mine = put(g, p, by_name("精灵龙"))
p.hand = [by_name("火球术")]
check("自己的法术也不能指定自己的精灵龙（扰魔）",
      not g.play_card(p, 0, target=mine) and mine.hp == 2, f"hp={mine.hp}")
g = newgame()
p, f = g.players
put(g, f, by_name("冰风雪人"))
p.hand = [by_name("精灵龙")]
check("敌方场上有精灵龙也不影响打别的目标", g.play_card(p, 0, target=f.board[0]),
      f"hp={f.board[0].hp}")

# 先祖之魂：死亡后召唤一个满血复制（不是原对象复活）
g = newgame()
p = g.players[0]
m = put(g, p, by_name("冰风雪人"))
p.hand = [by_name("先祖之魂")]
g.play_card(p, 0, target=m)
m.hp = 0
g.check_deaths()
back = [x for x in p.board if x.name == "冰风雪人"]
check("先祖之魂：随从死亡后满血回到战场",
      len(back) == 1 and back[0].hp == 5, [(x.name, x.hp) for x in p.board])

# 后手幸运币
g = Game(("你", "AI"), (["VAN_CS2_182"] * 30, ["VAN_CS2_182"] * 30), seed=5)
first, second = g.players
check("先手 3 张、后手 4 张 + 幸运币",
      len(first.hand) == 3 and len(second.hand) == 5
      and CARDS[second.hand[-1]]["name"] == "幸运币",
      f"先={len(first.hand)} 后={len(second.hand)} "
      f"{[CARDS[c]['name'] for c in second.hand]}")
second.mana = 1
g.turn = 1                                    # 轮到后手
g.play_card(second, len(second.hand) - 1)     # 打出幸运币
check("幸运币：0 费、本回合 +1 法力水晶（不涨上限）",
      second.mana == 2 and second.max_mana == 0,
      f"mana={second.mana}/{second.max_mana}")

print(f"\n结果：{ok} 通过 / {fail} 失败")
raise SystemExit(1 if fail else 0)
