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

**Phase A note, 6 October 2026.** Built as `web/story/weights.json`, tuned against The
First Dominion (scenario `new`, 150 seasons, following no one). The starting values above
met every limit on the first run and are the final numbers, unchanged. Alongside them:

- A modifier applies only to a beat whose base weight is above zero, so the four
  bookkeeping actions never headline. Top eight is measured at the start of the turn; a
  first is spent by the first beat that has it, and counts once even when it is both a
  first kind and a first province; the follow multiplier applies after the additions.
- Secondary threshold 20, at most three secondaries; cast size 8; standing 10 per riding
  and 20 per rank index.
- Four kinds the record holds that the table does not name: a riding returned to the
  Crown 35; an endowment 15; a response to a Minor or Significant era event 5; anything
  untyped 0 (none in The First Dominion).

Headlines over the 150 seasons: 144, with 6 quiet seasons, and 90 at or above the pause
threshold. By kind: quarrel 27 (18.8%), riding passes 26 (18.1%), response to a Major
event 14 (9.7%), expansion 11 (7.6%), marriage 11 (7.6%), dispute reconciled 9 (6.3%),
clean succession 8 (5.6%), elevation 8 (5.6%), compact 7 (4.9%), dispute won 6 (4.2%),
disorderly succession 5 (3.5%), Crown founding 4 (2.8%), partition 4 (2.8%), house
removed 2 (1.4%), failed attempt 1 (0.7%), endowment 1 (0.7%). The largest kind supplies
18.8% of headlines; no bookkeeping action headlines. `node tests/js/story_report.mjs
<site>/data/beats` reproduces these figures.

**Phase B note, 6 October 2026.** The four added kinds are approved as they stand.
Response to a Major event is now 15. At most one era response (Major or otherwise)
appears in a dispatch, and one headlines only when nothing else reaches the quiet
threshold. The callback modifier is gone, replaced by weight by position (§3.4 note).
Every other number above is unchanged.

One act is one beat. The story layer (`web/story/beats.js` `mergeActs`) folds these
pairs of events, which the engine writes for a single act, into one beat. That beat
carries both facts and is told in one sentence naming every party:

- a riding passing by cession, and the grievance it settles (31 in The First Dominion);
- a partition, and the clean succession of the parent that caused it (8);
- a disorderly succession, the riding it loses to the Crown and the neighbour it falls
  out with (12);
- a succession, and the removal of the same house it brings on (none);
- a contested expansion: the grievance, with the winner's expansion or the loser's
  failed Expand (none).

A house is named by its full style at its first mention in a dispatch, and by its
designation after that. Every line ends with a period.

Headlines over the 150 seasons: 145, with 5 quiet seasons. By kind:

| Kind | Headlines | Share |
|---|---|---|
| Expansion | 30 | 20.7% |
| Riding passes | 28 | 19.3% |
| Quarrel | 18 | 12.4% |
| Crown founding | 15 | 10.3% |
| Dispute reconciled | 12 | 8.3% |
| Dispute won | 9 | 6.2% |
| Elevation | 8 | 5.5% |
| Marriage | 5 | 3.4% |
| Clean succession | 5 | 3.4% |
| Disorderly succession | 5 | 3.4% |
| Compact | 3 | 2.1% |
| Partition | 3 | 2.1% |
| House removed | 2 | 1.4% |
| Correspondence | 1 | 0.7% |
| Response to a Major event | 1 | 0.7% |

The largest kind supplies 20.7% of headlines, and no bookkeeping action headlines.
125 of the 150 dispatches would pause Auto, either at the pause threshold or on a
cast storyline opening, reaching its climax or closing.

**Phase C1 note, 6 October 2026.** Clean succession is now 15 and marriage 35. Frontier
beats lost their escalation bonus (§3.4 note), which let routine successions and
marriages outside the cast take headlines that belong to no storyline; these two numbers
put the storyline share back above 85%. Rules 1.0's records add three kinds:

| Kind | Weight | What it is |
|---|---|---|
| heir_wanted | 25 | a holder turning sixty with no heir named |
| heir_of_age | 20 | an heir coming of age |
| bide | 0 | a house with no legal action |

Automatic letters type as correspondence.

Auto now pauses only when one of these happens:

- a storyline of at least four beats closes, involving a house that was in the cast at
  some point while it ran, or the followed house;
- a house is removed;
- a riding passes between two houses that are in the cast before or after the turn;
- the followed house is in a headline at or above the pause threshold.

That is 24 of The First Dominion's 150 seasons (16%). Headlines over the 150 seasons:
138, with 12 quiet. By kind:

| Kind | Headlines | Share |
|---|---|---|
| Riding passes | 28 | 20.3% |
| Expansion | 24 | 17.4% |
| Quarrel | 18 | 13.0% |
| Dispute reconciled | 12 | 8.7% |
| Crown founding | 11 | 8.0% |
| Dispute won | 9 | 6.5% |
| Elevation | 8 | 5.8% |
| Compact | 7 | 5.1% |
| Disorderly succession | 6 | 4.3% |
| Marriage | 3 | 2.2% |
| Partition | 3 | 2.2% |
| Failed attempt | 2 | 1.4% |
| House removed | 2 | 1.4% |
| Five other kinds | 1 each | 0.7% each |

The five kinds with one headline each are correspondence, endowment, response to a Major
event, riding lost and clean succession. The largest kind supplies 20.3% of headlines,
and no bookkeeping action headlines.

**Phase C2 note, 6 October 2026.** Rules 1.0's schemes and contests add ten kinds:

