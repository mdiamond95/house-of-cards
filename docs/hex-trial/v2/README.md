# The hex board on Meridian v1.0.5

The director chose hexes over ridings. This is the board rebuilt properly on
Meridian v1.0.5:
- city hexes;
- an opening year for every unit, which the draft rules now keep;
- the provincial and territorial borders of every year.

The preview at `outputs/site/preview-hex/` plays the draft on it. `rules/current.txt`
stays 0.9 and no scenario was created or played. The Dominion and both frozen
games replay unchanged.

**Step 3** (10 October 2026) tidied the set and added two flags to the 1.0 draft:
- city hexes named for their own municipality, with compass words;
- opening years by municipality;
- water rows and the director's ferry;
- `water_crossings` and `block_grants`, with their numbers in `board.json`.

The brief's third flag, `land_rush`, and its tuning step arrived cut off, and
wait on the rest of it.

## What was built

| Piece | Where |
|---|---|
| The pin: Meridian `v1.0.5`'s `hexes.r4.v1.2`, `hexes.r5.v1`, their two layers (the director's four hashes), and the mesh `mesh.v1.json.gz` (`f29ac1af…677`, recorded on the first fetch), refused on any other hash, format, version or unit | `scripts/fetch_meridian.py --board`, `data/reference/meridian/hex-v1.0.5/raw/` |
| The reference set `meridian-hex-v1.0.5`, in the six table shapes every set has | `scripts/build_world_hexboard.py`, `data/reference/meridian/hex-v1.0.5/` |
| The rules that turn the tables into integers | docs/DETERMINISM.md, "The hex board on v1.0.5" (rules 14–20) |
| `dated_openings`, a flag in the 1.0 draft, in both engines | `hoc/sim.py`, `web/engine/sim.js`; rules/README.md; rules/CHANGELOG.md |
| `water_crossings` and `block_grants` (step 3), flags in the 1.0 draft, in both engines; their numbers in `rules/versions/1.0/board.json` | `hoc/sim.py`, `web/engine/sim.js`, `web/engine/state.js`, `web/engine/adjacency.js`; DETERMINISM, "The hex board's flags" |
| The preview, on the new board | `scripts/build_preview.py`, `hoc/export/site.py`, `hoc/export/replay_js.py` |
| The trial | [trial-table.md](trial-table.md), [trial.json](trial.json) |
| Tests | `tests/test_hexboard.py`, `tests/test_dated_openings.py`, `tests/test_board_flags.py`, `tests/js/hexboard.e2e.mjs` |

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
- An accession names only the units it actually opens.

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

The riding preview (seed 1867) plays the same game.
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

**A city or core hex is named for its own municipality** (step 3; DETERMINISM
rule 17): the census subdivision Meridian's mesh gives its cell, never a
neighbouring one, and with no riding token. Where several units carry one
municipality, the unit holding the municipality's own place keeps the plain
name. Every other adds the compass word of its bearing from it: "Toronto East",
"Ottawa South-West".

