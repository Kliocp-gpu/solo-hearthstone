"""
从 HearthstoneJSON 自动生成卡池 cards.py

策略（安全第一）：
  能高置信度解析的效果 -> 生成 lambda 调用原语
  解析不了的          -> 降级为「白板」（保留 费/攻/血，效果为空）
这样保证卡池全在，且任何一张卡都不会让游戏崩溃。

三态：
  完整效果 = 全部文本都被实现
  partial  = 挂上了效果，但有部分句子没解析（界面标「部分」）
  白板     = 一句都没解析出来

用法：python3 gen_cards.py   （需联网，会缓存到 .cache/）
"""

import json, os, re, time, urllib.request

CACHE = os.path.join(os.path.dirname(__file__), ".cache")

# ============ 卡池版本演进 ============
# 按真实发布顺序追加；ENABLED 决定当前做到第几个版本。
# 加新版本：往列表末尾加一行，把 ENABLED 加 1，重跑本脚本即可（引擎不用动）。
RELEASES = [
    ("VANILLA", "2014 原版（基础 + 经典）"),      # 炉石上线时的全部卡
    # ("NAXX",  "纳克萨玛斯的诅咒"),              # 2014-07
    # ("GVG",   "地精大战侏儒"),                  # 2014-12
]
ENABLED = 1

SETS = {s for s, _ in RELEASES[:ENABLED]}
OUT = os.path.join(os.path.dirname(__file__), "cards.py")


UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                     "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"}


def _head_size(url):
    req = urllib.request.Request(url, headers=UA, method="HEAD")
    with urllib.request.urlopen(req, timeout=30) as r:
        return int(r.headers.get("Content-Length", 0))


def ranged_download(url, path, chunk=150_000):
    """分段 Range 下载：网络不稳时逐块重试，避免整体失败"""
    total = _head_size(url)
    if not total:
        return False
    buf = bytearray()
    start = 0
    while start < total:
        end = min(start + chunk - 1, total - 1)
        for attempt in range(8):
            try:
                req = urllib.request.Request(url, headers={**UA, "Range": f"bytes={start}-{end}"})
                with urllib.request.urlopen(req, timeout=30) as r:
                    data = r.read()
                if len(data) == end - start + 1:
                    buf += data
                    print(f"    {len(buf)}/{total}", flush=True)
                    break
            except Exception:
                time.sleep(1.5 + attempt)
        else:
            print(f"  [warn] 分段 {start}-{end} 反复失败")
            return False
        start = end + 1
    if len(buf) != total:
        return False
    try:
        json.loads(buf.decode("utf-8"))
    except Exception:
        return False
    tmp = path + ".tmp"
    with open(tmp, "wb") as f:
        f.write(bytes(buf))
    os.replace(tmp, path)
    return True


def fetch(locale):
    os.makedirs(CACHE, exist_ok=True)
    path = os.path.join(CACHE, f"cards.{locale}.json")
    if not os.path.exists(path):
        url = f"https://api.hearthstonejson.com/v1/latest/{locale}/cards.collectible.json"
        print(f"  下载 {locale} ...")
        if not ranged_download(url, path):
            print(f"  [warn] {locale} 下载失败" + ("（卡名将回退为英文）" if locale == "zhCN" else ""))
            return []
    try:
        return json.load(open(path, encoding="utf-8"))
    except Exception:
        print(f"  [warn] {locale} 缓存损坏，删除 .cache/cards.{locale}.json 后重跑可重试")
        return []


def clean(t: str) -> str:
    """清理卡面文本：<b> 标签、[x] 标记、法强符号、不换行空格"""
    t = re.sub(r"</?[bi]>", "", t or "")
    t = t.replace("\xa0", " ").replace("\u2019", "'")   # NBSP 会让正则匹配失败，必须归一
    t = t.replace("[x]", "").replace("[$]", "")
    t = re.sub(r"[$#](\d+)", r"\1", t)          # $3 / #3 -> 3
    t = re.sub(r"\s+", " ", t).strip()
    return t


# 「随机将一张X置入手牌」的词汇表
RARITY_WORD = {"legendary": "LEGENDARY", "epic": "EPIC", "rare": "RARE", "common": "COMMON"}
RACE_WORD = {"pirate": "PIRATE", "beast": "BEAST", "dragon": "DRAGON", "murloc": "MURLOC",
             "mech": "MECHANICAL", "demon": "DEMON", "elemental": "ELEMENTAL", "totem": "TOTEM",
             "undead": "UNDEAD", "naga": "NAGA", "quilboar": "QUILBOAR", "draenei": "DRAENEI"}
CLASS_WORD = {"mage", "priest", "warlock", "paladin", "warrior", "druid", "rogue",
              "hunter", "shaman", "demonhunter", "deathknight"}
TYPE_WORD = {"minion": "MINION", "spell": "SPELL", "weapon": "WEAPON"}


def rw(w: str):
    """种族词 → 代码，容忍复数（beasts / totems / murlocs）"""
    w = (w or "").lower().strip()
    return RACE_WORD.get(w) or RACE_WORD.get(w.rstrip("s"))


# 只有过载、没有其他效果的牌（雷铸战斧 / 尘魔）
# 奥秘：触发点必须由引擎钩子驱动，正则无法表达 → 按卡 id 显式登记（数量有限、可控）
SECRET_IDS = {
    "VAN_EX1_287": "counterspell",     # 法术反制
    "VAN_EX1_294": "mirror_entity",    # 镜像实体
    "VAN_EX1_295": "ice_block",        # 寒冰屏障
    "VAN_EX1_289": "ice_barrier",      # 寒冰护体
    "VAN_EX1_610": "explosive_trap",   # 爆炸陷阱
    "VAN_EX1_132": "eye_for_an_eye",   # 以眼还眼
    "VAN_EX1_130": "noble_sacrifice",  # 崇高牺牲
    "VAN_EX1_379": "repentance",       # 忏悔
    "VAN_EX1_611": "freezing_trap",    # 冰冻陷阱
    "VAN_EX1_609": "snipe",            # 狙击
    "VAN_EX1_554": "snake_trap",       # 毒蛇陷阱
    "VAN_EX1_533": "misdirection",     # 误导
    "VAN_EX1_594": "vaporize",         # 蒸发
    "VAN_EX1_136": "redemption",       # 救赎
}

# 引擎真正支持的关键词/机制（用于判断"纯关键词卡"）
SUPPORTED_KW = re.compile(
    r"\b(taunt|charge|rush|divine shield|stealth|windfury|lifesteal|poisonous|reborn|elusive)\b"
    r"|spell damage \+\d+", re.I)


def substance(t: str) -> str:
    """去掉 battlecry/deathrattle 前缀 + 已支持关键词 + 标点数字后，是否还剩实质描述"""
    t = re.sub(r"^(battlecry|deathrattle)\s*[::]\s*", "", t, flags=re.I)
    t = SUPPORTED_KW.sub("", t)
    t = re.sub(r"[。．.，,、:：！!？?（）()\s\d+/+\-]", "", t)
    return t.strip()


# ============ 光环 / 被动 ============
def _race(w: str):
    """'beast' -> 'BEAST'；'minion'/'minions' -> None（不限种族）；未知种族 -> False"""
    w = w.lower().strip()
    if w in ("minion", "minions"):
        return None
    return rw(w) or False


AURA_RULES = [
    # 「你的其他 X 拥有 +N/+N」/「所有其他 X 拥有 +N/+N」
    (r"your other (\w+) have \+(\d+)/\+(\d+)",
     lambda m: dict(aura_atk=int(m.group(2)), aura_hp=int(m.group(3)),
                    aura_scope="other", aura_race=_race(m.group(1)))),
    (r"all other (\w+) have \+(\d+)/\+(\d+)",
     lambda m: dict(aura_atk=int(m.group(2)), aura_hp=int(m.group(3)),
                    aura_scope="other", aura_race=_race(m.group(1)))),
    (r"your (\w+) have \+(\d+)/\+(\d+)",
     lambda m: dict(aura_atk=int(m.group(2)), aura_hp=int(m.group(3)),
                    aura_scope="all", aura_race=_race(m.group(1)))),
    # 只加攻击力
    (r"your other (\w+) have \+(\d+) attack",
     lambda m: dict(aura_atk=int(m.group(2)), aura_scope="other",
                    aura_race=_race(m.group(1)))),
    (r"all other (\w+) have \+(\d+) attack",
     lambda m: dict(aura_atk=int(m.group(2)), aura_scope="other",
                    aura_race=_race(m.group(1)))),
    (r"your (\w+) have \+(\d+) attack",
     lambda m: dict(aura_atk=int(m.group(2)), aura_scope="all",
                    aura_race=_race(m.group(1)))),
    (r"adjacent minions have \+(\d+) attack",
     lambda m: dict(aura_atk=int(m.group(1)), aura_scope="adjacent")),
    # 冲锋光环（苔原犀牛）
    (r"your (\w+) have charge",
     lambda m: dict(aura_charge=True, aura_race=_race(m.group(1)))),
    # 老瞎眼：战场上每有一个其他鱼人 +1 攻击
    (r"has \+(\d+) attack for each other (\w+) on the battlefield",
     lambda m: dict(aura_per_race=_race(m.group(2)), aura_per=int(m.group(1)))),
    # 激怒
    (r"enrage: windfury and \+(\d+) attack",
     lambda m: dict(enrage_atk=int(m.group(1)), enrage_windfury=True)),
    (r"enrage: \+(\d+) attack",
     lambda m: dict(enrage_atk=int(m.group(1)))),
    # 光耀之子
    (r"this minion's attack is always equal to its health",
     lambda m: dict(atk_eq_hp=True)),
    # 先知维伦：法术/技能伤害与治疗翻倍
    (r"double the damage and healing of your spells and hero power",
     lambda m: dict(spell_mult=2)),
    # 奥金尼灵魂祭司：治疗改为造成伤害
    (r"your cards and powers that restore health now deal damage instead",
     lambda m: dict(heal_as_damage=True)),
    # 恶毒铁匠：激怒时武器 +N 攻击
    (r"enrage: your weapon has \+(\d+) attack",
     lambda m: dict(enrage_weapon=int(m.group(1)))),
]

