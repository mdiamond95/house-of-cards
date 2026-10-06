# House of Cards — Story Game Design (rules 1.0)

Status: direction and the shared calendar approved by the director, 6 October 2026.
Supersedes docs/ENGINE_DESIGN.md where the two disagree, for scenarios played under
rules 1.0 only. Frozen games and their rules versions are untouched.

## 1. Why

Measured on The First Dominion (seed 1867, 150 seasons, 4,516 actions):

- 69% of actions are Invest, Cultivate influence, Correspond or Consolidate (rest).
  3% contest another house (Dispute, Cede/swap, Purchase, Challenge). One challenge was
  made in the whole game and it failed.
- Each season's action is an independent weighted draw. No house plans, so nothing is set
  up and paid off.
- By season 150, 58 houses act once each and the chronicle prints 47 lines of equal weight.
- On personal clocks, one season holds the Great War for one house and the Reciprocity
  Election for another. No event is shared.
- There are no standings, no chapters and no ending.

## 2. What the game becomes

A turn-based strategy game played by its characters and watched one turn at a time. The
director gives no input beyond advancing the turn and choosing whom to follow. Houses
pursue visible multi-turn schemes against each other on a shared calendar from 1867 to
1967; the engine tracks storylines; each turn is told as a dispatch with one headline.

## 3. The story layer (Phases A, B, E)

Architecture rule: the story layer is one implementation, in JavaScript, at web/story/. It
is a pure function of the game's record, runs in the browser and under node for tests, and
never feeds back into either engine. It is therefore outside the two-engine parity
contract. Anything a house's decisions depend on is engine state and belongs in §4, in
both engines.

### 3.1 Beats and story weight

A beat is one typed happening in a turn: kind, houses, riding, outcome, line. Each beat
gets an integer story weight. Starting values:

| Beat | Weight |
|---|---|
| House removed or extinct | 100 |
| Riding passes from one house to another (challenge, purchase, cession, absorption) | 80 |
| Partition; cadet house founded | 75 |
| Elevation granted | 60 |
| Disorderly succession | 60 |
| New quarrel (flashpoint, offence given) | 50 |
| Marriage alliance | 45 |
| Dispute won or reconciled | 45 |
| Crown founding | 40 |
| Clean succession | 30 |
| Response to a Major event | 30 |
| Compact | 25 |
| Expansion into unclaimed land | 20 |
| A failed attempt at any of the above | 10 |
| Correspondence opened | 5 |
| Invest, Cultivate influence, Consolidate (rest), Name heir | 0 |

Modifiers: +20 if a top-eight house is involved; double if the followed house is involved;
+15 for a first (first of its kind in the game, first riding in a province); +10 for a
callback (the same pair of houses shared a beat in the last ten turns); −15 if the same
kind headlined the previous turn. Pause threshold 60; quiet threshold 40.

### 3.2 The dispatch

One turn on screen is: a headline (the heaviest beat, with the map zoomed to where it
happened), up to three secondary beats, and a ledger line that counts the rest
("Elsewhere, fourteen houses tended their estates"). A turn with nothing at or above the
quiet threshold is a single quiet-turn line. The full record stays one tap away.

### 3.3 Standings, cast, following

A standings strip shows the top eight houses with movement since last turn. In Phase A
standing is provisional and story-layer only: 10 × holdings + 20 × rank index, computed
from beats. From Phase C it is the engine's prestige (§4.5). The top eight are the cast:
they get full coverage, and other houses appear when they touch the cast or headline on
their own weight. The director may follow one house; that changes weights, never the game.

### 3.4 Storylines (Phase B)

A storyline is a tracked thread: type, participants, turn opened, beats, state (rising,
climax, closed), outcome. Types and triggers:

- Rivalry: a quarrel opens between two houses. Closes on reconciliation, a riding
  changing hands, or one house's removal.
- Succession question: a holder reaches 60 with no heir, or a succession is disorderly.
  Closes when an heir of age stands or the house fails.
- Rise: a house enters the top eight. Closes when it reaches first or drops out.
- Decline: a top-eight house loses a riding or two places in standing. Closes on recovery
  or removal.
- Union: marriage or compact between two cast houses. Closes on partition, absorption or
  a falling-out.
- Frontier: first entry into a newly opened region. Closes when the region is half claimed.

Every beat is attached to the storylines its houses belong to. The dispatch names the
storyline a headline belongs to and how long it has run. Storylines are derived from the
record, so they exist for frozen games too.

### 3.5 Prose (Phase E)

Per-turn scenes come from deterministic templates keyed on storyline type, beat kind and
holder traits, with callbacks to earlier beats in the same storyline. Templates use only
facts in the record (hard rule 1). Claude writes one narrative per chapter and an epilogue
per cast house, through the existing Narrate block, fed storyline records rather than raw
season logs. No workflow calls a model.

