# The hex board on Meridian v1.0.5

The director chose hexes over ridings. This is the board rebuilt properly on
Meridian v1.0.5:
- city hexes;
- an opening year for every unit, which the draft rules now keep;
- the provincial and territorial borders of every year.

The preview at `outputs/site/preview-hex/` plays the draft on it. `rules/current.txt`
stays 0.9 and no scenario was created or played. The Dominion and both frozen
games replay unchanged.

## What was built

| Piece | Where |
|---|---|
| The pin: Meridian `v1.0.5`'s `hexes.r4.v1.2`, `hexes.r5.v1`, their two layers (the director's four hashes), and the mesh `mesh.v1.json.gz` (`f29ac1af…677`, recorded on the first fetch), refused on any other hash, format, version or unit | `scripts/fetch_meridian.py --board`, `data/reference/meridian/hex-v1.0.5/raw/` |
| The reference set `meridian-hex-v1.0.5`, in the six table shapes every set has | `scripts/build_world_hexboard.py`, `data/reference/meridian/hex-v1.0.5/` |
| The rules that turn the tables into integers | docs/DETERMINISM.md, "The hex board on v1.0.5" (rules 14–19) |
| `dated_openings`, a flag in the 1.0 draft, in both engines | `hoc/sim.py`, `web/engine/sim.js`; rules/README.md; rules/CHANGELOG.md |
| The preview, on the new board | `scripts/build_preview.py`, `hoc/export/site.py`, `hoc/export/replay_js.py` |
| The trial | [trial-table.md](trial-table.md), [trial.json](trial.json) |
| Tests | `tests/test_hexboard.py`, `tests/test_dated_openings.py`, `tests/js/hexboard.e2e.mjs` |

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
| Water links | 91, joining every group to another |
| Groups counting water links | 1 |

**Stranded without water crossings.** Every engine path reads land links only,
so 32 units are beyond any expansion from the mainland:

| Group | Units | How a house can get there |
|---|---|---|
| Newfoundland | 15 | a Crown founding from 1949 |
| Vancouver Island | 10 | a founding from 1871 |
| Prince Edward Island | 5 | a founding from 1873 |
| Les Îles-de-la-Madeleine | 1 | a founding (Quebec, open from 1867) |
| Iqaluit | 1 | **never**: a territory for the whole game |

## Names

A resolution-4 unit is named as in the trial: its own largest unused town, or
municipality, else one borrowed from the nearest hexagons.

**A city hex is named for its municipality** (DETERMINISM rule 17), taken from
Meridian's mesh. The mesh gives every resolution-5 cell one census
subdivision. Its schema doesn't say by what rule, but it reads as the one
covering most of the cell. Used alone, that names the hex by area, not by
people. Kitchener's core would be "Wilmot", the Burnaby–New Westminster hex
"Delta", Oshawa's core "Whitby", and two south-Calgary hexes of 117,000 and
127,000 people "Foothills County". So the mesh's municipality names the hex
only when it could hold the hex's people: as many people or more, and no town
in the hex larger. Otherwise the hex takes:
- its own largest town or municipality, if that holds a tenth of its people;
- else the municipality around it, in its province, that could hold them.

**Shared names.** Where several units carry one municipality, the unit holding
its own place keeps the plain name. The others add the first token of the
riding covering most of their land: "Ottawa", "Ottawa Nepean". A token that
already begins with the name stands alone ("Calgary Signal Hill"), and a token
that is another unit's name is passed over.

The result:
- Ottawa's hex is "Ottawa" and the one across the river is "Gatineau".
- No city hex is named for a county unless it lies in one: Strathcona County
  and Strathcona County Sherwood Park.
- 36 resolution-4 units borrow a name, as in the trial.

Every city hex, by its split parent (opening year; a mark where the name is not
plainly the mesh's municipality: [p] its own place, [m+t] the mesh's municipality
with the riding token, [n+t] a neighbouring municipality with the riding token):