# 纯标记型文本：挂个属性就行，不需要效果代码
FLAG_RULES = [
    (r"overload:?\s*\((\d+)\)", lambda m: dict(overload=int(m.group(1)))),
    (r"can'?t attack", lambda m: dict(cant_attack=True)),
    (r"destroy any minion damaged by this minion", lambda m: dict(poisonous=True)),
    (r"freeze any character damaged by this minion", lambda m: dict(freeze_on_damage=True)),
    (r"this minion's attack is always equal to its health", lambda m: dict(atk_eq_hp=True)),
    (r"can'?t be targeted by spells or hero powers", lambda m: dict(elusive=True)),
    (r"\belusive\b", lambda m: dict(elusive=True)),
    (r"attacking a minion costs 1 attack instead of 1 durability",
     lambda m: dict(no_durability_on_minion=True)),
    (r"your hero is immune while attacking", lambda m: dict(immune_attacking=True)),
    (r"has charge while you have a weapon equipped", lambda m: dict(charge_if_weapon=True)),
    # 游学者周卓：施法时给对方一张复制（钩子在引擎里）
    (r"whenever a player casts a spell, put a copy into the other player's hand",
     lambda m: dict(cho_copy=True)),
    # 诺兹多姆：双方回合限时 15 秒（倒计时在前端，引擎只提供标记）
    (r"players only have (\d+) seconds to take their turns",
     lambda m: dict(nozdormu=int(m.group(1)))),
]

# 这些句式本身带触发/时限味儿，但语义明确，放在 DANGER 判断之前先试
SAFE_RULES = [
    (r"summon three (\d+)/(\d+) treants with charge",
     lambda m: (f"summon_chargers(c, {m.group(1)}, {m.group(2)}, 3)", False)),
]

# 跨句、必须整张牌一起看的句式（「选择随从。当它…」这种），拆句会丢掉后半段
SPECIAL_RULES = [
    (r"choose a minion\. whenever it attacks, draw a card",
     lambda m: ("blessing_of_wisdom(c, c.target)", "any")),                       # 智慧祝福
    (r"choose a minion\. when that minion is destroyed, return it to the battlefield",
     lambda m: ("ancestral_spirit(c, c.target)", "any")),                         # 先祖之魂
    (r"choose an enemy minion\. at the start of your turn, destroy it",
     lambda m: ("corruption(c, c.target)", "enemy_minion")),                      # 腐蚀术

    # ---- 带条件的单张效果（「A；如果…则改为 B」这类，拆句会丢掉条件）----
    (r"freeze a character\. if it was already frozen, deal (\d+) damage instead",
     lambda m: ("ice_lance(c, c.target)", "any")),                                # 冰枪术
    (r"draw a card\. that card costs \((\d+)\) less",
     lambda m: (f"draw_cheap(c, 1, {m.group(1)})", False)),                       # 视界术
    (r"give a minion \+(\d+) attack\. combo: \+(\d+) attack instead",
     lambda m: ("cold_blood(c, c.target)", "any")),                               # 冷血
    (r"deal (\d+) damage\. combo: deal (\d+) damage instead",
     lambda m: ("eviscerate(c, c.target)", "any")),                               # 刺骨
    (r"deal (\d+) damage\. combo: deal (\d+) instead",
     lambda m: ("perdition_blade(c, c.target)", "any")),                          # 毁灭之刃（战吼）
    (r"deal (\d+) damage to the enemy hero\. combo: return this to your hand next turn",
     lambda m: ("headcrack(c)", False)),                                          # 裂颅之击
    (r"look at the top (\d+) cards of your deck\. draw one and discard the others",
     lambda m: ("track_draw3(c)", False)),                                        # 追踪术
    (r"give your minions stealth until your next turn",
     lambda m: ("hide_minions(c)", False)),                                       # 隐藏
    (r"return a friendly minion to your hand\. it costs \((\d+)\) less",
     lambda m: ("shadowstep(c, c.target)", "friendly_minion")),                   # 暗影步
    (r'give your minions "deathrattle: summon a (\d+)/(\d+) treant',
     lambda m: ("soul_of_the_forest(c)", False)),                                 # 丛林之魂
    (r"deal (\d+) damage to a minion\. if it dies, draw a card",
     lambda m: ("mortal_coil(c, c.target)", "any")),                              # 死亡缠绕
    (r"give a friendly minion \+(\d+)/\+(\d+) until end of turn\. then, it dies",
     lambda m: ("power_overwhelming(c, c.target)", "friendly_minion")),           # 力量的代价
    (r"deal (\d+) damage to a character\. if it dies, summon a random demon",
     lambda m: ("bane_of_doom(c, c.target)", "any")),                             # 末日灾祸
    (r"deal (\d+) damage to a minion\. if it survives, draw a card",
     lambda m: ("slam(c, c.target)", "any")),                                     # 猛击
    (r"deal (\d+) damage\. if you have (\d+) or less health, deal (\d+) instead",
     lambda m: ("mortal_strike(c, c.target)", "any")),                            # 致死打击
    (r"if you have a weapon, give it \+(\d+)/\+(\d+)\. otherwise equip a (\d+)/(\d+) weapon",
     lambda m: ("upgrade_weapon(c)", False)),                                     # 升级
    (r"deal (\d+) damage\. if you control a beast, deal (\d+) damage instead",
     lambda m: ("kill_command(c, c.target)", "any")),                             # 杀戮命令
    (r"all minions lose stealth\. destroy all enemy secrets\. draw a card",
     lambda m: ("flare(c)", False)),                                              # 照明弹
    (r"summon three (\d+)/(\d+) treants with charge that die at the end of the turn",
     lambda m: ("force_of_nature(c)", False)),                                    # 自然之力
    (r"all minions lose divine shield\. gain \+(\d+)/\+(\d+) for each shield lost",
     lambda m: ("blood_knight(c)", False)),                                       # 血骑士（战吼）
    (r"deal (\d+) damage to a minion\. if it'?s a friendly demon, give it \+(\d+)/\+(\d+) instead",
     lambda m: ("demonfire(c, c.target)", "any")),                                # 恶魔之火
    (r"your hero power becomes 'deal (\d+) damage\.' if already in shadowform: (\d+) damage",
     lambda m: ("shadowform(c)", False)),                                         # 暗影形态
    (r"your minions can't be reduced below 1 health this turn\. draw a card",
     lambda m: ("commanding_shout(c)", False)),                                   # 命令怒吼
]


def parse_special(text: str):
    """整段匹配的跨句效果 → (代码, 目标类型, True)；不匹配返回 None"""
    t = text.lower()
    for pat, fn in SPECIAL_RULES:
        m = re.search(pat, t)
        if m:
            code, tgt = fn(m)
            return (code, tgt, True)
    return None


def parse_aura(text: str):
    t = text.lower()
    for pat, fn in AURA_RULES:
        m = re.search(pat, t)
        if m:
            d = fn(m)
            if d.get("aura_race", 1) is False:      # 未知种族：放弃
                return None
            if d.get("aura_race", 1) is None:       # 不限种族
                d.pop("aura_race")
            if d.get("aura_per_race", 1) is False:
                return None
            return d
    return None


# ============ 触发 ============
# guard 名称 → 生成的判断代码（None 表示不判断）
GUARDS = {
    "self": "c.event_src is c.src",
    "target": "c.target is c.src",
    "any_minion": "is_minion(c.target)",
    "friendly_minion": "is_minion(c.target) and c.target.owner_id == c.me.pid",
    "friendly_death": "c.event_src is not None and c.event_src.owner_id == c.me.pid",
    "friendly_beast_death": ("c.event_src is not None and c.event_src.owner_id == c.me.pid "
                             "and 'BEAST' in c.event_src.races"),
    "beast_summon": "c.event_src is not None and 'BEAST' in getattr(c.event_src, 'races', [])",
    "murloc_summon": "c.event_src is not None and 'MURLOC' in getattr(c.event_src, 'races', [])",
    "small_summon": "c.event_src is not None and getattr(c.event_src, 'atk', 99) <= 3",
    "overload_card": "getattr(c, 'card', None) and c.card.get('overload')",
    "minion_heal": "is_minion(c.target)",
}

