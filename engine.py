"""
炉石like 规则引擎 —— 单机自用版，零第三方依赖

设计：
  * 效果原语（本文件提供原子操作）
  * 卡池用声明式配置调用原语（cards.py）
  * 实现不了的卡降级为「白板」：保留 费/攻/血，效果为空 —— 保证卡池全在且可玩
"""

from __future__ import annotations
import random
from dataclasses import dataclass, field
from typing import Callable, Optional

MAX_MANA, MAX_HP, MAX_BOARD, HAND_CAP = 10, 30, 7, 10

# 卡池注册表：cards.py 会往里塞
CARDS: dict[str, dict] = {}


def register(cid: str, **kw):
    kw.setdefault("implemented", True)
    kw.setdefault("cid", cid)          # 卡 id 也存进定义里，效果里要用（裂颅之击回手等）
    CARDS[cid] = kw
    return kw


# ============ 实体 ============
@dataclass
class Minion:
    name: str
    atk: int
    hp: int
    max_hp: int
    owner_id: int
    cid: str = ""
    text: str = ""
    taunt: bool = False
    charge: bool = False
    rush: bool = False
    shield: bool = False
    stealth: bool = False
    windfury: bool = False
    lifesteal: bool = False
    poisonous: bool = False
    reborn: bool = False
    frozen: bool = False
    silenced: bool = False
    immune: bool = False
    cant_attack: bool = False
    spell_power: int = 0
    elusive: bool = False          # 无法被法术/英雄技能指定（精灵龙）
    attacks_left: int = 0
    summoned_this_turn: bool = True
    base_atk: int = 0
    base_hp: int = 0
    rarity: str = "COMMON"
    races: list = field(default_factory=list)      # ['BEAST'] 等，供种族光环/触发判断
    freeze_on_damage: bool = False                 # 水元素：伤害即冻结
    buffs: list = field(default_factory=list)      # [(atk, hp)] 永久
    temp_buffs: list = field(default_factory=list)  # [(atk, hp)] 本回合有效
    deathrattle: Optional[Callable] = None
    triggers: list = field(default_factory=list)   # [(event, fn)]
    # ---- 动态费用光环（巫师学徒 / 召唤传送门 / 法力怨魂 / 小个子召唤师）----
    spell_discount: int = 0        # 己方法术 -N 费
    minion_discount: int = 0       # 己方随从 -N 费（下限 1）
    first_minion_discount: int = 0  # 本回合第一个随从 -N 费
    all_minion_more: int = 0       # 双方随从 +N 费
    minion_cost_more: int = 0      # 己方随从额外 +N 费（风险投资公司雇佣兵）
    spell_mult: int = 0            # 法术/技能伤害与治疗倍率（先知维伦 = 2）
    heal_as_damage: bool = False   # 治疗改为造成伤害（奥金尼灵魂祭司）
    die_at_end: bool = False       # 回合结束时死亡（力量的代价 / 自然之力树人）
    stealth_temp: bool = False     # 潜行只维持到自己的下个回合（隐藏）

    @property
    def alive(self) -> bool:
        return self.hp > 0

    @property
    def can_attack_hero(self) -> bool:
        return not (self.summoned_this_turn and self.rush and not self.charge)

    @property
    def attackable(self) -> bool:
        return not self.stealth


@dataclass
class Player:
    name: str
    pid: int
    hp: int = MAX_HP
    armor: int = 0
    mana: int = 0
    max_mana: int = 0
    fatigue: int = 0
    deck: list = field(default_factory=list)
    hand: list = field(default_factory=list)
    board: list = field(default_factory=list)
    weapon: Optional[dict] = None
    spell_power: int = 0
    hero_power_used: bool = False
    cls: str = "NEUTRAL"
    hero_atk: int = 0             # 本回合临时英雄攻击力（德鲁伊「变形」等）
    hero_attack_used: bool = False
    hero_attacks: int = 0         # 本回合已用脸攻击次数（风怒武器可用 2 次）
    secrets: list = field(default_factory=list)    # 已挂的奥秘 id 列表（按打出顺序触发）
    overload: int = 0             # 下回合要锁的法力水晶数
    locked_mana: int = 0          # 本回合被过载锁住的水晶数
    cards_played: int = 0         # 本回合已打出的牌数（连击判定）
    minions_played: int = 0       # 本回合已打出的随从数（小个子召唤师）
    next_spell_discount: int = 0  # 下一张法术 -N 费（伺机待发），本回合内有效
    next_secret_free: int = 0     # 本回合下一个奥秘免费（肯瑞托法师）
    spells_free: bool = False     # 下个回合我的法术全免费（米尔豪斯）
    enrage_weapon: int = 0        # 激怒带来的武器攻击加成（恶毒铁匠，recalc 维护）
    borrowed: list = field(default_factory=list)   # 暗影狂乱借来的随从，回合结束归还
    hero_max_hp: int = MAX_HP     # 英雄血量上限（加拉克苏斯大王变成 15）
    hero_name: str = ""           # 英雄本体名字（变了英雄后显示用）
    hero_power_key: str = ""      # 特殊英雄技能（JARAXXUS = 召唤 6/6 地狱火）
    spell_mult: int = 1           # 法术/技能伤害与治疗倍率（先知维伦 = 2）
    heal_as_damage: bool = False  # 治疗改为造成伤害（奥金尼灵魂祭司）
    immune_turn: bool = False     # 寒冰屏障：本回合免疫
    cheap: dict = field(default_factory=dict)          # 手牌降价 {cid: [减费额, 还生效的张数]}
    minions_survive: bool = False                      # 本回合随从不会被打死（命令怒吼）
    pending_hand: list = field(default_factory=list)   # 下回合开始回到手牌的卡（裂颅之击）
    frozen: bool = False                               # 英雄被冻结：下个回合不能攻击，回合结束解冻

    @property
    def attack(self) -> int:
        """英雄攻击力 = 武器攻击力 + 本回合临时攻击力 + 激怒加成；为 0 则不能用脸攻击"""
        return (self.weapon["atk"] if self.weapon else 0) + self.hero_atk + self.enrage_weapon


@dataclass
class Ctx:
    """效果上下文 —— 原语靠它知道「谁打的、打谁」"""
    g: "Game"
    me: Player
    foe: Player
    target: object = None
    src: object = None          # 触发者 / 本体（trigger 里就是拥有该效果的随从）
    amount: int = 0
    event: str = ""
    event_src: object = None    # 事件的实际发起者（攻击者、死掉的随从、打出的牌）
    combo: bool = False         # 本张牌是否处于「连击」状态
    card: object = None         # 触发事件涉及的卡牌定义（无羁元素判断过载）
    spell: bool = False         # 本次结算来自法术/英雄技能 → 吃法强、吃维伦


def is_minion(x) -> bool:
    return isinstance(x, Minion)


# ============ 效果原语 ============
def damage(c: Ctx, tgt, amount: int) -> int:
    """造成伤害。目标缺省打脸；返回实际造成的伤害"""
    if tgt is None or amount <= 0:
        return 0
    g = c.g
    src = c.src
    if c.spell:                              # 法术伤害：先吃法强，再吃维伦的倍率
        amount = int((amount + c.me.spell_power) * c.me.spell_mult)
    if is_minion(tgt):
        if tgt.shield:
            tgt.shield = False
            return 0
        tgt.hp -= amount
        owner = g.owner_of(tgt)
        if owner is not None and owner.minions_survive and tgt.hp < 1:
            tgt.hp = 1                       # 命令怒吼：本回合不会被降到 1 以下
        if tgt.freeze_on_damage:            # 水元素：伤害即冻结
            tgt.frozen = True
            tgt.attacks_left = 0
        if is_minion(src) and src.poisonous:  # 剧毒：伤害即消灭
            tgt.hp = 0
        real = amount
        g.emit("damage", target=tgt, amount=real, src=src)
    else:
        if getattr(tgt, "immune_turn", False):   # 寒冰屏障生效期间
            return 0
        absorbed = min(tgt.armor, amount)
        tgt.armor -= absorbed
        rest = amount - absorbed
        if rest > 0 and tgt.hp - rest <= 0 and g.check_secrets(tgt, "lethal", amount=rest):
            return 0                              # 寒冰屏障把致命伤害挡掉
        tgt.hp -= rest
        real = rest
        g.emit("damage", target=tgt, amount=real, src=src)
        if real > 0:
            g.check_secrets(tgt, "hero_damaged", amount=real)
    # 吸血
    if is_minion(src) and src.lifesteal:
        heal(c, c.me, real)
    g.check_deaths()
    g.recalc()
    return real


def heal(c: Ctx, tgt, amount: int):
    if tgt is None:
        tgt = c.me
    if c.spell and c.me.heal_as_damage:      # 奥金尼灵魂祭司：治疗改为造成伤害
        c.g.say("  奥金尼：治疗变为伤害")
        damage(c, tgt, amount)               # 法强/维伦在 damage 里统一结算
        return
    if c.spell:
        amount = int(amount * c.me.spell_mult)   # 维伦：治疗翻倍
    if is_minion(tgt):
        tgt.hp = min(tgt.max_hp, tgt.hp + amount)
    else:
        tgt.hp = min(getattr(tgt, "hero_max_hp", MAX_HP), tgt.hp + amount)
    c.g.emit("heal", target=tgt, src=tgt)


def summon(c: Ctx, cid_or_name, atk=0, hp=0, **kw) -> Optional[Minion]:
    """召唤随从。可传卡 id（查卡池）或直接传数值（token）"""
    if len(c.me.board) >= MAX_BOARD:
        return None
    if isinstance(cid_or_name, str) and cid_or_name in CARDS:
        d = CARDS[cid_or_name]
        m = make_minion(cid_or_name, d, c.me.pid)
    else:
        m = Minion(str(cid_or_name), atk, hp, hp, c.me.pid, **kw)
        m.base_atk = atk
        m.base_hp = hp
    m.summoned_this_turn = True
    m.attacks_left = 1 if (m.charge or m.rush) else 0
    c.me.board.append(m)
    c.g.emit("summon", src=m)
    c.g.recalc()
    return m


def summon_random_cost(c: Ctx, cost: int):
    """随机召唤一个法力值消耗为 cost 的随从（从当前卡池抽，如迷宫向导）"""
    pool = [cid for cid, d in CARDS.items()
            if d.get("type") == "MINION" and d.get("cost") == cost
            and not d.get("token") and d.get("implemented", True)]
    if pool:
        summon(c, c.g.rng.choice(pool))


def summon_token(c: Ctx, atk: int, hp: int, n: int = 1, name: str = "召唤物", **kw):
    """召唤 n 个数值随从（卡面上写的 N/M 小怪，没有对应卡牌数据）"""
    out = []
    for _ in range(n):
        m = summon(c, name, atk, hp, **kw)
        if m is not None:
            out.append(m)
    return out


def buff_hero_atk(c: Ctx, amount: int):
    """本回合给英雄加攻击力（含装备武器时）"""
    c.me.hero_atk += amount
    c.g.recalc()