| Kind | Weight | What it is |
|---|---|---|
| scheme_begun | 40 | a house begins a public scheme |
| scheme_answered | 45 | a house answers a claim against it |
| scheme_abandoned | 10 | a scheme given up |
| scheme_step | 0 | a preparation step (ledger-only) |
| scheme_resolved | 0 | a scheme's end, folded into the act that ended it |
| ally_joins | 25 | an ally stands with a party to a contest |
| ally_declines | 15 | an ally refuses |
| contest_won | 90 | a claim carried, the riding taken (or a rout) |
| contest_lost | 90 | a claim held off |
| fallen | 110 | a house with no riding left, fallen to the house that took its seat |

A scheme's resolution folds into the act that resolved it: the beat with the same scheme
id, else that house's act that turn. A claim's contest, its rout and the defender's fall
are one act. A headline that resolves a scheme ends "The scheme (…) ran N seasons." A
claim won between two houses of the cast pauses Auto, as a riding passing between them
does. On ten seeds of the draft at 100 turns, 95% of turns headline at or above the pause
threshold, and rivalries supply 61% of headlines, against 36% under 0.9.

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

**Phase B note, 6 October 2026.** Built as `web/story/storylines.js`, derived from typed
beats alone and tuned against The First Dominion (150 seasons, following no one).

The final numbers, in `weights.json` under `storylines`:

- No bonus for the beat that opens a storyline.
- An escalating beat gets +10 for each earlier beat in its storyline, to a maximum of +30.
- The closing beat gets +25.
- A quarrel that opens a rivalry between two houses outside the cast weighs 30.
- A storyline with no beat for 15 turns closes as "lapsed".
- A storyline is at climax from its fourth beat.
- A frontier closes when half its province is claimed.
- Afoot shows up to six storylines, ranked by their weight over the last 10 turns.

The rules as built:

- Only storyline beats count. Bookkeeping, letters and era responses never open,
  escalate or close a storyline.
- A succession question opens only on a disorderly succession. The record's beats do not
  carry a holder's age, so "a holder reaches 60 with no heir" cannot be derived from them.
  The question closes when an heir is named or succeeds cleanly, or when the house fails.
- A rise opens only below first place.
- A decline closes when the house's standing gets back to its score before the decline.
- A house's removal closes every storyline it is a principal of. A frontier belongs to its
  province rather than to any one settler, so the removed house only leaves it, and the
  frontier closes only when no house is left in it.

The First Dominion has 265 storylines: 135 rivalries, 48 rises, 43 declines, 17
succession questions, 13 frontiers and 9 unions. 237 closed, every one with an outcome:

| Type | Outcomes |
|---|---|
| Rivalry | reconciled 76, settled by cession 31, a riding changed hands 1, a house removed 1, lapsed 8 |
| Rise | fell back 29, reached first 4, lapsed 11 |
| Decline | recovered 32, lapsed 6 |
| Succession question | an heir named 14, lapsed 2 |
| Frontier | half claimed 6, lapsed 7 |
| Union | partition 2, lapsed 7 |

28 were still open at season 150: 18 rivalries, 5 declines, 4 rises and 1 succession
question.

Against the Phase B gates (§7):

- After season 20, 86.5% of headlines belong to a storyline, and 17.4% open one.
- 17 storylines have five or more beats.
- 17.2% of closed storylines lapsed.

The five longest are:

| Storyline | Beats | Seasons | Outcome |
|---|---|---|---|
| The Ontario frontier | 65 | 1–84 | half claimed |
| The Quebec frontier | 42 | 8–72 | half claimed |
| The British Columbia frontier | 15 | 14–103 | lapsed |
| The Alberta frontier | 12 | 71–145 | lapsed |
| The decline of Bellechasse | 10 | 105–145 | recovered |

**Phase C1 note, 6 October 2026.** These Phase B rules are approved as built:

- a removed house leaves a frontier without closing it;
- for a game without rules 1.0's succession watch, a succession question opens only on a
  disorderly succession.

Three changes:

- **Frontiers.** A frontier beat takes no escalation bonus. A riding passing between
  houses is never a frontier beat; only unclaimed land counts. A frontier names a headline
  only when the headline belongs to no other storyline.
- **The succession watch.** For a game whose record carries it, a succession question also
  opens on a holder turning sixty with no heir. The question then closes when an heir comes
  of age; naming one is a step towards that, not the answer.
- **Prestige.** Where the record carries prestige, the standings are the engine's prestige.

On The First Dominion the Phase B gates still hold:

- After season 20, 86.5% of headlines belong to a storyline, and 21.8% open one.
- 17 storylines have five or more beats.
- 17.2% of closed storylines lapsed.

The storyline counts by type and outcome, and the five longest, are as in the Phase B
note, except that the Ontario frontier has 64 beats and the Quebec frontier 40.

**Phase C2 note, 6 October 2026.** A claim (Claim a riding, or a Counter-claim given in
answer) belongs to the two houses' rivalry and opens one if none runs. Every scheme
event, answer and ally between them escalates it; preparation steps do not. A rivalry
now also closes when:

- a contest is decided between them ("won in a contest", "held in a contest");
- the weaker side cedes the claimed riding ("ceded under a claim");
- one of them falls.

**Plans afoot** sits above Afoot on the replay and play pages, for a game whose record
carries schemes. It lists every public scheme of a cast or followed house, with its target
and turns remaining.

### 3.5 Prose (Phase E)

