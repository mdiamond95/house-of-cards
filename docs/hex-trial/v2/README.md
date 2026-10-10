# The hex board on Meridian v1.0.5

The director chose hexes over ridings. This is the board rebuilt properly on
Meridian v1.0.5:
- city hexes;
- an opening year for every unit, which the draft rules now keep;
- the provincial and territorial borders of every year.

The preview at `outputs/site/preview-hex/` plays the draft on it. `rules/current.txt`
stays 0.9 and no scenario was created or played. The Dominion and both frozen
games replay unchanged.

**Step 3** (10 October 2026) tidied the set, added three flags to the 1.0 draft
and tuned it:
- city hexes named by the earlier rule (commit 064a93c), with compass words in
  place of riding tokens;
- opening years by the municipality a hex is named for, a core at its city's
  settled year;
- water rows and the director's ferry;
- `water_crossings`, `block_grants` and `land_rush`, with their numbers in
  `board.json`;
- an accession line no longer names land already open (Kenora, 1889);
- a jurisdiction's name that would crowd another is hidden;
- the draft tuned on ten seeds to every §6 and D1 target and the director's
  new ones.

## What was built

| Piece | Where |
|---|---|
| The pin: Meridian `v1.0.5`'s `hexes.r4.v1.2`, `hexes.r5.v1`, their two layers (the director's four hashes), and the mesh `mesh.v1.json.gz` (`f29ac1af…677`, recorded on the first fetch), refused on any other hash, format, version or unit | `scripts/fetch_meridian.py --board`, `data/reference/meridian/hex-v1.0.5/raw/` |
| The reference set `meridian-hex-v1.0.5`, in the six table shapes every set has | `scripts/build_world_hexboard.py`, `data/reference/meridian/hex-v1.0.5/` |
| The rules that turn the tables into integers | docs/DETERMINISM.md, "The hex board on v1.0.5" (rules 14–20) |
| `dated_openings`, a flag in the 1.0 draft, in both engines | `hoc/sim.py`, `web/engine/sim.js`; rules/README.md; rules/CHANGELOG.md |
| `water_crossings`, `block_grants` and `land_rush` (step 3), flags in the 1.0 draft, in both engines; their numbers in `rules/versions/1.0/board.json` | `hoc/sim.py`, `web/engine/sim.js`, `web/engine/state.js`, `web/engine/adjacency.js`; DETERMINISM, "The hex board's flags" |
| The rush's beat, its map mark and its sentence | `hoc/export/beats.py`, `web/story/beats.js`, `marks.js`, `text.js`, `weights.json` |
| The tuning, in the draft's tables | `upkeep.json`, `schemes.csv`, `schemes.json`, `board.json`; rules/CHANGELOG.md |
| The preview, on the new board | `scripts/build_preview.py`, `hoc/export/site.py`, `hoc/export/replay_js.py` |
| The trial | [trial-table.md](trial-table.md), [trial.json](trial.json) |
| Tests | `tests/test_hexboard.py`, `tests/test_dated_openings.py`, `tests/test_board_flags.py`, `tests/test_land_rush.py`, `tests/js/hexboard.e2e.mjs` |

`meridian-hex-v1.0.4`, the first trial's set, was removed once the preview played
on the new board. Its record is [../README.md](../README.md).

## `dated_openings`

The flag, approved by the director, is on in the 1.0 draft and false in 0.7–0.9,
in both engines. Under `world_calendar`:
- A unit takes no grant, no expansion and no claim before its opening year.
- That year is the later of `riding_stats.csv`'s `opens_year` and its first year
  under Canada in the atlas.
- From then on the unit is open for good, whatever the atlas says of a later year.
  The Ontario–Manitoba disputed area no longer drops out in 1881–1889.
- A Crown founding still needs a province that year.
- A unit that opens after it came under Canada opens as a quiet world event:
  "In the District of Alberta, one holding opens: Leduc."
- An accession names only the units it actually opens, and never a unit already
  open (step 3): Kenora opens in 1882 and is not named again when the disputed
  area joins Ontario in 1889.

**Why the later-of rule.** The riding sets' `opens_year` was built by 0.9's
rule, and reads 1867 for British Columbia, Prince Edward Island and
Newfoundland. Taking the atlas's first year as well makes the flag repeat the
atlas there. On the hex board `opens_year` is never earlier than the atlas, so
it changes nothing.

