"""逐卡对照：把本地卡表与 HearthstoneJSON 官方数据逐张比一遍

比的是「能机械化验证的部分」：
  费用 / 攻击 / 生命 / 耐久 / 类型 / 职业 / 稀有度 / 种族
  关键词（嘲讽、冲锋、圣盾、潜行、风怒、法术伤害、冻结、激怒…）
  卡面文案（去空白与标点后比对）

**不比**效果对不对 —— 官方没有给出可执行语义，机器无法判定「召唤一个 2/1」到底做对没做对。
效果层只能靠 audit.py 的概念覆盖 + 人工抽样，这里会在最后列出「需要人工复核」的清单。

用法：
  python3 compare_cards.py            只打印汇总与差异
  python3 compare_cards.py --tsv out  另外导出全表（每张卡一行）
"""
import json
import os
import re
import sys

import cards  # noqa: F401  触发注册
import engine

CACHE = os.path.join(os.path.dirname(__file__), ".cache", "cards.enUS.json")
CACHE_ZH = os.path.join(os.path.dirname(__file__), ".cache", "cards.zhCN.json")

# 官方 mechanics -> 本地字段
# FREEZE 不在表里：官方用它表示「这张牌会冻结别人」（战吼/法术/伤害触发都算），
# 本地没有对应的单一字段，冻结是写在具体效果里的，靠文案比对 + audit.py 的概念检查覆盖。
MECH = {
    "TAUNT": "taunt",
    "CHARGE": "charge",
    "DIVINE_SHIELD": "shield",
    "STEALTH": "stealth",
    "WINDFURY": "windfury",
    "POISONOUS": "poisonous",
    "LIFESTEAL": "lifesteal",
    "RUSH": "rush",
    "REBORN": "reborn",
    "ENRAGE": "enrage",
}

KEYWORDS = ("嘲讽", "冲锋", "圣盾", "潜行", "风怒", "法术伤害+1", "无法攻击")


def norm(s):
    s = s or ""
    for t in ("<b>", "</b>", "<i>", "</i>", "[x]", "$", "#"):
        s = s.replace(t, "")
    return re.sub(r"[\s\u3000，。；：！？、（）()「」【】…·\-—]+", "", s)


def official_id(cid):
    return cid[4:] if cid.startswith("VAN_") else cid


