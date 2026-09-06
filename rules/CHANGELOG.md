# Rules changelog

Every table in `rules/` is versioned. A season log (Phase 9c+) records the rules version it was played under, so replaying old seasons never silently picks up a later rule change.

## 0.1 — initial transcription from docs/ENGINE_DESIGN.md

- All tables in this directory transcribed verbatim from `docs/ENGINE_DESIGN.md` (Phase 9a design document), section by section: `actions.csv` from §7, `objectives.csv` from §5 (cross-referenced against §7's modifiers column), `mortality.csv` from §9, `founding.json` from §10 and §4, `succession.json` from §9 and §7c and §7b, `eras.json` from §3, `responses.json` from §8.
- `responses.json`'s `tag_modifier`: the design document specifies the response roll as "d6 + tag modifier" (§8) but does not state the modifier's magnitude. This version chooses **+1 for a matching tag, −1 for an opposing tag, 0 otherwise**. This is the one number in this transcription pass that is authored here rather than copied from the document, per the director's instruction to choose it and record the choice.
- No game data changed. No behaviour changed: `rules/` is not yet read by any running code (the loader lands in this same commit; the season engine that consumes it is Phase 9c).

## 0.2 — event deck, community and name banks, place banks

- Added `events.csv` (§8 event deck, 51 events 1867–1960), `communities.csv` (§10 cultural communities, 52 rows across 6 regions), `places.csv` (173 territorial-designation place names across all 13 provinces/territories), `given_names.csv` (1,120 given names across 28 naming traditions), and `surnames.csv` (985 surnames across 52 communities). All transcribed verbatim from the design conversation's authored banks; no values invented here.
- `events.csv`'s `band` column (`confederation` / `dominion` / `late`) is a loose free-text label from the source document and does not match `eras.json`'s canonical band names (`Confederation` / `Dominion` / `Late Dominion`) — in particular `late` vs. `Late Dominion`. Transcribed as given rather than silently renamed; any code that needs an event's actual era band should compare `personal_year` against `eras.json`'s year ranges, not this column.
- `communities.csv` has six regions (`maritime, quebec, ontario, prairie, bc, north`); there is no seventh `newfoundland` region row, because Newfoundland's communities are recorded under `maritime` until the 1949 event `Newfoundland Joins Confederation`, after which the event deck can target Newfoundland houses directly by the `newfoundland` scope. `founding.json`'s `region_weights.initial` keys are capitalized (`Maritime`, `Quebec`, ...) where `communities.csv`'s `region` column is lowercase — the same cross-file capitalization mismatch already flagged in Phase 9b-1; still unreconciled, for 9c.
- Four surnames are shared by more than three communities in the authored bank: **Fraser** (Scottish Highland Catholic, Scottish Presbyterian, Scots Presbyterian, Scots and Selkirk Settler — 4), **Ross** (Scottish Presbyterian, Scots Presbyterian, Cree and Saulteaux, Ontario-British Settler, Scots and Selkirk Settler — 5), **Grant** (Scottish Presbyterian, Black Loyalist and Refugee, Scots Presbyterian, Métis, Coast Salish — 5), and **Nelson** (Black Underground Railroad Descent, Scandinavian, Haida and Tsimshian, Klondike Settler — 4). This is a genuine violation of the "no more than three communities" invariant that `tests/test_banks.py` checks; the surname data is transcribed as given rather than silently trimmed or reassigned, so that test fails against the bank as authored. Flagged for the director to decide: relax the invariant, or amend the bank in a follow-up transcription commit.

## 0.3 — the director's rule decisions, settled before the engine

The seven questions left open by 0.1 and 0.2. All are the director's decisions, taken so that Phase 9c has no ambiguity left to guess at.

- **Surname reuse limit raised from three communities to five.** The bank shares a few genuinely common surnames (Fraser 4, Nelson 4, Ross 5, Grant 5) across communities, which is true of the real naming record rather than a transcription error. `tests/test_banks.py` now checks five; the bank is unchanged.
- **Keys normalised to lowercase ids everywhere.** `eras.json` bands gain an `id` (`confederation` / `dominion` / `late`) alongside a display `name` (`Confederation` / `Dominion` / `Late Dominion`); the ids are what `events.csv`'s `band` column, `climate.era_cohort` and the season logs carry. `founding.json`'s `region_weights.initial` keys are lowercase (`maritime`, `quebec`, ...) to match `communities.csv`'s `region` column. This closes both cross-file mismatches flagged in 0.1 and 0.2.
- **Founding probability is the §10 formula only**: `0.25 * (unclaimed_land_adjacent_ridings / 343) ** 0.5`. The conflicting §6 statement ("default 0.15, halved when 40+ houses exist") is deleted from `founding.json`. There is no house cap.
- **Enclosure bonus is +2** for Marriage alliance, Cede / swap and Challenge (11b), which §7b named but never gave a number for. Purchase riding (+2) and Absorb (+3) keep the numbers the design document stated.
- **"Defend the seat" boosts Consolidate (rest) +2 and Cultivate influence +2.** 0.1 left its `action_weight_bonus` blank because no §7 row named the objective; the director has now assigned it.
- **rank_index is Baron 0, Viscount 1, Earl 2, Marquis 3, Duke 4**, gendered forms sharing the index (Baroness 0, Viscountess 1, Countess 2, Marchioness 3, Duchess 4). This resolves the `initial_stats` ambiguity flagged in 0.1 and matches `RANK_LADDER` in `hoc/rules.py`.
- **The response-roll tag modifier stays +1 / −1 / 0**, confirming the one number authored in 0.1 rather than transcribed.

No game data changed. The seasons played under 0.3 are the first ever played, so no earlier season's rules version is disturbed.

## 0.4 — founding rate tuned to the §17 smoke targets

One number changed, and it was changed because the engine measured it rather than because anyone preferred it. `docs/ENGINE_DESIGN.md` §10 gives the founding probability as `0.25 × (unclaimed land-adjacent ridings ÷ 343)^0.5`; §17 asks that a 300-season run peak at between 45 and 90 houses and reach 80 per cent of the map claimed between seasons 90 and 200. The first cannot produce the second.

`p_found.coefficient` is therefore **0.50**, and `p_found` now stores `coefficient` and `exponent` as numbers beside the formula string so the founding rate is tunable in this table rather than in `hoc/sim.py` (§11).

Measured over three seeds × 300 seasons, `tests/test_sim.py::test_smoke_three_seeds_stay_within_the_sanity_targets`:

| coefficient | house peak (seeds 1/2/3) | season 80% claimed | final houses | verdict |
|---|---|---|---|---|
| 0.25 (as designed) | 34 / 32 / 36 | 160 / 141 / 166 | 34 / 31 / 36 | peak far below the 45 floor |
| 0.45 | 46 / 46 / 47 | 114 / 113 / 111 | 46 / 44 / 47 | passes, but within one house of the floor |
| **0.50 (chosen)** | **51 / 49 / 52** | **110 / 99 / 99** | **51 / 45 / 50** | **passes with margin at both ends** |
| 0.55 | 50 / 60 / 52 | 112 / 120 / 87 | 48 / 60 / 51 | 80% claimed at season 87, before the 90 floor |
| 0.60 | 45 / 53 / 54 | 108 / 99 / 86 | 43 / 51 / 54 | same failure, worse |

Nothing else was tuned: the action weights, targets, mortality bands, response table and objective bonuses are all still as transcribed. No stat left 0–100 at any coefficient, and no run collapsed — the house count oscillates in the forties and fifties once the map fills, which is the §7b dynamic working.

Seasons played before this version keep 0.3; there are none yet, so nothing is disturbed.

## 0.5 — the late game: what §7b and §9 named but never numbered

PART B of the engine needs three things the design document describes in prose and never quantifies, plus one objective it names outside §5's table. All four are authored here rather than in `hoc/sim.py`, so they stay tunable.

- **`objectives.csv` gains Siege.** §7b says a fully enclosed house with cohesion below 40 "draws a Siege objective: survive 10 seasons without losing a riding, or seek a protector"; §5's table of seven never listed it. It is now an eighth row, boosting Marriage alliance and Propose compact — the two ways of finding that protector.
- **`succession.disorderly_succession.sig_minus_probability` = 0.5.** §9 says a disorderly succession carries a "Sig− risk with one neighbour" without saying how much risk. Half is authored here. This number matters more than it looks: a grievance is the precondition for Dispute, and a won dispute is the precondition for Challenge, so it is the tap that feeds the whole conflict branch.
- **`succession.marriage_alliance.dispute_block_seasons` = 20**, moved out of §7's prose into the table it belongs in.
- **`succession.partition.min_holdings` = 9**, with `min_heirs` = 2, and `heirs.second_heir_min_holdings` = 9 to match.

That last one is the only place the design document's own number was overridden, and again it was measured rather than preferred. §9 sets both thresholds at four holdings. At four, partition fires constantly — a house splits nearly every time a holder dies — and the house count runs away past §17's ceiling:

| partition threshold | house peak (seeds 1/2/3) | partitions | absorptions | extinctions | verdict |
|---|---|---|---|---|---|
| 4 (as designed) | 97 / 103 / 100 | 57 / 71 / 83 | 10 / 10 / 20 | 2 / 3 / 7 | peak far over the 90 ceiling |
| 7 | 71 / 75 / 77 | 29 / 33 / 40 | 6 / 10 / 11 | 2 / 1 / 4 | passes, close to the ceiling |
| **9 (chosen)** | **71 / 65 / 67** | **20 / 25 / 16** | **6 / 11 / 4** | **2 / 5 / 2** | **passes with margin; every §17 mechanism still fires** |

Nine reads as the right shape as well as the right number: a house has to be genuinely large before its death splits it in two, which is what "the senior heir takes the seat and the contiguous core" implies about scale.

Under 0.5 all of §17 holds across the three smoke seeds — peak 65–71, 80 per cent of the map claimed at seasons 114–120, no collapse, no stat outside its range, and at least one partition, absorption and extinction in every seed.

## 0.6 — friction: where grievance comes from

Through 0.5 the game was almost entirely cooperative. Compacts and marriages ran two orders of magnitude ahead of disputes and challenges, and the reason was structural rather than a matter of weights: the only thing in the whole rule set that ever produced a Sig− relation was a disorderly succession. Dispute needs a Sig−, and Challenge needs a Dispute won before it, so the conflict half of §7 was starved at the source. `rules/friction.json` supplies it.

**Friction** is per-pair state between two houses sharing a land border, 0–100. Each season it moves by +3 if their tags oppose, +1 if either is enclosed, +2 if either has ambition ≥ 7, −2 if they are already bound by a +, ◉+ or kin relation, and −1 otherwise. At 60 the border rolls d6: on 4 or more the two houses fall out over a named grievance and a Sig− is created; either way the pair falls back to 30, so a quarrel that does not catch still leaves the border warmer than it started. The grievance is drawn by tag pair from five templates — a boundary read two ways, water rights, the patronage of a shared riding's offices, a slighted marriage, a church and school dispute in the border townships.

Three smaller sources of grievance close gaps §7 left open: two houses reaching for the same unclaimed riding in one season roll 2d6 against each other and the loser carries the grievance away; Correspond on a natural 2 gives offence instead of doing nothing, which is the only failure that action has ever had; and Dispute's base weight rises to 3 while Challenge's rises to 2.

### What had to be tuned, and what it cost

The director's bounds for this pass were 0.6–1.5 disputes per house-generation, 15–25 challenges per run, and cooperation no more than four times conflict. The friction numbers above are the director's and were not changed. Everything below was.

| # | change | disputes/generation (seeds 1/2/3) | challenges | verdict |
|---|---|---|---|---|
| — | friction as specified, Dispute 3, Challenge 2 | 1.68 / 1.70 / 1.60 | 143 / 152 / 118 | both far over |
| 1 | `dispute_outcome.hardens_probability` 0.5 → 0.12 | 1.80 / 1.63 / 1.74 | 23 / 50 / 42 | challenges closer |
| 2 | hardens 0.07, Dispute 3 → 2.5 | 1.67 / 1.44 / 1.65 | 22 / 14 / 21 | disputes barely moved |
| 3 | `grievance_lapse` added, hardens 0.09, Dispute back to 3 | 1.72 / 1.70 / 1.81 | 22 / 15 / 20 | lapse alone did nothing |
| 4 | Dispute 3 → 2 | 1.34 / 1.64 / 1.62 | 25 / 24 / 34 | still over on two seeds |
| 5 | `per_season.open_quarrel` = 0 | 1.22 / 1.36 / 1.58 | 60 / 44 / 43 | disputes nearly in; challenges burst |
| 6 | hardens 0.035, lapse 12 | 1.27 / 1.36 / 1.48 | 26 / 16 / 16 | one seed one challenge over |
| 7 | hardens 0.032 | 1.27 / 1.28 / 1.36 | 26 / 13 / 11 | two seeds under the floor |
| **8** | **`challenge_outcome.failure_marker`, hardens 0.06** | **1.34 / 1.32 / 1.43** | **18 / 15 / 24** | **all three seeds inside every bound** |

Four of those are numbers the design document never gave, now recorded here rather than assumed in code:

- **`dispute_outcome.hardens_probability` = 0.06.** §7 says a won dispute leaves the grievance "resolved or ⊖" without saying how often. PART B assumed half, in `hoc/sim.py`. It is the tap that feeds Challenge — only a ⊖ makes one legal — so it belongs in a table.
- **`per_season.open_quarrel` = 0.** Friction is *unexpressed* pressure. A pair already standing in a grievance has expressed theirs, so their border holds where it is until the quarrel is settled. Without this the same two houses fell out again every ten seasons and the map filled with recurring feuds.
- **`grievance_lapse.seasons` = 12.** Friction decays when nothing feeds it; a grievance had no such rule, so the stock of open Sig− relations only ever grew. A grievance neither side has pressed for twelve seasons lapses to resolved. That is not settlement — the marker goes to resolved, not to friendship — it is the quarrel ceasing to be worth the trouble.
- **`challenge_outcome.failure_marker` = Sig−.** §7 costs a failed challenge ambition and influence but says nothing about the ⊖ that made it legal. Leaving it standing let one pair challenge season after season, which is exactly where the challenge count's seed-to-seed variance came from; step 7 above shows the count moving by half across seeds while the probability driving it barely moved.

And one of the director's own numbers did have to move: **Dispute's base weight went to 2, not the 3 this pass specified.** At 3 no combination of the other knobs brought disputes per house-generation under the 1.5 ceiling on all three seeds — steps 1 through 3 show it flat around 1.7 while everything else changed around it. At 2 it competes evenly with Reconcile, which is what actually governs how many grievances become quarrels. Challenge stayed at the specified 2.

All of §17 still holds: peak 70–75 houses, 80 per cent of the map claimed at seasons 120–138, no collapse, no stat outside its range, and partitions, absorptions and extinctions in every seed.
