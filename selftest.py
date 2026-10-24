"""Smoke test: random decks play each other, checking the engine and pool do not crash."""
import random, sys, collections
import engine
import cards  # noqa: F401  注册卡池

CARDS = engine.CARDS
PLAYABLE = [cid for cid, d in CARDS.items()
            if d.get("type") in ("MINION", "SPELL", "WEAPON") and d.get("cost", 0) >= 0]


def make_deck(rng, n=30, cls=None):
    pool = PLAYABLE
    if cls:
        sub = [c for c in pool if CARDS[c].get("cls") in (cls, "NEUTRAL")]
        if len(sub) > 20:
            pool = sub
    return [rng.choice(pool) for _ in range(n)]


def ai_turn(g: engine.Game):
    p = g.cur
    for _ in range(15):
        idxs = [i for i, cid in enumerate(p.hand)
                if CARDS.get(cid) and CARDS[cid].get("cost", 0) <= p.mana]
        if not idxs:
            break
        i = max(idxs, key=lambda i: CARDS[p.hand[i]]["cost"])
        tgt = None
        d = CARDS[p.hand[i]]
        if d.get("targeting"):
            foes = g.opp.board
            tgt = g.rng.choice(foes) if foes else g.opp
        if not g.play_card(p, i, tgt):
            break
    for m in list(p.board):
        while m.attacks_left > 0 and not m.frozen and m.atk > 0:
            foes = g.opp.board
            taunts = [x for x in foes if x.taunt and x.alive]
            pool = taunts or foes
            if pool:
                kill = [x for x in pool if x.hp <= m.atk]
                tgt = min(kill or pool, key=lambda x: x.hp)
                if not g.attack(m, tgt):
                    break
            else:
                if not g.attack(m, g.opp):
                    break
    g.end_turn()


def main(n=300):
    rng = random.Random(7)
    wins = collections.Counter()
    errs = collections.Counter()
    turns = []
    for _ in range(n):
        g = engine.Game(("A", "B"), (make_deck(rng), make_deck(rng)), seed=rng.randrange(1 << 30))
        g.start_turn()
        t = 0
        while not g.over and t < 300:
            ai_turn(g)
            t += 1
        turns.append(t)
        if g.over:
            wins[g.winner] += 1
        else:
            wins["timeout"] += 1
        for line in g.log:
            for tag in ("[card-error]", "[dr-error]", "[trigger-error]"):
                if tag in line:
                    errs[line.split(":")[0]] += 1
    print(f"跑了 {n} 局")
    print(f"  胜负      : {dict(wins)}")
    print(f"  平均回合  : {sum(turns)/len(turns):.1f}")
    print(f"  最长/最短 : {max(turns)} / {min(turns)}")
    if errs:
        print(f"  ⚠ 卡效果报错 {sum(errs.values())} 次:")
        for k, v in errs.most_common(10):
            print(f"      {k}: {v}")
    else:
        print("  卡效果报错: 0")


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 300)
