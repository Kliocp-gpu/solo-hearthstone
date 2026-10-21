"""AI 对手：局面估值 + 贪心出牌。够笨，但够玩。

思路：
  1. 出牌：枚举所有打得起的牌，按「费用利用率 + 期望收益」贪心，能斩杀优先斩杀
  2. 攻击：优先换掉能白吃的敌方随从，否则打脸
"""

from engine import CARDS, Minion, is_minion


def _minion_value(m: Minion) -> float:
    v = m.atk * 1.0 + m.hp * 1.0
    if m.taunt:        v += 1.5
    if m.shield:       v += m.atk * 0.6 + m.hp * 0.4
    if m.lifesteal:    v += m.atk * 0.5
    if m.poisonous:    v += 3.0
    if m.stealth:      v += 1.5
    if m.windfury:     v += m.atk * 0.8
    if m.spell_power:  v += 1.0
    return v


def _board_value(p) -> float:
    return sum(_minion_value(m) for m in p.board)


def evaluate(g, me) -> float:
    """站在 me 视角的局面分"""
    foe = g.foe_of(me)
    score = 0.0
    score += _board_value(me) - _board_value(foe) * 1.05   # 略微偏向解场
    score += (me.hp + me.armor * 0.8) * 0.35
    score -= (foe.hp + foe.armor * 0.8) * 0.35
    score += len(me.hand) * 0.9
    score -= max(0, len(me.deck) - len(foe.deck)) * 0.02   # 疲劳压力
    if foe.hp <= 0:
        score += 999
    if me.hp <= 0:
        score -= 999
    return score


def _lethal(g, me) -> bool:
    """能否这回合打死对方：所有可攻击随从的攻击力之和 >= 对方血量（忽略嘲讽的粗略判断）"""
    foe = g.foe_of(me)
    if any(m.taunt and m.alive for m in foe.board):
        return False
    total = sum(m.atk for m in me.board
                if m.attacks_left > 0 and not m.frozen and m.can_attack_hero)
    return total >= foe.hp + foe.armor


def _choose_index(g, p, d):
    """抉择牌选哪个选项：按选项文字里的关键词粗略打分（够用就行）"""
    opts = d.get("choose") or []
    if not opts:
        return None
    foe = g.opp
    best, best_s = 0, -1e9
    for k, (label, _fn, _tgt) in enumerate(opts):
        s = 0.0
        if "召唤" in label:
            s += 4.0 if len(p.board) < 4 else 0.5
        if "抽" in label:
            s += 1.0 + max(0, 6 - len(p.hand)) * 0.5
        if "伤害" in label:
            s += (3.5 if foe.board else 0.8) + (0.8 if "所有" in label else 0.0)
        if "沉默" in label:
            s += 3.0 if any(m.taunt or m.spell_power for m in foe.board) else 0.5
        if "攻击力" in label or "生命值" in label or "+" in label:
            s += 1.6 if p.board else 0.3
        if "法力水晶" in label:
            s += 2.5 if p.max_mana <= 8 else 1.0
        if "嘲讽" in label:
            s += 1.0 if p.hp < 22 else 0.3
        if "恢复" in label:
            s += 2.5 if p.hp < 25 else 0.2
        if s > best_s:
            best, best_s = k, s
    return best


def _pick_target(g, p, t):
    """按目标类型挑一个目标（敌方/己方/不限）"""
    if not t:
        return None
    foe = g.opp
    if t.startswith("friendly"):
        if t == "friendly_any":
            return max(list(p.board) + [p], key=lambda x: getattr(x, "max_hp", 30) - x.hp)
        if not p.board:
            return p if t == "friendly" else None
        return max(p.board, key=_minion_value)
    if t == "beast":
        pool = [m for m in p.board if "BEAST" in m.races]
        return pool[0] if pool else None
    if foe.board:
        pool = [m for m in foe.board
                if not getattr(m, "elusive", False) and m.attackable]
        if pool:
            return max(pool, key=lambda m: (m.hp <= 4, _minion_value(m)))
    return foe


def ai_turn(g):
    p = g.cur
    rng = g.rng

    # ---- 1. 出牌：贪心，尽量花光法力 ----
    for _ in range(20):
        playable = [i for i, cid in enumerate(p.hand)
                    if CARDS.get(cid) and g.cost(p, cid) <= p.mana]
        if not playable:
            break
        # 优先打高费（法力利用率），斩杀牌优先
        i = max(playable, key=lambda i: g.cost(p, p.hand[i]))
        d = CARDS[p.hand[i]]
        choice = _choose_index(g, p, d)
        ttgt = d["choose"][choice][2] if (choice is not None and
                                          choice < len(d["choose"])) else d.get("targeting")
        tgt = _pick_target(g, p, ttgt)
        if not g.play_card(p, i, tgt, choice=choice):
            break
        if g.over:
            return

    # ---- 2. 英雄技能 ----
    if not g.over and not p.hero_power_used and p.mana >= 2:
        foe = g.opp
        use = False
        tgt = None
        if p.cls in ("WARRIOR", "DRUID"):
            use = True                                     # 加甲/变脸总是赚
        elif p.cls == "PRIEST":
            use = p.hp < 30 or any(m.hp < m.max_hp for m in p.board)
            if any(m.hp < m.max_hp for m in p.board):
                tgt = min((m for m in p.board if m.hp < m.max_hp),
                          key=lambda m: m.hp / max(1, m.max_hp))
        else:                                              # 伤害型：能补刀就用
            killable = [m for m in foe.board if m.alive and m.hp <= 1]
            use = bool(killable) or (foe.hp + foe.armor <= 1)
            tgt = max(killable, key=_minion_value) if killable else None
        if use:
            g.hero_power(p, tgt)
            if g.over:
                return

    # ---- 3. 攻击 ----
    lethal = _lethal(g, p)
    for m in list(p.board):
        while m.attacks_left > 0 and not m.frozen and m.atk > 0 and not g.over:
            foes = g.opp.board
            taunts = [x for x in foes if x.taunt and x.alive and x.attackable]
            pool = taunts or [x for x in foes if x.attackable]

            if lethal and not taunts:
                g.attack(m, g.opp)
                continue
            if pool:
                # 白吃：打得过且不亏太多
                killable = [x for x in pool if x.hp <= m.atk and m.hp > x.atk]
                if killable:
                    tgt = max(killable, key=_minion_value)
                else:
                    trade = [x for x in pool if x.hp <= m.atk]
                    tgt = max(trade, key=_minion_value) if trade else max(pool, key=_minion_value)
                if not g.attack(m, tgt):
                    break
            else:
                if not g.attack(m, g.opp):
                    break

    # ---- 4. 英雄攻击（有武器或德鲁伊变脸后；风怒武器可打两次）----
    max_hits = 2 if (p.weapon and p.weapon.get("windfury")) else 1
    while not g.over and p.attack > 0 and p.hero_attacks < max_hits:
        foes = g.opp.board
        taunts = [x for x in foes if x.taunt and x.alive]
        acted = False
        if not taunts and p.attack >= g.opp.hp + g.opp.armor:
            acted = g.hero_attack(p, g.opp)              # 斩杀
        else:
            pool = taunts or foes
            cand = [x for x in pool if x.alive and x.attackable and x.hp <= p.attack
                    and x.atk < p.hp + p.armor]          # 白吃且不致死
            if cand:
                acted = g.hero_attack(p, max(cand, key=_minion_value))
        if not acted:
            break

    if not g.over:
        g.end_turn()
