# Phase D2: the dry run

On 10 October 2026, on a scratch git worktree, The Centennial was begun exactly
as Phase D2's step 3 will begin it, played to its reckoning, exported and
checked at 390 px. **Nothing was frozen or published in the repository**:
`rules/current.txt` is still 0.9, The Dominion is still live, and no
`scenarios/centennial/` exists here. What the dry run found wrong was fixed in
the repository. The fixes are listed below, each with its test.

## How the scratch game was begun

On the worktree only:
1. The Dominion's manifest set to `"status": "frozen"`.
2. `scenarios/centennial/`:
   - `scenario.json`: name `centennial`, title "The Centennial", `status: "live"`, `kind: "autoplay"`, `reference_data: "meridian-hex-v1.0.5"`, `rules_version: "1.0"`;
   - The Dominion's header-only `seed/*.csv`.
3. `rules/current.txt` set to 1.0.
4. The commands:
   - `python -m hoc scenario use centennial`;
   - `python scripts/rebuild.py`: `sim new` refuses a database that still holds another game, so the rebuild has to come first;
   - `python -m hoc sim new --seed 1905`.

`sim new` plays season 1 and seats one house: **Baron Boulton of Mattawa, at
Mattawa, with North Bay and Temiskaming Shores** (its block grant). The next
years of the scratch game founded:

| Year | House | Seat |
|---|---|---|
| 1868 | Viscount Almon of Lunenburg | Lunenburg, with Halifax and Stewiacke |
| 1869 | Baron Gowan of Ottawa South-East | Ottawa South-East (this designation is what led to the token fix below) |
| 1870 | Baron Hodgins of Whitby | Whitby, with Clarington |
| 1870 | Baron Lacerte de Cartier | Cartier, with Portage la Prairie and Carman (the Manitoba land rush) |
| 1871 | Baron Comeau de Perth-Andover | Perth-Andover, with Bathurst and Edmundston |
| 1871 | Viscount Tong of Armstrong | Armstrong, with Kelowna and Sun Peaks Mountain (the British Columbia land rush) |

After that, `python -m hoc sim run 99` played to 1966 in 19 seconds. The game
ended with the reckoning of 1967 ("Duke Elliott of Lincoln stands first"):
34 houses, 232 of 494 holdings held. `sim run 1` then refused: "the game is
over: it ended after turn 100 (1966) with its reckoning, and there is no turn
101".

## Auto at 1×

Measured from the exported record with `tests/js/story_round_report.mjs`, the
quantity Phase V3 measured:

| Game | Quiet turns shown | Quiet turns skipped | 1900–1910 shown |
|---|---|---|---|
| The scratch Centennial (seed 1905) | **51.5 min** | 44.7 min | 5.7 min (25–27 house turns a year) |
| The hex preview (seed 1867) | 49.9 min | 42.7 min | 6.0 min (28–30 a year) |
| The riding preview (seed 1867) | 40.0 min | 34.4 min | 4.2 min (22 a year) |

Phase V3's band for the riding preview was 35–45 minutes with quiet turns
shown. The hex board's 37 houses take about a quarter longer.

## The live site, step 4, at 390 px

| Item | Before the fixes | Now |
|---|---|---|
| Home page | the riding map, "ridings", "season 1" | the map Replay of the live game, as preview-hex has it (`home-1867`, `home-1905`, `home-1966`) |
| Map | hexagons drawn as dots | `map.html`, the hex board drawn as the Replay draws it (`map`) |
| Holdings | "All 494 ridings of the 2023 Representation Order", personal years | "Holdings", the hex board, opening years (`ridings`) |
| Chronicle | by season | by year; a line's "Season N ·" is not repeated under its year (`chronicle`) |
| Climate | the legacy game's era-cohorts and lost workbook | one ledger, the world's (`climate`) |
| Storylines, Reckoning | none for the live game | both; the Reckoning after turn 100 (`reckoning`) |
| About | 343 ridings, personal clocks | the hex board, 1867–1966, the reckoning |
| House pages | "season", personal clock | years; no personal clock |
| Play page | seasons, ridings, no round, no end | years, holdings, the year's round house by house, and "The game ended in 1966 with its reckoning: there is no year 1967" (`play-at-1966`) |
| Console | worked | works |
| Archive | three frozen games | three frozen games; its index has the live site's nav |