**On the riding sets.** The brief expected the games to be byte-identical with
the flag on and off. That holds on:
- `ne-2026`, seeds 1867, 2 and 3;
- `meridian-v1.0.3`, seeds 1867 and 2;
- nine of the trial's ten seeds (1867–1876).

It does not hold quite everywhere. The atlas takes two ridings out of Canada
and back: Nunavut (62001) is the British Arctic Islands' in 1876–1879, and
Labrador (10004) is Newfoundland's in 1927–1948. With the flag, both stay open:
- **`meridian-v1.0.3`, seed 3:** identical through 1876. In 1877 a frontier
  draw sees Nunavut among its candidates.
- **Seed 1874:** identical through 1932. In 1933 a house's scheme choice
  reads Labrador.
- **`meridian-v1.0.3`, seeds 1867 and 2** (step 3): the two stay open, so their
  return is not named again. Nunavut's 1880 line goes, and Newfoundland's 1949
  line names six ridings without Labrador. Nothing else differs.
`tests/test_dated_openings.py` holds all of this.

**On the hex board.** In 100-turn games on seeds 1867, 2 and 3, no unit is
held before its opening year. Before the flag, 30, 22 and 18 were.

## The board

**Units: 494.**
- 423 resolution-4 hexagons of 5,000 people or more.
- The 16 hexagons of 500,000 or more are split into city hexes. Of each one's
  cells, the units are those of 25,000 or more and its most populous cell, the
  core. That gives 16 cores and 55 others.
- Ids are nine digits, with the province first (DETERMINISM rule 16).

**Links.** The trial's rule, on the mixed board.

| | |
|---|---|
| Land links before the cap | 1,235 |
| Land-connected groups | 462, 15, 10, 5, 1, 1 |
| Land links after the cap (53 longer than 6 dropped) | 1,182 |
| Bridges kept over the cap | Fort Frances–Neebing 7, Thompson–The Pas 7, Happy Valley-Goose Bay–Wabush 10, Kapuskasing–Thunder Bay 12, High Level–Yellowknife 13, Terrace–Whitehorse 20 |
| Water links (all in `links.csv`) | 92 |
| Water rows in `adjacency.csv` (3 hexagons or fewer, and the ferry) | 83 |
| Groups through the land and water rows together | 2: 493 units, and Iqaluit |

**Water rows** (step 3). `adjacency.csv` keeps a water row only for a water link
of 3 hexagons or fewer, plus the director's ferries. A longer water link stays in
`links.csv` only, marked `in_adjacency = 0`. Nine do:
- Springdale–Happy Valley-Goose Bay, 13 steps (the Strait of Belle Isle);
- Thompson–Iqaluit, 61;
- Bay Roberts–Marystown and Holyrood–Marystown, 4 each (across Placentia and
  Conception Bays);
- Gore Bay–Owen Sound, 4;
- four inland, where two units' territories meet only across water: The
  Pas–Gillam 8, Teulon–Dauphin 5, Fort St. John–Prince George 9 and Fort St.
  John–Vanderhoof 9.

**The ferry, by the director's decree (10 October 2026).** Cape Breton to the
Newfoundland unit whose hinterland holds Channel-Port aux Basques: Stephenville,
8 steps across the Cabot Strait. It is a water row of `adjacency.csv` and
`ferry = 1` in `links.csv`.

Through the land and water rows together, every island group reaches the
mainland:
- Newfoundland by the ferry;
- Vancouver Island across the Strait of Georgia;
- Prince Edward Island across Northumberland Strait;
- Les Îles-de-la-Madeleine by its link to Three Rivers.

**Iqaluit stays unreachable.** Its one link, 61 steps from Thompson, is not a
row, so no house can expand there. It is a territory all game, so no Crown
founding reaches it either. With `water_crossings` off, the 32 island units are
reachable by founding alone, as before.

## Names

A resolution-4 unit is named as in the trial: its own largest unused town, or
municipality, else one borrowed from the nearest hexagons.

**A city or core hex is named for its municipality** by the rule of commit
064a93c, which the director restored at step 3 (DETERMINISM rule 17). The
municipality is the first of these that holds:
1. the census subdivision Meridian's mesh gives the cell, when it holds at
   least the cell's people and no town in the cell is larger;
2. else the cell's own largest place, when it holds a tenth of the cell's
   people;
