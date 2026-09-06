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