# (正则, 事件, guard名, 固定代码或None)
TRIGGER_RULES = [
    # 报警机器人：必须排在通用「回合开始」之前
    (r"at the start of your turn, swap this minion with a random one in your hand",
     "turn_start", None, "alarm_o_bot(c)"),
    # 伊瑟拉：必须排在通用「回合结束」之前
    (r"at the end of your turn, add a dream card to your hand",
     "turn_end", None, "add_random_dream(c)"),
    # 回合开始 / 结束
    (r"at the start of your turn[,:]?\s*(.+)", "turn_start", None, None),
    (r"at the end of your turn[,:]?\s*(.+)", "turn_end", None, None),
    (r"at the end of each turn[,:]?\s*(.+)", "turn_end", None, None),
    # 受伤
    (r"whenever this minion takes damage[,:]?\s*(.+)", "damage", "target", None),
    (r"whenever a friendly minion takes damage[,:]?\s*(.+)", "damage", "friendly_minion", None),
    (r"whenever a minion takes damage[,:]?\s*(.+)", "damage", "any_minion", None),
    # 治疗
    (r"whenever a character is healed[,:]?\s*(.+)", "heal", None, None),
    (r"whenever a minion is healed[,:]?\s*(.+)", "heal", "minion_heal", None),
    # 召唤
    (r"whenever a murloc is summoned[,:]?\s*(.+)", "summon", "murloc_summon", None),
    (r"whenever a player summons a murloc[,:]?\s*(.+)", "summon", "murloc_summon", None),
    (r"(?:after|whenever) you summon a beast[,:]?\s*(.+)", "summon", "beast_summon", None),
    (r"(?:after|whenever) you summon a minion with 3 or less attack[,:]?\s*(.+?)$",
     "summon", "small_summon", "give_charge(c, c.event_src)"),
    (r"(?:after|whenever) you summon a minion[,:]?\s*(.+)", "summon", None, None),
    # 死亡
    (r"whenever a friendly beast dies[,:]?\s*(.+)", "death", "friendly_beast_death", None),
    (r"after a friendly minion dies[,:]?\s*(.+)", "death", "friendly_death", None),
    (r"whenever a minion dies[,:]?\s*(.+)", "death", None, None),
    # 施法 / 出牌
    (r"whenever you cast a spell[,:]?\s*(.+)", "spell_cast", None, None),
    (r"(?:after|whenever) you cast a spell[,:]?\s*(.+)", "spell_cast", None, None),
    (r"whenever you play a card with overload[,:]?\s*(.+)", "play_card", "overload_card", None),
    (r"whenever you play a card[,:]?\s*(.+)", "play_card", None, None),
    # 奥秘
    (r"whenever a secret is played[,:]?\s*(.+)", "secret_played", None, None),
    (r"whenever a secret is revealed[,:]?\s*", "secret_played", None,
     "weapon_gain_dura(c, 1)"),
    # 攻击
    (r"whenever your hero attacks[,:]?\s*restore (\d+) health",
     "hero_attack", None, lambda m: f"heal(c, c.me, {m.group(1)})"),
    (r"(?:after|whenever) this attacks[,:]?\s*(.+)", "attack", "self", None),
    (r"whenever a friendly minion attacks[,:]?\s*(.+)", "attack", None, None),
]


def parse_trigger(text: str):
    """把触发句式解析成 (事件名, 判断代码或None, 效果代码)。返回 None 表示不支持"""
    low = text.lower()
    for pat, event, guard_key, fixed in TRIGGER_RULES:
        m = re.search(pat, low)
        if not m:
            continue
        if fixed:
            code = fixed(m) if callable(fixed) else fixed
        else:
            r = parse_effect(m.group(1))
            if not r:
                return None
            code, need_target, _ = r
            if need_target:                 # 触发效果不能手动选目标
                return None
        return (event, GUARDS.get(guard_key) if guard_key else None, code)
    return None


# 这些句式虽然能解析，但卡面效果是有时限的，标「部分」更诚实
PARTIAL_HINT = re.compile(
    r"until your next turn|until the end of the turn|die at the end of the turn|"
    r"until end of turn", re.I)

# 暗影狂乱这类「本回合控制权、回合结束归还」已经真的实现了，不该再标「部分」
SHADOW_MADNESS = re.compile(
    r"gain control of an enemy minion with \d+ or less attack until end of turn", re.I)

# 时限效果现在已经真的做出来了（回合结束死亡 / 潜行到期 / 当回合不死），这些不再算「部分」
FULL_TIMED = {"Conceal", "Force of Nature", "Power Overwhelming"}


# ============ 危险句式 ============
# 命中就放弃这句（宁可漏实现，也不要实现成错误的效果）。
# 注意：combo / overload / for each 已被显式规则覆盖，故不在此列。
DANGER = re.compile(
    r"\b(instead|twice|cast this again|each time|"
    r"whenever|every time|at the end|at the start|if|unless|while|"
    r"choose one|discover|hasn't|didn't|already)\b", re.I)


def split_clauses(t: str):
    """按句号/分号拆成子句（炉石卡面常用多句描述）

    纯括号子句是卡面的补充说明（「(+4 Attack/+4 Health)」「(chosen randomly)」），
    不是独立效果，直接丢掉 —— 否则会被算成「有一句没解析」而错标成「部分实现」。
    """
    parts = re.split(r"(?<=[a-z0-9\)])\s*[.;]\s*", t)
    out = []
    for p in parts:
        p = p.strip()
        if not p or re.fullmatch(r"\([^()]*\)\.?", p):
            continue
        out.append(p)
    return out


# ============ 抉择（Choose One）============
# 卡面：<b>Choose One -</b> A; or B.
# 难点：A / B 里有一半是「省略主语的残句」（"+5 Attack"、"$2 damage to all enemy minions"），
# 走通用规则会被截成半句或漏掉，所以单独一张小规则表；只有抉择选项会用它。
# 每条返回 (代码, 目标类型)；fn(m, self_t, self_tgt)
#   self_t   = 该效果作用在谁身上（随从牌 = 自己 c.src；法术牌 = 选的目标 c.target）
#   self_tgt = 这张牌默认需要目标时的类型（随从牌 None，法术牌 "any"）
CHOOSE_OPT_RULES = [
    (r"(\d+) damage and draw a card",                   # 「1点伤害并抽一张牌」（愤怒）
     lambda m, s, t: (f"(damage(c, c.target, {m.group(1)}), draw(c, 1))", "any")),
    (r"(\d+) damage to all enemy minions",             # 「对所有敌方随从造成2点伤害」（星辰坠落）
     lambda m, s, t: (f"aoe(c, lambda x: damage(c, x, {m.group(1)}), side='foe')", None)),
    (r"give your other minions \+(\d+)/\+(\d+)",       # 塞纳留斯
     lambda m, s, t: (f"buff_all(c, {m.group(1)}, {m.group(2)}, exclude_src=True)", None)),
    (r"give your minions \+(\d+)/\+(\d+)",             # 野性之力
     lambda m, s, t: (f"buff_all(c, {m.group(1)}, {m.group(2)})", None)),
    (r"\+(\d+) health and taunt",                      # 「+4生命值并具有嘲讽」
     lambda m, s, t: (f"buff(c, {s}, 0, {m.group(1)}, taunt=True)", t)),
    (r"\+(\d+) attack",                                # 「+5攻击力」
     lambda m, s, t: (f"buff(c, {s}, {m.group(1)}, 0)", t)),
    (r"\+(\d+)/\+(\d+)",                               # 「+2/+2」
     lambda m, s, t: (f"buff(c, {s}, {m.group(1)}, {m.group(2)})", t)),
    (r"(?:gain )?(\d+) mana crystals?",                # 「获得两个法力水晶」（滋养）
     lambda m, s, t: (f"gain_mana(c, {m.group(1)})", None)),
    (r"charge",                                        # 利爪德鲁伊
     lambda m, s, t: (f"give_charge(c, {s})", None)),
    (r"summon two (\d+)/(\d+) treants with taunt",     # 塞纳留斯
     lambda m, s, t: (f"summon_token(c, {m.group(1)}, {m.group(2)}, 2, '树人', taunt=True)", None)),
    (r"summon a (\d+)/(\d+) panther",                  # 野性之力
     lambda m, s, t: (f"summon_token(c, {m.group(1)}, {m.group(2)}, 1, '猎豹')", None)),
]

# ============ 动态费用 ============
# 费用句只是「标签」，真正的计算在 engine.Game.cost()，这里只负责标出参数。
# 匹配到的句子会从卡面文本里摘掉，避免被当成没实现的效果。
COST_RULES = [
    (r"costs \((\d+)\) less for each other card in your hand",
     lambda m: {"cost_less_per": ("hand_other", int(m.group(1)))}),          # 山岭巨人
    (r"costs \((\d+)\) less for each damage your hero has taken",
     lambda m: {"cost_less_per": ("hero_damage", int(m.group(1)))}),         # 熔核巨人
    (r"costs \((\d+)\) less for each other minion on the battlefield",
     lambda m: {"cost_less_per": ("board_minions", int(m.group(1)))}),       # 海巨人
    (r"costs \((\d+)\) less per attack of your weapon",
     lambda m: {"cost_less_per": ("weapon_atk", int(m.group(1)))}),          # 恐怖海盗
    (r"your spells cost \((\d+)\) less",
     lambda m: {"spell_discount": int(m.group(1))}),                          # 巫师学徒
    (r"your minions cost \((\d+)\) less, but not less than \(1\)",
     lambda m: {"minion_discount": int(m.group(1))}),                         # 召唤传送门
    (r"all minions cost \((\d+)\) more",
     lambda m: {"all_minion_more": int(m.group(1))}),                         # 法力怨魂
    (r"the first minion you play each turn costs \((\d+)\) less",
     lambda m: {"first_minion_discount": int(m.group(1))}),                   # 小个子召唤师
    (r"your minions cost \((\d+)\) more",
     lambda m: {"minion_cost_more": int(m.group(1))}),                        # 风险投资公司雇佣兵
]