3. else the neighbouring municipality, by the same people test.

Where several units carry one municipality, the unit holding the
municipality's own place keeps the plain name. Every other adds the compass
word of its bearing from the plain-named unit: "Toronto East", "Ottawa
South-West". That word replaces the riding token the earlier build added.

**Names by source:** the mesh's municipality 20, with a compass word 13; the
hex's own largest place 29; a neighbouring municipality with a compass word 9.
No city hex borrows, and no rural hexagon borrows a city's name: the build fails
if one would.

**One collision.** Two hexes fell on one bearing from Calgary: Calgary North-West
and **Calgary Outer North-West** (the next ring's word). No numeral was needed.

**The 71 city and core names**, by split parent, with their opening years:

| Parent | City hexes |
|---|---|
| Toronto | Toronto East (core) 1867; Toronto 1867; Toronto South-East 1867; Mississauga 1867; Brampton 1867; Markham 1867; Vaughan 1867 |
| Montréal | Montréal (core) 1867; Montréal West 1867; Laval 1867; Montréal North-East 1867; Blainville 1867; Terrebonne 1867; Sainte-Sophie 1867 |
| Vancouver | Vancouver (core) 1871; Burnaby 1871; Richmond 1871; Delta 1871 |
| Ottawa | Gatineau (core) 1867; Ottawa 1867; Ottawa East 1867; Ottawa South-East 1867; Ottawa West 1867; Gatineau West 1867; Ottawa South-West 1867 |
| Hamilton | Mississauga West (core) 1867; Oakville 1867; Burlington 1867; Milton 1867; Hamilton 1867 |
| Surrey | Surrey (core) 1871; Coquitlam 1871; Maple Ridge 1871; Langley 1871; Mission 1871 |
| Calgary | Calgary (core) 1875; Calgary North-West 1894; Calgary South 1894; Calgary South-West 1894 |
| Kitchener | Kitchener (core) 1867; Cambridge 1867; Guelph 1867; Waterloo 1867; Centre Wellington 1867 |
| Winnipeg | Winnipeg (core) 1870; Winnipeg North-West 1873; Winnipeg West 1873 |
| Strathcona County | Edmonton East (core) 1870; Strathcona County South 1870; Edmonton North-East 1904; Strathcona County 1870 |
| Longueuil | Longueuil (core) 1867; Chambly 1867; Beloeil 1867; Saint-Hyacinthe 1867; Sainte-Julie 1867 |
| Oshawa | Oshawa (core) 1867; Pickering 1867; Whitchurch-Stouffville 1867 |
| Airdrie | Calgary North (core) 1875; Airdrie 1899; Calgary Outer North-West 1894 |
| Québec | Québec (core) 1867; Québec East 1867; Lévis 1867 |
| Haldimand County | Hamilton South-East (core) 1867; Grimsby 1867 |
| London | London (core) 1867; Thames Centre 1867; Middlesex Centre 1867; St. Thomas 1867 |

The cities the step-3 brief named are all back: Kitchener, Waterloo, Guelph,
Burnaby, Markham, Oshawa, St. Thomas, Airdrie, Saint-Hyacinthe, Beloeil,
Chambly, Sainte-Julie, Blainville and Terrebonne.

## Opening years

By the director's rules (DETERMINISM rule 18). A unit opens at the latest of:
- **(a) The atlas:** the first year its land is under Canada.
- **(b) Its `settledYear`:** this counts only when the land came under Canada
  after 1867, and only when it is 1930 or earlier.
  - A resolution-4 unit's is its own row's.
  - A city or core hex takes the dates of the municipality it is named for.
    The tables date a municipality only where some row names it as its settled
    place.
- **(c) The city year:** only for a city hex that is not a core, when its
  municipality has one. A core opens at its municipality's settled year, so
  only the outer city hexes wait for the city year (step 3).

**The director's twelve overrides** beat every part. `units.csv` records each
part.

So Edmonton's core (Edmonton East) opens in 1870, and north Calgary (Calgary
North, the core of its parent hexagon) in 1875 with Calgary. No hex named
Calgary opens before 1875.

| Year | Units open |
|---|---|
| 1867 | 261 |
| 1885 | 400 |
| 1914 | 458 |
| 1945 | 472 |
| 1966 | 494 |

**Every unit opening after 1914** (* an override):