def buff_weapon(c: Ctx, amount: int):
    """给装备中的武器加攻击力"""
    if c.me.weapon:
        c.me.weapon["atk"] += amount


def destroy_weapon(c: Ctx, side: str = "foe"):
    """摧毁一方的武器（酸性沼泽软泥怪）"""
    p = c.foe if side == "foe" else c.me
    p.weapon = None


def transform(c: Ctx, tgt, atk: int, hp: int, name: str = "变形产物"):
    """把随从变成另一只（变形术 → 1/1 绵羊）"""
    if not is_minion(tgt):
        return
    tgt.name, tgt.text, tgt.cid = name, "", ""
    tgt.base_atk, tgt.base_hp = atk, hp
    tgt.max_hp, tgt.hp, tgt.atk = hp, hp, atk
    tgt.buffs = []
    for k in ("taunt", "shield", "stealth", "windfury", "lifesteal",
              "poisonous", "reborn", "charge", "rush"):
        setattr(tgt, k, False)
    tgt.deathrattle = None
    tgt.triggers = []
    c.g.recalc()


def heal_full(c: Ctx, tgt):
    """治疗到满血（先祖治疗 / 治疗之环）"""
    if tgt is None:
        tgt = c.me
    if is_minion(tgt):
        tgt.hp = tgt.max_hp
    else:
        tgt.hp = getattr(tgt, "hero_max_hp", MAX_HP)


def set_health(c: Ctx, tgt, value: int):
    """把生命值降为 value（猎人印记）"""
    if is_minion(tgt):
        tgt.hp = min(tgt.hp, value)


def double_health(c: Ctx, tgt):
    """生命值翻倍（神圣之灵）"""
    if is_minion(tgt):
        tgt.max_hp *= 2
        tgt.hp *= 2


def atk_to_health(c: Ctx, tgt):
    """攻击力变成与生命值相等（心灵之火）"""
    if is_minion(tgt):
        tgt.buffs.append((tgt.hp - tgt.atk, 0))
        c.g.recalc()


def draw_for_both(c: Ctx, n: int = 1):
    """双方各抽 n 张（寒光智者）"""
    draw(c, n)
    for _ in range(n):
        p = c.foe
        if not p.deck:
            p.fatigue += 1
            p.hp -= p.fatigue
            continue
        if len(p.hand) < HAND_CAP:
            p.hand.append(p.deck.pop())


def add_random_to_hand(c: Ctx, rarity=None, ctype=None, race=None, cls=None):
    """随机将一张符合条件的牌置入手牌（光明之翼等）
    参数都可为 None：rarity='LEGENDARY' / ctype='MINION' / race='PIRATE' / cls='SHAMAN'
    """
    pool = []
    for cid, d in CARDS.items():
        if d.get("type") not in ("MINION", "SPELL", "WEAPON") or d.get("token"):
            continue
        if rarity and d.get("rarity") != rarity:
            continue
        if ctype and d.get("type") != ctype:
            continue
        if race and race not in (d.get("races") or []):
            continue
        if cls and d.get("cls") not in (cls, "NEUTRAL"):
            continue
        pool.append(cid)
    if not pool or len(c.me.hand) >= HAND_CAP:
        return None
    cid = c.g.rng.choice(pool)
    c.me.hand.append(cid)
    c.g.say(f"  将 {CARDS[cid].get('name', cid)} 置入手牌")
    return cid


def draw(c: Ctx, n: int = 1):
    for _ in range(n):
        p = c.me
        if not p.deck:
            p.fatigue += 1
            p.hp -= p.fatigue
            continue
        cid = p.deck.pop()
        if len(p.hand) >= HAND_CAP:
            continue
        p.hand.append(cid)


def buff(c: Ctx, tgt, atk: int = 0, hp: int = 0, **kw):
    if not is_minion(tgt):
        return
    tgt.buffs.append((atk, hp))
    tgt.atk += atk
    tgt.max_hp += hp
    tgt.hp += hp
    for k in ("taunt", "charge", "shield", "windfury", "lifesteal", "poisonous", "rush"):
        if kw.get(k):
            setattr(tgt, k, True)
    c.g.recalc()


def destroy(c: Ctx, tgt):
    if is_minion(tgt):
        tgt.hp = 0
        c.g.check_deaths()


def silence(c: Ctx, tgt):
    if not is_minion(tgt):
        return
    tgt.silenced = True
    for k in ("taunt", "charge", "rush", "shield", "stealth", "windfury",
              "lifesteal", "poisonous", "reborn", "frozen"):
        setattr(tgt, k, False)
    tgt.spell_power = 0
    tgt.buffs.clear()
    tgt.temp_buffs.clear()
    tgt.atk = tgt.base_atk
    tgt.max_hp = max(1, tgt.max_hp)
    tgt.hp = min(tgt.hp, tgt.max_hp)
    tgt.deathrattle, tgt.triggers = None, []
    c.g.recalc()


def freeze(c: Ctx, tgt):
    if is_minion(tgt):
        tgt.frozen = True
        tgt.attacks_left = 0
    elif tgt is not None:
        tgt.frozen = True          # 英雄被冻结：下个回合不能攻击（回合结束时解冻）


def gain_armor(c: Ctx, amount: int):
    c.me.armor += amount


def swap_stats(c: Ctx, tgt):
    if is_minion(tgt):
        tgt.atk, tgt.max_hp = tgt.max_hp, tgt.atk
        tgt.hp = min(tgt.hp, tgt.max_hp)
        c.g.check_deaths()


def aoe(c: Ctx, fn: Callable, side: str = "foe"):
    board = c.foe.board if side == "foe" else c.me.board
    for m in list(board):
        fn(m)


def all_minions(c: Ctx):
    return list(c.me.board) + list(c.foe.board)


def buff_neighbors(c: Ctx, atk=0, hp=0, **kw):
    b = c.me.board
    if not is_minion(c.src) or c.src not in b:
        return
    i = b.index(c.src)
    for j in (i - 1, i + 1):
        if 0 <= j < len(b):
            buff(c, b[j], atk, hp, **kw)


def buff_all(c: Ctx, atk=0, hp=0, side="own", exclude_src=False, **kw):
    b = c.me.board if side == "own" else c.foe.board
    for m in list(b):
        if exclude_src and m is c.src:
            continue
        buff(c, m, atk, hp, **kw)


def add_to_hand(c: Ctx, cid, n=1):
    for _ in range(n):
        if len(c.me.hand) < HAND_CAP:
            c.me.hand.append(cid)


def shuffle_into_deck(c: Ctx, cid, n=1):
    for _ in range(n):
        pos = c.g.rng.randrange(len(c.me.deck) + 1)
        c.me.deck.insert(pos, cid)


def return_to_hand(c: Ctx, tgt):
    if is_minion(tgt) and tgt in c.me.board:
        c.me.board.remove(tgt)
        add_to_hand(c, tgt.cid)


def take_control(c: Ctx, tgt):
    if not is_minion(tgt) or tgt in c.me.board:
        return
    c.foe.board.remove(tgt)
    c.me.board.append(tgt)
    tgt.owner_id = c.me.pid
    tgt.attacks_left = 0


def equip_weapon(c: Ctx, atk: int, durability: int, name="Weapon"):
    c.me.weapon = dict(name=name, atk=atk, durability=durability)


def gain_mana(c: Ctx, amount: int):
    c.me.mana = min(MAX_MANA, c.me.mana + amount)


def copy_minion(c: Ctx, tgt):
    if is_minion(tgt):
        summon(c, tgt.name, tgt.atk, tgt.hp)


def random_minion(c: Ctx, side="foe"):
    b = c.foe.board if side == "foe" else c.me.board
    return c.g.rng.choice(b) if b else None


def spell_damage_of(c: Ctx) -> int:
    return c.me.spell_power + sum(m.spell_power for m in c.me.board)


def enemy_hero(c: Ctx):
    return c.foe


def own_hero(c: Ctx):
    return c.me


# ============ 本回合临时增益 ============
def temp_buff(c: Ctx, tgt, atk: int = 0, hp: int = 0):
    """「在本回合中」的增益：回合结束自动消失。英雄则加到临时攻击力"""
    if tgt is None:
        tgt = c.me
    if is_minion(tgt):
        tgt.temp_buffs.append((atk, hp))
        c.g.recalc()
    else:
        tgt.hero_atk += atk


def set_atk(c: Ctx, tgt, value: int):
    """把攻击力改为 value（谦逊 / 奥尔多卫士）"""
    if is_minion(tgt):
        tgt.buffs.append((value - tgt.atk, 0))
        c.g.recalc()


def double_atk(c: Ctx, tgt):
    """攻击力翻倍（受祝福的勇士）"""
    if is_minion(tgt):
        tgt.buffs.append((tgt.atk, 0))
        c.g.recalc()


def give_charge(c: Ctx, tgt):
    if is_minion(tgt):
        tgt.charge = True
        tgt.attacks_left = max(tgt.attacks_left, 2 if tgt.windfury else 1)


def give_windfury(c: Ctx, tgt):
    if is_minion(tgt):
        tgt.windfury = True
        if tgt.attacks_left > 0:
            tgt.attacks_left = 2


def next_spell_discount(c: Ctx, n: int = 3):
    """伺机待发：本回合下一张法术 -n 费（回合结束自动清零）"""
    c.me.next_spell_discount += n


def next_secret_free(c: Ctx):
    """肯瑞托法师：本回合下一个奥秘 0 费"""
    c.me.next_secret_free = 1


def enemy_spells_free(c: Ctx):
    """米尔豪斯·法力风暴：对手下个回合的法术全 0 费"""
    c.foe.spells_free = True


# ============ 随机 / 概率 ============
def damage_random_enemy(c: Ctx, amount: int = 1, times: int = 1):
    """随机对敌方角色（随从或英雄）造成伤害"""
    for _ in range(times):
        pool = list(c.foe.board)
        if c.foe.hp > 0:
            pool.append(c.foe)
        if not pool:
            return
        damage(c, c.g.rng.choice(pool), amount)


def damage_random(c: Ctx, amount: int = 1, times: int = 1):
    """随机对所有角色造成伤害（疯狂投弹者）"""
    for _ in range(times):
        pool = list(c.me.board) + list(c.foe.board) + [c.me, c.foe]
        damage(c, c.g.rng.choice(pool), amount)


def destroy_random_enemy(c: Ctx, max_atk=None):
    pool = [m for m in c.foe.board
            if max_atk is None or m.atk <= max_atk]
    if pool:
        destroy(c, c.g.rng.choice(pool))


def chance_draw(c: Ctx, pct: int = 50, n: int = 1):
    if c.g.rng.randrange(100) < pct:
        draw(c, n)
        c.g.say("  幸运地多抽了一张牌")


def buff_random_other(c: Ctx, atk: int = 0, hp: int = 0):
    pool = [m for m in c.me.board if m is not c.src and m.alive]
    if pool:
        buff(c, c.g.rng.choice(pool), atk, hp)