CHOOSE_SPLIT_EN = re.compile(r";\s*or\s+", re.I)
CHOOSE_SPLIT_ZH = re.compile(r"；\s*或者\s*|；\s*或\s*")


def parse_choose_option(opt: str, is_minion: bool):
    """解析抉择里的一个选项 → (代码, 目标类型)。返回 None 表示解析不了"""
    o = clean(opt).lower().strip().rstrip(".。")
    if not o:
        return None
    self_t = "c.src" if is_minion else "c.target"
    self_tgt = None if is_minion else "any"
    for pat, fn in CHOOSE_OPT_RULES:
        m = re.match(pat + r"$", o)          # 整段匹配，避免只吃到半句
        if m:
            return fn(m, self_t, self_tgt)
    r = parse_one(o)                          # 剩下的交给通用规则
    if r:
        code, need = r
        tgt = (need if isinstance(need, str) else "any") if need else None
        if "restore" in o or "heal" in o:     # 治疗类默认往自己脸上/自己随从上放
            tgt = "friendly_any"
        return code, tgt
    return None


def parse_choose(text_en: str, text_zh: str, is_minion: bool):
    """'Choose One - A; or B' → [(中文标签, 代码, 目标类型), ...]；解析不全则返回 None"""
    en = re.sub(r"^.*?choose one\s*-\s*", "", clean(text_en), flags=re.I | re.S)
    zh = re.sub(r"^.*?抉择[：:]\s*", "", clean(text_zh), flags=re.S)
    parts_en = [p for p in CHOOSE_SPLIT_EN.split(en) if p.strip()]
    parts_zh = [re.sub(r"\s+", "", p).rstrip("。.")
                for p in CHOOSE_SPLIT_ZH.split(zh) if p.strip()]
    if len(parts_en) != 2 or len(parts_zh) != 2:
        return None
    out = []
    for i, p in enumerate(parts_en):
        r = parse_choose_option(p, is_minion)
        if not r:
            return None
        out.append((parts_zh[i], r[0], r[1]))
    return out


# 这些句式在通用规则之前必须先匹配，否则会被「只说半句」的通用规则截胡
PRIORITY_RULES = [
    (r"the next spell you cast this turn costs \((\d+)\) less",   # 伺机待发
     lambda m: (f"next_spell_discount(c, {m.group(1)})", False)),
    (r"the next secret you play this turn costs \(0\)",           # 肯瑞托法师
     lambda m: ("next_secret_free(c)", False)),
    (r"enemy spells cost \(0\) next turn",                        # 米尔豪斯·法力风暴
     lambda m: ("enemy_spells_free(c)", False)),
    (r"destroy both adjacent minions and gain their attack and health",   # 虚空恐魔
     lambda m: ("void_terror(c)", False)),
    (r"if your opponent has (\d+) or more minions, take control of one at random",
     lambda m: (f"mind_control_tech(c, {m.group(1)})", False)),    # 精神控制技师
    (r"transform another random minion into a \d+/\d+ devilsaur or a \d+/\d+ squirrel",
     lambda m: ("tinker(c)", False)),                              # 工匠大师欧沃斯巴克
    (r"gain control of an enemy minion with (\d+) or less attack until end of turn",
     lambda m: (f"shadow_madness(c, c.target, {m.group(1)})", "enemy_minion")),   # 暗影狂乱
    (r"give your opponent 2 bananas",                              # 穆克拉
     lambda m: ("give_foe_tokens(c, 'TOKEN_BANANA', 2)", False)),
    (r"give both players the power to rock",                        # 精英牛头人酋长
     lambda m: ("etc_chord(c)", False)),
    (r"destroy your hero and replace it with lord jaraxxus",         # 加拉克苏斯大王
     lambda m: ("jaraxxus(c)", False)),
    (r"silence a minion, then deal (\d+) damage to it",
     lambda m: (f"(silence(c, c.target), damage(c, c.target, {m.group(1)}))", "any")),
    (r"destroy your opponent's weapon and draw cards equal to its durability",
     lambda m: ("harrison(c)", False)),
    (r"draw a card and deal damage equal to its cost",
     lambda m: ("holy_wrath(c)", False)),
    (r"destroy a murloc and gain \+(\d+)/\+(\d+)",
     lambda m: (f"hungry_crab(c, {m.group(1)}, {m.group(2)})", "any")),
    (r"destroy a demon", lambda m: ("destroy_if_race(c, c.target, 'DEMON')", "any")),
    (r"destroy your weapon and deal its damage to all enemies",
     lambda m: ("blade_flurry(c)", False)),
    (r"deal (\d+) damage to all enemy minions and freeze them",
     lambda m: (f"(aoe(c, lambda x: damage(c, x, {m.group(1)}), side='foe'), "
                f"aoe(c, lambda x: freeze(c, x), side='foe'))", False)),
    (r"deal (\d+) damage to a character and freeze it",
     lambda m: (f"freeze_and_damage(c, c.target, {m.group(1)})", "any")),
    (r"deal (\d+) damage to an enemy character and freeze it",
     lambda m: (f"freeze_and_damage(c, c.target, {m.group(1)})", "any")),
    (r"freeze a minion and the minions next to it, and deal (\d+) damage to them",
     lambda m: (f"cone_of_cold(c, c.target, {m.group(1)})", "enemy_minion")),
    (r"deal (\d+) damage to an enemy and (\d+) damage to all other enemies",
     lambda m: (f"cleave_enemies(c, c.target, {m.group(1)}, {m.group(2)})", "enemy_minion")),
    (r"deal (\d+) damage to a minion and (\d+) damage to adjacent ones",
     lambda m: (f"explosive_shot(c, c.target, {m.group(1)}, {m.group(2)})", "enemy_minion")),
]


def parse_one(clause: str):
    """解析单个子句 → (代码, 是否需要目标/目标类型)。返回 None 表示这一句不处理"""
    t = clause.lower().strip()
    t = re.sub(r"^(combo|outcast|finale|frenzy|battlecry|deathrattle)\s*[::]\s*", "", t)
    if not t:
        return None
    for pat, fn in PRIORITY_RULES:      # 复合句先匹配，避免被通用规则截成半句
        m = re.search(pat, t)
        if m:
            return fn(m)
    for pat, fn in SAFE_RULES:          # 语义明确的句式优先，不受 DANGER 拦截
        m = re.search(pat, t)
        if m:
            return fn(m)
    if DANGER.search(t):
        return None

    # 「随机将一张X牌置入手牌」
    m = re.search(r"add a random (.+?) to your hand", t)
    if m:
        words = m.group(1).split()
        rarity = next((RARITY_WORD[w] for w in words if w in RARITY_WORD), None)
        ctype = next((TYPE_WORD[w] for w in words if w in TYPE_WORD), None)
        race = next((RACE_WORD[w] for w in words if w in RACE_WORD), None)
        cls = next((w.upper() for w in words if w in CLASS_WORD), None)
        if race and not ctype:
            ctype = "MINION"
        if rarity or ctype or race or cls:
            args = []
            if rarity:
                args.append(f"rarity={rarity!r}")
            if ctype:
                args.append(f"ctype={ctype!r}")
            if race:
                args.append(f"race={race!r}")
            if cls:
                args.append(f"cls={cls!r}")
            return (f"add_random_to_hand(c, {', '.join(args)})", False)

    for pat, fn in RULES:
        m = re.search(pat, t)
        if m:
            return fn(m)
    return None


def parse_effect(text: str):
    """多子句解析 → (代码, 目标类型, 是否完整覆盖)"""
    hit = parse_special(text)          # 跨句条件先整段匹配（战吼文本也走这里）
    if hit:
        return hit
    text = re.sub(r"overload:?\s*\(\d+\)", " ", text, flags=re.I)   # 过载走旗标，不算子句
    clauses = split_clauses(text)
    codes, tgt, total, covered = [], None, 0, 0
    for cl in clauses:
        if not substance(cl):
            continue
        total += 1
        r = parse_one(cl)
        if r:
            code, need = r
            codes.append(code)
            if need and not tgt:
                tgt = need if isinstance(need, str) else "any"
            elif need and tgt:
                tgt = tgt
            covered += 1
    if not codes:
        return None
    code = f"({', '.join(codes)})" if len(codes) > 1 else codes[0]
    return (code, tgt, covered == total)


KW_FIELD = {"windfury": "windfury", "taunt": "taunt", "divine shield": "shield",
            "lifesteal": "lifesteal", "poisonous": "poisonous", "charge": "charge",
            "rush": "rush", "stealth": "stealth", "immune": "immune"}