Per-turn scenes come from deterministic templates keyed on storyline type, beat kind and
holder traits, with callbacks to earlier beats in the same storyline. Templates use only
facts in the record (hard rule 1). Claude writes one narrative per chapter and an epilogue
per cast house, through the existing Narrate block, fed storyline records rather than raw
season logs. No workflow calls a model.

### 3.6 The map view (Phase V)

The director's review of the preview (7 October 2026): still not engaging, and a visual
problem. The game is spatial and the Replay was a column of text with a small map that
visited an event and snapped back. Phase V makes the map the page. It is presentation
only: no engine, rules or record change, and the dispatch, weights and storylines are
those of §3.1–§3.4.

Layout (`replay.html`; portrait phone first, 390 × 844, and an iPad either way round):

- The map fills the viewport (100dvh).
- Over it at the top: the year, the chapter and a thin turn scrubber; a tag saying what
  the game is (an archive, or the draft preview, not a game of record); and the chips.
- At the bottom: Next year, Auto with its speeds (1×, 2×, 4×) and, in free mode, Recentre.
- The standings are a collapsed strip (the top three's colours and the leader) that opens
  to a single-column list naming each house "Surname of Place" (its peerage less its rank
  word), with the follow menu. This is how a reader tells Robinson of Hamilton from a
  house named Hamilton.
- The dispatch, Plans afoot, Afoot and the full record are in a drawer, closed by
  default; a count on its button says how many beats the map left off.
- The site's links are behind a menu button.
- The text Replay stays, at `replay-text.html`, linked from the nav as "Replay (text)".

The stage:

- The inline SVG of 343 ridings, as before, with no new dependency.
- One finger pans, two pinch, a double tap zooms in two-fold; on a desktop the wheel zooms
  and the mouse drags. The view is kept within limits: never narrower than 3 map units
  (a downtown riding fills the screen), never wider than the whole map with a margin, and
  its centre never off the map.
- During a gesture or a flight the drawn map moves by a CSS transform, and the SVG's
  viewBox is set when the movement ends.
- Borders and outlines use a non-scaling stroke. Marks, lines and labels are drawn in
  screen pixels, so all of them keep their size at every zoom.

Geometry. The site's inline map has whole-number coordinates on a 1,000-unit-wide map, so
a city's ridings snap to a grid of about five-kilometre squares; Toronto spans six units.
Its coarser topology also folds the island of Montreal. The map view therefore draws the
coarse map for its first paint and fetches `data/map-detail.json` (the fuller simplified
geometry at one decimal, in the same coordinates) the first time the camera comes closer
than 220 units across. Page weight of the preview's Replay, measured on export (raw,
then gzipped as a server sends it):

| | Before | After |
|---|---|---|
| Page, script and stylesheets | 357 KB (102 KB) | 400 KB (114 KB) |
| Story modules | 119 KB (39 KB) | 149 KB (50 KB) |
| Seat history and jurisdictions (`atlas.json`) | none | 34 KB (2 KB) |
| The first chunk of beats and the index, unchanged | 510 KB (57 KB) | 510 KB (57 KB) |
| Fuller map, on the first close zoom | none | 1,400 KB (401 KB) |

On first load the page grows from about 198 KB to 223 KB gzipped. Its first close zoom,
which follow mode reaches on most headlines, adds 401 KB.

The camera (`web/story/camera.js`) has two modes:

- **Follow**, the default. Each year it flies to frame the headline's ground in the part
  of the screen its card leaves free (below the ground on an upright screen, beside it
  on a wide one), and stays there. It never snaps back to a home view: a year with
  nothing to frame leaves it where it is. A single riding is framed with at least 60 map
  units of its surroundings.
- **Free**, after any gesture. The camera does not move until Recentre, which returns to
  follow mode and the latest framing. Auto respects both modes.

Where an event is (`web/story/marks.js`, one pure function tested under node). A
dispatch and the game state go in; marks come out. Each beat's ground is:

1. the ridings it names;
2. else its scheme's target;
3. else the seats of its houses.

A house's seat is its principal riding (hard rule 4), from a seat history the exporter
ships in `data/beats/atlas.json`: for an engine-played game, the riding held with the
lowest holding id, since the engine appends holdings and never reorders them. A beat
with no place (it names no house and no riding, as the reckoning does) is a banner, not
a mark; the camera then frames the year's other marks.

The marks. A small vocabulary, drawn in SVG with a glyph and a one-word label, so none
relies on colour alone:

| Mark | Drawn as |
|---|---|
| Transfer | A riding changing hands: its fill moves from the old colour to the new, outlined, with a ⇄ (or +, for unclaimed land) badge |
| Claim | A claim or contest: the target riding outlined and pulsing, a dashed arrow from the claimant's seat, and on resolution "taken" (✓) or "held" (shield). A defence (Fortify) draws the threat from the claimant to the defended riding |
| Scheme | A scheme begun or given up: an arrow from the seat to its target, labelled by scheme ("frontier", "courtship", "buy-out") |
| Intent | Every public scheme of the cast and the followed house with a target: a faint dotted arrow from seat to target, before it resolves |
| Seat | At the seat: founded (★), succession or an heir (↻), elevated (crown), a fall (✕), a failure (⊘) |
| Bond | A match, compact or peace: a solid gold line between the two seats |
| Strife | A quarrel or dispute: a dashed red line between the two seats |
| Crisis | Every standing house's seat marked by camp: lead ▲, resist ▼, aside ○; the camera takes the whole table |
| Chip | An event still running ("The Great War, year 3 of 5"), and "a quiet year" |
| Closed land | Land not under Canada in the year shown, hatched; opened in its accession year, with the accession as the event |