def heal_random_damaged(c: Ctx, amount: int = 3):
    pool = [m for m in c.me.board if m.hp < m.max_hp]
    if c.me.hp < MAX_HP:
        pool.append(c.me)
    if pool:
        heal(c, c.g.rng.choice(pool), amount)


def steal_random_minion(c: Ctx):
    if c.foe.board:
        take_control(c, c.g.rng.choice(list(c.foe.board)))


# ============ 手牌 / 牌库 ============
def discard_random(c: Ctx, n=1):
    for _ in range(n):
        if c.me.hand:
            c.me.hand.pop(c.g.rng.randrange(len(c.me.hand)))


def discard_hand(c: Ctx):
    n = len(c.me.hand)
    c.me.hand.clear()
    return n


def copy_from_foe_hand(c: Ctx, n: int = 1):
    """随机复制对手手牌（心灵视界）"""
    for _ in range(n):
        if not c.foe.hand or len(c.me.hand) >= HAND_CAP:
            return
        cid = c.g.rng.choice(c.foe.hand)
        c.me.hand.append(cid)
        c.g.say(f"  复制了 {CARDS.get(cid, {}).get('name', cid)}")


def copy_from_foe_deck(c: Ctx, n: int = 1, only_minion: bool = False):
    """复制对手牌库（思维窃取 / 控心术）"""
    pool = [cid for cid in c.foe.deck
            if not only_minion or CARDS.get(cid, {}).get("type") == "MINION"]
    for _ in range(n):
        if not pool:
            return
        cid = c.g.rng.choice(pool)
        pool.remove(cid)
        if only_minion:
            summon(c, cid)
        elif len(c.me.hand) < HAND_CAP:
            c.me.hand.append(cid)
            c.g.say(f"  复制了 {CARDS.get(cid, {}).get('name', cid)}")


def draw_until_even(c: Ctx):
    """神恩术：抽到手牌数追平对手"""
    while len(c.me.hand) < len(c.foe.hand) and c.me.deck:
        draw(c, 1)


def draw_per_damaged(c: Ctx):
    """战斗怒火：每个受伤的友方角色抽一张"""
    n = sum(1 for m in c.me.board if m.hp < m.max_hp) + (1 if c.me.hp < MAX_HP else 0)
    draw(c, n)


# ============ 场面 ============
def destroy_all_other_minions(c: Ctx):
    """死亡之翼：消灭所有其他随从"""
    for p in (c.me, c.foe):
        for m in list(p.board):
            if m is not c.src:
                destroy(c, m)


def set_all_health(c: Ctx, value: int = 1):
    """生而平等：所有随从生命值变为 1"""
    for p in (c.me, c.foe):
        for m in list(p.board):
            m.hp = min(m.hp, value)
    c.g.check_deaths()


def buff_race(c: Ctx, race: str, atk: int = 0, hp: int = 0, other: bool = True):
    """种族群体增益（寒光先知：所有其他鱼人 +2 生命）"""
    for m in list(c.me.board):
        if other and m is c.src:
            continue
        if race in m.races:
            buff(c, m, atk, hp)


def set_hero_hp(c: Ctx, tgt=None, value: int = 15):
    """阿莱克丝塔萨：把一方英雄生命变为 15"""
    if isinstance(tgt, Player):
        tgt.hp = value
    elif c.me.hp < value:
        c.me.hp = value
    else:
        c.foe.hp = value


def armor_as_damage(c: Ctx, tgt):
    """盾牌猛击：造成等同于护甲值的伤害"""
    damage(c, tgt, c.me.armor)


def hero_atk_damage(c: Ctx, tgt):
    """野蛮之击：造成等同于英雄攻击力的伤害"""
    damage(c, tgt, c.me.attack)


def destroy_if_atk(c: Ctx, tgt, min_atk: int = 7):
    """王牌猎人 / 暗言术：灭，只对满足攻击力条件的随从生效"""
    if is_minion(tgt) and tgt.atk >= min_atk:
        destroy(c, tgt)


def take_control_if(c: Ctx, tgt, max_atk: int = 2):
    """暗影狂乱 / 白卡牧师：只对攻击力不超标的敌方随从生效"""
    if is_minion(tgt) and tgt.atk <= max_atk:
        take_control(c, tgt)


def shadow_madness(c: Ctx, tgt, max_atk: int = 3):
    """暗影狂乱：本回合抢过来，回合结束时还回去"""
    if not is_minion(tgt) or tgt not in c.foe.board or tgt.atk > max_atk:
        return
    take_control(c, tgt)
    tgt.summoned_this_turn = False          # 抢来就能打
    tgt.attacks_left = 0 if tgt.frozen else 1
    c.me.borrowed.append(tgt)


def void_terror(c: Ctx):
    """虚空恐魔：吃掉左右相邻随从，获得它们的攻击力与生命值"""
    m = c.src
    board = c.me.board
    if not is_minion(m) or m not in board:
        return
    i = board.index(m)
    eat = [board[j] for j in (i - 1, i + 1) if 0 <= j < len(board)]
    atk = sum(x.atk for x in eat)
    hp = sum(max(0, x.hp) for x in eat)
    for x in eat:
        board.remove(x)
        c.g.say(f"  吞噬了 {x.name}")
    c.g.check_deaths()
    if atk or hp:
        buff(c, m, atk, hp)


def mind_control_tech(c: Ctx, need: int = 4):
    """精神控制技师：对手有 N 个以上随从时，随机抢一个"""
    if len(c.foe.board) >= need:
        take_control(c, c.g.rng.choice(c.foe.board))


def tinker(c: Ctx):
    """工匠大师欧沃斯巴克：把另一个随机随从变成 5/5 暴掠龙或 1/1 松鼠"""
    pool = [x for x in c.me.board + c.foe.board if x is not c.src and x.alive]
    if not pool:
        return
    t = c.g.rng.choice(pool)
    if c.g.rng.random() < 0.5:
        transform(c, t, 5, 5, "暴掠龙")
    else:
        transform(c, t, 1, 1, "松鼠")


def blessing_of_wisdom(c: Ctx, tgt):
    """智慧祝福：给随从挂一个「攻击时抽一张牌」的触发"""
    if not is_minion(tgt):
        return
    def fn(x):
        if x.event_src is tgt:
            draw(x, 1)
    tgt.triggers.append(("attack", fn))


def ancestral_spirit(c: Ctx, tgt):
    """先祖之魂：随从死亡时原样复活一次"""
    if not is_minion(tgt):
        return
    cid = tgt.cid
    owner = tgt.owner_id
    def dr(x):
        pl = x.g.players[owner]
        if len(pl.board) >= MAX_BOARD:
            return
        m = make_minion(cid, CARDS.get(cid, {}), owner)
        m.summoned_this_turn = True
        m.attacks_left = 0
        pl.board.append(m)
        x.g.say(f"  先祖之魂：{m.name} 复活")
        x.g.emit("summon", src=m)
        x.g.recalc()
    if tgt.deathrattle:                       # 原本就有亡语：两个都触发
        old = tgt.deathrattle
        tgt.deathrattle = lambda x: (old(x), dr(x))
    else:
        tgt.deathrattle = dr


def corruption(c: Ctx, tgt):
    """腐蚀术：目标随从在施法者下个回合开始时被摧毁"""
    if not is_minion(tgt):
        return
    caster = c.me.pid
    def fn(x):
        if x.g.cur.pid == caster:
            x.g.say(f"  腐蚀：{tgt.name} 被摧毁")
            destroy(x, tgt)
    tgt.triggers.append(("turn_start", fn))


def alarm_o_bot(c: Ctx):
    """报警机器人：回合开始时和手牌里随机一个随从交换"""
    m = c.src
    board = c.me.board
    if not is_minion(m) or m not in board:
        return
    idxs = [i for i, cid in enumerate(c.me.hand)
            if CARDS.get(cid, {}).get("type") == "MINION"]
    if not idxs:
        return
    i = c.g.rng.choice(idxs)
    cid = c.me.hand.pop(i)
    pos = board.index(m)
    nm = make_minion(cid, CARDS[cid], c.me.pid)
    nm.summoned_this_turn = True
    nm.attacks_left = 1 if (nm.charge or nm.rush) else 0
    board[pos] = nm
    c.me.hand.append(m.cid)
    c.g.say(f"  报警机器人换成 {nm.name}")
    c.g.emit("summon", src=nm)
    c.g.recalc()


def cho_on_board(g: "Game") -> bool:
    """场上是否有游学者周卓（有则每次施法都要给对方一张复制）"""
    return any(CARDS.get(m.cid, {}).get("cho_copy")
               for pl in g.players for m in pl.board if not m.silenced)


# ============ 带条件的单张效果 ============
# 卡面是「A；如果…则改为 B」这类，正则表达不了条件，单独写。
def ice_lance(c: Ctx, tgt):
    """冰枪术：已冻结则打 4 点，否则冻结"""
    if is_minion(tgt) and tgt.frozen:
        damage(c, tgt, 4)
    elif not is_minion(tgt):
        damage(c, tgt, 4) if getattr(tgt, "frozen", False) else freeze(c, tgt)
    else:
        freeze(c, tgt)


def cold_blood(c: Ctx, tgt):
    """冷血：+2 攻；连击改为 +4"""
    buff(c, tgt, 4 if c.combo else 2, 0)


def eviscerate(c: Ctx, tgt):
    """刺骨：2 伤；连击改为 4 伤"""
    damage(c, tgt, 4 if c.combo else 2)


def perdition_blade(c: Ctx, tgt):
    """毁灭之刃战吼：1 伤；连击改为 2 伤"""
    damage(c, tgt, 2 if c.combo else 1)


def mortal_strike(c: Ctx, tgt):
    """致死打击：4 伤；自己血量 ≤12 时改为 6 伤"""
    damage(c, tgt, 6 if c.me.hp <= 12 else 4)


def kill_command(c: Ctx, tgt):
    """杀戮命令：3 伤；控制野兽时 5 伤"""
    has_beast = any("BEAST" in m.races for m in c.me.board)
    damage(c, tgt, 5 if has_beast else 3)


def mortal_coil(c: Ctx, tgt):
    """死亡缠绕：1 伤，若目标死亡则抽一张"""
    damage(c, tgt, 1)
    if is_minion(tgt) and not tgt.alive:
        draw(c, 1)


def slam(c: Ctx, tgt):
    """猛击：2 伤，若目标仍存活则抽一张"""
    damage(c, tgt, 2)
    if is_minion(tgt) and tgt.alive:
        draw(c, 1)


def bane_of_doom(c: Ctx, tgt):
    """末日灾祸：3 伤，若目标死亡则随机召唤一个恶魔"""
    damage(c, tgt, 3)
    dead = (is_minion(tgt) and not tgt.alive) or (isinstance(tgt, Player) and tgt.hp <= 0)
    if dead:
        pool = [cid for cid, d in CARDS.items()
                if d.get("type") == "MINION" and "DEMON" in (d.get("races") or [])
                and not d.get("token")]
        if pool:
            summon(c, c.g.rng.choice(pool))