| Opens | Units |
|---|---|
| 1918 | Barraute, La Sarre, Preissac (QC) |
| 1919 | Kirkland Lake (ON), Peace River (AB), Teulon (MB) |
| 1926–1928 | Vanderhoof (BC) 1926, Terrace (BC) 1927, Beaverlodge (AB) 1928 |
| 1931–1939 | Meadow Lake (SK) 1931 \*, Dawson Creek (AB) 1932 \*, Yellowknife (NT) 1936 \*, Baie-Comeau (QC) 1937 \*, Malartic (QC) 1939 \* |
| 1947 | Fort St. John (BC) \* |
| 1949 | Newfoundland's 16: Bay Roberts, Bonavista, Clarenville, Corner Brook, Gander, Grand Falls-Windsor, Happy Valley-Goose Bay, Holyrood, Lewisporte, Marystown, Mount Moriah, Pouch Cove, Springdale, St. John's, Stephenville, Twillingate |
| 1952–1956 | Chibougamau (QC) 1952 \*, Kitimat (BC) 1953 \*, Elliot Lake (ON) 1955 \*, Wabush (QC) 1955 \*, Thompson (MB) 1956 \* |

**Every unit in Ontario, Quebec and the Maritimes that opens after 1867**:

| | Units |
|---|---|
| **Old Ontario and Quebec** (land under Canada in 1867), all by override | Greater Sudbury 1883, Baie-Comeau 1937, Elliot Lake 1955, Wabush 1955 (its hexagon is mostly Quebec) |
| **Prince Edward Island** (Canada from 1873) | Borden-Carleton, Charlottetown, Summerside and Three Rivers 1873; Alberton 1901 (settled) |
| **Northern Ontario** (Rupert's Land in 1867), by settlement | Kenora 1882, Dryden 1895, Fort Frances 1899, Iroquois Falls 1908, Kapuskasing 1911, Timmins 1912, Kirkland Lake 1919 |
| **Northern Quebec** (Rupert's Land in 1867), by settlement | Barraute, La Sarre and Preissac 1918 |
| **Northern Quebec**, by override | Malartic 1939, Chibougamau 1952 |

Nothing in Nova Scotia or New Brunswick opens after 1867.

**City years.** The adviser's years agree with The Canadian Encyclopedia for
all but Québec, which is corrected from 1832 to 1833. The Encyclopedia and the
City's chronology date its first charter to 1833; 1832 is the Act. Every
source is in the script and the report.

A caveat on the sources: they were read through search results, because this
environment's network policy refused the pages themselves.

The city years open only outer city hexes:
- Winnipeg North-West and Winnipeg West, 1873;
- Calgary North-West, Calgary South, Calgary South-West and Calgary Outer
  North-West, 1894;
- Edmonton North-East, 1904.

Airdrie opens at its own settled year, 1899. Every other city year predates
the atlas, so those hexes open with it.

## `water_crossings` and `block_grants` (step 3)

Both flags are in the 1.0 draft only, in both engines, and false in 0.7–0.9.
Their numbers are in `rules/versions/1.0/board.json`.

**`water_crossings`.** A water row of `adjacency.csv` counts as adjacency for:
- expansion targets;
- claim targets;
- neighbouring houses (bordering pairs, an adjacent holding, a forced sale's
  buyer).

An Expand across water costs `expand_cost` (5) more capital: a water row joins
the target to one of the house's holdings and no land row does. Enclosure,
cohesion strain, contiguity, the founding room and designations stay land only.

**`block_grants`.** A Crown founding on a resolution-4 hexagon also grants up to
`extra_hexes` (2) of the seat's land neighbours that are open at the founding
year, unclaimed and resolution 4. They are taken most populous first, ties to
the lower fed_id, so no draw is made. A founding on a city hex grants that hex
alone. The engines read a unit's resolution from `riding_stats.csv`'s new
`resolution` column, not from `units.csv`: it is a table both engines and the
browser already load, and it is absent on the riding sets.

**On the riding sets**, which have no water rows and no `resolution` column,
the season files are identical with both flags on and off: seeds 1867, 2 and
3, over 100 turns, on both sets. The riding preview is unchanged.

**On the hex board**, seed 1867:
- 16 of 30 foundings are granted a block, 31 hexagons in all;
- 8 expansions cross water.

## `land_rush` (step 3)

A third flag in the 1.0 draft, in both engines, false in 0.7–0.9; its numbers
are in `board.json`. Under `world_calendar`:
- **When.** Each jurisdiction the atlas first has as a province after 1867
  has a rush there for `land_rush.years` (6), from that year: Manitoba 1870,
  British Columbia 1871, Prince Edward Island 1873, Alberta and Saskatchewan
  1905, Newfoundland 1949. The brief named the "extension" event. British
  Columbia, Prince Edward Island and Newfoundland join as provinces, which the
  engine records as an accession, so "a jurisdiction becomes a province" is
  read as either. Land joining a province later (Ontario 1889, Manitoba 1881
  and 1912) starts no rush, and units opening later in a rushing province do
  not restart one.
- **The Crown's roll.** In each rush year, while fewer than `until_held_pct`
  (25%) of the province's open units are held, the Crown makes one extra
  founding roll at `roll_pct` (40%) among its open, unclaimed units. The roll
  comes after the founding roll, and the season record lists the houses it
  founds as `rushed`. A rush founding takes its block like any other.
- **Cheaper land.** An Expand into a unit of a rushing province costs
  `expand_discount` (5) less.
- **On the map.** A rush is a world event: "A land rush opens in Alberta: for
  six years the Crown founds there more readily, and its 62 open holdings cost
  less to take." Its first year is a `rush` beat drawn on the province's open
  land, and each later year an `event_continues` chip ("Land rush in Alberta,
  year 3 of 6").
- **On the riding sets** it does not run unless `land_rush.riding_sets` is 1,
  which only its own test sets. Both riding sets play the same game with it on
  and off (`tests/test_land_rush.py`).

The brief's start values were 8 years and 50%. The tuning below took them to 6
and 40%.

## Borders by year

`jurisdictions.geojson` holds 21 spans of years, from 1867 to today. Each holds
the lines between first-order jurisdictions along hexagon edges, and each
jurisdiction's name, sovereign and status, at the hexagon deepest inside it.

A span ends when any of these changes:
- a line moves;
- a name changes;
- a jurisdiction's sovereign or status changes (Prince Edward Island in 1873,
  Newfoundland in 1949).

**First-order.** A district is part of the North-West Territories, except
Keewatin from 1876 to 1904, as Natural Resources Canada's *Territorial
Evolution* has it.

## The preview

`outputs/site/preview-hex/replay.html`, seed 1867, 1867–1966 under the 1.0 draft,
the same view as before, plus:
- **City hexes** are drawn at their own size. The camera comes within about
  seven of them, 24 map units across against 90 before.
- **A unit not yet open** is drawn closed, with the atlas's hatch, and opens on
  its year. Its card says "Not yet open: it opens in 1894." Its opening is a
  quiet event on the world's turn.
- **The provincial and territorial borders** of the year shown are drawn as a
  dashed line, and change on the years the atlas changes. Land not under
  Canada is named in italic.
- **Jurisdiction names** are drawn at wide zoom. A name that would come within
  6 px of another name, a badge or a house's name is hidden, never crowded in
  (step 3). Each name is measured as it is drawn, so none runs off a 390 px
  screen. A name gives way to the turn's houses but not to the standings'.
- **A land rush** is marked on the province's open land on its first year.

The riding preview plays the same draft on `meridian-v1.0.3`. The tuning moved
it too: see the trial below.

**Screenshots at 390 × 844** (this directory):
- the country in `country-1875`, `-1900`, `-1915`, `-1950` and `-1966`, and the
  border years `country-1867`, `-1871`, `-1905` and `-1949`;
- `pei-1880`, `vancouver-island-1900` and `newfoundland-1955`;
- `kitchener-1870` and `edmonton-1870`;
- `toronto-1867`, `winnipeg-1872` and `-1874`, `calgary-1893` and `-1895`;
- one rush year, 1905, turn by turn (`1905-NN-*`): Alberta and Saskatchewan
  become provinces and their rushes open.

## The trial

`scripts/story_trial.py --rules-version 1.0 --reference meridian-hex-v1.0.5`,
ten seeds (1867–1876), 100 turns. The full table is
[trial-table.md](trial-table.md), with the seeds in [trial.json](trial.json).
It has four columns:
- **step 2**: `dated_openings` on the step-2 set, as measured on 10 October;
- **step 3 as it stands**: the corrected set, with `water_crossings` and
  `block_grants`, untuned;
- **three flags, untuned**: `land_rush` at the brief's start values (8 years,
  50%);
- **three flags, tuned**.

`story_trial.py` now also measures the islands, the Prairies before 1896, and
Prairie and BC at turn 100. Its `--set TABLE.KEY=N` tries a number without
changing a table. The step-2 column predates those measures.

| measure (target) | Step 2 | Step 3 | Three flags, untuned | **Three flags, tuned** |
|---|---|---|---|---|
| actions aimed at another house (≥ 30%) | 30% | 32% | 33% | **32%** |
| passes a turn after 20 (≥ 0.33) | 0.34 | 0.49 | 0.58 | **0.55** |
| houses active at turn 100 (24–40) | 21.9 | 21.5 | 35.9 | **37.1** |
| houses fallen or removed (4–10) | 9.3 | 10.6 | 11.8 | **8.9** |
| lead changes (≥ 4) | 17.6 | 17.8 | 16.4 | **18.0** |
| longest lead (≤ 50) | 22.7 | 28.4 | 30.9 | **26.0** |
| chapters II–V with top-eight churn (4) | 4.0 | 4.0 | 4.0 | **4.0** |
| ranks spanned by the top eight at 60 (≥ 3) | 3.4 | 3.6 | 3.6 | **3.5** |
| first at the reckoning Earl or higher (≥ 8 of 10) | 10 | 8 | 10 | **10** |
| a Marquis or Duke at 100 (≥ 8 of 10) | 10 | 10 | 10 | **10** |
| a Duke created (≥ 3 of 10) | 8 | 7 | 8 | **9** |
| headline at or above pause (40–65%) | 54% | 60% | 64% | **60%** |
| Auto pauses (15–30%) | 27% | 29% | 31% | **29.6%** |
| storylines of 5+ beats (≥ 8) | 29.6 | 34.3 | 48.7 | **44.7** |
| rise and decline storylines (≤ 20) | 11.0 | 16.5 | 20.6 | **19.0** |
| median rivalry, turns (4–10) | 7.9 | 7.0 | 8.2 | **8.5** |
| rivalries reconciled (≤ 40%) | 16% | 14% | 17% | **15%** |
| rivalries ended decisively (≥ 25%) | 50% | 54% | 47% | **48%** |
| contests resolved (20–35) | 20.5 | 22.1 | 31.2 | **32.0** |
| attacker wins (35–60%) | 52% | 64% | 57% | **54%** |
| claims answered (≥ 50%) | 63% | 62% | 65% | **64%** |
| schemes resolved (≥ 60%) | 80% | 77% | 77% | **79%** |
| median capital at 100 (30–70) | 49.0 | 44.2 | 40.6 | **49.8** |
| median influence at 100 (40–70) | 56.8 | 54.5 | 53.5 | **47.5** |
| median cohesion at 100 (55–85) | 77.0 | 72.2 | 76.6 | **73.3** |
| crises with both camps (≥ 70%) | 91% | 91% | 92% | **92%** |
| map held at turn 100 (40–60%) | 34% | 35% | 54% | **56%** |
| Prairie held at turn 100 (≥ 30%) | 9% | 5% | 45% | **34%** |
| BC held at turn 100 (≥ 30%) | 13% | 14% | 44% | **48%** |
| Prairies held before 1896, the most in a turn (< 10%) | — | 2% | 9% | **7%** |
| PEI held at 100 (≥ 7 of 10) | — | 6 | 8 | **10** |
| Vancouver Island held at 100 (≥ 7 of 10) | — | 4 | 8 | **8** |
| Newfoundland held at 100 (≥ 7 of 10) | — | 0 | 10 | **8** |

**Tuned, every §6 and D1 target and each of the director's new ones is met on
the mean.** The rush is what fills the West and the islands: Newfoundland had
no holder at turn 100 on any seed without it.

The tuning, all in the draft's tables (rules/CHANGELOG.md):

| Table | Number | Was | Now |
|---|---|---|---|
| `upkeep.json` | `cohesion.recovery` | 3 | 5 |
| `schemes.csv` | Secure the line, `utility` | 55 | 70 |
| `schemes.csv` | Claim a riding, `utility` | 20 | 15 |
| `schemes.json` | `contest.committed_per_point` | 15 | 18 |
| `board.json` | `land_rush.roll_pct` | 50 | 40 |
| `board.json` | `land_rush.years` | 8 | 6 |

Why these:
- **The removals** came from absorption (about 6 a game), disorderly
  successions with no successor (about 3) and cohesion collapse (about 2.5).
  Faster cohesion recovery, and a house more ready to name an heir, cut all
  three.
- **Fewer houses fell, so more lived.** The smaller rush (40%, 6 years) keeps
  houses active at 100 inside 24–40, and the map held under 60%.
- **The claims.** A lower claim utility keeps contests under 35. A dearer point
  of committed capital brings attacker wins to 54%.
- **The cooldown is untouched.** Lengthening the contest cooldown instead left
  a chapter without top-eight churn on some seeds.

**Where it is thin.** The worst seed holds 12% of the Prairies before 1896
(the mean is 7%). Auto pauses are 29.6% against a ceiling of 30%, and rise and
decline storylines 19.0 against 20. These numbers are fitted to these ten
seeds.

**What it does to the riding preview.** The same draft on `meridian-v1.0.3`
now misses three targets: median cohesion 86.2 (55–85), median rivalry 11.2
turns (4–10) and attacker wins 60.1% (35–60%). The brief tuned the hex board
only, so this is the director's call.

**The share of the map held, tuned** (step 3 untuned in brackets):

| Held | Maritime | Quebec | Ontario | Prairie | BC | North |
|---|---|---|---|---|---|---|
| Turn 25 (1891) | 30% (28%) | 27% (31%) | 38% (40%) | 6% (2%) | 21% (6%) | 0% (0%) |
| Turn 100 (1966) | 56% (31%) | 62% (52%) | 80% (67%) | 34% (5%) | 48% (14%) | 0% (0%) |

**Units open**: 261 in 1867, 400 in 1885, 458 in 1914, 472 in 1945, 494 in 1966.
This is the same on every seed, being the data's.

## What does not read well

- **The North is never held** at turn 100, tuned:
  - Whitehorse opens in 1898 and Yellowknife in 1936, at the ends of long
    bridges.
  - Iqaluit can't be reached at all: no land row and no water row of 3 hexes
    or fewer joins it.
  - No territory becomes a province, so no rush runs there.
- **Names the rule gives.** The restored rule is the one the director chose, so
  these are as the data has them:
  - Hamilton's core is "Mississauga West", named for the neighbouring
    municipality;
  - London's outer hexes are Thames Centre and Middlesex Centre, and two of
    Edmonton's are Strathcona County and Strathcona County South.
- **The cores aren't always named for their cities.** Toronto's core is
  "Toronto East", and the plain "Toronto" goes to the hex holding Toronto's own
  place. Edmonton's core is "Edmonton East" beside the resolution-4 "Edmonton".
- **Hidden jurisdiction names.** At 390 px on the whole country, a name that
  would crowd a badge or a house is hidden. In 1905 British Columbia, Alberta,
  Saskatchewan, Ontario and Quebec go unnamed beside the rush's badges and the
  houses' names.
- **Wikidata's settlement dates are sometimes incorporations.** They now count
  only after 1867 and to 1930, which drops Camrose's 1944 and Calmar's 1949.
  Some late ones remain: Barraute, La Sarre and Preissac 1918, Teulon 1919,
  Terrace 1927.
- **"Lloydminster (Part)"** is still the census place's name.

## Checks

- **The tests:**
  - `tests/test_hexboard.py`: units, unique names, the restored names with the
    fourteen cities, symmetric links, the land groups, water rows and the ferry,
    the opening rules, no unit held before its year on three seeds, no float
    in a table an engine reads, both engines on three seeds.
  - `tests/test_dated_openings.py`: the flag on the riding sets, and the
    dropped lines for land already open.
  - `tests/test_board_flags.py` and `tests/test_land_rush.py`: the three flags.
  - `tests/js/hexboard.e2e.mjs`, through `tests/test_mapview.py`: closed units,
    borders by year, names that never overlap, Edmonton's core in 1870.
- **The cross-checks:**
  - under 1.0 on this set, seeds 1867, 2 and 3 over 100 turns: byte-identical;
  - under 1.0 on `meridian-v1.0.3`, seed 3 over 100 turns: byte-identical;
  - under 0.9 on both riding sets.
- **The rest:** the full suite, node tests, the map view's browser checks at
  three sizes on both previews, and the referee on every scenario. The results
  are in the PR.