The cap:

- Each year shows the headline and at most five other marks, by story weight; the rest
  are a count that opens the drawer. One crisis's camps are drawn a year.
- A year with no beat above the quiet threshold shows no marks and no scheme arrows,
  only its "a quiet year" chip.
- Following a house outlines its ridings.
- Badges never sit on one another: each, most important first, takes the nearest free
  spot and keeps a leader line to its place, and a label is drawn only where it fits.

Cards:

- The headline opens as a card attached to its mark, placed so it does not cover it: the
  kicker, the sentence and the "previously" line.
- Tapping any mark opens its own card, the beat told on its own.
- Tapping a riding gives its holder, rank, whether it is the seat, and its jurisdiction
  that year (for a game without a calendar, its province).
- One card at a time; a tap on the map closes it.
- Chapter closes and the reckoning are full-screen cards over the map, and Auto pauses on
  them as before.

Checks: node tests for marks (every type, the ground order, the cap, one crisis a year,
a quiet year, the intent arrows) and for the camera (framing on three screens, both
modes, limits, flights, cards that do not cover their mark, gestures).
`tests/js/mapview.e2e.mjs` (run by `tests/test_mapview.py` where Playwright is
installed) drives the preview at 390 × 844 and 820 × 1180 and checks:

- follow mode frames 1885, 1914 and 1966;
- a drag, a pinch and a double tap move the map and free the camera;
- free mode holds still across Next year, and Recentre frames the year;
- a mark's card opens without covering its mark and closes on a tap on the map;
- no page logs an error.

## 4. Rules 1.0 (Phase C)

Each item is a named flag in rules/versions/1.0/features.json, false in every earlier
version, implemented in both engines, integers only.

### 4.1 Upkeep (`upkeep_phase`)
Income, influence drift and cohesion recovery happen automatically at the start of a
turn, scaled by holdings and wealth tier. Invest, Cultivate influence and Consolidate
(rest) leave the action table. A house's one action per turn is always a real move.

**Phase C1 note, 6 October 2026.** Built in both engines (rules 1.0, draft), with these
numbers in `upkeep.json`:

- capital: 1 + holdings // 4 + the seat's wealth tier − 3;
- influence: 1;
- cohesion: 0, plus 3 while cohesion is below 40;
- a Courtier holder adds 1 to influence, and an Improver 1 to capital.

Correspond leaves the action table too. Each house gets one automatic letter a turn, at a
30% chance, resolved exactly as Correspond was, giving offence included. A house with no
legal action bides.

With this flag alone on, median capital, influence and cohesion at turn 100 are within
five points of 0.9's on the same ten seeds:

| Median at turn 100 | Upkeep alone | 0.9 |
|---|---|---|
| Capital | 39.6 | 39.0 |
| Influence | 60.1 | 55.5 |
| Cohesion | 97.3 | 97.8 |

### 4.2 Schemes (`schemes`)
A house commits to a scheme: a multi-turn plan with a named target, preparation steps that
cost capital or influence, an abort condition and a resolution roll. Schemes are public
state. Starting set: Claim a riding, Buy out a neighbour, Break a rival, Seek a protector,
Dynastic match, Win elevation, Open the frontier, Secure the line. A house chooses by
integer utility from its situation, objectives and holder traits, with a seeded draw among
the top three. A house that is the target of a visible scheme may answer it.

**Phase C2 note, 6 October 2026.** Built in both engines (rules 1.0, draft) as
`schemes.csv` and `schemes.json`, behind `schemes`. With it the weighted action draw is not
used.

How a house takes its turn:

- A house holds at most one scheme. Each turn it takes that scheme's next step, each step
  committing capital or influence.
- When a scheme's steps are done, it resolves on the house's next turn, through the
  existing action handler or the contest.
- A house without a scheme begins one, by the integer utility and a seeded draw among the
  three highest, or bides.

Every begin, step, answer, abandonment and resolution is an event with its turns
remaining. Each season record carries `plans`.

The schemes, with their final numbers:

| Scheme | Utility | Steps | Each step | Resolves as |
|---|---|---|---|---|
| Claim a riding | 20 | 3–5 | 5 capital, 2 influence | contest (§4.4) |
| Open the frontier | 75 | 2 | 2 capital | Expand on the named riding; a roll of 8+ takes a second beside it |
| Buy out a neighbour | 30 | 1–2 | 3 influence | Purchase riding |
| Break a rival | 30 | 1–2 | 3 influence | Dispute, hardening to hostility on success |
| Dynastic match | 25 | 2 | 2 influence | Marriage alliance |
| Win elevation | 20 | 2–3 | 5 capital | Petition elevation |
| Seek a protector | 15 | 2 | 2 influence | Propose compact, with a friendly house above |
| Secure the line | 55 | 2 | 1 capital | Name heir |
| Make peace | 5 | 2 | 2 influence | Reconcile (open hostility as well as grievance) |
| Fortify (answer) | 35 | until the claim resolves | 8 capital | adds to the defence |
| Sue for peace (answer) | 20 | 1 | 3 influence | the weaker side cedes the claimed riding; the stronger buys peace for 10 capital |
| Counter-claim (answer) | 25 | 2–4 | 5 capital, 2 influence | contest |

The utility:

- Every term is in `schemes.json` `utility`.
- The base is adjusted by:
  - 20 per held objective favouring the action the scheme reads;
  - 10 per point of each holder trait on it;
  - 2 per point of ambition, for a scheme that takes land or presses a quarrel;
  - −30 below cohesion 40.