def demonfire(c: Ctx, tgt):
    """恶魔之火：2 伤；若目标是友方恶魔则改为 +2/+2"""
    if is_minion(tgt) and tgt.owner_id == c.me.pid and "DEMON" in tgt.races:
        buff(c, tgt, 2, 2)
    else:
        damage(c, tgt, 2)


def upgrade_weapon(c: Ctx):
    """升级：有武器就 +1/+1，没有就装备 1/3 的武器"""
    if c.me.weapon:
        c.me.weapon["atk"] += 1
        c.me.weapon["durability"] += 1
    else:
        equip_weapon(c, 1, 3, "步兵长剑")


def blood_knight(c: Ctx):
    """血骑士：所有随从失去圣盾，每失去一个 +3/+3"""
    n = 0
    for pl in (c.me, c.foe):
        for m in list(pl.board):
            if m.shield:
                m.shield = False
                n += 1
    if n and is_minion(c.src):
        buff(c, c.src, 3 * n, 3 * n)


def soul_of_the_forest(c: Ctx):
    """丛林之魂：友方随从获得「亡语：召唤一个 2/2 树人」"""
    for m in list(c.me.board):
        if m.silenced:
            continue
        def dr(x):
            summon_token(x, 2, 2, 1, "树人")
        if m.deathrattle:
            old = m.deathrattle
            m.deathrattle = lambda x, old=old, dr=dr: (old(x), dr(x))
        else:
            m.deathrattle = dr


def power_overwhelming(c: Ctx, tgt):
    """力量的代价：+4/+4，回合结束时死亡"""
    if not is_minion(tgt):
        return
    buff(c, tgt, 4, 4)
    tgt.die_at_end = True


def flare(c: Ctx):
    """照明弹：所有随从失去潜行，摧毁敌方奥秘，抽一张"""
    for pl in (c.me, c.foe):
        for m in pl.board:
            m.stealth = False
    destroy_enemy_secrets(c)
    draw(c, 1)


def force_of_nature(c: Ctx):
    """自然之力：召唤三个 2/2 冲锋树人，回合结束时消灭它们"""
    for _ in range(3):
        m = summon(c, "树人", 2, 2)
        if m is not None:
            m.charge = True
            m.attacks_left = 1
            m.die_at_end = True


def commanding_shout(c: Ctx):
    """命令怒吼：本回合己方随从血量不会低于 1，抽一张"""
    c.me.minions_survive = True
    draw(c, 1)


def shadowform(c: Ctx):
    """暗影形态：英雄技能变成造成 2 点伤害；再放一次变 3 点"""
    if c.me.hero_power_key != "SHADOW":
        c.me.hero_power_key = "SHADOW"
        c.g.say("  暗影形态：英雄技能变为造成 2 点伤害")
    else:
        c.me.hero_power_key = "SHADOW2"
        c.g.say("  暗影形态加深：英雄技能变为造成 3 点伤害")


def draw_cheap(c: Ctx, n: int = 1, disc: int = 3):
    """视界术：抽一张，抽到的那张降价"""
    before = len(c.me.hand)
    draw(c, n)
    if len(c.me.hand) > before:
        cid = c.me.hand[-1]
        reg = c.me.cheap.setdefault(cid, [0, 0])
        reg[0] = max(reg[0], disc)
        reg[1] += 1


def shadowstep(c: Ctx, tgt):
    """暗影步：把一个友方随从移回手牌，并让它降价 2 费"""
    if not is_minion(tgt):
        return
    cid = tgt.cid
    return_to_hand(c, tgt)
    if cid:
        reg = c.me.cheap.setdefault(cid, [0, 0])
        reg[0] = max(reg[0], 2)
        reg[1] += 1


def track_draw3(c: Ctx):
    """追踪术：看牌库顶三张，拿走一张，弃掉另外两张"""
    deck = c.me.deck
    if not deck:
        return
    top = deck[-3:]
    pick = top[-1]                       # 简化：默认拿最上面那张
    for cid in top:
        deck.remove(cid)
        if cid != pick:
            c.g.say(f"  追踪术弃掉 {CARDS.get(cid, {}).get('name', cid)}")
    if len(c.me.hand) < HAND_CAP:
        c.me.hand.append(pick)


def silence_all_foe(c: Ctx):
    for m in list(c.foe.board):
        silence(c, m)


def give_stealth_all(c: Ctx):
    for m in list(c.me.board):
        m.stealth = True


def hide_minions(c: Ctx):
    """隐藏：己方随从获得潜行，到你的下个回合开始前有效"""
    for m in list(c.me.board):
        m.stealth = True
        m.stealth_temp = True


def headcrack(c: Ctx, tgt=None):
    """裂颅之击：对敌方英雄造成 2 点伤害；连击则这张牌下回合回到手牌"""
    damage(c, tgt if tgt is not None else c.foe, 2)
    cid = (c.card or {}).get("cid")
    if c.combo and cid:
        c.me.pending_hand.append(cid)
        c.g.say("  连击：裂颅之击将在下个回合回到手中")


def destroy_enemy_secrets(c: Ctx):
    n = len(c.foe.secrets)
    c.foe.secrets.clear()
    for m in list(c.me.board) + list(c.foe.board):
        m.stealth = False
    if n:
        c.g.say(f"  摧毁了对手 {n} 个奥秘")


def shadowflame(c: Ctx, tgt):
    """暗影烈焰：消灭一个友方随从，对所有敌方随从造成等同其攻击力的伤害"""
    if not is_minion(tgt):
        return
    atk = tgt.atk
    destroy(c, tgt)
    for m in list(c.foe.board):
        damage(c, m, atk)


def betrayal(c: Ctx, tgt):
    """背叛：让一个敌方随从殴打它两侧的同伴"""
    if not is_minion(tgt) or tgt not in c.foe.board:
        return
    b = c.foe.board
    i = b.index(tgt)
    for j in (i - 1, i + 1):
        if 0 <= j < len(b) and b[j] is not tgt:
            damage(c, b[j], tgt.atk)


def brawl(c: Ctx):
    """乱斗：只留一个随从"""
    pool = [m for m in list(c.me.board) + list(c.foe.board)]
    if len(pool) <= 1:
        return
    keep = c.g.rng.choice(pool)
    for m in pool:
        if m is not keep:
            destroy(c, m)


def buff_neighbors_sp(c: Ctx, n: int = 1):
    """年迈的法师：相邻随从获得法术伤害 +1"""
    b = c.me.board
    if not is_minion(c.src) or c.src not in b:
        return
    i = b.index(c.src)
    for j in (i - 1, i + 1):
        if 0 <= j < len(b):
            b[j].spell_power += n


def draw_filtered(c: Ctx, race=None, n: int = 1):
    """感知恶魔：从牌库中抽指定种族的牌"""
    for _ in range(n):
        for k in range(len(c.me.deck) - 1, -1, -1):
            cid = c.me.deck[k]
            d = CARDS.get(cid, {})
            if race is None or race in (d.get("races") or []):
                c.me.deck.pop(k)
                if len(c.me.hand) < HAND_CAP:
                    c.me.hand.append(cid)
                break


def add_card_named(c: Ctx, en_name: str, n: int = 1):
    """按英文名检索卡池并置入手牌（大法师安东尼达斯 → 火球术）"""
    target = en_name.lower()
    for cid, d in CARDS.items():
        if (d.get("en") or "").lower() == target:
            add_to_hand(c, cid, n)
            c.g.say(f"  将 {d.get('name')} 置入手牌")
            return
    for cid, d in CARDS.items():
        if target in (d.get("en") or "").lower():
            add_to_hand(c, cid, n)
            c.g.say(f"  将 {d.get('name')} 置入手牌")
            return


def buff_per_hand(c: Ctx, per_hp: int = 1):
    """暮光幼龙：手里每有一张牌 +N 生命"""
    buff(c, c.src, 0, per_hp * len(c.me.hand))


def buff_per_board(c: Ctx, per: int = 1):
    """霜狼督军：场上每有一个其他友方随从 +N/+N"""
    n = max(0, len(c.me.board) - 1)
    buff(c, c.src, per * n, per * n)


def combo_buff(c: Ctx, per: int = 2):
    """艾德温·范克里夫：本回合此前每打出一张牌 +N/+N"""
    n = max(0, c.me.cards_played)
    buff(c, c.src, per * n, per * n)


def damage_step(c: Ctx, tgt, lo: int, hi: int):
    """闪电风暴：在区间内随机伤害（2-3 点）"""
    damage(c, tgt, c.g.rng.randint(lo, hi))


def aoe_range(c: Ctx, lo: int, hi: int, side: str = "foe"):
    for m in list(c.foe.board if side == "foe" else c.me.board):
        damage(c, m, c.g.rng.randint(lo, hi))


def cleave_enemies(c: Ctx, tgt, main: int, splash: int):
    """横扫：对目标造成 main，其余敌人 splash"""
    damage(c, tgt, main)
    for m in list(c.foe.board):
        if m is not tgt:
            damage(c, m, splash)
    if tgt is not c.foe:
        damage(c, c.foe, splash)


def explosive_shot(c: Ctx, tgt, main: int, splash: int):
    """爆炸射击：目标 main，相邻 splash"""
    if not is_minion(tgt) or tgt not in c.foe.board:
        return
    b = c.foe.board
    i = b.index(tgt)
    damage(c, tgt, main)
    for j in (i - 1, i + 1):
        if 0 <= j < len(b):
            damage(c, b[j], splash)


def cone_of_cold(c: Ctx, tgt, amount: int = 1):
    """冰锥术：冻结目标及相邻，并造成伤害"""
    if not is_minion(tgt) or tgt not in c.foe.board:
        return
    b = c.foe.board
    i = b.index(tgt)
    for j in (i - 1, i, i + 1):
        if 0 <= j < len(b):
            freeze(c, b[j])
            damage(c, b[j], amount)


def blade_flurry(c: Ctx):
    """剑刃乱舞：摧毁武器，把攻击力打到所有敌人身上"""
    atk = c.me.weapon["atk"] if c.me.weapon else 0
    c.me.weapon = None
    for m in list(c.foe.board):
        damage(c, m, atk)
    damage(c, c.foe, atk)


def freeze_and_damage(c: Ctx, tgt, amount: int):
    """寒冰箭：伤害并冻结"""
    damage(c, tgt, amount)
    freeze(c, tgt)


def destroy_if_race(c: Ctx, tgt, race: str):
    """牺牲契约：只对指定种族生效"""
    if is_minion(tgt) and race in tgt.races:
        destroy(c, tgt)


def hungry_crab(c: Ctx, atk: int = 2, hp: int = 2):
    """鱼人杀手蟹：吃掉一个鱼人并 +2/+2"""
    if is_minion(c.target) and "MURLOC" in c.target.races:
        destroy(c, c.target)
        buff(c, c.src, atk, hp)


def harrison(c: Ctx):
    """哈里森·琼斯：毁掉对手武器，按其耐久抽牌"""
    w = c.foe.weapon
    n = w["durability"] if w else 0
    c.foe.weapon = None
    draw(c, n)