| Parent | City hexes |
|---|---|
| Toronto | Toronto Scarborough (core) 1867 [m+t]; Toronto 1867; Toronto Danforth 1867 [m+t]; Mississauga 1867; Brampton 1867; Markham 1867 [p]; Vaughan 1867 |
| Montréal | Montréal (core) 1867; Montréal Pierrefonds 1867 [m+t]; Laval 1867; Montréal Pierre-Boucher 1867 [m+t]; Blainville 1867 [p]; Terrebonne 1867 [p]; Sainte-Sophie 1867 [p] |
| Vancouver | Vancouver (core) 1871 [p]; Burnaby 1871 [p]; Richmond 1871; Delta 1871 |
| Ottawa | Gatineau (core) 1867 [p]; Ottawa 1867; Ottawa Carleton 1867 [m+t]; Ottawa Nepean 1867 [m+t]; Ottawa Kanata 1867 [m+t]; Gatineau Pontiac 1867 [n+t]; Ottawa Lanark 1867 [m+t] |
| Hamilton | Mississauga Halton Hills (core) 1867 [n+t]; Oakville 1867 [p]; Burlington 1867 [p]; Milton 1867; Hamilton 1867 |
| Calgary | Calgary (core) 1875; Calgary Signal Hill 1894 [m+t]; Calgary Foothills 1894 [n+t]; Calgary Heritage 1894 [n+t] |
| Surrey | Surrey (core) 1871; Coquitlam 1871 [p]; Maple Ridge 1871 [p]; Langley 1871; Mission 1871 [p] |
| Kitchener | Kitchener (core) 1867 [p]; Cambridge 1867 [p]; Guelph 1867 [p]; Waterloo 1867 [p]; Centre Wellington 1867 |
| Winnipeg | Winnipeg (core) 1870; Winnipeg Kildonan 1873 [n+t]; Winnipeg Portage 1873 [n+t] |
| Longueuil | Longueuil (core) 1867 [p]; Chambly 1867 [p]; Beloeil 1867 [p]; Saint-Hyacinthe 1867 [p]; Sainte-Julie 1867 [p] |
| Strathcona County | Edmonton Strathcona (core) 1870 [m+t]; Strathcona County Sherwood Park 1870 [m+t]; Edmonton St. Albert 1904 [n+t]; Strathcona County 1870 |
| Oshawa | Oshawa (core) 1867 [p]; Pickering 1867 [p]; Whitchurch-Stouffville 1867 [p] |
| Québec | Québec (core) 1867; Québec Bellechasse 1867 [n+t]; Lévis 1867 |
| Haldimand County | Hamilton Flamborough (core) 1867 [m+t]; Grimsby 1867 [p] |
| Airdrie | Calgary Skyview (core) 1899 [m+t]; Airdrie 1899 [p]; Calgary Crowfoot 1894 [n+t] |
| London | London (core) 1867; Thames Centre 1867 [p]; Middlesex Centre 1867 [p]; St. Thomas 1867 [p] |

## Opening years

By the director's rules (DETERMINISM rule 18). A unit opens at the latest of:
- **(a) The atlas:** the first year its land is under Canada.
- **(b) Its `settledYear`:** this counts only when the land came under Canada
  after 1867, and only when it is 1930 or earlier.
- **(c) The city year:** for a city hex whose municipality is its parent's core
  city.

Then:
- **A core** opens by its parent's rules, the parent's `settledYear` included.
- **Any other city hex** is a town in its own right and opens as a hexagon
  would. It takes its parent's `settledYear` when the parent's settled place is
  in it.
- **The director's twelve overrides** beat every part.

`units.csv` records each part.

| Year | Units open |
|---|---|
| 1867 | 261 |
| 1885 | 399 |
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

Under the new rule a city year applies only to its core city's own extra
hexes. It opens these:
- Calgary's three, 1894;
- Calgary Crowfoot (Airdrie's parent), 1894;
- Winnipeg's two, 1873;
- Edmonton St. Albert, 1904;
- Ottawa's five, Toronto's two, Montréal's two, Québec's one and Hamilton's one:
  each city year is before 1867, so these open with the atlas, in 1867.

Vancouver's 1886, Kitchener's 1912, Longueuil's 1920, Oshawa's 1924 and
London's 1855 open no hex. Their other city hexes are towns in their own
right.

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
untuned. The full table is [trial-table.md](trial-table.md). It has four
columns:
- the first trial's ridings and hexes (measured on 9 October, before
  `dated_openings`);
- ridings now;
- the new board.

