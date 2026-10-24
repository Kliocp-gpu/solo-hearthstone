# Web Hearthstone

**English** | [简体中文](README.zh-CN.md)

**v1.04** · a single-player Hearthstone you run locally · pure Python standard library + one HTML file · zero dependencies

Play a browser-based Hearthstone against an AI. No art, no animation — just the **card effects**.
All **382 cards** of the original 2014 set (Basic + Classic) are fully implemented:
every card text does what it says, with zero placeholder cards.

```
python3 serve.py        # then open http://localhost:8765
```

---

## What it is

A small project that turns Hearthstone rules into code: card text → rule tables → effect
primitives → turn resolution.

- **Card pool** — the full 2014 set (Basic + Classic), 382 cards, official Simplified Chinese names and text
- **Opponent** — built-in AI that calculates lethal, trades for board, and picks its own Choose One option
- **Deck building** — pick a class → click cards to add / one-click random deck → 30 cards → play
- **Verification** — 161 behavioral assertions + 1000-game self-test + card-text↔code audit

There are no images; a card face is text. All the effort went into
"does this card actually do what its text says?"

---

## Quick start

Requires Python 3.9+ (standard library only — nothing to install).

```bash
git clone https://github.com/Kliocp-gpu/web-hearthstone.git
cd web-hearthstone
python3 serve.py
```

Then open <http://localhost:8765>.

**macOS**: you can also double-click `启动游戏.command` (starts the server and opens the browser);
double-click `停止游戏.command` to stop it.

> If macOS blocks the `.command` file the first time ("unidentified developer"):
> right-click → Open → confirm once.
>
> If a local proxy prevents the page from loading: add `127.0.0.1` to the proxy bypass list,
> or use another port: `PORT=9000 python3 serve.py`.

---

## How to play

**Deck building**: pick a class → click cards in the pool to add → or hit "随机卡组" (random deck)
→ once you have 30 cards, hit "开始对战" (start match).

**In a match**:

- Click a card in hand to select it → targeted cards need a click on an enemy/friendly minion or hero;
  non-targeted cards are played by clicking an **empty spot on your own side of the board**
- **Choose One cards** (marked 「抉择」 in the corner) → a picker pops up; choose an option, then pick a target if needed
- Click your own minion → click an enemy minion or hero to attack
- **Click your own hero** → click the enemy to attack with your hero (needs a weapon; Druid shapeshift grants attack;
  a windfury weapon allows 2 hero attacks per turn)
- "英雄技能 (2费)" (hero power) → click a target to use it
- "结束回合" (end turn) → the AI plays out its turn

On screen: green ● = can attack this turn; `🔒N` = number of your secrets; `过载N` = mana crystals locked
by overload this turn; unaffordable cards are dimmed; a frozen hero shows `❄冻结`.

> The UI is in Chinese, since the card data is the official Simplified Chinese set.

---

## Card coverage

| State | Cards | Share | Meaning |
|---|---|---|---|
| Fully implemented | **382** | **100%** | every line of the card text is implemented |
| Partial | 0 | 0% | main effect works, conditions missing (marked 「部分」 on the card) |
| Vanilla | 0 | 0% | stats only, no effect (marked 「白板」 on the card) |

Implemented keywords: Taunt, Charge, Rush, Divine Shield, Stealth, Windfury, Lifesteal, Poisonous,
Reborn, Spell Damage, Freeze (including frozen heroes), Silence, Can't Attack, Elusive.

Implemented mechanics:

- **Battlecry / Deathrattle**, multi-clause effects ("Deal 3 damage. Gain 3 Armor." — both resolve)
- **Secrets** — 14 of them: Counterspell, Mirror Entity, Ice Barrier, Ice Block, Explosive Trap,
  Eye for an Eye, Noble Sacrifice, Repentance, Freezing Trap, Snipe, Snake Trap, Misdirection,
  Vaporize, Redemption
- **Overload** (actually locks crystals next turn), **Combo** (triggers only if you played a card first this turn)
- **Choose One** — 10 Druid cards; a picker on play, and the AI picks based on the board
- **Dynamic costs** — 9 cards: Mountain/Molten/Sea Giant and Dread Corsair are costed live from hand size,
  hero damage, board size and weapon attack; Sorcerer's Apprentice, Summoning Portal, Mana Wraith,
  Pint-Sized Summoner and Preparation modify other cards' costs
- **Tribal auras** — Dire Wolf Alpha, Murloc Warleader, Southsea Captain, Tundra Rhino (Charge for Beasts), Old Murk-Eye
- **Triggers** — turn start/end, after a spell, after summoning, on damage, on heal, friendly Beast died, Overload card played
- **Enrage** (Raging Worgen: +1 Attack and Windfury while damaged), **Attack = Health** (Lightspawn)
- **Weapons** — durability, on-attack triggers (Truesilver Champion heals), Gorehowl doesn't lose durability
  when hitting minions, Gladiator's Longbow is immune while attacking, Doomhammer grants 2 hero attacks per turn
- **Duration effects** — dies at end of turn (Power Overwhelming / Force of Nature treants), stealth until
  your next turn (Conceal), your minions can't drop below 1 Health this turn (Commanding Shout),
  temporary hand discounts (Far Sight / Shadowstep), return to hand next turn (Headcrack)