def holy_wrath(c: Ctx):
    """神圣愤怒：抽一张牌，造成等同于其费用的伤害"""
    p = c.me
    if not p.deck:
        return
    cid = p.deck.pop()
    if len(p.hand) < HAND_CAP:
        p.hand.append(cid)
    cost = CARDS.get(cid, {}).get("cost", 0)
    damage(c, c.target if c.target is not None else c.foe, cost)


def draw_foe(c: Ctx, n: int = 1):
    """让对手抽牌（自然平衡 / 寒光智者）"""
    for _ in range(n):
        p = c.foe
        if not p.deck:
            p.fatigue += 1
            p.hp -= p.fatigue
            continue
        if len(p.hand) < HAND_CAP:
            p.hand.append(p.deck.pop())


def temp_buff_all(c: Ctx, atk: int = 0, hp: int = 0):
    """本回合给所有友方角色加攻（野蛮咆哮：+2 攻击）"""
    for m in list(c.me.board):
        m.temp_buffs.append((atk, hp))
    c.me.hero_atk += atk
    c.g.recalc()


def buff_from_weapon(c: Ctx):
    """血帆袭击者：获得等同于武器攻击力的攻击力"""
    if c.me.weapon:
        buff(c, c.src, c.me.weapon["atk"], 0)


def weapon_durability(c: Ctx, side: str = "foe", delta: int = -1):
    """血帆海盗：让对手的武器掉耐久"""
    p = c.foe if side == "foe" else c.me
    if not p.weapon:
        return
    p.weapon["durability"] += delta
    if p.weapon["durability"] <= 0:
        c.g.say(f"  {p.weapon['name']} 已损坏")
        p.weapon = None


def weapon_gain_dura(c: Ctx, n: int = 1):
    """绿皮船长 / 鹰角弓：武器加耐久"""
    if c.me.weapon:
        c.me.weapon["durability"] += n


def summon_chargers(c: Ctx, atk: int, hp: int, n: int = 3, name: str = "树人"):
    """自然之力：召唤带冲锋的随从"""
    for _ in range(n):
        m = summon(c, name, atk, hp)
        if m is not None:
            m.charge = True
            m.attacks_left = 1


def destroy_damaged_enemy(c: Ctx):
    """斩杀：消灭一个受伤的敌方随从"""
    pool = [m for m in c.foe.board if m.hp < m.max_hp]
    if pool:
        destroy(c, c.g.rng.choice(pool))


def return_all_minions(c: Ctx):
    """消失：所有随从回手"""
    for p in (c.me, c.foe):
        for m in list(p.board):
            p.board.remove(m)
            if m.cid and len(p.hand) < HAND_CAP:
                p.hand.append(m.cid)
    c.g.recalc()


def summon_per_enemy(c: Ctx, atk: int = 1, hp: int = 1, name: str = "猎犬"):
    """关门放狗：每有一个敌方随从召唤一个"""
    for _ in range(len(c.foe.board)):
        m = summon(c, name, atk, hp)
        if m is not None:
            m.charge = True
            m.attacks_left = 1


def summon_companion(c: Ctx):
    """动物伙伴：随机三选一"""
    opts = [("霍弗", 4, 2), ("雷欧克", 2, 4), ("米莎", 4, 4)]
    name, a, h = c.g.rng.choice(opts)
    summon(c, name, a, h)


def track_draw(c: Ctx, look: int = 3):
    """追踪术：看牌库顶三张，抽一张弃掉其余"""
    if not c.me.deck:
        return
    top = [c.me.deck.pop() for _ in range(min(look, len(c.me.deck)))]
    if len(c.me.hand) < HAND_CAP:
        c.me.hand.append(top.pop(0))
    for cid in top:
        c.g.say(f"  弃掉 {CARDS.get(cid, {}).get('name', cid)}")


# ============ 资源 ============
def overload(c: Ctx, n: int):
    """过载：下回合锁住 n 个法力水晶"""
    c.me.overload += n


def burn_crystal(c: Ctx, n: int = 1):
    """摧毁自己的法力水晶（恶魔卫士）"""
    c.me.max_mana = max(0, c.me.max_mana - n)
    c.me.mana = min(c.me.mana, c.me.max_mana)


def give_crystal(c: Ctx, side: str = "foe", n: int = 1):
    """给一方一个空的法力水晶（奥术傀儡）"""
    p = c.foe if side == "foe" else c.me
    p.max_mana = min(MAX_MANA, p.max_mana + n)


def become_copy(c: Ctx, tgt):
    """无面操纵者：成为目标随从的复制"""
    if not is_minion(tgt) or not is_minion(c.src):
        return
    s = c.src
    s.name, s.atk, s.hp, s.max_hp = tgt.name, tgt.atk, tgt.hp, tgt.max_hp
    s.base_atk, s.base_hp = tgt.base_atk, tgt.base_hp
    s.text, s.races = tgt.text, list(tgt.races)
    s.taunt, s.shield, s.stealth = tgt.taunt, tgt.shield, tgt.stealth
    s.windfury, s.charge, s.rush = tgt.windfury, tgt.charge, tgt.rush
    s.poisonous, s.lifesteal = tgt.poisonous, tgt.lifesteal
    s.deathrattle, s.triggers = tgt.deathrattle, list(tgt.triggers)
    c.g.recalc()


# ============ 衍生牌（不在卡池，只能被效果生成）============
def bounce(c: Ctx, tgt):
    """把一个随从移回其拥有者的手牌（梦境）"""
    if not is_minion(tgt):
        return
    owner = c.g.players[tgt.owner_id]
    if tgt in owner.board:
        owner.board.remove(tgt)
    if tgt.cid and len(owner.hand) < HAND_CAP:
        owner.hand.append(tgt.cid)
    c.g.recalc()


def nightmare(c: Ctx, tgt):
    """梦魇：+5/+5，施法者下回合开始时摧毁它"""
    if not is_minion(tgt):
        return
    buff(c, tgt, 5, 5)
    caster = c.me.pid
    def fn(x):
        if x.g.cur.pid == caster:
            x.g.say(f"  梦魇：{tgt.name} 被摧毁")
            destroy(x, tgt)
    tgt.triggers.append(("turn_start", fn))


def ysera_awakens(c: Ctx):
    """伊瑟拉的苏醒：对所有角色造成 5 点伤害（伊瑟拉自己除外）"""
    for pl in (c.me, c.foe):
        for m in list(pl.board):
            if m.name != "伊瑟拉":
                damage(c, m, 5)
        damage(c, pl, 5)


def summon_horde(c: Ctx):
    """部落的力量：随机召唤一名部落勇士（固定六张池，官方原文就是这句）"""
    pool = [cid for cid in HORDE_CHAMPIONS if cid in CARDS]
    if pool:
        summon(c, c.g.rng.choice(pool))


def give_foe_tokens(c: Ctx, cid: str, n: int = 1):
    """给对手 n 张衍生牌（穆克拉的香蕉）"""
    for _ in range(n):
        if len(c.foe.hand) < HAND_CAP:
            c.foe.hand.append(cid)


DREAM_CARDS = ["TOKEN_DREAM", "TOKEN_NIGHTMARE", "TOKEN_AWAKEN",
               "TOKEN_DRAKE", "TOKEN_SISTER"]
CHORD_CARDS = ["TOKEN_MURLOC", "TOKEN_HORDE", "TOKEN_ROGUE"]

# 「部落的力量」的召唤池：官方就是固定六名部落勇士，不是随机传说
# 霜狼步兵 / 森金持盾卫士 / 萨尔玛先知 / 银月城卫兵 / 凯恩·血蹄 / 牛头人战士
HORDE_CHAMPIONS = ["VAN_CS2_121", "VAN_CS2_179", "VAN_EX1_021",
                   "VAN_EX1_023", "VAN_EX1_110", "VAN_EX1_390"]


def add_random_dream(c: Ctx):
    """伊瑟拉：回合结束随机给一张梦境牌"""
    if len(c.me.hand) >= HAND_CAP:
        return
    cid = c.g.rng.choice(DREAM_CARDS)
    c.me.hand.append(cid)
    c.g.say(f"  伊瑟拉给了你「{CARDS[cid]['name']}」")


def etc_chord(c: Ctx):
    """精英牛头人酋长：双方各得同一张力量和弦牌"""
    cid = c.g.rng.choice(CHORD_CARDS)
    for pl in (c.me, c.foe):
        if len(pl.hand) < HAND_CAP:
            pl.hand.append(cid)
    c.g.say(f"  力量和弦：「{CARDS[cid]['name']}」")


def jaraxxus(c: Ctx):
    """加拉克苏斯大王：英雄变成 15 血的加拉克苏斯，装备 3/8 血怒"""
    p = c.me
    p.hp = 15
    p.armor = 0
    p.hero_max_hp = 15
    p.hero_name = "加拉克苏斯大王"
    p.hero_power_key = "JARAXXUS"
    p.weapon = dict(name="血怒", atk=3, durability=8)
    c.g.say("  加拉克苏斯大王降临！英雄变为 15 血，装备血怒 3/8")
    c.g.recalc()


def _tok(cid: str, **kw):
    """登记一张衍生牌（不进卡池、不能被随机开出）"""
    kw["token"] = True
    kw.setdefault("implemented", True)
    return register(cid, **kw)


_tok("TOKEN_BANANA", name="香蕉", cost=1, type="SPELL", cls="NEUTRAL", text="使一个随从获得+1/+1。",
     rarity="COMMON", targeting="any", effect=lambda c: buff(c, c.target, 1, 1))
_tok("TOKEN_DREAM", name="梦境", cost=0, type="SPELL", cls="NEUTRAL",
     text="将一个随从移回其拥有者的手牌。", rarity="COMMON", targeting="any",
     effect=lambda c: bounce(c, c.target))
_tok("TOKEN_NIGHTMARE", name="梦魇", cost=0, type="SPELL", cls="NEUTRAL",
     text="使一个随从获得+5/+5，下个回合开始时摧毁它。", rarity="COMMON", targeting="any",
     effect=lambda c: nightmare(c, c.target))
_tok("TOKEN_AWAKEN", name="伊瑟拉的苏醒", cost=2, type="SPELL", cls="NEUTRAL",
     text="对所有角色造成5点伤害，除了伊瑟拉。", rarity="COMMON",
     effect=ysera_awakens)
_tok("TOKEN_DRAKE", name="翡翠幼龙", cost=4, type="MINION", cls="NEUTRAL", text="",
     rarity="COMMON", atk=7, hp=6, races=["DRAGON"])
_tok("TOKEN_SISTER", name="欢笑姐妹", cost=3, type="MINION", cls="NEUTRAL",
     text="无法被法术或英雄技能指定。", rarity="COMMON", atk=3, hp=5, elusive=True)
_tok("TOKEN_MURLOC", name="我是鱼人", cost=4, type="SPELL", cls="NEUTRAL",
     text="随机召唤3至5个1/1的鱼人。", rarity="COMMON",
     effect=lambda c: summon_token(c, 1, 1, c.g.rng.randint(3, 5), "鱼人"))