- A claim or frontier adds 6 per wealth tier of the target riding.
- A claim adds 15 for a grievance or 10 for hostility, and 10 for a weaker target. It
  takes −30 for a seat, and its steps cost 2 capital less against a house it already
  quarrels with.
- Make peace adds 50 only with cause: a claim on the house, a recent contest lost to the
  target, cohesion below 40, or a Conciliator holder.
- Overreach, under `cohesion_strain`: −10 for each holding past the rank's free reach,
  on any scheme that would add a riding.

Peace and answers:

- A grievance cannot be reconciled in its first 3 turns.
- A house answers a claim only when an answer's utility beats 55. One already pressing a
  claim against its claimant keeps to it.
- A scheme is abandoned when its target or its funds are gone, returning half its stake. A
  succession re-scores it under the new holder, abandoning it below 10.

On ten seeds, 81% of ended schemes reach resolution, and the median resolved scheme runs
3 turns.

### 4.3 Traits (`holder_traits`)
Each holder draws two traits at accession from a rules table (for example Cautious,
Grasping, Pious, Reformer, Dynast, Litigious). Traits shift scheme utilities and crisis
responses. An heir's traits are drawn when the heir is named and are public, so a
succession can be anticipated.

**Phase C1 note, 6 October 2026.** Built as `traits.csv`, with eight traits. Each shifts
its named action weights by 2 × WEIGHT_SCALE, or its named upkeep by 1:

| Trait | Effect |
|---|---|
| Grasping | + Expand, Purchase riding, Challenge |
| Cautious | − Expand, − Dispute, + Name heir |
| Litigious | + Dispute, − Reconcile |
| Conciliator | + Reconcile, Propose compact, Cede / swap |
| Dynast | + Marriage alliance, Name heir |
| Courtier | + Petition elevation; +1 influence upkeep |
| Improver | + Endow; +1 capital upkeep |
| Zealot | never Neutral in an era response; +1 friction a turn on each opposed-tag border |

Grasping and Cautious never occur together, nor Litigious and Conciliator. Traits are
drawn in two draws, in the table's order, at founding or accession, or when an heir is
named. They are recorded on the person and in the founding, succession and naming events,
and shown on the house page. Scheme utilities wait for Phase C2.

### 4.4 Contests (`contested_claims`)
A claim on a neighbour's riding resolves as 2d6 plus committed capital, influence and
allies on each side. The loser pays; the riding can change hands; a seat can be lost; a
house with no ridings falls. Quarrels are no longer a precondition for every contest.

**Phase C2 note, 6 October 2026.** Built behind `contested_claims` with exactly these
numbers:

- the attacker rolls 2d6 + committed // 10 + rank index + 2 per ally + the holder's claim
  trait (Grasping +1, Cautious −1);
- the defender rolls 2d6 + fortified // 10 + cohesion // 25 + 2 per ally + 2 for its seat;
- ties go to the defender.

After a contest:

- The winner takes or keeps the riding; the loser loses its stake and 10 cohesion.
- A win by 5 or more against cohesion below 40 takes a second adjacent riding.
- A house left with no riding falls, and the record names the house that took its seat.
- The pair is hostile, and may not contest again for 5 turns.

Allies are the compact and kin of each side, asked in name order. Each joins on a
per-cent test: 50, +15 for kin, −100 for one bound to both sides, and −25 for joining the
prestige leader under `prestige_politics`. A refusal is recorded as an event.

Without this flag no claim is offered at all. On ten seeds:

- a game resolves 65 contests (53–80), and the attacker wins 46%;
- 62% of claims are answered by their target;
- 7.7 houses fall or are removed.

### 4.5 Prestige (`prestige`)
An integer score per house from holdings, rank, influence, alliances and contests won.
It is the standings, it is what the game is scored on at the end, and houses read it: the
leader draws coalitions, and a falling house draws claims.

**Phase C1 note, 6 October 2026.** Prestige is recomputed at the end of every turn. It is
written to `house_stats.prestige`, `prestige_history` and the season record. It is the sum
of:

- 10 per holding;
- 20 per rank index;
- influence // 5;
- 5 per compact or kin tie with an active house;
- 15 per dispute or challenge won;
- −15 per riding lost to another house (cession, sale, purchase, challenge, or being
  outbid for a contested riding).

Nothing in the engine reads it yet; houses reading it is Phase C2. Where a record carries
it, the story layer's standings use it.

**Phase C2 note, 6 October 2026.** Houses read prestige behind `prestige_politics`, as
utility terms:

- **The leader as a target.** A claim on the prestige leader by another top-eight house
  gains 25.
- **The weak draw claims.** A claim on a house that lost a contest in the last 10 turns,
  or has cohesion below 40, gains 20.
- **Protectors are sought above.** A protector must stand above the house. Seeking one
  gains 1 per 10 points of prestige gap, up to 30, and 40 more while the house is under
  a claim.
- **The leader is a poorer ally.** Courting the leader as a protector costs 25, and so
  does an ally's test to join the leader.

Standing is the house's prestige as last computed, or, without `prestige`, 10 per holding
and 20 per rank index.

**Phase D1 follow-up note, 7 October 2026.** Rank follows power. In the D1 preview the
reckoning's first house was a Baron of 29 ridings, ahead of a Marquis of 11, and no game
made a Duke. Three things held a large house back:

