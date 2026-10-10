# The hex trial

> **Superseded.** The director chose hexes over ridings, and the board was
> rebuilt on Meridian v1.0.5 as `meridian-hex-v1.0.5` (docs/hex-trial/v2/README.md).
> The set this page describes, `meridian-hex-v1.0.4`, was removed on 10 October 2026
> when the preview moved to the new board. Its pin, builder and tests went with it;
> the trial below stands as it was measured.

A hex board in place of the 343 ridings, tried beside the riding world and not
in place of it. Ridings run from 7 km² to 2 million km² and make a poor map to
watch; an H3 resolution-4 hexagon is about 1,770 km² and 45 km across,
everywhere.

Nothing about the games of record changes. `rules/current.txt` stays 0.9, no
rule was tuned, no scenario was created or played, and The Dominion, both
frozen games and the riding preview replay exactly as before.

## What was built

| Piece | Where |
|---|---|
| The pin: Meridian `v1.0.4`, `hexes.r4.v1.json.gz` (`94c2f806…a8a`) and `layers/hexes.r4.v1.topojson.gz` (`336cb743…325`), refused on any other hash, format, version or unit | `scripts/fetch_meridian.py --hexes`, `data/reference/meridian/hex-v1.0.4/raw/` |
| The reference set `meridian-hex-v1.0.4`, in the shapes every set has | `scripts/build_world_hex.py`, `data/reference/meridian/hex-v1.0.4/` |
| The rules that turn the table into integers | docs/DETERMINISM.md, "The hex board" |
| Both engines read the map's size, not 343 | `hoc/sim.py` `World.total_units`, `web/engine/sim.js` `map.ridings.length` |
| The trial table | `scripts/story_trial.py --reference meridian-hex-v1.0.4`; [trial-table.md](trial-table.md), [trial.json](trial.json) |
| The second preview | `outputs/site/preview-hex/`, built by `scripts/build_preview.py` beside `preview/` |
| Tests | `tests/test_hex.py`; the map view's browser check runs on both previews |

## The board

**Units.** The 439 rows with 5,000 people or more. Each has the id
`PP × 1,000,000 + S`: the province's two-digit federal code, then the H3 cell's
base cell and four resolution digits as one base-7 number. It depends only on
the hexagon and its province, so it is stable across builds and meshes, and its
first two digits are its province as a FED number's are (the story layer reads
them). `units.csv` keeps the H3 index.

**Names.** Units are named largest first: each takes its largest place of a
city, town, village or hamlet type, failing that of a general municipal type,
skipping a name already taken. 34 units had no such place: 15 hold no census
place at all (their people live in CSDs whose point falls in the next hexagon:
the Durham hexagon of 207,572 people, a Windsor suburb's of 136,447) and 19 hold
only reserves, regional district areas or county subdivisions. **By the
director's decision of 8 October 2026 they borrow** the largest unused town (then
municipality) from the nearest hexagons over land, ring by ring; two more borrow
because a larger unit had taken their only name. 36 in all, listed in
`build_report.json` and marked in `units.csv` (`named_from_h3`). No name is
rewritten. One unit, North Bay, has no name token (both words are dropped by the
riding-token rule), so its designations come from its places and neighbours.

**Designations** come from the unit's own places by csdType: 2,188 of 2,696
places, in 385 units.

**Links.** The settled hexagons alone are 80 separate pieces, so every
wilderness hexagon goes to the nearest unit over land links (ties to the lower
id), and two units are neighbours when their territories touch.

| | Before the cap | After |
|---|---|---|
| Land links | 1,127 | 1,069 (58 longer than 6 dropped) |
| Land links a unit (mean) | 5.13 | 4.87 |
| Land-connected groups | 438 and 1 | 438 and 1 |
| Water links | | 42 |
| Groups counting water links | | 1 (all 439) |
| Links a unit, all kinds (mean) | | 5.06 |

Lengths before the cap: 681 of 1, 165 of 2, 112 of 3, 50 of 4, 35 of 5, 18 of
6, and 66 longer. Eight longer links were kept because they alone join a group:
Fort Frances–Neebing (7), Thompson–The Pas (7), Happy Valley-Goose Bay–Wabush
(10), Sault Ste. Marie–Thunder Bay (11), High Level–Yellowknife (11),
Springdale–Happy Valley-Goose Bay (13), Terrace–Whitehorse (20) and
Thompson–Iqaluit (61). Les Îles-de-la-Madeleine touch nothing in the table (the
sea round them has no rows) and take one water link to Three Rivers, PEI, 123 km
away. 450 hexagons are reached by no unit over land (Arctic islands with no one
of 5,000) and belong to none. 412 links are longer than one step and are drawn
as routes.