_tok("TOKEN_HORDE", name="部落的力量", cost=4, type="SPELL", cls="NEUTRAL",
     text="随机召唤一名部落勇士。", rarity="COMMON", effect=summon_horde)
_tok("TOKEN_ROGUE", name="潜行者最行", cost=4, type="SPELL", cls="NEUTRAL",
     text="造成4点伤害并抽一张牌。", rarity="COMMON", targeting="any",
     effect=lambda c: (damage(c, c.target, 4), draw(c, 1)))


# ============ 卡牌实例化 ============
def make_minion(cid: str, d: dict, pid: int) -> Minion:
    m = Minion(d.get("name", cid), d.get("atk", 0), d.get("hp", 0),
               d.get("hp", 0), pid, cid=cid, text=d.get("text", ""))
    m.base_atk = d.get("atk", 0)
    m.base_hp = d.get("hp", 0)
    m.rarity = d.get("rarity", "COMMON")
    m.cant_attack = bool(d.get("cant_attack"))
    m.races = list(d.get("races") or [])
    m.freeze_on_damage = bool(d.get("freeze_on_damage"))
    for k in ("taunt", "charge", "rush", "shield", "stealth", "windfury",
              "lifesteal", "poisonous", "reborn", "elusive"):
        if d.get(k):
            setattr(m, k, True)
    m.spell_power = d.get("spell_power", 0)
    for k in ("spell_discount", "minion_discount", "first_minion_discount",
              "all_minion_more", "minion_cost_more", "spell_mult", "heal_as_damage"):
        if d.get(k):
            setattr(m, k, d[k])
    if d.get("deathrattle"):
        m.deathrattle = d["deathrattle"]
    if d.get("trigger"):
        m.triggers = list(d["trigger"])
    return m


# ============ 奥秘 ============
# key = cards.py 里 secret= 的值；kind = 触发时机；fn(g, owner, foe, **kw) -> bool(是否消耗)
def _s_counterspell(g, owner, foe, **kw):
    g.say("  奥秘触发：法术反制！")
    return True


def _s_mirror_entity(g, owner, foe, **kw):
    m = kw.get("minion")
    if not m:
        return False
    g.say("  奥秘触发：镜像实体！")
    if len(owner.board) < MAX_BOARD:
        c = Ctx(g, owner, foe, src=m)
        summon(c, m.name, m.atk, m.hp)
        if owner.board:
            owner.board[-1].taunt = m.taunt
            owner.board[-1].shield = m.shield
            owner.board[-1].races = list(m.races)
    return True


def _s_ice_barrier(g, owner, foe, **kw):
    g.say("  奥秘触发：寒冰护体！获得 8 点护甲")
    owner.armor += 8
    return True


def _s_ice_block(g, owner, foe, **kw):
    g.say("  奥秘触发：寒冰屏障！致命伤害被防止")
    owner.immune_turn = True
    return True


def _s_explosive_trap(g, owner, foe, **kw):
    g.say("  奥秘触发：爆炸陷阱！")
    c = Ctx(g, owner, foe)
    aoe(c, lambda x: damage(c, x, 2), side="foe")
    damage(c, foe, 2)
    return True


def _s_noble_sacrifice(g, owner, foe, **kw):
    g.say("  奥秘触发：崇高牺牲！")
    c = Ctx(g, owner, foe)
    m = summon(c, "保卫者", 2, 1)
    if m is not None:
        m.taunt = True
        attacker = kw.get("attacker") or kw.get("hero")
        if attacker is not None:
            damage(c, m, getattr(attacker, "attack", 0) or getattr(attacker, "atk", 0))
    return True


def _s_snipe(g, owner, foe, **kw):
    m = kw.get("minion")
    if not m:
        return False
    g.say("  奥秘触发：狙击！")
    c = Ctx(g, owner, foe)
    damage(c, m, 4)
    return True


def _s_snake_trap(g, owner, foe, **kw):
    g.say("  奥秘触发：毒蛇陷阱！")
    c = Ctx(g, owner, foe)
    summon_token(c, 1, 1, 3, "蛇")
    return True


def _s_vaporize(g, owner, foe, **kw):
    m = kw.get("attacker")
    if not m:
        return False
    g.say("  奥秘触发：蒸发！")
    c = Ctx(g, owner, foe)
    destroy(c, m)
    return True


def _s_misdirection(g, owner, foe, **kw):
    m = kw.get("attacker")
    if not m:
        return False
    g.say("  奥秘触发：误导！")
    pool = [x for x in foe.board if x is not m and x.alive]
    if foe.hp > 0:
        pool.append(foe)
    if pool:
        c = Ctx(g, foe, owner, src=m)
        damage(c, g.rng.choice(pool), m.atk)
    return True


def _s_freezing_trap(g, owner, foe, **kw):
    m = kw.get("attacker")
    if not m or m not in foe.board:
        return False
    g.say("  奥秘触发：冰冻陷阱！")
    foe.board.remove(m)
    if len(foe.hand) < HAND_CAP and m.cid:
        foe.hand.append(m.cid)
    g.recalc()
    return True


def _s_eye_for_an_eye(g, owner, foe, **kw):
    g.say("  奥秘触发：以眼还眼！")
    c = Ctx(g, owner, foe)
    damage(c, foe, kw.get("amount", 0))
    return True


def _s_redemption(g, owner, foe, **kw):
    m = kw.get("minion")
    if not m:
        return False
    g.say("  奥秘触发：救赎！")
    if len(owner.board) < MAX_BOARD:
        m.buffs = []
        m.max_hp = max(1, m.base_hp)
        m.hp = 1
        m.silenced = False
        m.deathrattle = None
        m.triggers = []
        owner.board.append(m)
        g.recalc()
    return True


def _s_repentance(g, owner, foe, **kw):
    m = kw.get("minion")
    if not m:
        return False
    g.say("  奥秘触发：忏悔！")
    m.hp = 1
    return True


SECRETS = {
    "counterspell":    ("foe_spell",         _s_counterspell),
    "mirror_entity":   ("foe_minion_played", _s_mirror_entity),
    "ice_block":       ("lethal",            _s_ice_block),
    "ice_barrier":     ("hero_attacked",     _s_ice_barrier),
    "explosive_trap":  ("hero_attacked",     _s_explosive_trap),
    "noble_sacrifice": ("minion_attacked",   _s_noble_sacrifice),
    "snake_trap":      ("minion_attacked",   _s_snake_trap),
    "vaporize":        ("hero_attacked",     _s_vaporize),
    "misdirection":    ("hero_attacked",     _s_misdirection),
    "freezing_trap":   ("minion_attacked",   _s_freezing_trap),
    "eye_for_an_eye":  ("hero_damaged",      _s_eye_for_an_eye),
    "redemption":      ("friendly_died",     _s_redemption),
    "repentance":      ("foe_minion_played", _s_repentance),
    "snipe":           ("foe_minion_played", _s_snipe),
}