The play page played one year in the browser without saving, from 1867 to
1868: "Next year", "Holdings 6 of 494", and the round as "The world · Boulton
sets out to open Sables-Spanish Rivers · The close — 1 house founded". The
save path was checked headlessly (`web/engine/savecheck.js`: 5 seasons would
be committed exactly as played; a frozen scenario is refused) and so was the
restore (`restorecheck.js`). The referee verified the scratch Centennial's 100
years and The Dominion, and both frozen games' archives built.

## What the dry run fixed

| Fix | Where | Test |
|---|---|---|
| The live site told as a story under the world calendar (the table above) | `hoc/export/site.py`, `play_js.py`, `replay_js.py` | `tests/test_live_story_site.py` |
| An intervention was applied under `rules/current.txt`, not the game's own rules. The Python turn runner built its World without a version, unlike the JavaScript `World.intervene`. | `hoc/turn.py` | `tests/test_atlas.py` (four tests that failed with 1.0 current) |
| A relation set by the director was a second row in the order given; both engines keep one ordered row per pair. Under 1.0 they then diverged (`meridian-v1.0.3`, seed 1867, from season 37). | `hoc/turn.py` | `tests/test_world_snapshot.py`: all seven operations under 1.0, 100 turns, on both boards |
| A holding taken and lost in one season stayed held on the map's scrubber. | `hoc/export/timeline.py` | `tests/test_timeline.py` |
| A compass-named city hex gave its own constructed name as a designation ("Baron Gowan of Ottawa South-East"). It now gives the city. Ten tokens of the hex set change; the riding sets' are byte-identical, and the trial is unchanged. | `scripts/build_places.py`, `meridian-hex-v1.0.5/riding_tokens.csv` | `tests/test_hexboard.py`, `tests/test_meridian.py` |
| The turn-order strip's placeholder before the first year was bare text. | `hoc/export/replay_js.py` | the map view's browser check |

No recorded game is changed by any of these. No scenario has an intervention
or a relation operation. The First Dominion's archived timeline carries the
same changes, with each frame's keys in event order.

## What the publish step must update

With 1.0 current and The Centennial live, the full suite has 15 failures and 10
errors after the fixes. All of them encode the state before publishing, or
assume that the current rules are 0.9:
- **The state:**
  - `test_frozen.py` (three tests): The Dominion live, two frozen games;
  - `test_meridian.py`: the frozen games and their sets;
  - `test_rules10.py`: 1.0 is a draft;
  - `test_site.py`: the live site has no Replay; the preview is in the nav while a draft exists.
- **The previews, which go with the draft** (`test_site.py`, six fixtures; `test_mapview.py`, three):
  - the riding preview's checks retire;
  - the hex board's own browser check (`tests/js/hexboard.e2e.mjs`) should move to the live site.
- **The current rules taken as 0.9** (they play over 100 turns, or read the Confederation ledger):
  - `test_sim.py` (three tests);
  - `test_site.py`: unique element ids; the play page's path;
  - `test_timeline.py`: the scrubber is on `map.html`;
  - `test_world_snapshot.py`: a late world; the 0.9 interventions.

  Each should name 0.9, which it tests.

## Still open

- **The play page's size.** On the hex board, the play page and its assets
  are 2.5 MB against the exporter's 2 MB budget: the page's hex map is 690 KB
  and the world snapshot 720 KB. It is a warning, and the page works.
- **37 houses.** A late year is about 26 house turns, and Auto runs 51 minutes
  at 1×.