# 伤害/治疗/抽牌/增益的常规句式。顺序 = 优先级，越具体越靠前。
RULES = [
    # ---------- 消灭 ----------
    (r"destroy all minions except one", lambda m: ("brawl(c)", False)),
    (r"destroy all other minions and discard your hand",
     lambda m: ("(destroy_all_other_minions(c), discard_hand(c))", False)),
    (r"destroy all other minions", lambda m: ("destroy_all_other_minions(c)", False)),
    (r"destroy all minions",
     lambda m: ("(aoe(c, lambda x: destroy(c, x), side='own'), "
                "aoe(c, lambda x: destroy(c, x), side='foe'))", False)),
    (r"destroy a damaged enemy minion", lambda m: ("destroy_damaged_enemy(c)", False)),
    (r"destroy a random enemy minion with (\d+) or less attack",
     lambda m: (f"destroy_random_enemy(c, {m.group(1)})", False)),
    (r"destroy a random enemy minion", lambda m: ("destroy_random_enemy(c)", False)),
    (r"destroy a minion with (\d+) or more attack",
     lambda m: (f"destroy_if_atk(c, c.target, {m.group(1)})", "any")),
    (r"destroy a friendly minion and deal its attack damage to all enemy minions",
     lambda m: ("shadowflame(c, c.target)", "friendly_minion")),
    (r"^destroy an? (?:enemy )?minion", lambda m: ("destroy(c, c.target)", "any")),
    (r"^destroy a minion", lambda m: ("destroy(c, c.target)", "any")),
    # ---------- 控制权 ----------
    (r"take control of an enemy minion with (\d+) or less attack",
     lambda m: (f"take_control_if(c, c.target, {m.group(1)})", "enemy_minion")),
    (r"take control of an enemy minion that has (\d+) or less attack",
     lambda m: (f"take_control_if(c, c.target, {m.group(1)})", "enemy_minion")),
    (r"take control of a random enemy minion", lambda m: ("steal_random_minion(c)", False)),
    (r"take control of an enemy minion",
     lambda m: ("take_control(c, c.target)", "enemy_minion")),
    # ---------- 变形 / 属性改写 ----------
    (r"transform a minion into a (\d+)/(\d+)",
     lambda m: (f"transform(c, c.target, {m.group(1)}, {m.group(2)}, '绵羊')", "any")),
    (r"swap the attack and health of a minion", lambda m: ("swap_stats(c, c.target)", "any")),
    (r"change a minion's attack to be equal to its health",
     lambda m: ("atk_to_health(c, c.target)", "any")),
    (r"change an enemy minion's attack to (\d+)",
     lambda m: (f"set_atk(c, c.target, {m.group(1)})", "enemy_minion")),
    (r"change a minion's attack to (\d+)",
     lambda m: (f"set_atk(c, c.target, {m.group(1)})", "any")),
    (r"change the health of all minions to (\d+)",
     lambda m: (f"set_all_health(c, {m.group(1)})", False)),
    (r"change a minion's health to (\d+)", lambda m: ("set_health(c, c.target, 1)", "any")),
    (r"double a minion's attack", lambda m: ("double_atk(c, c.target)", "any")),
    (r"double a minion's health", lambda m: ("double_health(c, c.target)", "any")),
    (r"restore a minion to full health", lambda m: ("heal_full(c, c.target)", "any")),
    (r"restore a friendly character to full health", lambda m: ("heal_full(c, c.me)", False)),
    (r"set a hero's remaining health to (\d+)",
     lambda m: (f"set_hero_hp(c, None, {m.group(1)})", False)),
    # ---------- 复制 / 变成 ----------
    (r"choose a minion and become a copy of it",
     lambda m: ("become_copy(c, c.target)", "friendly_any")),
    # ---------- 群体伤害 ----------
    (r"deal (\d+) damage to all enemy minions and freeze them",
     lambda m: (f"(aoe(c, lambda x: damage(c, x, {m.group(1)}), side='foe'), "
                f"aoe(c, lambda x: freeze(c, x), side='foe'))", False)),
    (r"deal (\d+) damage randomly split among all enemy characters",
     lambda m: (f"damage_random_enemy(c, 1, {m.group(1)})", False)),
    (r"deal (\d+) damage randomly split between all other characters",
     lambda m: (f"damage_random(c, 1, {m.group(1)})", False)),
    (r"deal (\d+)-(\d+) damage to all enemy minions",
     lambda m: (f"aoe_range(c, {m.group(1)}, {m.group(2)}, 'foe')", False)),
    (r"deal (\d+) damage to all other characters",
     lambda m: (f"(aoe(c, lambda x: damage(c, x, {m.group(1)}), side='own'), "
                f"aoe(c, lambda x: damage(c, x, {m.group(1)}), side='foe'), "
                f"damage(c, c.me, {m.group(1)}), damage(c, c.foe, {m.group(1)}))", False)),
    (r"deal (\d+) damage to all characters",
     lambda m: (f"(aoe(c, lambda x: damage(c, x, {m.group(1)}), side='own'), "
                f"aoe(c, lambda x: damage(c, x, {m.group(1)}), side='foe'), "
                f"damage(c, c.me, {m.group(1)}), damage(c, c.foe, {m.group(1)}))", False)),
    (r"deal (\d+) damage to all enemies",
     lambda m: (f"(aoe(c, lambda x: damage(c, x, {m.group(1)}), side='foe'), "
                f"damage(c, c.foe, {m.group(1)}))", False)),
    (r"deal (\d+) damage to all (enemy )?minions",
     lambda m: (f"aoe(c, lambda x: damage(c, x, {m.group(1)}), side='foe')" if m.group(2)
                else f"(aoe(c, lambda x: damage(c, x, {m.group(1)}), side='own'), "
                     f"aoe(c, lambda x: damage(c, x, {m.group(1)}), side='foe'))", False)),
    # ---------- 群体治疗 ----------
    (r"restore (\d+) health to all (friendly|your) (minions|characters)",
     lambda m: (f"aoe(c, lambda x: heal(c, x, {m.group(1)}), side='own')", False)),
    (r"restore (\d+) health to all minions",
     lambda m: (f"(aoe(c, lambda x: heal(c, x, {m.group(1)}), side='own'), "
                f"aoe(c, lambda x: heal(c, x, {m.group(1)}), side='foe'))", False)),
    # ---------- 单体伤害 ----------
    (r"deal (\d+) damage to a character and freeze it",
     lambda m: (f"freeze_and_damage(c, c.target, {m.group(1)})", "any")),
    (r"deal (\d+) damage to an enemy character and freeze it",
     lambda m: (f"freeze_and_damage(c, c.target, {m.group(1)})", "any")),
    (r"deal (\d+) damage to a minion and freeze it",
     lambda m: (f"freeze_and_damage(c, c.target, {m.group(1)})", "any")),
    (r"deal (\d+) damage to all enemy minions and freeze them",
     lambda m: (f"(aoe(c, lambda x: damage(c, x, {m.group(1)}), side='foe'), "
                f"aoe(c, lambda x: freeze(c, x), side='foe'))", False)),
    (r"deal (\d+) damage to all enemy minions and freeze them",
     lambda m: (f"(aoe(c, lambda x: damage(c, x, {m.group(1)}), side='foe'), "
                f"aoe(c, lambda x: freeze(c, x), side='foe'))", False)),
    (r"freeze a minion and the minions next to it, and deal (\d+) damage to them",
     lambda m: (f"cone_of_cold(c, c.target, {m.group(1)})", "enemy_minion")),
    (r"deal (\d+) damage to an enemy and (\d+) damage to all other enemies",
     lambda m: (f"cleave_enemies(c, c.target, {m.group(1)}, {m.group(2)})", "enemy_minion")),
    (r"deal (\d+) damage to a minion and (\d+) damage to adjacent ones",
     lambda m: (f"explosive_shot(c, c.target, {m.group(1)}, {m.group(2)})", "enemy_minion")),
    (r"destroy your weapon and deal its damage to all enemies",
     lambda m: ("blade_flurry(c)", False)),
    (r"deal damage equal to your hero's attack to a minion",
     lambda m: ("hero_atk_damage(c, c.target)", "any")),
    (r"deal 1 damage to a minion for each armor you have",
     lambda m: ("armor_as_damage(c, c.target)", "any")),
    (r"deal (\d+) damage to a random enemy",
     lambda m: (f"damage_random_enemy(c, {m.group(1)})", False)),
    (r"deal (\d+) damage to this minion and summon a (\d+)/(\d+)",
     lambda m: (f"(damage(c, c.src, {m.group(1)}), "
                f"summon_token(c, {m.group(2)}, {m.group(3)}, 1))", False)),
    (r"deal (\d+) damage to this minion", lambda m: (f"damage(c, c.src, {m.group(1)})", False)),
    (r"deal (\d+) damage to your hero", lambda m: (f"damage(c, c.me, {m.group(1)})", False)),
    (r"deal (\d+) damage to the enemy hero", lambda m: (f"damage(c, c.foe, {m.group(1)})", False)),
    (r"deal (\d+) damage to a minion and give it \+(\d+) attack",
     lambda m: (f"(damage(c, c.target, {m.group(1)}), "
                f"buff(c, c.target, {m.group(2)}, 0))", "any")),
    (r"deal (\d+) damage", lambda m: (f"damage(c, c.target, {m.group(1)})", "any")),
    # ---------- 治疗 ----------
    (r"restore (\d+) health to a damaged friendly character",
     lambda m: (f"heal_random_damaged(c, {m.group(1)})", False)),
    (r"restore (\d+) health to (?:your hero|a friendly character|your character|all characters)",
     lambda m: (f"heal(c, c.me, {m.group(1)})", False)),
    (r"restore (\d+) health", lambda m: (f"heal(c, c.target, {m.group(1)})", "any")),
    # ---------- 抽牌 ----------
    (r"draw cards until you have as many in hand as your opponent",
     lambda m: ("draw_until_even(c)", False)),
    (r"draw a card for each damaged friendly character",
     lambda m: ("draw_per_damaged(c)", False)),
    (r"draw (\d+) (demons|pirates) from your deck",
     lambda m: (f"draw_filtered(c, {rw(m.group(2))!r}, {m.group(1)})", False)),
    (r"draw a (pirate|demon|beast|dragon|murloc) from your deck",
     lambda m: (f"draw_filtered(c, {rw(m.group(1))!r}, 1)", False)),
    (r"each player draws (\d+|a|two) cards?",
     lambda m: (f"draw_for_both(c, {_num(m.group(1))})", False)),
    (r"your opponent draws (\d+) cards?", lambda m: (f"draw_foe(c, {m.group(1)})", False)),
    (r"draw (\d+|a|two|three) cards?",
     lambda m: (f"draw(c, {_num(m.group(1))})", False)),
    (r"look at the top (\d+) cards of your deck", lambda m: ("track_draw(c)", False)),
    # ---------- 护甲 / 资源 ----------
    (r"gain (\d+) armor", lambda m: (f"gain_armor(c, {m.group(1)})", False)),
    (r"gain (\d+) mana crystals? this turn only",
     lambda m: (f"gain_mana(c, {m.group(1)})", False)),
    (r"gain an empty mana crystal", lambda m: ("gain_mana(c, 1)", False)),
    (r"gain (\d+) mana crystals?", lambda m: (f"gain_mana(c, {m.group(1)})", False)),
    (r"destroy one of your mana crystals", lambda m: ("burn_crystal(c, 1)", False)),
    (r"give your opponent a mana crystal", lambda m: ("give_crystal(c, 'foe', 1)", False)),
    # ---------- buff：带关键词的写法要排在通用写法前面 ----------
    (r"give a friendly beast \+(\d+)/\+(\d+) and taunt",
     lambda m: (f"buff(c, c.target, {m.group(1)}, {m.group(2)}, taunt=True)", "beast")),
    (r"give (?:a |an )?minion \+(\d+)/\+(\d+) and taunt",
     lambda m: (f"buff(c, c.target, {m.group(1)}, {m.group(2)}, taunt=True)", "any")),
    (r"give (?:a |an )?minion \+(\d+)/\+(\d+) and divine shield",
     lambda m: (f"buff(c, c.target, {m.group(1)}, {m.group(2)}, shield=True)", "any")),
    (r"give (?:a |an )?minion \+(\d+)/\+(\d+) and lifesteal",
     lambda m: (f"buff(c, c.target, {m.group(1)}, {m.group(2)}, lifesteal=True)", "any")),
    # 本回合有效
    (r"give a friendly minion \+(\d+)/\+(\d+) until end of turn",
     lambda m: (f"temp_buff(c, c.target, {m.group(1)}, {m.group(2)})", "friendly_minion")),
    (r"give an? minion \+(\d+)/\+(\d+) until end of turn",
     lambda m: (f"temp_buff(c, c.target, {m.group(1)}, {m.group(2)})", "any")),
    (r"give a minion \+(\d+) attack this turn",
     lambda m: (f"temp_buff(c, c.target, {m.group(1)}, 0)", "any")),
    (r"give a beast \+(\d+) attack and immune this turn",
     lambda m: (f"(temp_buff(c, c.target, {m.group(1)}, 0), "
                f"setattr(c.target, 'immune', True))", "beast")),
    (r"give your hero \+(\d+) attack this turn",
     lambda m: (f"temp_buff(c, c.me, {m.group(1)}, 0)", False)),
    (r"give your characters \+(\d+) attack this turn",
     lambda m: (f"temp_buff_all(c, {m.group(1)}, 0)", False)),
    (r"give a friendly character \+(\d+) attack this turn",
     lambda m: (f"temp_buff(c, c.target, {m.group(1)}, 0)", "friendly")),
    # 永久 buff（单体）
    (r"give a friendly minion \+(\d+)/\+(\d+)",
     lambda m: (f"buff(c, c.target, {m.group(1)}, {m.group(2)})", "friendly_minion")),
    (r"give a minion taunt and \+(\d+)/\+(\d+)",
     lambda m: (f"buff(c, c.target, {m.group(1)}, {m.group(2)}, taunt=True)", "any")),
    (r"give a minion \+(\d+)/\+(\d+) and taunt",
     lambda m: (f"buff(c, c.target, {m.group(1)}, {m.group(2)}, taunt=True)", "any")),
    (r"give a damaged minion \+(\d+)/\+(\d+)",
     lambda m: (f"buff(c, c.target, {m.group(1)}, {m.group(2)})", "any")),
    (r"give (?:a |your |an |all )?(?:friendly )?minions? \+(\d+)/\+(\d+)",
     lambda m: (f"buff(c, c.target, {m.group(1)}, {m.group(2)})", "any")),
    (r"give (?:a )?minion \+(\d+)/\+(\d+)",
     lambda m: (f"buff(c, c.target, {m.group(1)}, {m.group(2)})", "any")),
    (r"give a friendly minion \+(\d+) attack",
     lambda m: (f"buff(c, c.target, {m.group(1)}, 0)", "friendly_minion")),
    (r"give (?:a |an )?minion \+(\d+) attack",
     lambda m: (f"buff(c, c.target, {m.group(1)}, 0)", "any")),
    (r"give a friendly minion \+(\d+) health",
     lambda m: (f"buff(c, c.target, 0, {m.group(1)})", "friendly_minion")),
    (r"give (?:a |an )?minion \+(\d+) health",
     lambda m: (f"buff(c, c.target, 0, {m.group(1)})", "any")),
    (r"give your hero \+(\d+) attack", lambda m: (f"buff_hero_atk(c, {m.group(1)})", False)),
    # 种族群体
    (r"give all other (\w+) \+(\d+) health",
     lambda m: (f"buff_race(c, {rw(m.group(1))!r}, 0, {m.group(2)}, other=True)", False)),
    (r"give your (\w+) \+(\d+) health",
     lambda m: (f"buff_race(c, {rw(m.group(1))!r}, 0, {m.group(2)}, other=False)", False)),
    # 关键词
    (r"give (?:a |an )?(?:friendly )?minion (windfury|taunt|divine shield|lifesteal|poisonous|charge|rush|stealth)",
     lambda m: (f"buff(c, c.target, 0, 0, {KW_FIELD[m.group(1)]}=True)", "friendly_minion")),
    (r"give your (?:other )?minions? stealth",
     lambda m: ("give_stealth_all(c)", False)),
    (r"give your minions \+(\d+) attack", lambda m: (f"buff_all(c, {m.group(1)}, 0)", False)),
    # 相邻随从
    (r"give adjacent minions \+(\d+)/\+(\d+) and taunt",
     lambda m: (f"buff_neighbors(c, {m.group(1)}, {m.group(2)}, taunt=True)", False)),
    (r"give adjacent minions \+(\d+)/\+(\d+)",
     lambda m: (f"buff_neighbors(c, {m.group(1)}, {m.group(2)})", False)),
    (r"give adjacent minions spell damage \+(\d+)",
     lambda m: (f"buff_neighbors_sp(c, {m.group(1)})", False)),
    (r"give adjacent minions taunt", lambda m: ("buff_neighbors(c, 0, 0, taunt=True)", False)),
    # 随机一个友方随从（铸剑师 / 年轻的女祭司 / 鲜血小鬼）
    (r"give another random friendly minion \+(\d+)/\+(\d+)",
     lambda m: (f"buff_random_other(c, {m.group(1)}, {m.group(2)})", False)),
    (r"give another random friendly minion \+(\d+) attack",
     lambda m: (f"buff_random_other(c, {m.group(1)}, 0)", False)),
    (r"give another random friendly minion \+(\d+) health",
     lambda m: (f"buff_random_other(c, 0, {m.group(1)})", False)),
    # 概率抽牌（纳特·帕格）
    (r"you have a (\d+)% chance to draw", lambda m: (f"chance_draw(c, {m.group(1)})", False)),
    # 自身 scaling
    (r"gain \+(\d+)/\+(\d+) for each card played earlier this turn",
     lambda m: ("combo_buff(c, 2)", False)),
    (r"gain \+(\d+) health for each card in your hand",
     lambda m: (f"buff_per_hand(c, {m.group(1)})", False)),
    (r"gain \+(\d+)/\+(\d+) for each other friendly minion",
     lambda m: (f"buff_per_board(c, {m.group(1)})", False)),
    (r"gain \+(\d+)/\+(\d+)", lambda m: (f"buff(c, c.src, {m.group(1)}, {m.group(2)})", False)),
    (r"gain \+(\d+) attack this turn", lambda m: (f"temp_buff(c, c.src, {m.group(1)}, 0)", False)),
    (r"gain \+(\d+) attack", lambda m: (f"buff(c, c.src, {m.group(1)}, 0)", False)),
    (r"gain attack equal to (?:the attack of )?your weapon(?:'?s attack)?",
     lambda m: ("buff_from_weapon(c)", False)),
    # 武器 / 法力 / 手牌
    (r"destroy your opponent's weapon", lambda m: ("destroy_weapon(c, 'foe')", False)),
    (r"destroy your weapon", lambda m: ("destroy_weapon(c, 'own')", False)),
    (r"your opponent's weapon loses (\d+) durability",
     lambda m: (f"weapon_durability(c, 'foe', -{m.group(1)})", False)),
    (r"remove (\d+) durability from your opponent's weapon",
     lambda m: (f"weapon_durability(c, 'foe', -{m.group(1)})", False)),
    (r"give your weapon \+(\d+)/\+(\d+)",
     lambda m: (f"(buff_weapon(c, {m.group(1)}), "
                f"weapon_gain_dura(c, {m.group(2)}))", False)),
    (r"give your weapon \+(\d+) attack", lambda m: (f"buff_weapon(c, {m.group(1)})", False)),
    # 回手
    (r"return a friendly minion (?:from the battlefield )?to (?:your|its owner's) hand",
     lambda m: ("return_to_hand(c, c.target)", "friendly_minion")),
    (r"return an enemy minion to (?:your|its owner's|your opponent's) hand",
     lambda m: ("return_to_hand(c, c.target)", "enemy_minion")),
    (r"return a minion to its owner's hand", lambda m: ("return_to_hand(c, c.target)", "any")),
    (r"return all minions to (?:their|your opponent's) owner'?s? hand",
     lambda m: ("return_all_minions(c)", False)),
    # 弃牌
    (r"discard (a|two|\d+) random cards?",
     lambda m: (f"discard_random(c, {_num(m.group(1))})", False)),
    (r"discard your hand", lambda m: ("discard_hand(c)", False)),
    # 复制对手的牌
    (r"copy of (\d+) random cards from your opponent's deck",
     lambda m: (f"copy_from_foe_deck(c, {m.group(1)})", False)),
    (r"copy (\d+) cards? in your opponent's deck",
     lambda m: (f"copy_from_foe_deck(c, {m.group(1)})", False)),
    (r"copy of a random minion from your opponent's deck into the battlefield",
     lambda m: ("copy_from_foe_deck(c, 1, only_minion=True)", False)),
    (r"random card (?:(?:from|in) your opponent's hand)", lambda m: ("copy_from_foe_hand(c, 1)", False)),
    (r"add a '([^']+)' spell to your hand",
     lambda m: (f"add_card_named(c, {m.group(1)!r})", False)),
    # 沉默
    (r"silence all enemy minions", lambda m: ("silence_all_foe(c)", False)),
    (r"silence a minion, then deal (\d+) damage to it",
     lambda m: (f"(silence(c, c.target), damage(c, c.target, {m.group(1)}))", "any")),
    (r"^silence a minion", lambda m: ("silence(c, c.target)", "any")),
    # 哈里森·琼斯：毁武器并按耐久抽牌
    (r"destroy your opponent's weapon and draw cards equal to its durability",
     lambda m: ("harrison(c)", False)),
    # 神圣愤怒：抽牌并按费用造成伤害
    (r"draw a card and deal damage equal to its cost",
     lambda m: ("holy_wrath(c)", False)),
    # 鱼人杀手蟹：吃掉一个鱼人并 +2/+2
    (r"destroy a murloc and gain \+(\d+)/\+(\d+)",
     lambda m: (f"hungry_crab(c, {m.group(1)}, {m.group(2)})", "enemy_minion")),
    # 牺牲契约：消灭一个恶魔
    (r"destroy a demon", lambda m: ("destroy_if_race(c, c.target, 'DEMON')", "any")),
    # 奥秘相关
    (r"destroy all enemy secrets",
     lambda m: ("destroy_enemy_secrets(c)", False)),
    # 背叛：让敌方随从打自己的同伴
    (r"force an enemy minion to deal its damage to the minions next to it",
     lambda m: ("betrayal(c, c.target)", "enemy_minion")),
    # 冻结
    (r"freeze all enemy minions",
     lambda m: ("aoe(c, lambda x: freeze(c, x), side='foe')", False)),
    (r"freeze all minions",
     lambda m: ("(aoe(c, lambda x: freeze(c, x), side='own'), "
                "aoe(c, lambda x: freeze(c, x), side='foe'))", False)),
    (r"freeze (?:a |an |the )?(?:enemy )?(?:character|minion|enemy)\b",
     lambda m: ("freeze(c, c.target)", "any")),
    # 召唤
    (r"for each enemy minion, summon a (\d+)/(\d+)",
     lambda m: (f"summon_per_enemy(c, {m.group(1)}, {m.group(2)})", False)),
    (r"summon three (\d+)/(\d+) treants with charge",
     lambda m: (f"summon_chargers(c, {m.group(1)}, {m.group(2)}, 3)", False)),
    (r"summon a random (\d+)-cost minion",
     lambda m: (f"summon_random_cost(c, {m.group(1)})", False)),
    (r"summon a random beast companion", lambda m: ("summon_companion(c)", False)),
    (r"summon an awesome invention", lambda m: ("summon_token(c, 3, 3, 1, '发明')", False)),
    (r"summon a (\d+)/(\d+) (?:mechanical )?dragonling",
     lambda m: (f"summon_token(c, {m.group(1)}, {m.group(2)}, 1)", False)),
    (r"summon (a |two |three )?(\d+)/(\d+)",
     lambda m: (f"summon_token(c, {m.group(2)}, {m.group(3)}, {SUMMON_N[m.group(1) or '']})", False)),
    (r"equip a (\d+)/(\d+)", lambda m: (f"equip_weapon(c, {m.group(1)}, {m.group(2)})", False)),
]