# ============ 引擎 ============
class Game:
    def __init__(self, names=("你", "AI"), decks=(None, None), seed=None):
        self.rng = random.Random(seed)
        self.players = [Player(names[i], i) for i in range(2)]
        for i, p in enumerate(self.players):
            p.deck = list(decks[i] or [])
            self.rng.shuffle(p.deck)
        self.players[0].hand = [self.players[0].deck.pop() for _ in range(3)]
        self.players[1].hand = [self.players[1].deck.pop() for _ in range(4)]
        self.turn = 0
        self.log: list[str] = []
        self.over = False
        self.winner = None

    # -- 基础查询 --
    @property
    def cur(self) -> Player:
        return self.players[self.turn % 2]

    @property
    def opp(self) -> Player:
        return self.players[(self.turn + 1) % 2]

    def foe_of(self, p: Player) -> Player:
        return self.players[1 - p.pid]

    def owner_of(self, m):
        """随从的归属玩家（被偷过来的随从看 owner_id，场上位置以实际所在方为准）"""
        for p in self.players:
            if m in p.board:
                return p
        return None

    def ctx(self, target=None, src=None, amount=0, event="") -> Ctx:
        return Ctx(self, self.cur, self.opp, target, src, amount, event)

    def say(self, s: str):
        self.log.append(s)
        if len(self.log) > 400:
            self.log.pop(0)

    # -- 事件 --
    def emit(self, event: str, **kw):
        for p in list(self.players):
            for m in list(p.board):
                if not m.alive or m.silenced:
                    continue
                for (e, fn) in list(m.triggers):
                    if e != event:
                        continue
                    c = Ctx(self, p, self.foe_of(p), src=m, event=event)
                    c.target = kw.get("target")
                    c.amount = kw.get("amount", 0)
                    c.event_src = kw.get("src")
                    c.card = kw.get("card")
                    try:
                        fn(c)
                    except Exception as ex:  # 单卡出错不能拖垮整局
                        self.say(f"[trigger-error] {m.name}: {ex}")
            # 武器上的触发（真银圣剑 / 鹰角弓 …）
            w = p.weapon
            if w and w.get("triggers"):
                for (e, fn) in list(w["triggers"]):
                    if e != event:
                        continue
                    c = Ctx(self, p, self.foe_of(p), src=p, event=event)
                    c.target = kw.get("target")
                    c.amount = kw.get("amount", 0)
                    c.event_src = kw.get("src")
                    try:
                        fn(c)
                    except Exception as ex:
                        self.say(f"[weapon-trigger-error] {w.get('name')}: {ex}")

    # -- 奥秘 --
    def check_secrets(self, owner: Player, kind: str, **kw) -> bool:
        """owner 的奥秘是否有能对 kind 事件响应的；有则消耗并执行，返回 True。
        handler 返回 False 表示「当前不适用」，奥秘原样放回。"""
        for i, sid in enumerate(list(owner.secrets)):
            item = SECRETS.get(sid)
            if not item or item[0] != kind:
                continue
            owner.secrets.remove(sid)
            try:
                ok = item[1](self, owner, self.foe_of(owner), **kw)
            except Exception as ex:
                self.say(f"[secret-error] {sid}: {ex}")
                return False
            if ok:
                return True
            owner.secrets.insert(min(i, len(owner.secrets)), sid)
        return False

    # -- 回合 --
    def start_turn(self):
        p = self.cur
        p.max_mana = min(MAX_MANA, p.max_mana + 1)
        p.locked_mana = min(p.overload, p.max_mana)   # 上回合的过载在本回合生效
        p.overload = 0
        p.mana = max(0, p.max_mana - p.locked_mana)
        p.hero_power_used = False
        p.hero_attack_used = False
        p.hero_attacks = 0
        p.hero_atk = 0                  # 临时英雄攻击力只在当回合有效
        p.cards_played = 0
        p.minions_played = 0
        p.next_spell_discount = 0       # 伺机待发：只在本回合内有效
        p.next_secret_free = 0          # 肯瑞托法师：只在本回合内有效
        p.immune_turn = False           # 寒冰屏障的免疫只覆盖被触发的那一回合
        for m in p.board:
            m.attacks_left = 0 if m.cant_attack else (2 if m.windfury else 1)
            m.frozen = False
            m.summoned_this_turn = False
            if m.stealth_temp:              # 隐藏：潜行只维持到自己的这个回合开始
                m.stealth = False
                m.stealth_temp = False
        while p.pending_hand:               # 裂颅之击这类「下回合回手」的牌
            cid = p.pending_hand.pop(0)
            if len(p.hand) < HAND_CAP:
                p.hand.append(cid)
                self.say(f"  {CARDS.get(cid, {}).get('name', cid)} 回到了手中")
        draw(self.ctx())
        self.emit("turn_start")
        self.recalc()

    def end_turn(self):
        self.emit("turn_end")
        self.check_deaths()
        # 力量的代价 / 自然之力的树人：回合结束就地死亡
        doomed = [m for m in self.cur.board if m.die_at_end]
        for m in doomed:
            self.say(f"  {m.name} 因效果在本回合结束时死亡")
            m.hp = 0
        if doomed:
            self.check_deaths()
        # 暗影狂乱借来的随从：回合结束还给对面（对面满场就挤死）
        if self.cur.borrowed:
            owner = self.foe_of(self.cur)
            for m in list(self.cur.borrowed):
                if m not in self.cur.board:
                    continue
                self.cur.board.remove(m)
                if len(owner.board) >= MAX_BOARD:
                    self.say(f"  {m.name} 因对面满场被挤死")
                    continue
                m.owner_id = owner.pid
                m.attacks_left = 0
                m.summoned_this_turn = True
                owner.board.append(m)
            self.cur.borrowed.clear()
        for pl in self.players:         # 「本回合」临时增益到期
            for m in pl.board:
                if m.temp_buffs:
                    m.temp_buffs.clear()
        self.cur.hero_atk = 0          # 变脸等临时攻击力：自己回合结束即失效
        self.cur.frozen = False        # 英雄被冻结只影响这一个回合
        self.cur.minions_survive = False   # 命令怒吼：只在自己这一个回合生效
        self.cur.spells_free = False   # 米尔豪斯：只覆盖对手的一个回合
        self.recalc()
        for p in self.players:
            if p.hp <= 0:
                self.over = True
                self.winner = self.foe_of(p).name
                return
        self.turn += 1
        self.start_turn()

    # -- 出牌 --
    def cost(self, p: Player, cid: str) -> int:
        """实时费用 = 基础费 + 自身条件减费 + 场面光环 + 本回合临时效果

        动态费用全靠这里算，出牌/界面/AI 都走它，避免三处各算一套。
        """
        d = CARDS.get(cid) or {}
        base = d.get("cost", 0)
        if not base:
            return 0
        c, t = base, d.get("type")

        per = d.get("cost_less_per")            # 巨人 / 恐怖海盗：按条件逐点减
        if per:
            kind, n = per
            if kind == "hand_other":            # 山岭巨人：手牌里其他牌数
                k = max(0, len(p.hand) - 1)
            elif kind == "hero_damage":         # 熔核巨人：英雄已受的伤害
                k = max(0, MAX_HP - p.hp)
            elif kind == "board_minions":       # 海巨人：场上其他随从数
                k = sum(len(x.board) for x in self.players)
            elif kind == "weapon_atk":          # 恐怖海盗：武器攻击力
                k = p.weapon["atk"] if p.weapon else 0
            else:
                k = 0
            c -= k * n

        reg = p.cheap.get(cid)                  # 视界术 / 暗影步：抽到或回手的牌降价
        if reg and reg[1] > 0:
            c -= reg[0]

        if t == "SPELL":
            if p.spells_free:                        # 米尔豪斯：本回合法术全 0 费
                c = 0
            elif d.get("secret") and p.next_secret_free:   # 肯瑞托法师：下个奥秘 0 费
                c = 0
            for m in p.board:
                c -= m.spell_discount          # 巫师学徒
            c -= p.next_spell_discount         # 伺机待发
        elif t == "MINION":
            for m in p.board:
                if m.minion_discount:          # 召唤传送门：减费但不低于 1
                    c = max(1, c - m.minion_discount)
            if p.minions_played == 0:          # 小个子召唤师：本回合第一个随从
                for m in p.board:
                    c -= m.first_minion_discount
            for m in p.board:                  # 风险投资公司雇佣兵
                c += m.minion_cost_more
            for q in self.players:             # 法力怨魂：双方随从都涨价
                for m in q.board:
                    c += m.all_minion_more
        return max(0, c)

    def can_play(self, p: Player, cid: str) -> bool:
        d = CARDS.get(cid)
        return bool(d) and p.mana >= self.cost(p, cid)

    def play_card(self, p: Player, idx: int, target=None, choice=None) -> bool:
        if idx < 0 or idx >= len(p.hand):
            return False
        cid = p.hand[idx]
        d = CARDS.get(cid)
        cost = self.cost(p, cid)
        if not d or p.mana < cost:
            return False
        if d.get("choose") and not (choice is not None and 0 <= choice < len(d["choose"])):
            choice = 0                 # 没选就默认第一个选项（AI / 误点兜底）
        # 精灵龙这类「无法被法术指定」：目标不对就直接打不出（不扣费）
        if (d.get("type") == "SPELL" and is_minion(target)
                and getattr(target, "elusive", False)):
            self.say(f"  {target.name} 无法被法术指定")
            return False
        p.mana -= cost
        if d.get("type") == "SPELL":
            p.next_spell_discount = 0          # 消耗掉减费（伺机待发自己会再设上）
        elif d.get("type") == "MINION":
            p.minions_played += 1
        p.hand.pop(idx)
        reg = p.cheap.get(cid)                 # 用掉了这张牌的降价额度
        if reg:
            reg[1] -= 1
            if reg[1] <= 0:
                p.cheap.pop(cid, None)
        combo = p.cards_played > 0
        c = Ctx(self, p, self.foe_of(p), target=target, combo=combo, card=d,
                spell=(d.get("type") == "SPELL"))
        foe = self.foe_of(p)
        self.say(f"{p.name} 打出 {d.get('name', cid)}")

        # 奥秘牌：挂上去等触发
        if d.get("secret"):
            p.secrets.append(d["secret"])
            p.next_secret_free = 0          # 肯瑞托法师的减免只顶一个奥秘
            self.say(f"  挂上奥秘「{d.get('name', cid)}」（场上共 {len(p.secrets)} 个）")
            self.emit("secret_played")
            self._maybe_cho(p, cid, d)
            p.cards_played += 1
            return True

        countered = False
        try:
            if d.get("type") == "SPELL":
                if self.check_secrets(foe, "foe_spell"):
                    countered = True
                else:
                    if c.target is None and d.get("targeting"):
                        c.target = self.auto_target(p, d)
                    if d.get("effect"):
                        d["effect"](c)
                    self._run_choose(c, p, d, choice)
            elif d.get("type") == "WEAPON":
                equip_weapon(c, d.get("atk", 0), d.get("durability", 1), d.get("name", ""))
                if p.weapon:
                    for k in ("triggers", "immune_attacking", "no_durability_on_minion",
                              "windfury"):
                        if d.get(k):
                            p.weapon[k] = d[k]
                if d.get("effect"):
                    d["effect"](c)
            else:
                if len(p.board) < MAX_BOARD:
                    m = make_minion(cid, d, p.pid)
                    m.attacks_left = 1 if (m.charge or m.rush) else 0
                    p.board.append(m)
                    c.src = m
                    self.emit("summon", src=m)
                if d.get("battlecry"):
                    if c.target is None and d.get("targeting"):
                        c.target = self.auto_target(p, d)
                    d["battlecry"](c)
                self._run_choose(c, p, d, choice)
                if is_minion(c.src):
                    self.check_secrets(foe, "foe_minion_played", minion=c.src)
        except Exception as ex:
            self.say(f"[card-error] {d.get('name', cid)}: {ex}")
        self.check_deaths()
        self.recalc()
        p.cards_played += 1
        if d.get("overload"):
            overload(c, d["overload"])
        self.emit("play_card", src=c.src, card=d)
        if d.get("type") == "SPELL" and not countered:
            self.emit("spell_cast", src=c.src, card=d)
            self._maybe_cho(p, cid, d)
        return True

    def _maybe_cho(self, caster: Player, cid: str, d: dict):
        """游学者周卓：任一方施法后，把这张牌的复制塞进对方手里"""
        if not cho_on_board(self):
            return
        other = self.foe_of(caster)
        if len(other.hand) >= HAND_CAP:
            return
        other.hand.append(cid)
        self.say(f"  游学者周卓：把「{d.get('name')}」的复制给对方一张")

    def _run_choose(self, c: Ctx, p: Player, d: dict, choice):
        """抉择牌：按玩家选的选项执行对应的那一段效果"""
        opts = d.get("choose") or []
        if not opts:
            return
        if choice is None or not (0 <= choice < len(opts)):
            choice = 0
        label, fn, tgt = opts[choice]
        self.say(f"  抉择：{label}")
        if tgt and c.target is None:
            c.target = self.auto_target(p, {"targeting": tgt})
        fn(c)

    def auto_target(self, p: Player, d: dict):
        """无指定目标时的默认选择：优先敌方随从，否则敌方英雄"""
        foe = self.foe_of(p)
        t = d.get("targeting")
        if t == "friendly":
            return self.rng.choice(p.board) if p.board else p
        if t == "friendly_minion":
            return self.rng.choice(p.board) if p.board else None
        if t == "friendly_any":            # 治疗/增益：挑「缺血最多」的那个（含自己英雄）
            cands = list(p.board) + [p]
            return max(cands, key=lambda x: getattr(x, "max_hp", MAX_HP) - x.hp)
        if t == "beast":
            pool = [m for m in p.board if "BEAST" in m.races]
            return self.rng.choice(pool) if pool else p
        if t == "damaged":
            pool = [m for m in foe.board if m.hp < m.max_hp]
            return self.rng.choice(pool) if pool else None
        pool = [m for m in foe.board if not getattr(m, "elusive", False)]
        if pool:
            return self.rng.choice(pool)
        return foe

    # -- 攻击 --
    def attack(self, attacker: Minion, tgt) -> bool:
        if attacker.attacks_left <= 0 or attacker.frozen or attacker.atk <= 0:
            return False
        if is_minion(tgt) and tgt not in self.foe_of(self.players[attacker.owner_id]).board:
            return False
        if not is_minion(tgt) and not attacker.can_attack_hero:
            return False
        taunts = [m for m in self.foe_of(self.players[attacker.owner_id]).board
                  if m.taunt and m.alive and m.attackable]
        if taunts and not (is_minion(tgt) and tgt.taunt):
            return False
        owner = self.players[attacker.owner_id]
        defender = self.foe_of(owner)
        # 奥秘：冰冻陷阱（任何攻击）/ 蒸发 / 误导（打英雄）
        if self.check_secrets(defender, "minion_attacked", attacker=attacker):
            attacker.attacks_left -= 1
            self.check_deaths()
            self.recalc()
            return True
        if not is_minion(tgt) and self.check_secrets(defender, "hero_attacked", attacker=attacker):
            attacker.attacks_left -= 1
            self.check_deaths()
            self.recalc()
            return True
        c = Ctx(self, owner, defender, src=attacker)
        attacker.attacks_left -= 1
        attacker.stealth = False
        self.say(f"{attacker.name} 攻击 {getattr(tgt, 'name', '英雄')}")
        # 交战伤害是同时结算的：反击伤害要取「打之前」的攻击力，
        # 目标就算这一下被打死，也得把伤害打回来（以前用打完后查 tgt.alive，导致白嫖）
        counter = tgt.atk if is_minion(tgt) else 0
        dmg_done = damage(c, tgt, attacker.atk)
        if counter > 0 and not attacker.immune:
            damage(c, attacker, counter)
            self.say(f"  ↳ {attacker.name} 受到 {counter} 点反击伤害")
        self.emit("attack", src=attacker, target=tgt, amount=dmg_done)
        self.check_deaths()
        self.recalc()
        return True

    # -- 英雄攻击（用脸/用武器）--
    def hero_attack(self, p: Player, tgt) -> bool:
        """英雄攻击：需要有攻击力（武器或临时增益），风怒武器每回合 2 次"""
        max_atk = 2 if (p.weapon and p.weapon.get("windfury")) else 1
        if self.over or p.hero_attacks >= max_atk or p.frozen:
            return False
        atk = p.attack
        if atk <= 0:
            return False
        foe = self.foe_of(p)
        taunts = [m for m in foe.board if m.taunt and m.alive]
        if is_minion(tgt):
            if tgt not in foe.board or not tgt.alive:
                return False
            if taunts and not tgt.taunt:            # 有嘲讽必须先打嘲讽
                return False
        elif tgt is not foe:
            return False
        elif taunts:                                # 打脸时 likewise 被嘲讽挡住
            return False

        p.hero_attack_used = True
        p.hero_attacks += 1
        c = Ctx(self, p, foe, src=p)
        wname = f"（{p.weapon['name']}）" if p.weapon else ""
        self.say(f"{p.name} 的英雄{wname} 攻击 {getattr(tgt, 'name', '敌方英雄')}")
        # 奥秘：误导（英雄/随从攻击我方英雄都能被误导）
        if self.check_secrets(foe, "hero_attacked", attacker=None, hero=p):
            self.check_deaths()
            self.recalc()
            return True
        counter = tgt.atk if is_minion(tgt) else 0      # 同上：反击按交手前的攻击力算
        damage(c, tgt, atk)
        w = p.weapon
        immune_atk = bool(w and w.get("immune_attacking"))   # 角斗士的长弓
        if counter > 0 and not immune_atk:                    # 随从反击
            damage(c, p, counter)
            self.say(f"  ↳ {p.name} 受到 {counter} 点反击伤害")
        if w:                                                 # 武器结算
            if is_minion(tgt) and w.get("no_durability_on_minion"):   # 血吼
                w["atk"] = max(0, w["atk"] - 1)
                if w["atk"] <= 0:
                    self.say(f"  {w['name']} 已损坏")
                    p.weapon = None
            else:
                w["durability"] -= 1
                if w["durability"] <= 0:
                    self.say(f"  {w['name']} 已损坏")
                    p.weapon = None
        self.emit("hero_attack", target=tgt, amount=atk)
        self.check_deaths()
        self.recalc()
        return True

    # -- 英雄技能（2 费，按职业简化）--
    def hero_power(self, p: Player, target=None) -> bool:
        if p.hero_power_used or p.mana < 2 or self.over:
            return False
        p.mana -= 2
        p.hero_power_used = True
        c = Ctx(self, p, self.foe_of(p), target=target, spell=True)   # 技能也吃法强/维伦
        if p.hero_power_key == "JARAXXUS":          # 加拉克苏斯大王：召唤 6/6 地狱火
            summon_token(c, 6, 6, 1, "地狱火")
            self.say("  加拉克苏斯召唤了一个 6/6 地狱火")
        elif p.hero_power_key in ("SHADOW", "SHADOW2"):   # 暗影形态：2/3 点伤害
            n = 3 if p.hero_power_key == "SHADOW2" else 2
            c.target = target if target is not None else self.foe_of(p)
            damage(c, c.target, n)
        elif p.cls == "WARRIOR":
            gain_armor(c, 2)                       # 护甲值：+2 护甲
        elif p.cls == "DRUID":
            p.hero_atk += 1                        # 变形：本回合 +1 攻击力
            gain_armor(c, 1)                       #       并 +1 护甲
        elif p.cls == "PRIEST":
            heal(c, target if is_minion(target) else p, 2)
        else:
            damage(c, target if target is not None else self.foe_of(p), 1)
        self.say(f"{p.name} 使用英雄技能")
        self.check_deaths()
        self.recalc()
        return True

    # -- 死亡与光环 --
    def check_deaths(self):
        for _ in range(6):  # 亡语可能连锁召唤，最多递归 6 层
            died = False
            for p in self.players:
                for m in [x for x in p.board if not x.alive]:
                    p.board.remove(m)
                    self.say(f"  {m.name} 死亡")
                    self.emit("death", src=m)
                    if m.deathrattle and not m.silenced:
                        try:
                            m.deathrattle(Ctx(self, p, self.foe_of(p), src=m))
                        except Exception as ex:
                            self.say(f"[dr-error] {m.name}: {ex}")
                    if m.reborn and not m.silenced:
                        m.reborn = False
                        m.hp = 1
                        p.board.append(m)
                    else:
                        self.check_secrets(p, "friendly_died", minion=m)   # 救赎
                    died = True
            if not died:
                break
        for p in self.players:
            if p.hp <= 0:
                self.over = True
                self.winner = self.foe_of(p).name

    def recalc(self):
        """重算属性 —— base + 永久buff + 临时buff + 光环 + 激怒"""
        for p in self.players:
            for i, m in enumerate(p.board):
                d = CARDS.get(m.cid, {})
                base_atk = d.get("atk", m.base_atk)
                base_hp = d.get("hp", m.base_hp or m.max_hp)
                buff_atk = sum(b[0] for b in m.buffs) + sum(b[0] for b in m.temp_buffs)
                buff_hp = sum(b[1] for b in m.buffs) + sum(b[1] for b in m.temp_buffs)
                # 光环：aura_atk / aura_hp + aura_scope('other'|'adjacent'|'all')
                #       + aura_race（只影响指定种族，如「其他鱼人」）
                aura_atk = aura_hp = 0
                for j, s in enumerate(p.board):
                    ad = CARDS.get(s.cid, {})
                    a, h = ad.get("aura_atk", 0), ad.get("aura_hp", 0)
                    race = ad.get("aura_race")
                    if race and race not in m.races:
                        continue
                    if ad.get("aura_charge") and (not race or race in m.races):
                        m.charge = True
                    if not a and not h:
                        continue
                    scope = ad.get("aura_scope", "other")
                    if scope == "other" and s is m:
                        continue
                    if scope == "adjacent" and abs(j - i) != 1:
                        continue
                    aura_atk += a
                    aura_hp += h
                # 南海船工：有武器时才有冲锋
                if d.get("charge_if_weapon") and p.weapon:
                    m.charge = True
                # 激怒：受伤时加攻击力（暴怒的狼人还带风怒）
                enraged = m.hp < m.max_hp and not m.silenced
                enrage = d.get("enrage_atk", 0) if enraged else 0
                if enraged and d.get("enrage_windfury"):
                    m.windfury = True
                # 老瞎眼：战场上每有一个其他鱼人 +1 攻击
                per_race = d.get("aura_per_race")
                if per_race:
                    cnt = sum(1 for pl in self.players for x in pl.board
                              if x is not m and per_race in x.races)
                    enrage += cnt * d.get("aura_per", 1)
                m.atk = max(0, base_atk + buff_atk + aura_atk + enrage)
                new_max = base_hp + buff_hp + aura_hp
                delta = new_max - m.max_hp
                m.max_hp = new_max
                if delta:
                    m.hp = min(m.max_hp, max(0, m.hp + delta))
                if d.get("atk_eq_hp"):          # 光耀之子：攻击力始终等于生命值
                    m.atk = max(0, m.hp)
            p.spell_power = sum(m.spell_power for m in p.board)
            mults = [m.spell_mult for m in p.board if m.spell_mult]
            p.spell_mult = max(mults) if mults else 1
            p.heal_as_damage = any(m.heal_as_damage for m in p.board)
            p.enrage_weapon = 0                     # 恶毒铁匠：激怒时武器 +N 攻
            for m in p.board:
                if not m.silenced and m.hp < m.max_hp:
                    p.enrage_weapon += CARDS.get(m.cid, {}).get("enrage_weapon", 0)

    # -- 序列化给前端 --
    def state(self, viewer: int = 0) -> dict:
        def pm(m: Minion, hide=False):
            return dict(name=m.name, atk=m.atk, hp=m.hp, max_hp=m.max_hp,
                        taunt=m.taunt, shield=m.shield, frozen=m.frozen,
                        stealth=m.stealth, attackable=m.attacks_left > 0 and not m.frozen,
                        text=m.text, cid=m.cid, rarity=m.rarity,
                        elusive=m.elusive, spell_power=m.spell_power)
        def pp(p: Player, hide_hand: bool):
            return dict(name=p.name, cls=getattr(p, "cls", None),
                        hp=p.hp, armor=p.armor, mana=p.mana,
                        max_mana=p.max_mana, deck=len(p.deck),
                        hero_name=p.hero_name or p.name,
                        hero_max_hp=p.hero_max_hp,
                        locked_mana=p.locked_mana, overload=p.overload,
                        secrets=len(p.secrets),
                        hero_atk=p.attack,
                        frozen=p.frozen,
                        hero_can_attack=(p.attack > 0 and not p.frozen and p.hero_attacks <
                                         (2 if (p.weapon and p.weapon.get("windfury")) else 1)),
                        weapon=dict(p.weapon) if p.weapon else None,
                        hand=(["?"] * len(p.hand)) if hide_hand else
                             [dict(cid=c, cost=self.cost(p, c),
                                   playable=(self.cost(p, c) <= p.mana),
                                   **{k: CARDS.get(c, {}).get(k)
                                      for k in ("name", "text", "type",
                                                "atk", "hp", "rarity")},
                                   choose=[dict(label=l, tgt=t) for l, _f, t in
                                           (CARDS.get(c, {}).get("choose") or [])])
                              for c in p.hand],
                        board=[pm(m) for m in p.board])
        return dict(
            turn=self.turn, over=self.over, winner=self.winner,
            cur=self.cur.pid,
            timer=(15 if any(CARDS.get(m.cid, {}).get("nozdormu")
                             for pl in self.players for m in pl.board) else 0),
            me=pp(self.players[viewer], False),
            foe=pp(self.players[1 - viewer], True),
            log=self.log[-30:],
        )