- A petition could not go past Marquis: the cap was written into both engines.
- It needed only three holdings at any rank, and its roll (2d6 + committed // 15 against
  9) took no account of size.
- A large house is a weak one under strain, so claims kept setting its suit aside.

The draft's `schemes.json` gains `elevation`, read by both engines with the old terms as
its default:

- A petition reaches Duke (`highest`).
- It needs 3 + 2 × rank index holdings (`holdings_from`, `holdings_per_rank`), the same
  reach §4.9 strains against.
- Each holding beyond that adds one to the roll (`bonus_per_holdings`).

Two contest terms moved with it, because more elevation schemes meant fewer claims and a
settled top eight:

- A claim on the prestige leader by another top-eight house gains 40, not 25.
- The truce after a contest is 6 turns, not 8.

### 4.6 A smaller table (`founding_curve`)
Crown foundings are front-loaded so the board is set in the first quarter of the game and
rare afterwards. The late game is zero-sum between established houses and their cadets.

**Phase C1 note, 6 October 2026.** An integer schedule in `founding.json` replaces
p_found: 100% through turn 24, 3% through turn 40, then 2%. After turn 40 no Crown founding
falls within ten turns of the last, and a house records whether the Crown or a partition
founded it. Cadet foundings by partition are unaffected.

On ten seeds:

- 24 houses are seated by turn 25 on every seed;
- there is at most one Crown founding in any ten turns after turn 40;
- 29 houses (24–33) are active at turn 100 with this flag alone, and 39 (35–42) with
  every flag on.

### 4.7 Marriage pairing (`marriage_pairing`)
A Marriage alliance pairs one man and one woman, by recorded gender, from the two houses'
unmarried heirs and children; the action is legal only when such a pair exists.
Director's decision, 6 October 2026.

### 4.8 Succession watch (`succession_watch`)
The engine records one event when a holder turns 60 with no heir named, and one when an
heir comes of age at 25, or is named already of age. The story layer opens a succession
question on the first and closes it on the second, for games whose record carries them.
Phase C1, 6 October 2026.

### 4.9 Cohesion strain (`cohesion_strain`)
Cohesion must be able to fall. Each turn a house loses 1 cohesion for each holding beyond
3 + 2 × its rank index, and 1 more while its holder is over 70; the contest and
succession losses stand. Cohesion recovers only as `upkeep.json` gives it. Schemes spend
influence, so influence has a sink.

**Phase C2 note, 6 October 2026.** Built as `upkeep.json`'s `strain`, behind
`cohesion_strain`, with the numbers above.

- Recovery is 3 a turn, and 6 below cohesion 50.
- Overreach (§4.2) makes another riding worth less to a house past its reach. Without
  it, houses outgrew their rank, their cohesion collapsed at succession and their land
  went back to the Crown: in one trial only 10 houses were left at turn 100.

On ten seeds, median cohesion at turn 100 is 66 (48–78) and median influence 48 (39–57),
against 96 and 75 in Phase C1.

**Phase D1 note, 6 October 2026.** Cohesion's base is 2 a turn. A contest's loser pays 30.

**Phase D1 follow-up note, 7 October 2026.** Cohesion's base is 1 a turn. With crises
evenly fought, median cohesion at turn 100 rose to 91 at 2.
A house at or past its reach values Win elevation by `elevation_at_reach` (45) more.

### 4.10 Distinct surnames (`distinct_surnames`)

A Crown founding never draws a surname that an active house bears while its community's
bank has an unused one. A house's surname is its name less any numeral ("Benjamin 2" bears
Benjamin). A director's chosen surname is kept, and a cadet keeps its parent's. The bank's
order is kept, so with no borne surname in it the draw is the draw it was.

**Phase D1 note, 6 October 2026.** Built in both engines. Over five seeds and sixty turns,
the Crown houses that took a numeral fell from 4 to none.

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

**Phase D1 notes, 6 October 2026.** Built behind `world_calendar`, in both engines.

The calendar:

- `game.json` holds the calendar: start 1867, 100 turns, and the five chapters, whose ids
  (`confederation`, `rails`, `war`, `depression`, `centennial`) are the era bands. Season
  records carry `year`.
- One climate ledger, `world`.
- Turn 1 is the first founding alone, so 1867's events, Confederation among them, are that
  founding.

Events:

- From 1868 every event of the year fires for every house, in deck order.
- An event's `through_year` repeats its direct effect each year, recorded as one world
  event a year ("The Great War continues: year 3 of 5"). The four that do are the Long
  Depression (1874–1879), the Great War (1914–1918), the Long Contraction (1930–1939) and
  the Second World War (1939–1945).
- Their effects are sized per year (rules/CHANGELOG.md). A §7c contraction sale lands only
  in an event's first year.

The atlas:

- The atlas is read at the world year from `riding_jurisdictions.csv`. A riding is in play
  while its sovereign is Canada; the Crown founds only on a riding in a province; land
  outside Canada is not taken or claimed that year.
- On meridian-v1.0.3, the ridings in play and in a province by year:

  | Year | In play | In a province |
  |---|---|---|
  | 1867 | 216 | 216 |
  | 1870 | 290 | 226 |
  | 1871 | 333 | 269 |
  | 1873 | 337 | 273 |
  | 1905 | 337 | 330 |
  | 1949 | 343 | 340 |

- Rupert's Land and the North-Western Territory come under Canada in 1870, Manitoba as a
  province with 10 ridings. British Columbia's 43 follow in 1871 and Prince Edward
  Island's 4 in 1873.