DRAW_N = {"a": 1, "two": 2, "three": 3}
SUMMON_N = {"": 1, "a ": 1, "two ": 2, "three ": 3}


def _num(s: str) -> int:
    """'2' / 'a' / 'two' → 数字"""
    return int(s) if s.isdigit() else DRAW_N.get(s, 1)


def gen():
    print("拉取卡表 ...")
    en = fetch("enUS")
    zh = fetch("zhCN")
    zh_by_id = {c["id"]: c for c in zh}

    cards = [c for c in en if c.get("set") in SETS and c.get("collectible")]
    versions = " + ".join(n for s, n in RELEASES[:ENABLED])
    print(f"当前版本：{versions} → 卡池 {len(cards)} 张")

    lines = [f"""# 自动生成，请勿手改 —— 改了会被 gen_cards.py 覆盖
# 卡池版本：{versions}
# 三态标注：完整效果 / partial=True（部分效果）/ implemented=False（白板）
from engine import (register, damage, heal, summon, draw, buff, destroy, silence,
                    freeze, gain_armor, swap_stats, aoe, buff_neighbors, buff_all,
                    discard_random, add_to_hand, shuffle_into_deck, return_to_hand,
                    take_control, equip_weapon, gain_mana, random_minion, spell_damage_of,
                    summon_random_cost, add_random_to_hand, summon_token, buff_hero_atk,
                    buff_weapon, heal_full, set_health, double_health, atk_to_health,
                    draw_for_both, transform, destroy_weapon,
                    temp_buff, set_atk, double_atk, give_charge, give_windfury,
                    damage_random_enemy, damage_random, destroy_random_enemy, chance_draw,
                    buff_random_other, heal_random_damaged, steal_random_minion,
                    discard_hand, copy_from_foe_hand, copy_from_foe_deck, draw_until_even,
                    draw_per_damaged, destroy_all_other_minions, set_all_health, buff_race,
                    set_hero_hp, armor_as_damage, hero_atk_damage, destroy_if_atk,
                    take_control_if, silence_all_foe, give_stealth_all, destroy_enemy_secrets,
                    shadowflame, betrayal, brawl, buff_neighbors_sp, draw_filtered,
                    add_card_named, buff_per_hand, buff_per_board, combo_buff, damage_step,
                    aoe_range, draw_foe, temp_buff_all, buff_from_weapon, weapon_durability,
                    destroy_damaged_enemy, return_all_minions, summon_per_enemy,
                    summon_companion, track_draw, overload, burn_crystal, give_crystal,
                    become_copy, is_minion, weapon_gain_dura, summon_chargers,
                    cleave_enemies, explosive_shot, cone_of_cold, blade_flurry,
                    freeze_and_damage, destroy_if_race, hungry_crab, harrison,
                    holy_wrath, next_spell_discount, next_secret_free,
                    enemy_spells_free, shadow_madness, void_terror,
                    mind_control_tech, tinker, blessing_of_wisdom, ancestral_spirit,
                    corruption, alarm_o_bot, give_foe_tokens, etc_chord,
                    add_random_dream, jaraxxus,
                    ice_lance, cold_blood, eviscerate, perdition_blade, mortal_strike,
                    kill_command, mortal_coil, slam, bane_of_doom, demonfire,
                    upgrade_weapon, blood_knight, soul_of_the_forest, power_overwhelming,
                    flare, force_of_nature, commanding_shout, shadowform,
                    draw_cheap, shadowstep, track_draw3, hide_minions, headcrack)
"""]
    stats = {"full": 0, "partial": 0, "vanilla": 0}

    for c in cards:
        cid = c["id"]
        z = zh_by_id.get(cid, {})
        name = z.get("name") or c.get("name") or cid
        text = clean(c.get("text", ""))                       # 英文原文：用于解析
        zhtext = clean(z.get("text") or c.get("text") or "")  # 显示用：优先中文，没有就用英文
        cost = c.get("cost", 0)
        ctype = c.get("type", "MINION")
        mech = set(c.get("mechanics") or [])
        low = text.lower()

        kw = [f"name={name!r}", f"cost={cost}", f"type={ctype!r}", f"text={zhtext!r}",
              f"rarity={(c.get('rarity') or 'COMMON')!r}", f"en={c.get('name', cid)!r}"]
        if c.get("races"):
            kw.append(f"races={c['races']!r}")

        # 关键词（用官方 mechanics 字段，最可靠）
        for src, dst in (("TAUNT", "taunt"), ("CHARGE", "charge"), ("RUSH", "rush"),
                         ("DIVINE_SHIELD", "shield"), ("STEALTH", "stealth"),
                         ("WINDFURY", "windfury"), ("LIFESTEAL", "lifesteal"),
                         ("POISONOUS", "poisonous"), ("REBORN", "reborn")):
            if src in mech:
                kw.append(f"{dst}=True")
        # 法术伤害：JSON 里 58 张有 SPELLPOWER 机制却没给 spellPower 字段，必须从文本补
        sp = c.get("spellPower")
        if not sp and "SPELLPOWER" in mech:
            m_sp = re.search(r"spell damage \+(\d+)", low)
            sp = int(m_sp.group(1)) if m_sp else 1
        if sp:
            kw.append(f"spell_power={sp}")

        if ctype == "MINION":
            kw += [f"atk={c.get('attack', 0)}", f"hp={c.get('health', 0)}"]
        elif ctype == "WEAPON":
            # 武器在 hearthstonejson 里耐久放在 health 字段，durability 常年是 0
            dura = c.get("durability") or c.get("health") or 1
            kw += [f"atk={c.get('attack', 0)}", f"durability={dura}"]

        # ---- 拆出战吼段 / 亡语段（有的牌两段都有）----
        bc_text = dr_text = ""
        rest = text
        if "deathrattle:" in low:
            pos = low.index("deathrattle:")
            dr_text = text[pos + len("deathrattle:"):].strip()
            rest = text[:pos].strip()
        if "battlecry:" in rest.lower():
            pos = rest.lower().index("battlecry:")
            bc_text = rest[pos + len("battlecry:"):].strip()
            rest = rest[:pos].strip()

        mounted = False
        partial = False
        targeting = None
        tail = []            # 追加 kw（旗标 / 光环 / 触发 / 奥秘）

        # ---- 0.5) 跨句/带条件的整段效果：必须在拆战吼-亡语之前判断 ----
        # （丛林之魂的「亡语：召唤2/2树人」是给随从的，不是自己的亡语，先拆就拆坏了）
        sp_hit = parse_special(text)
        if sp_hit:
            bc_text = dr_text = ""
            rest = ""

        # ---- 0) 动态费用：先摘掉费用句，别影响后面的解析 ----
        cost_kw = []
        for pat, fn in COST_RULES:
            m_cost = re.search(pat, text, flags=re.I)
            if not m_cost:
                continue
            for k, v in fn(m_cost).items():
                cost_kw.append(f"{k}={v!r}")
            text = re.sub(pat, " ", text, flags=re.I)
            rest = re.sub(pat, " ", rest, flags=re.I)
            bc_text = re.sub(pat, " ", bc_text, flags=re.I)
            dr_text = re.sub(pat, " ", dr_text, flags=re.I)
        if cost_kw:
            low = text.lower()
            tail.extend(cost_kw)
            mounted = True

        # ---- 1) 纯标记 ----
        if c.get("overload"):                 # JSON 里有直接的过载数值，优先用它
            tail.append(f"overload={c['overload']!r}")
        scan = text
        for pat, fn in FLAG_RULES:
            for mm in re.finditer(pat, scan, re.I):
                for k, v in fn(mm).items():
                    tail.append(f"{k}={v!r}")
            scan = re.sub(pat, " ", scan, flags=re.I)

        # ---- 2) 奥秘 / 抉择 ----
        block = False        # 抉择解析失败 → 整张如实降级为白板
        choose_opts = None
        if "choose one" in low:
            choose_opts = parse_choose(text, zhtext, ctype == "MINION")
            rest = bc_text = dr_text = ""          # 抉择文本整段交给选项处理
            if choose_opts:
                mounted = True
                tg = next((t for _l, _c, t in choose_opts if t), None)
                if tg:
                    targeting = tg
            else:
                block = True
                tail = []
                mounted = False
        elif cid in SECRET_IDS:
            tail.append(f"secret={SECRET_IDS[cid]!r}")
            mounted = True
            rest = ""        # 奥秘文本全部由引擎钩子负责
            bc_text = dr_text = ""

        # ---- 3) 连击牌：整段包在 if c.combo 里 ----
        combo_only = low.startswith("combo:")
        if combo_only:
            bc_text = re.sub(r"^combo:\s*", "", bc_text or rest, flags=re.I)
            rest = ""            # 整段已经挂到战吼上，别再算成「有残留文本」

        # ---- 4) 效果挂载 ----
        def mount(slot, body, tgt):
            nonlocal mounted, targeting, partial
            if slot == "battlecry" and ctype == "WEAPON":
                slot = "effect"      # 武器的战吼在 play_card 里是由 effect 结算的
            kw.append(f"{slot}=lambda c: {body}")
            mounted = True
            if tgt:
                targeting = tgt
            return True

        if bc_text:
            r = parse_effect(bc_text)
            if r:
                code, tgt, complete = r
                if combo_only:
                    code = f"({code}) if c.combo else None"
                mount("battlecry", code, tgt)
                if not complete:
                    partial = True
        if dr_text:
            r = parse_effect(dr_text)
            if r:
                code, tgt, complete = r
                mount("deathrattle", code, tgt)
                if not complete:
                    partial = True
        if sp_hit and not mounted and not block:
            code, tgt, complete = sp_hit
            mount("battlecry" if ctype == "MINION" else "effect", code, tgt)
            if not complete:
                partial = True
        elif ctype in ("SPELL", "WEAPON") and not mounted and not block:
            r = parse_special(text) or parse_effect(text)
            if r:
                code, tgt, complete = r
                mount("effect", code, tgt)
                if not complete:
                    partial = True

        # ---- 5) 武器上的触发（真银圣剑 / 鹰角弓 / 公正之剑）----
        if ctype == "WEAPON" and not mounted and not block:
            trig = parse_trigger(text)
            if trig:
                event, guard, code = trig
                body = f"{code} if {guard} else None" if guard else code
                tail.append(f"triggers=[({event!r}, lambda c: {body})]")
                mounted = True
        if ctype == "WEAPON" and "after you summon a minion" in low and not mounted and not block:
            tail.append("triggers=[('summon', lambda c: "
                        "((buff(c, c.event_src, 1, 1), weapon_durability(c, 'own')) "
                        "if is_minion(c.event_src) else None))]")
            mounted = True

        # ---- 6) 光环 / 触发（随从）----
        if ctype == "MINION" and not mounted and not block:
            aura = parse_aura(text)
            if aura:
                for k, v in aura.items():
                    tail.append(f"{k}={v!r}")
                mounted = True
            else:
                trig = parse_trigger(text)
                if trig:
                    event, guard, code = trig
                    body = f"{code} if {guard} else None" if guard else code
                    tail.append(f"trigger=[({event!r}, lambda c: {body})]")
                    mounted = True

        # ---- 7) 剩余文本是否已被覆盖 ----
        # 只检查「战吼/亡语之外」的那部分（正常情况只剩关键词）。
        # 整段文本走 parse_effect 的牌，是否覆盖已由 complete 标志判定。
        outside = rest if (bc_text or dr_text) else ""
        leftover = substance(re.sub(r"overload:?\s*\(\d+\)", " ", outside, flags=re.I))
        if leftover:
            if mounted:
                partial = True
        # 只有旗标（纯过载 / 免疫 / 剧毒文本）也算已实现
        if not mounted and (tail or not text):
            mounted = True
        # 文本里只剩关键词（嘲讽/风怒/圣盾…）→ 属性已经落到字段上，属于完整实现
        if not mounted and not substance(re.sub(r"overload:?\s*\(\d+\)", " ", text, flags=re.I)):
            mounted = True
        if (mounted and PARTIAL_HINT.search(text) and not SHADOW_MADNESS.search(text)
                and c.get("name") not in FULL_TIMED):
            partial = True

        implemented = mounted
        if targeting:
            kw.append(f"targeting={targeting!r}")
        seen_keys = set()                    # 同名字段只留一份（旗标与光环可能重复给）
        uniq_tail = []
        for item in tail:
            k = item.split("=", 1)[0]
            if k in seen_keys:
                continue
            seen_keys.add(k)
            uniq_tail.append(item)
        kw.extend(uniq_tail)
        if choose_opts:                      # 抉择：两个选项各存一个 lambda，出牌时选一个执行
            kw.append("choose=[" + ", ".join(
                f"({lbl!r}, lambda c: {code}, {tgt!r})"
                for lbl, code, tgt in choose_opts) + "]")
        if partial:
            kw.append("partial=True")
            if os.environ.get("DBG"):
                print(f"PARTIAL {name} | 剩余: {leftover!r} | 全文: {text!r}")
        kw.append(f"implemented={implemented}")
        kw.append(f"cls={c.get('cardClass', 'NEUTRAL')!r}")

        if not implemented:
            stats["vanilla"] += 1
        elif partial:
            stats["partial"] += 1
        else:
            stats["full"] += 1
        lines.append(f"register({cid!r}, {', '.join(kw)})")

    open(OUT, "w", encoding="utf-8").write("\n".join(lines) + "\n")
    total = sum(stats.values())
    print(f"\n生成 {OUT}")
    print(f"  完整实现      : {stats['full']:3d} ({stats['full']/total*100:5.1f}%)")
    print(f"  部分实现      : {stats['partial']:3d} ({stats['partial']/total*100:5.1f}%)  ← 界面标「部分」")
    print(f"  白板（无效果）: {stats['vanilla']:3d} ({stats['vanilla']/total*100:5.1f}%)")
    print(f"  合计          : {total} 张")


if __name__ == "__main__":
    gen()