Two hexes fell on one bearing from the same plain-named unit once: Rocky View
County West and **Rocky View County Outer West** (the next ring's word). No
numeral was needed.

The 71 city and core names, by split parent, with their opening years:

| Parent | City hexes |
|---|---|
| Toronto | Toronto East (core) 1867; Toronto 1867; Toronto South-East 1867; Mississauga 1867; Brampton 1867; Richmond Hill 1867; Vaughan 1867 |
| Montréal | Montréal (core) 1867; Montréal West 1867; Laval 1867; Montréal North-East 1867; Mirabel South-East 1867; Mascouche 1867; Sainte-Anne-des-Plaines 1867 |
| Vancouver | Vancouver (core) 1871; Delta North 1871; Richmond 1871; Delta 1871 |
| Ottawa | Gatineau (core) 1867; Ottawa 1867; Ottawa East 1867; Ottawa South-East 1867; Ottawa West 1867; Pontiac South 1867; Ottawa South-West 1867 |
| Hamilton | Halton Hills (core) 1867; Oakville 1867; Burlington 1867; Milton 1867; Hamilton 1867 |
| Calgary | Calgary (core) 1875; Calgary North-West 1894; Foothills County North-East 1870; Foothills County North 1870 |
| Surrey | Surrey (core) 1871; Coquitlam 1871; Maple Ridge 1871; Langley 1871; Mission 1871 |
| Kitchener | Wilmot (core) 1867; Cambridge 1867; Guelph/Eramosa 1867; Woolwich 1867; Centre Wellington 1867 |
| Winnipeg | Winnipeg (core) 1870; Rosser 1870; Macdonald 1870 |
| Longueuil | Longueuil (core) 1867; Saint-Jean-sur-Richelieu North-East 1867; Saint-Jean-Baptiste 1867; La Présentation 1867; Saint-Marc-sur-Richelieu 1867 |
| Strathcona County | Edmonton East (core) 1904; Strathcona County South 1870; Sturgeon County South-West 1870; Strathcona County 1870 |
| Oshawa | Whitby (core) 1867; Pickering 1867; Whitchurch-Stouffville 1867 |
| Québec | Québec (core) 1867; Lévis North-East 1867; Lévis 1867 |
| Haldimand County | Hamilton South-East (core) 1867; Grimsby 1867 |
| Airdrie | Calgary North (core) 1894; Rocky View County West 1870; Rocky View County Outer West 1870 |
| London | London (core) 1867; Thames Centre 1867; Middlesex Centre 1867; Central Elgin 1867 |

**Cities left without a hex of their name.** The mesh gives a cell the
municipality covering most of its land, so a city that is small in area can
cover no cell: Kitchener, Waterloo, Guelph, Burnaby, New Westminster, Markham,
Airdrie, Saint-Hyacinthe, Beloeil, Chambly, Sainte-Julie, Blainville,
Terrebonne, Repentigny, Brossard, Ajax and Port Coquitlam.

Their places are then free for the trial's borrowing rule:
- "Oshawa" now names a rural resolution-4 hexagon beside the city;
- "St. Thomas" names one beside St. Thomas.

## Opening years

By the director's rules (DETERMINISM rule 18). A unit opens at the latest of:
- **(a) The atlas:** the first year its land is under Canada.
- **(b) Its `settledYear`:** this counts only when the land came under Canada
  after 1867, and only when it is 1930 or earlier.
  - A resolution-4 unit's is its own row's.
  - A city or core hex's is that of the municipality it is named for (step 3).
    The tables date a municipality only where some row names it as its settled
    place.
- **(c) The city year:** for every hex of a city's municipality but the
  plain-named one. The plain-named hex opens at the settled year alone.

**The director's twelve overrides** beat every part. `units.csv` records each
part.

North Calgary (Calgary North, Airdrie's core) now opens in 1894 with Calgary's
other extra hexes; Calgary itself opens in 1875.

| Year | Units open |
|---|---|
| 1867 | 261 |
| 1885 | 403 |
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

The city years now open:
- Calgary North-West and Calgary North, 1894;
- Edmonton East, 1904.

The rest of a city's extra hexes date from before 1867 and open with the atlas:
- Ottawa's four;
- Toronto's two (Toronto East, the core, among them);
- Montréal's two;
- Hamilton South-East.

Winnipeg's other hexes are Rosser and Macdonald, other municipalities, so they
open with Manitoba in 1870. Vancouver's, Kitchener's, Longueuil's, Oshawa's and
London's years open no hex.

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
  dashed line, and change on the years the atlas changes. At wide zoom the
  jurisdictions are named. Land not under Canada is named in italic. A name
  gives way to the turn's houses but not to the standings'.

The riding preview plays the same game as before.

**Screenshots at 390 × 844** (this directory):
- `toronto-1867`;
- `winnipeg-1872` and `winnipeg-1874`;
- `calgary-1893` and `calgary-1895`;
- `country-1867`, `country-1871`, `country-1905` and `country-1949`;
- 1912 turn by turn (`1912-NN-*`).

## The trial

`scripts/story_trial.py --rules-version 1.0`, ten seeds (1867–1876), 100 turns,
untuned. The full table is [trial-table.md](trial-table.md), with the seeds in
[trial.json](trial.json). It has five columns:
- the first trial's ridings and hexes (measured on 9 October, before
  `dated_openings`);
- ridings now;
- the hex board at step 2 (`dated_openings`, the old names and every water
  link);
- **the hex board at step 3**: the tidied set (names, opening years, water rows
  of 3 hexes or fewer and the ferry), with `water_crossings` and
  `block_grants` on.

| §6 measure | Ridings now | Hexes v1.0.4 | Hexes v1.0.5, step 2 | **Hexes v1.0.5, step 3** |
|---|---|---|---|---|
| actions aimed at another house (≥ 30%) | 32% | 30% | 30% | 32% (27–39) |
| passes a turn after 20 (≥ 0.33) | 0.35 | 0.33 | 0.34 | **0.47** (0.35–0.56) |
| houses active at turn 100 (20–40) | 22.1 | 22.7 | 21.9 | 21.6 (17–28) |
| houses fallen or removed (4–10) | 7.5 | 8.5 | 9.3 | **10.9** (5–17) |
| lead changes (≥ 4) | 18.2 | 17.9 | 17.6 | 18.6 |
| longest lead (≤ 50) | 26.7 | 27.8 | 22.7 | 26.6 (12–51) |
| ranks spanned by the top eight at 60 (≥ 3) | 3.2 | 3.8 | 3.4 | 3.6 (3–4) |
| first at the reckoning Earl or higher (≥ 8 of 10) | 10 | 7 | 10 | 9 |
| a Marquis or Duke at 100 (≥ 8 of 10) | 10 | 10 | 10 | 10 |
| a Duke created (≥ 3 of 10) | 6 | 7 | 8 | 8 |
| headline at or above pause (40–65%) | 57% | 55% | 54% | 59% |
| Auto pauses (15–30%) | 24% | 25% | 27% | 29% (22–35) |
| storylines of 5+ beats (≥ 8) | 32.4 | 31.3 | 29.6 | 29.9 |
| rise and decline storylines (≤ 20) | 12.9 | 14.2 | 11.0 | 15.2 |
| median rivalry, turns (4–10) | 9.7 | 9.1 | 7.9 | 6.7 |
| rivalries reconciled (≤ 40%) | 10% | 17% | 16% | 14% |
| rivalries ended decisively (≥ 25%) | 51% | 44% | 50% | 54% |
| contests resolved (20–35) | 22.8 | 16.3 | 20.5 | 21.8 (14–30) |
| attacker wins (35–60%) | 51% | 54% | 52% | **60%** (46–72) |
| claims answered (≥ 50%) | 62% | 68% | 63% | 65% |
| schemes resolved (≥ 60%) | 78% | 79% | 80% | 79% |
| median capital at 100 (30–70) | 44.8 | 44.2 | 49.0 | 39.9 |
| median influence at 100 (40–70) | 55.3 | 56.8 | 56.8 | 54.2 |
| median cohesion at 100 (55–85) | 82.0 | 85.8 | 77.0 | 76.5 |
| crises with both camps (≥ 70%) | 92% | 91% | 91% | 91% |
| games ending with a reckoning | 10 | 10 | 10 | 10 |

At step 3, every §6 target but one is met on the mean:
- **Houses fallen or removed** is 10.9, over the 4–10 band. Seed 1875 loses
  17, and six seeds lose more than 10.
- **Attacker wins** sits on the band's top edge (60%).
- Seed 1875 is also the one whose first house at the reckoning is below Earl.

What the two flags did:
- **More land changes hands.** Passes after turn 20 rose from 0.34 to 0.47 a
  turn, and ridings passing between houses from 27.6 to 37.9 a game.
- **The map fills faster at the start.** Units claimed at turn 25 rose from
  71.9 to 102.4, and Quebec is 35% held at turn 25 against 17%.
- **Capital is tighter.** The median at 100 is 39.9, down from 49.0. The
  trial does not say which flag, or the tidied set, accounts for it.

These are untuned. Tuning waits on the director's instructions, as does
`land_rush`.

**The share of the map held, step 3** (step 2 in brackets):

| Held | All units | Maritime | Quebec | Ontario | Prairie | BC | North |
|---|---|---|---|---|---|---|---|
| Turn 25 (1891) | 21% (15%) | 20% (16%) | 35% (17%) | 31% (28%) | 7% (4%) | 10% (5%) | 0% (0%) |
| Turn 50 (1916) | 30% (27%) | 29% (25%) | 49% (38%) | 47% (52%) | 10% (8%) | 14% (8%) | 0% (0%) |
| Turn 75 (1941) | 25% (24%) | 21% (15%) | 37% (34%) | 44% (49%) | 7% (6%) | 11% (8%) | 3% (0%) |
| Turn 100 (1966) | 37% (34%) | 36% (27%) | 56% (49%) | 57% (63%) | 13% (9%) | 17% (13%) | 3% (0%) |

Ridings at turn 100, for comparison: 46% in all; Maritime 35%, Quebec 52%,
Ontario 70%, Prairie 19%, BC 22%, North 7%.

**Units open**: 261 in 1867, 403 in 1885, 458 in 1914, 472 in 1945, 494 in 1966.
This is the same on every seed, being the data's.

## What does not read well

- **The North is barely held.** At step 3 one seed of ten holds a northern
  unit at turns 75 and 100 (3% on the mean); at step 2 none did.
  - Whitehorse opens in 1898 and Yellowknife in 1936, at the ends of long
    bridges.
  - Iqaluit can't be reached at all: no land row and no water row of 3 hexes
    or fewer joins it.

  The Prairie is held thinly (13% at 1966) and BC too (17%). The slow West is
  the intended result, and it is slower here than on ridings.
- **Cities named for the township around them** (step 3). By the rule of the
  municipality covering most of the cell, these hexes are named for the
  township, not the city in them:
  - Kitchener's core is "Wilmot";
  - Oshawa's core is "Whitby";
  - the Burnaby–New Westminster hex is "Delta North";
  - Waterloo's is "Woolwich" and Guelph's "Guelph/Eramosa";
  - Saint-Hyacinthe's is "La Présentation";
  - Airdrie's is "Rocky View County West";
  - Hamilton's core is "Halton Hills".

  Seventeen cities have no unit of their name (listed under Names). "Oshawa"
  and "St. Thomas" are borrowed by rural hexagons beside them.
- **County names on city hexes.** Calgary's southern hexes, of 117,000 and
  127,000 people, are "Foothills County North" and "Foothills County
  North-East". Edmonton's northern one is "Sturgeon County South-West".
- **Suburbs open before their city.** Calgary's two southern hexes and
  Airdrie's two western ones lie in Foothills and Rocky View counties, so they
  open at those counties' year (1870), before Calgary (1875). Edmonton's
  outer hexes open in 1870 too, and its core in 1904.
- **Thames Centre, Middlesex Centre and Central Elgin** are London's outer
  hexes.
- **The cores aren't always named for their cities.** Toronto's core is
  "Toronto East", and the plain "Toronto" goes to the hex holding Toronto's
  own place.
- **Edmonton's core opens late.** It is "Edmonton East", and opens in 1904 with
  the city year, after the hexagon holding Edmonton's place (1870).
- **Wikidata's settlement dates are sometimes incorporations.** They now count
  only after 1867 and to 1930, which drops Camrose's 1944 and Calmar's 1949.
  Some late ones remain: Barraute, La Sarre and Preissac 1918, Teulon 1919,
  Terrace 1927.
- **The disputed area's 1889 line.** It stays open, but the atlas's return of
  Kenora to Ontario in 1889 is still told as an accession ("Ontario comes under
  Canada as a province, opening one holding: Kenora"), though Kenora opened in
  1882.
- **Names crowd out at 390 px.** On the whole country, the houses' names and
  the year's badges crowd out some jurisdictions' names. In 1871 British
  Columbia and the North-West Territories go unnamed under the "opens" badge.
- **"Lloydminster (Part)"** is still the census place's name.

## Checks

- **The tests:**
  - `tests/test_hexboard.py`: units, unique names, symmetric links, six land
    groups joined by water, the opening rules, no unit held before its year
    on three seeds, no float in a table an engine reads, both engines on three
    seeds.
  - `tests/test_dated_openings.py`: the flag on the riding sets.
  - `tests/js/hexboard.e2e.mjs`, through `tests/test_mapview.py`.
- **The cross-checks:**
  - under 1.0 on this set, seeds 1867, 2 and 3 over 100 turns: byte-identical;
  - under 1.0 on `meridian-v1.0.3`, seed 3 over 100 turns: byte-identical;
  - under 0.9 on both riding sets.
- **The rest:** the full suite, node tests, the map view's browser checks at
  three sizes on both previews, and the referee on every scenario. The results
  are in the PR.