**Jurisdictions**, units in a province: 227 in 1867, 240 in 1870, 300 in 1871,
305 in 1873, 417 in 1905, 436 in 1949, as expected. `opens_year`: 308 units
1867, 130 in 1870, one (the Arctic islands') 1880.

**Known and accepted, not worked round.**

- *Narrow water read as land.* Meridian's rule measures the hexagon edge, so a
  strait narrower than a hexagon is a land link. What it affects: Newfoundland
  joins the board by land across the Strait of Belle Isle (the Springdale–Happy
  Valley-Goose Bay bridge); Prince Edward Island has land links to New Brunswick
  (Summerside, Borden-Carleton and Alberton to Cap-Pelé) and Nova Scotia
  (Borden-Carleton–Amherst; Three Rivers to Stellarton, Westville and New
  Glasgow); Vancouver Island has land links to the mainland through the Gulf
  Islands and the Strait of Georgia (Qualicum Beach–Sechelt, Ladysmith–Gibsons,
  Nanaimo–Gibsons, Powell River to Qualicum Beach and Campbell River); Iqaluit
  reaches the mainland by land (the 61-step bridge). Within provinces, 43 unit
  links run between two hexagons whose drawn land does not touch: the St
  Lawrence estuary (Baie-Comeau and Saint-Siméon to Saint-Fabien), Georgian Bay
  (Gore Bay–Owen Sound), Howe Sound (Vancouver–Gibsons) and river and lake
  narrows. All are in `build_report.json`, `known_and_accepted.strait_links`.
- *Big lakes drawn as land.* Lake Winnipeg, Lake Manitoba, Great Slave Lake and
  Lac Saint-Jean are land in the layer, so routes run across them: Kenora to
  Arborg and Winnipeg Beach, Gimli–Dauphin, Dauphin–Portage la Prairie, High
  Level–Yellowknife, and the Lac Saint-Jean ring (Roberval, Alma,
  Dolbeau-Mistassini, Chibougamau). The list is by a box round each lake, so it
  takes in shore too (`routes_through_lakes_drawn_as_land`). Great Bear Lake,
  Lake Athabasca and Lake Nipigon carry no route.

## The engines

Everything that assumed 343: `TOTAL_RIDINGS` in both engines, as the founding
formula's denominator (`p_found`), now the map's unit count; `hoc sim status`'s
"of 343 held" and the play page's "Ridings N of 343", now the count; the story
pages' map label. `TOTAL_RIDINGS` stays as a constant for the tests that name
it. Under rules 1.0 `founding_curve` replaces `p_found`, so the change matters
to the hex board only under 0.9. Not changed, and calibrated to ridings rather
than assuming them: the region-weight drift (`(20 + room) // 20`) and the
`founding.json` notes that write "/ 343".

The cross-check: both engines byte-identical on the hex set under 1.0 for seeds
1867, 2 and 3 over 100 turns, and under 0.9 for seed 1867 over 120; on both
riding sets under 0.9 as before; the referee replays every scenario unchanged.

## The trial

`scripts/story_trial.py --rules-version 1.0` on ten seeds (1867–1876), 100
turns, every flag on, untuned: the riding column is `meridian-v1.0.3` (it
reproduces docs/STORY_DESIGN.md §6 exactly), the hex column
`meridian-hex-v1.0.4`. Mean (min–max). The full table, with every breakdown, is
[trial-table.md](trial-table.md).

| §6 measure | Ridings | Hexes |
|---|---|---|
| actions aimed at another house (≥ 30%) | 32% (27–36) | 30% (23–39) |
| passes a turn after 20 (≥ 0.33) | 0.34 (0.16–0.47) | 0.33 (0.17–0.57) |
| houses active at turn 100 (20–40) | 21.8 (18–30) | 22.7 (19–26) |
| houses fallen or removed (4–10) | 7.5 (6–12) | 8.5 (3–12) |
| lead changes (≥ 4) | 18.0 (3–27) | 17.9 (9–28) |
| longest lead (≤ 50) | 26.8 (15–52) | 27.8 (12–72) |
| chapters with top-eight churn (4) | 4.0 | 4.0 |
| ranks spanned by the top eight at 60 (≥ 3) | 3.2 (3–4) | 3.8 (3–5) |
| first at the reckoning Earl or higher (≥ 8 of 10) | 9 of 10 | **7 of 10** |
| a Marquis or Duke at 100 (≥ 8 of 10) | 10 of 10 | 10 of 10 |
| a Duke created (≥ 3 of 10) | 6 of 10 | 7 of 10 |
| headline at or above pause (40–65%) | 57% (43–63) | 55% (47–69) |
| Auto pauses (15–30%) | 24% (18–28) | 25% (17–33) |
| longest quiet run after 10 (≤ 3) | 0 | 0 |
| storylines of 5+ beats (≥ 8) | 32.1 | 31.3 |
| rise and decline storylines (≤ 20) | 12.8 (6–21) | 14.2 (7–19) |
| closed storylines without an outcome (0) | 0 | 0 |
| median rivalry, turns (4–10) | 9.1 (7–13) | 9.1 (5–15) |
| rivalries reconciled (≤ 40%) | 11% (4–23) | 17% (8–35) |
| rivalries ended decisively (≥ 25%) | 51% (38–58) | 44% (26–65) |
| contests resolved (20–35) | 22.9 (11–32) | **16.3 (6–43)** |
| attacker wins (35–60%) | 51% (34–64) | 54% (45–67) |
| claims answered (≥ 50%) | 61% (49–74) | 68% (55–78) |
| schemes resolved (≥ 60%) | 78% (74–84) | 79% (77–84) |
| median scheme, turns (3–6) | 3 | 3 |
| turns with 3+ cast schemes after 15 (≥ 80%) | 99% | 99% |
| median capital at 100 (30–70) | 45.2 (32–52.5) | 44.2 (35–54.5) |
| median influence at 100 (40–70) | 55.2 (39–70) | 56.8 (50–67) |
| median cohesion at 100 (55–85) | 81.7 (62–94.5) | **85.8 (72.5–96.5)** |
| crises with both camps (≥ 70%) | 92% | 91% |
| crises carried by the leaders (35–65%) | 40% (17–61) | 45% (11–72) |
| games ending with a reckoning | 10 of 10 | 10 of 10 |

The share of the map held (every unit, and by the founding regions):

| Held | Ridings: all | Hexes: all | Hexes: Maritime | Quebec | Ontario | Prairie | BC | North |
|---|---|---|---|---|---|---|---|---|
| Turn 25 (1891) | 21% | 17% | 16% | 25% | 33% | 3% | 8% | 0% |
| Turn 50 (1916) | 37% | 29% | 26% | 41% | 54% | 7% | 18% | 7% |
| Turn 75 (1941) | 29% | 23% | 22% | 30% | 47% | 5% | 14% | 3% |
| Turn 100 (1966) | 46% | 36% | 32% | 54% | 65% | 11% | 22% | 7% |

On ridings, by region at turn 100: Maritime 35%, Quebec 51%, Ontario 69%, Prairie
18%, BC 22%, North 7% (the rest in the full table).

**What the hex board misses untuned, and why I think so.** Three targets miss on
the mean: contests resolved (16.3 against 20–35), the first house at the
reckoning an Earl or higher (7 games of 10 against 8), and median cohesion (85.8,
just over 85). All three look like one cause: houses meet less. They claim about
as many units as on ridings (160 against 157 at turn 100) on a map of 439, so
they hold 36% of it rather than 46%, with more empty land between them: on these
ten seeds two houses share a border 21.3 times at turn 50 on hexes against 27.5
on ridings (31.6 against 36.9 at turn 100). Fewer borders, fewer claims pressed
to a contest (fewer held in a contest too: 7.2 rivalries a game against 11.3),
less strain on cohesion, and a slower climb in rank for the leader, whose rise
comes partly from contests won. The Earl figure is one game in ten either side of
the line and may be noise. The Prairie is held thinly (11% at 1966, against 18%
on ridings): it has 116 units on hexes against 65 ridings, opened by expansion
from the east as the 0.9 note intends, and the hexes make that distance real.

## What reads better and worse than ridings

Better:

- Every unit is the same size, so a holding's colour on the map is a fair
  picture of its weight; Toronto no longer vanishes and Nunavut no longer fills
  the screen.
- The empty country between settlements is drawn as land, washed in the nearest
  holder's colour within two hexagons, so a house's reach is visible beyond its
  units.
- Routes say where expansion can go, and an expansion along one is drawn along
  it.
- Units are named for real places ("takes Gimli", not "takes
  Selkirk—Interlake—Eastman").

Worse:

- The board is sparse in the west and north: a unit can be a dozen hexagons
  from its neighbour, and the routes there (Terrace–Whitehorse, Thompson–Iqaluit)
  are long lines over empty land.
- Straits and big lakes read as land (above), which a player sees on the map.
- 36 units carry a borrowed name, a town that lies in the next hexagon.
- The page is heavier: the hex replay page is about 600 KB against 330 KB, most
  of it the Arctic coast, though the static land is drawn in its own layer so a
  turn repaints only the units and their wilderness.

## The preview

`outputs/site/preview-hex/replay.html`, seed 1867, 1867–1966 under the 1.0
draft, linked from the riding preview's menu ("Preview on hexes (trial)") and
back ("Preview on ridings"). All land is drawn as neutral hexagons, units on top
in their holder's colour, a unit's wilderness within one and two hexagons tinted
faintly, routes as dotted lines, an expansion along a route drawn along it, and
the word "holding" in the counts and cards, from the set's `set.json`. The camera
comes no closer than about ten hexagons across.

Screenshots at 390 × 844: the opening of 1867, 1885, 1914, 1936 and 1966 (the
world's turn and the first notable house turn), and 1899 turn by turn
(`1899-NN-*.png`), a year with three expansions along routes.