## 4. Rules 1.0 (Phase C)

Each item is a named flag in rules/versions/1.0/features.json, false in every earlier
version, implemented in both engines, integers only.

### 4.1 Upkeep (`upkeep_phase`)
Income, influence drift and cohesion recovery happen automatically at the start of a
turn, scaled by holdings and wealth tier. Invest, Cultivate influence and Consolidate
(rest) leave the action table. A house's one action per turn is always a real move.

### 4.2 Schemes (`schemes`)
A house commits to a scheme: a multi-turn plan with a named target, preparation steps that
cost capital or influence, an abort condition and a resolution roll. Schemes are public
state. Starting set: Claim a riding, Buy out a neighbour, Break a rival, Seek a protector,
Dynastic match, Win elevation, Open the frontier, Secure the line. A house chooses by
integer utility from its situation, objectives and holder traits, with a seeded draw among
the top three. A house that is the target of a visible scheme may answer it.

### 4.3 Traits (`holder_traits`)
Each holder draws two traits at accession from a rules table (for example Cautious,
Grasping, Pious, Reformer, Dynast, Litigious). Traits shift scheme utilities and crisis
responses. An heir's traits are drawn when the heir is named and are public, so a
succession can be anticipated.

### 4.4 Contests (`contested_claims`)
A claim on a neighbour's riding resolves as 2d6 plus committed capital, influence and
allies on each side. The loser pays; the riding can change hands; a seat can be lost; a
house with no ridings falls. Quarrels are no longer a precondition for every contest.

### 4.5 Prestige (`prestige`)
An integer score per house from holdings, rank, influence, alliances and contests won.
It is the standings, it is what the game is scored on at the end, and houses read it: the
leader draws coalitions, and a falling house draws claims.

### 4.6 A smaller table (`founding_curve`)
Crown foundings are front-loaded so the board is set in the first quarter of the game and
rare afterwards. The late game is zero-sum between established houses and their cadets.

## 5. The shared calendar (Phase D)

Flag `world_calendar`. It replaces hard rule 5 and ENGINE_DESIGN §16 decision 4 for
scenarios played with the flag on, and for no other.

- One turn is one year. Turn 1 is 1867 and turn 100 is 1966. The game ends with the
  Centennial reckoning of 1 July 1967: final prestige standings and an epilogue per cast
  house.
- Five chapters, each closing with a standings interstitial and a chapter narrative:
  I Confederation 1867–1885; II Rails and Wheat 1886–1913; III The Great War 1914–1929;
  IV Depression and War 1930–1945; V The Centennial Road 1946–1966.
- Events fire for every house in the same turn, by world year. The deck is extended to
  1966.
- Major events are crises. Each cast house takes a side according to its tag and its
  holder's traits. Houses on the same side warm to each other; opposed houses gain
  friction; the outcome moves the climate. One climate ledger, not one per band.
- The atlas is read at the world year. A riding is in play for Crown grants and expansion
  only while riding_jurisdictions.csv gives its sovereign as Canada in that year. Each
  accession or extension is a world event that opens land. This reads an existing closed
  table in a new way under a new flag; it does not change the table.
- Personal clocks survive as reign years, for display only.
- The game is a new scenario under rules 1.0. Working name `centennial`; the director may
  rename it. The Dominion is frozen when that scenario begins.

## 6. Story targets (replace ENGINE_DESIGN §17 for rules 1.0)

Initial targets across ten seeds, 100 turns, to be tuned and recorded in rules/CHANGELOG.md:

- At least 30% of actions are aimed at another named house.
- After turn 20, a riding passes between houses at least once every three turns on average.
- The prestige lead changes at least four times; no house leads for more than 50 turns.
- In every chapter after the first, at least one house that began it in the top eight
  ends it outside the top eight or removed.
- At least 70% of turns have a headline at or above the pause threshold; never more than
  three quiet turns in a row after turn 10.
- At least 60% of schemes reach resolution; median scheme length is three to six turns.
- 20 to 40 houses are active at turn 100; at least 85% of in-play ridings are claimed by
  turn 60.
- At least eight storylines of five or more beats per game, each closed with an outcome.

## 7. Phases

| Phase | Scope | Engine change | Gate |
|---|---|---|---|
| A | Beats, story weight, dispatch, standings, follow, Replay page | None | First Dominion replays as dispatches; headline mix within §3.1 limits |
| B | Storylines derived from the record; dispatch organised by them | None | Every First Dominion headline after turn 20 belongs to a storyline |
| C | Rules 1.0 flags §4.1–4.6, both engines | Yes | Cross-check byte-identical; §6 targets on a personal-clock trial |
| D | `world_calendar`, chapters, crises, ending; new scenario begins | Yes | §6 targets across ten seeds; a full game ends in 1967 |
| E | Scene templates, chapter narration, epilogues | None | A full game reads start to finish from the site |