- Alberta's 37 and Saskatchewan's 14 ridings become foundable in 1905. Ontario extends in
  1874 and 1889, Manitoba in 1881, and Manitoba, Ontario and Quebec in 1912, each by a few
  ridings.
- Seven Newfoundland ridings join in 1949. Labrador is one of them: it was Canada's from
  1870 to 1926, then Newfoundland's, a British colony, from 1927 to 1948. That makes six
  ridings new to play and 343 in all.
- Each accession or extension is a world event naming its ridings.

The ending:

- After turn 100 the engine writes the reckoning: final standings, and for every house ever
  of the top eight its ridings, rank, place, peak prestige and year, contests won and lost,
  and successions. `house_stats` keeps the running facts in both engines and the world
  snapshot.
- `hoc sim run` refuses turn 101 with a message that the game is over.

Personal clocks still run, reset and sync, as reign years; nothing reads them.

The story layer (Part 2):

- Headings, kickers, plans, storylines and the full record count years.
- Each chapter ends with an interstitial (its title and years, the standings with their
  movement over the chapter, the cast's storylines it closed and left open), and Auto
  always pauses there.
- The last turn carries the reckoning, with an epilogue per house built by template from
  its facts (`web/story/reckoning.js`). The preview is the draft's whole game, with a
  Reckoning page.

The page (Phase D1 follow-up, 7 October 2026):

- With the calendar, the Replay page says "year" (its Next button, its go-to box and its
  opening paragraph); a game without it keeps "season".
- The go-to box takes a year (1885) or a turn, and shows that turn's dispatch with its
  interstitial or reckoning, the turn already on screen included.
- A reader never sees a house key's numeral. The standings and the follow menu name a
  house by its surname; where two houses of the game share one, both are named by their
  peerage less the rank ("Robinson of Hamilton", "Robinson of Brampton"), which is how
  the standings tell them apart (`web/story/text.js` `readerNames`). Dispatches already
  named houses by peerage and designation.

### 5.1 Crises (`crises`)

A Major event is a crisis. In the world's turn, before any house acts, every house takes a
side by the existing response roll, with its tag modifier and the steadfast trait:

- Lead and Resist are the camps. Exploit takes its capital and Neutral stands aside.
- The camp with more total influence carries the crisis. The climate moves its way, its
  members gain 5 influence, and the other camp's members lose 3.
- Land neighbours in the same camp cool their border by 10, and a compact with a house of
  the same camp is worth 20 more for ten turns. Neighbours in opposed camps gain 10
  friction.
- One societal event records both camps, who carried it and, for a multi-year crisis, how
  many years it runs.
- The crisis's direct effect lands on each house in its own turn.
- It reads the world year, so without `world_calendar` it does nothing.

**Phase D1 note, 6 October 2026.** Built in both engines, with a parity test of one
crisis's camps, influence and borders. On ten seeds:

- Both camps are non-empty in 87% (83–94) of crises.
- Those who lead carry 12%: the response roll gives Lead only on a 6.
- Most crises with an empty camp come before a dozen houses are seated: the Red River
  Resistance (1869) on nine seeds of ten, the Manitoba Act (1870) on seven, the Indian Act
  (1876) on four. Four later crises had one, each on a single seed.

**Phase D1 follow-up note, 7 October 2026.** Side-taking has its own thresholds,
`game.json` `crises.response`, symmetric between Lead and Resist before the tag modifier
and the steadfast trait. The event response roll (`responses.json`) and ordinary events
are unchanged.

- On d6 + modifier: Lead on 5 or more, Resist on 2 or less, Exploit on 4, Neutral on 3.
  Before the modifier each camp has two faces of six.
- A matching tag (+1) gives Lead three faces and Resist one; an opposing tag the reverse.
- A steadfast holder still turns Neutral to Resist.

On ten seeds:

- Those who lead carry 40% (17–61) of crises, against 12%.
- Both camps are non-empty in 92% (89–100).

The story layer orders two crises of one year at equal weight: the one that opens a
multi-year event is the headline (1914 is the Great War, with the Komagata Maru beneath
it), then the one with more houses in its camps. A crisis headline begins with the
event's article: "The" before a title that has none, except a one-word title or one with
a number ("Regulation 17").

## 6. Story targets (replace ENGINE_DESIGN §17 for rules 1.0)

Targets across ten seeds (1867–1876), 100 turns, on the Meridian world, measured by
`scripts/story_trial.py` and recorded in rules/CHANGELOG.md.

- Phase C2 merged its own targets into the list.
- Phase D1 added the pacing targets and the calendar's, and the director dropped the land
  target.
- The Phase D1 follow-up added the crisis balance target and three rank targets.
- The figure after each is the draft 1.0 with every flag on, the shared calendar
  included, as the Phase D1 follow-up trial measured it: mean (min–max). **Met** means
  met on the mean.

Action and land:

- At least 30% of actions are aimed at another named house. **Met**: 32% (27–36).
- After turn 20, a riding passes between houses at least once every three turns on
  average. **Met**: 0.34 a turn (0.16–0.47).
- 20 to 40 houses are active at turn 100. **Met**: 21.8 (18–30).
- 4 to 10 houses have fallen or been removed by turn 100. **Met**: 7.5 (6–12).
- Land has no target from Phase D1. The share of the ridings in play that year that are
  held is 22% at turn 25, 38% at 50, 30% at 75 (the Long Contraction's debt sales) and 46%
  at 100.

The lead, the rank and the chapters:

- The prestige lead changes at least four times. **Met**: 18.0 (3–27).
- No house leads for more than 50 turns. **Met**: 26.8 (15–52).
- In every chapter after the first, a house that began it in the top eight ends it
  outside or removed. **Met**: 4 of 4 on every seed.
- At turn 60 the top eight by prestige span at least three ranks. **Met**: 3.2 (3–4).
- The house placed first at the reckoning is an Earl or higher in at least 8 games of 10.
  **Met**: 9 of 10.
- A Marquis or Duke is active at turn 100 in at least 8 games of 10. **Met**: 10 of 10.
- At least one Duke is created in at least 3 games of 10. **Met**: 6 of 10.

Headlines and storylines:

- 40–65% of turns have a headline at or above the pause threshold. **Met**: 57% (43–63).
- Auto pauses on 15–30% of turns. **Met**: 24% (18–28).
- Never more than three quiet turns in a row after turn 10. **Met**: none.
- At least eight storylines of five or more beats per game. **Met**: 32.1.
- At most 20 rise and decline storylines a game. **Met**: 12.8 (6–21).
- Every closed storyline has an outcome. **Met**: none without one.

Quarrels:

- The median rivalry runs 4 to 10 turns. **Met**: 9.1 (7–13).
- At most 40% of rivalries are reconciled. **Met**: 11% (4–23).
- At least 25% end in a contest, a cession under a standing claim, or a house's fall.
  **Met**: 51% (38–58).

Contests and claims:

- 20 to 35 contests are resolved per game. **Met**: 22.9 (11–32).
- The attacker wins 35–60% of them. **Met**: 51% (34–64).
- At least half of claims are answered by their target. **Met**: 61% (49–74).

Schemes:

- At least 60% of schemes reach resolution. **Met**: 78% (74–84).
- The median scheme runs three to six turns. **Met**: 3.
- After turn 15, at least three public schemes involve a cast house in at least 80% of
  turns. **Met**: 99%.

The economy:

- Median capital at turn 100 is 30–70. **Met**: 45.2 (32–52.5).
- Median cohesion at turn 100 is 55–85. **Met**: 81.7 (62–94.5).
- Median influence at turn 100 is 40–70. **Met**: 55.2 (39–70).

The calendar:

- Both camps are non-empty in at least 70% of crises. **Met**: 92% (89–100).
- Those who lead carry 35–65% of crises. **Met**: 40% (17–61).
- Every game ends with a reckoning. **Met**: 10 of 10.

## 7. Phases

| Phase | Scope | Engine change | Gate |
|---|---|---|---|
| A | Beats, story weight, dispatch, standings, follow, Replay page | None | First Dominion replays as dispatches; headline mix within §3.1 limits |
| B | Storylines derived from the record; dispatch organised by them | None | On The First Dominion: at least 85% of headlines after turn 20 belong to a storyline; at least eight storylines have five or more beats, and each closed one has an outcome; no more than 25% of headlines after turn 20 are storyline openings; fewer than 20% of closed storylines close as "lapsed" (if not reachable without distorting the triggers, the figure is reported, as it measures the engine); the Phase A limits still hold |
| C1 | Rules 1.0's mechanical flags (§4.1, §4.3, §4.5–§4.8) as a draft version, both engines; the trial harness | Yes | Every flag in both engines, false before 1.0; cross-check byte-identical on seeds 1867, 2 and 3 at 120 turns under 1.0 and the current version; the baseline trial table (current / each flag alone / all on) recorded in rules/CHANGELOG.md |
| C2 | Schemes (§4.2), contested claims (§4.4), houses reading prestige (§4.5), cohesion strain (§4.9) as draft flags; beats, Plans afoot and the draft-rules preview; the trial's C2 measures | Yes | §6 targets on a personal-clock trial: every one met on the mean except land claimed by turn 60 (63% against 80%), reported with what holds it back; the before/after table (C1 against C2 all on) recorded in rules/CHANGELOG.md. Built 6 October 2026 |
| D1 | Pacing (fewer, weightier contests; scarce capital; rank that differentiates), `distinct_surnames` (§4.10), `world_calendar` (§5) with the deck to 1966 and the reckoning, `crises` (§5.1), all in the 1.0 draft; years, chapter interstitials and the reckoning in the story layer; the preview as the whole game | Yes | §6 targets across ten seeds on the mean; cross-check byte-identical on seeds 1867, 2 and 3 at 120 turns under 0.9 and 100 under 1.0; the three-column table (C2 all on, D1 without `world_calendar`, D1 all on) in rules/CHANGELOG.md. Built 6 October 2026 |
| D1 follow-up | Crisis side-taking with its own thresholds; rank that follows power (`schemes.json` `elevation`, Dukes); crisis headline order and articles; years, go-to and numeral-free names on the page | Yes | §6 targets, the four new ones included, across ten seeds on the mean; the before/after table in rules/CHANGELOG.md. Built 7 October 2026 |
| D2 | The director reviews the preview; then the new scenario begins under 1.0, The Dominion is frozen, and 1.0 is published (`rules/current.txt` points at it) | Yes | A full game ends in 1967 with its reckoning, from the record |
| V | The map view (§3.6): the Replay as a full-screen map with gestures, a follow/free camera, marks and cards; the text Replay kept as its own page | None | node tests for marks and camera; the browser checks at 390 × 844 and 820 × 1180; full suite, node tests and the referee on every scenario green; both frozen games' archive pages render. Built 7 October 2026 |
| E | Scene templates, chapter narration, epilogues | None | A full game reads start to finish from the site |
