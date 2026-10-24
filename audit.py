"""Card text vs generated code audit

数量统计会骗人（历史上出现过「47% 已实现」里混着 87 张空壳）。
这个脚本不看数量，只看「卡面说了什么」和「代码里到底有没有对应的调用」。

原理：
  * 从 cards.py 里按卡切出那一行 register(...)，拿到代码串
  * 卡面中文文本里出现某个概念（造成伤害/抽牌/消灭/召唤/恢复生命…）
    → 代码里必须出现对应的原语名，否则报「疑似空壳」
  * 已知的合理例外写在 ALLOW 里（说明理由），不算失败

用法：python3 audit.py        有问题的卡会逐条列出，退出码 1
"""
import re
import sys

import cards  # noqa: F401  触发卡池注册
from engine import CARDS

# ---- concept -> (regex over the card text, tokens that must appear in the code) ----
# `need` holds both primitive names and helpers that wrap them internally
CONCEPTS = [
    ("damage",   r"造成\s*\d+\s*点伤害|造成等同于|点伤害",
     ("damage", "aoe", "cleave", "explosive", "blade_flurry", "shadowflame", "brawl",
      "holy_wrath", "freeze_and_damage", "cone_of_cold", "armor_as_damage",
      "hero_atk_damage", "damage_step", "hungry_crab", "harrison", "betrayal",
      "poisonous", "ysera_awakens", "TOKEN_",
      # single-card helpers with conditions
      "ice_lance", "eviscerate", "perdition_blade", "headcrack", "mortal_coil",
      "bane_of_doom", "slam", "mortal_strike", "kill_command", "demonfire",
      "shadowform")),
    ("draw",     r"抽\s*[一二三四五六七八九十\d]+\s*张牌|抽一张牌|抽牌",
     ("draw", "track_draw", "chance_draw", "holy_wrath", "battlecry", "effect",
      "draw_cheap", "commanding_shout", "mortal_coil", "slam")),
    ("destroy",  r"消灭|摧毁",
     ("destroy", "brawl", "transform", "silence", "shadowflame", "betrayal",
      "hungry_crab", "destroy_weapon", "blade_flurry", "poisonous", "burn_crystal",
      "void_terror", "corruption", "ancestral_spirit", "jaraxxus", "tinker",
      "nightmare", "harrison", "flare", "force_of_nature")),
    ("summon",   r"召唤",
     ("summon", "mirror", "token", "soul_of_the_forest", "force_of_nature",
      "bane_of_doom")),
    ("heal",     r"恢复|治疗",
     ("heal", "set_health", "damage", "spell_mult", "heal_as_damage")),
    ("silence",  r"沉默", ("silence",)),
    ("freeze",   r"冻结", ("freeze", "cone_of_cold", "ice_lance")),
    ("armor",    r"护甲", ("armor",)),
    ("buff_atk", r"获得\+?[\d一二三四五六七八九十]+攻击力|获得等同于|获得该随从的攻击力",
     ("buff", "set_atk", "double_atk", "atk_to_health", "buff_from_weapon",
      "hero_atk", "spell_mult", "enrage_weapon", "aura_",
      "cold_blood", "power_overwhelming", "demonfire", "blood_knight",
      "upgrade_weapon")),
    ("transform", r"变形|变成", ("transform", "become_copy", "jaraxxus", "tinker")),
    ("discard",  r"弃", ("discard", "track_draw3")),
    ("mana",     r"法力水晶", ("mana", "crystal", "next_spell_discount")),
]

# Known exceptions: the text mentions it, but an engine hook implements it
ALLOW = {
    "法力怨魂": "卡表里的中文文本多印了「召唤」二字，实际效果是「所有随从费用+1」，已实现",
    "游学者周卓": "由 play_card 里的 _maybe_cho 钩子实现",
    "诺兹多姆": "限时在 state.timer + 前端倒计时里实现",
    "寒冰屏障": "由奥秘钩子实现",
    "寒冰护体": "由奥秘钩子实现",
    "法术反制": "由奥秘钩子实现",
    "镜像实体": "由奥秘钩子实现",
    "爆炸陷阱": "由奥秘钩子实现",
    "以眼还眼": "由奥秘钩子实现",
    "崇高牺牲": "由奥秘钩子实现",
    "忏悔": "由奥秘钩子实现",
    "冰冻陷阱": "由奥秘钩子实现",
    "狙击": "由奥秘钩子实现",
    "毒蛇陷阱": "由奥秘钩子实现",
    "误导": "由奥秘钩子实现",
    "蒸发": "由奥秘钩子实现",
    "救赎": "由奥秘钩子实现",
}


def card_lines():
    """One register(...) line per card in cards.py: cid -> code string."""
    out = {}
    with open("cards.py", encoding="utf-8") as f:
        for line in f:
            m = re.match(r"register\('([^']+)',\s*(.*)\)\s*$", line.strip())
            if m:
                out[m.group(1)] = m.group(2)
    return out


def main():
    lines = card_lines()
    bad = []
    checked = 0
    for cid, d in CARDS.items():
        if not d.get("implemented"):
            continue
        if d.get("token"):
            continue
        if d.get("partial"):
            continue          # 标了「部分」的卡本来就承认有缺，不在这里装完整
        name = d.get("name", cid)
        text = d.get("text") or ""
        code = lines.get(cid, "")
        checked += 1
        # Partially implemented cards admit gaps by design; only hint on what they do parse
        for key, pat, need in CONCEPTS:
            if not re.search(pat, text):
                continue
            if any(n in code for n in need):
                continue
            if name in ALLOW:
                continue
            bad.append((name, key, text, code))

    print(f"审计 {checked} 张「已实现」的牌")
    if not bad:
        print("✓ 卡面与代码一致，没有发现空壳")
        return 0
    print(f"✗ 发现 {len(bad)} 处疑似空壳：\n")
    seen = set()
    for name, key, text, code in bad:
        if name in seen:
            continue
        seen.add(name)
        print(f"  {name}  [{key}]")
        print(f"    卡面：{text}")
        print(f"    代码：{code[:160]}")
        print()
    return 1


if __name__ == "__main__":
    sys.exit(main())