- **Hero level** — hero replacement (Lord Jaraxxus → 15 Health + Blood Fury + summon an Infernal),
  Shadowform changes the hero power (2 → 3 damage), frozen hero, Prophet Velen (double spell damage and healing),
  Auchenai Soulpriest (healing becomes damage)
- **Tokens** — Banana, Dream cards, Power Chord cards, Treants, Infernals, etc. — in the card pool but not collectible

---

## Project layout

| File | Purpose |
|---|---|
| `engine.py` | Rules engine: entities, event system, effect primitives, turn/combat/death resolution, secret hooks, cost calculation |
| `cards.py` | The card pool (**auto-generated — don't hand-edit**) — 382 cards |
| `gen_cards.py` | Card text → `cards.py` generator. `RELEASES` / `ENABLED` at the top select how many sets are included |
| `ai.py` | AI opponent: board evaluation + greedy play |
| `serve.py` | Local HTTP server + JSON API (`/api/start`, `/api/play`, `/api/attack`, …) |
| `static/index.html` | The UI, single file (inline CSS/JS), no framework |
| `selftest.py` | Smoke test: play N random-deck games, check for crashes and card-effect errors |
| `test_cards.py` | Behavioral tests: 161 assertions that key cards really do what their text says |
| `test_api.py` | HTTP-layer regression: 28 assertions on error codes, reasons, and state preservation |
| `audit.py` | Card-text ↔ code audit: if the text says "deal damage", the code must contain the corresponding call |

### Why cards are generated

The 382 cards are not hand-written. Each card is **declarative data**, with its effect assembled from
small primitives in the engine:

```python
register('VAN_CS2_029', name='火球术', cost=4, type='SPELL',
         text='造成6点伤害。', effect=lambda c: damage(c, c.target, 6),
         targeting='any', cls='MAGE')
```

`gen_cards.py` parses the English card text from HearthstoneJSON (Chinese text is used for display)
and translates it into the lambda above via rule tables. Sentences it can't parse are honestly
downgraded (marked partial or vanilla) instead of being given a wrong effect.

Rule tables (in `gen_cards.py`):

| Table | Handles |
|---|---|
| `SPECIAL_RULES` | Cross-sentence / conditional effects ("A; if …, do B instead") — matched **before** splitting battlecry-deathrattle |
| `PRIORITY_RULES` | Compound sentences ("Deal X damage and Freeze") — must come first, or a generic rule truncates them |
| `RULES` | Ordinary effect sentences, order = priority |
| `TRIGGER_RULES` | Trigger phrasing → `(event, guard, effect code)` |
| `AURA_RULES` | Auras / passives (tribal auras, enrage, Attack = Health) |
| `CHOOSE_OPT_RULES` | Subject-less fragments inside Choose One options ("+5 Attack") |
| `COST_RULES` | Dynamic-cost sentences → flags (the actual math lives in `Game.cost()`) |

---

## Verification

```bash
python3 test_cards.py       # 161/161 (verifies behavior card by card, not just counting)
python3 test_api.py         # 28/28 (HTTP layer: error codes, reasons, state untouched on failure)
python3 selftest.py 1000    # 1000 random games, 0 card-effect errors
python3 audit.py            # card-text ↔ code audit, 0 empty shells
```

`audit.py` exists because **counting cards lies**. Mid-project, the "47% implemented" figure included
87 cards that had stats but no actual effect code. Now, if the card text says "deal damage", the code
must contain the corresponding call, or the audit fails.

`test_api.py` exists because **correct rules don't mean a smooth UI**. Whether a failed play is
"you shouldn't click that" or "the program did nothing" is only observable at the HTTP layer —
it guarantees every failure carries an error code and a human-readable reason, and that a failed
action leaves the board completely untouched (no mana spent, no card lost, no selection cleared).

---

## Roadmap

Sets are added in release order, one at a time:

- [x] **2014 Classic** (Basic + Classic) — 382 cards, 100%
- [ ] Curse of Naxxramas (NAXX, 2014-07)
- [ ] Goblins vs Gnomes (GVG, 2014-12)
- [ ] …

Adding a set only requires editing the top of `gen_cards.py`:

```python
RELEASES = [
    ("VANILLA", "2014 原版（基础 + 经典）"),
    ("NAXX",    "纳克萨玛斯的诅咒"),      # uncomment
]
ENABLED = 2        # 1 → 2
```

Then `python3 gen_cards.py` → `python3 selftest.py 300`.
When you meet an unseen mechanic, add a rule-table entry and a primitive in `engine.py`.

---

## Legal

**You must own a copy of the game.** Hearthstone is a trademark of Blizzard Entertainment, Inc.
This is an **independent, non-commercial fan project**. It is not affiliated with, endorsed by,
or sponsored by Blizzard Entertainment.

- The **code** in this repository is released under the MIT License (see [LICENSE](LICENSE)).
  That license covers the code only — **not** Hearthstone, its card names, card texts,
  artwork, or any other Blizzard intellectual property.
- Card names and card texts come from the public [HearthstoneJSON](https://hearthstonejson.com/)
  dataset and are used only for a local, single-player, non-commercial reimplementation of the rules.
- **No official artwork, audio, or asset files** are included in this repository.
- Use it only for personal, offline play — not for any commercial purpose.