| §6 measure | Ridings now | Hexes v1.0.4 | **Hexes v1.0.5** |
|---|---|---|---|
| actions aimed at another house (≥ 30%) | 32% | 30% | 30% (19–37) |
| passes a turn after 20 (≥ 0.33) | 0.35 | 0.33 | 0.34 |
| houses active at turn 100 (20–40) | 22.1 | 22.7 | 21.9 |
| houses fallen or removed (4–10) | 7.5 | 8.5 | 9.3 |
| lead changes (≥ 4) | 18.2 | 17.9 | 17.6 |
| longest lead (≤ 50) | 26.7 | 27.8 | 22.7 |
| ranks spanned by the top eight at 60 (≥ 3) | 3.2 | 3.8 | 3.4 (2–5) |
| first at the reckoning Earl or higher (≥ 8 of 10) | 10 | 7 | **10** |
| a Marquis or Duke at 100 (≥ 8 of 10) | 10 | 10 | 10 |
| a Duke created (≥ 3 of 10) | 6 | 7 | 8 |
| headline at or above pause (40–65%) | 57% | 55% | 54% |
| Auto pauses (15–30%) | 24% | 25% | 27% |
| storylines of 5+ beats (≥ 8) | 32.4 | 31.3 | 29.6 |
| rise and decline storylines (≤ 20) | 12.9 | 14.2 | 11.0 |
| median rivalry, turns (4–10) | 9.7 | 9.1 | 7.9 |
| rivalries reconciled (≤ 40%) | 10% | 17% | 16% |
| rivalries ended decisively (≥ 25%) | 51% | 44% | 50% |
| contests resolved (20–35) | 22.8 | 16.3 | **20.5** (11–33) |
| attacker wins (35–60%) | 51% | 54% | 52% |
| claims answered (≥ 50%) | 62% | 68% | 63% |
| schemes resolved (≥ 60%) | 78% | 79% | 80% |
| median capital at 100 (30–70) | 44.8 | 44.2 | 49.0 |
| median influence at 100 (40–70) | 55.3 | 56.8 | 56.8 |
| median cohesion at 100 (55–85) | 82.0 | 85.8 | **77.0** |
| crises with both camps (≥ 70%) | 92% | 91% | 91% |
| games ending with a reckoning | 10 | 10 | 10 |

Every §6 target is met on the mean. That includes the three the first hex trial
missed (contests resolved, the Earl at the reckoning, median cohesion). The
board is denser in the cities, and houses meet there more.

One seed's top eight span only two ranks at turn 60 (the mean is 3.4). The
ridings-now column differs from the first trial's only on seed 1874, for the
Labrador reason above.

**The share of the map held**:

| Held | All units | Maritime | Quebec | Ontario | Prairie | BC | North |
|---|---|---|---|---|---|---|---|
| Turn 25 (1891) | 15% | 16% | 17% | 28% | 4% | 5% | 0% |
| Turn 50 (1916) | 27% | 25% | 38% | 52% | 8% | 8% | 0% |
| Turn 75 (1941) | 24% | 15% | 34% | 49% | 6% | 8% | 0% |
| Turn 100 (1966) | 34% | 27% | 49% | 63% | 9% | 13% | 0% |

Ridings at turn 100, for comparison: 46% in all; Maritime 35%, Quebec 52%,
Ontario 70%, Prairie 19%, BC 22%, North 7%.

**Units open**: 261 in 1867, 399 in 1885, 458 in 1914, 472 in 1945, 494 in 1966.
This is the same on every seed, being the data's.

## What does not read well

- **The North is never held**, on any seed:
  - Whitehorse opens in 1898 and Yellowknife in 1936, at the ends of long
    bridges.
  - Iqaluit can't be reached at all.

  The Prairie is held thinly (9% at 1966) and BC too (13%). The slow West is
  the intended result, and it is slower here than on ridings.
- **North Calgary opens after the rest of Calgary.** Airdrie's core is north
  Calgary, named Calgary Skyview, and opens in 1899 by its parent's
  settledYear (Airdrie's), after Calgary's own extra hexes (1894). On the
  1895 map it is the one hatched hexagon among Calgary's. The rule as given
  makes it so.
- **Some suffixes don't name the hex's own district:**
  - "Mississauga Halton Hills" is the hex between Brampton, Mississauga and
    Milton.
  - "Québec Bellechasse" is the Beauport hex across from Lévis; Bellechasse is
    the riding's first token.
  - "Montréal Pierre-Boucher" names a riding on the far shore.
  - "Hamilton Flamborough" is Hamilton Mountain.
- **Two municipalities are named by area, not people:** "Thames Centre" and
  "Middlesex Centre" are London's outer hexes.
- **The cores aren't always named for their cities.** The rule names a core
  for its municipality, so Toronto's core is "Toronto Scarborough", and the
  plain "Toronto" goes to the hex holding Toronto's own place.
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