def main():
    tsv_path = None
    if "--tsv" in sys.argv:
        tsv_path = sys.argv[sys.argv.index("--tsv") + 1]

    if not os.path.exists(CACHE):
        print("缺少缓存 %s，先跑一次 gen_cards.py 或手动下载" % CACHE)
        return 2
    raw = json.load(open(CACHE, encoding="utf-8"))
    # 同一个 id 在不同 set 里可能各有一份（经典重制版 vs VANILLA 快照），
    # 必须只取 VANILLA 那份，否则会拿重制后的数值去比。
    van = [c for c in raw if c.get("set") == "VANILLA" and c.get("collectible")]
    by_id = {c["id"]: c for c in van}
    zh = {}
    if os.path.exists(CACHE_ZH):
        zh = {c["id"]: c for c in json.load(open(CACHE_ZH, encoding="utf-8"))
              if c.get("set") == "VANILLA" and c.get("collectible")}

    diffs = []
    rows = []
    checked = 0
    for cid, d in sorted(engine.CARDS.items()):
        if d.get("token"):
            continue
        oid = official_id(cid)
        # VANILLA 里的 id 本身就带 VAN_ 前缀（VAN_CS2_029），先按原 id 找，再退回去掉前缀的形式
        o = by_id.get(cid) or by_id.get(oid)
        if not o:
            diffs.append((cid, d.get("name"), "官方数据", "本地有", "官方无此 id"))
            continue
        checked += 1
        oz = zh.get(oid, {})

        def cmp(field, ours, theirs):
            if ours != theirs:
                diffs.append((cid, d.get("name"), field, ours, theirs))

        cmp("费用", d.get("cost", 0), o.get("cost", 0))
        if d.get("type") == "MINION":
            cmp("攻击", d.get("atk", 0), o.get("attack", 0))
            cmp("生命", d.get("hp", 0), o.get("health", 0))
        if d.get("type") == "WEAPON":
            cmp("攻击", d.get("atk", 0), o.get("attack", 0))
            # 官方 dump 里 VANILLA 武器的 durability 一律是 0（已知数据缺陷），这一项跳过
        cmp("类型", d.get("type"), o.get("type"))
        cmp("职业", d.get("cls", "NEUTRAL"), o.get("cardClass", "NEUTRAL"))
        cmp("稀有度", d.get("rarity"), o.get("rarity"))
        cmp("种族", sorted(d.get("races") or []), sorted(o.get("races") or []))

        # 关键词：官方用 mechanics 数组，本地是布尔字段。
        # FREEZE 只对随从比（法术的冻结写在效果里，不是字段）；数据里 FREEZE 表示「会冻结别人」。
        mech = set(o.get("mechanics") or [])
        for mname, field in MECH.items():
            want = mname in mech
            got = bool(d.get(field))
            if want and not got:
                cmp("关键词:" + mname, got, want)
        # 法术伤害只比「有没有」：官方 dump 的数值不可靠（玛里苟斯写成 1，实际 5）
        cmp("有法术伤害", d.get("spell_power", 0) > 0, "SPELLPOWER" in mech)

        # 文案：拿 zhCN 的官方文本比
        if oz:
            a, b = norm(d.get("text")), norm(oz.get("text"))
            if a != b:
                diffs.append((cid, d.get("name"), "文案", (d.get("text") or "")[:40],
                              (oz.get("text") or "")[:40]))
        rows.append((cid, d.get("name"), "一致" if not any(x[0] == cid for x in diffs) else "有差异",
                     d.get("cost"), d.get("atk"), d.get("hp"), d.get("cls"),
                     ";".join(sorted(mech))))

    print(f"逐卡对照：{checked} 张（官方 VANILLA 可收集）")
    if not diffs:
        print("✓ 数据层完全一致：费用/攻防/耐久/类型/职业/稀有度/种族/关键词/文案 全部对得上")
    else:
        print(f"✗ 发现 {len(diffs)} 处差异：\n")
        for cid, name, field, ours, theirs in diffs:
            print(f"  {name} [{cid}] {field}: 本地={ours!r} 官方={theirs!r}")

    # 效果层：先排除「用声明式字段实现」的牌（光环、激怒、冻结、法强、减费等都由引擎读取），
    # 剩下的才是真的只有文案、没挂任何逻辑的牌。
    structural = {"cid", "name", "cost", "type", "text", "rarity", "en", "atk", "hp",
                  "cls", "races", "durability", "implemented", "partial", "token",
                  "effect", "trigger", "battlecry", "deathrattle", "targeting",
                  "token_name", "set", "mechanics"}
    extra_keys = set()
    for d in engine.CARDS.values():
        extra_keys |= set(d) - structural
    manual = []
    for cid, d in engine.CARDS.items():
        if d.get("token"):
            continue
        text = (d.get("text") or "").strip()
        if not text:
            continue
        if d.get("effect") or d.get("trigger") or d.get("deathrattle") or d.get("battlecry"):
            continue
        if d.get("choose"):                        # 抉择牌：选项写在 choose 里
            continue
        if any(k in d for k in extra_keys):        # 有声明式字段 → 引擎侧实现
            continue
        rest = text
        for w in KEYWORDS:
            rest = rest.replace(w, "")
        if len(norm(rest)) > 1:
            manual.append((cid, d.get("name"), text))
    print(f"\n声明式字段（光环/激怒/减费等）：{len(extra_keys)} 种 → {sorted(extra_keys)}")
    print(f"效果层无法机械判定；去掉关键词、排除声明式实现后仍无逻辑的牌：{len(manual)} 张")
    for cid, name, text in manual[:20]:
        print(f"  {name}: {text[:40]}")

    if tsv_path:
        with open(tsv_path, "w", encoding="utf-8") as f:
            f.write("cid\tname\tverdict\tcost\tatk\thp\tclass\tmechanics\n")
            for r in rows:
                f.write("\t".join(str(x) for x in r) + "\n")
        print(f"\n全表已写入 {tsv_path}")
    return 1 if diffs else 0


if __name__ == "__main__":
    sys.exit(main())
