# The hex board on Meridian v1.0.5

The hex trial's world rebuilt on Meridian v1.0.5: city hexes, opening years by
unit and borders by year. No rules change and no tuning: `rules/current.txt`
stays 0.9, no scenario was created or played, and every existing game replays
unchanged.

## Where this stopped

The brief said that expansion and founding read the opening year "through the
existing opens_year path; if that path cannot express it without a rules
change, stop and say so". **It cannot, under the 1.0 draft**, so the work
stopped once the reference set was built. The preview, the trial table and the
screenshots were not made, and `meridian-hex-v1.0.4` was not removed, because
the riding-to-hex preview still plays on it.

- Under rules 0.9 (`atlas_jurisdiction`), `opens_year` is read against a
  house's *personal* year: `World.riding_open` (`hoc/sim.py`) and `ridingOpen`
  (`web/engine/sim.js`).
- Under the 1.0 draft, `world_calendar` is on, and both engines return before
  that line. A unit is open while `in_play` says its sovereign is Canada that
  world year, and the Crown founds while `crown_may_found` says it is a
  province. **Neither engine reads `opens_year` under `world_calendar`.** The
  settlement dates, city years and the director's five new towns therefore
  reach `riding_stats.csv` but change no draft game.
- Measured on this set: 100-turn draft games on seeds 1867, 2 and 3 hold 30,
  22 and 18 units before their opening years. For example, Greater Sudbury is
  held in 1868 (it opens in 1893), Cambridge in 1869 (1912), Baie-Comeau in
  1876 (1937) and Malartic in 1882 (1939). `tests/test_hexboard.py` records
  this as a strict expected failure,
  `test_no_unit_is_held_before_its_opening_year`. When the engines keep the
  dates, that test passes, the strict xfail turns it red, and the marker must
  then be removed.

Nor can the data say it without a rules change. The only other thing the
engines read under `world_calendar` is `riding_jurisdictions.csv`, and writing
"closed" spans into it would make up atlas history (hard rule 1).

**The smallest change that would do it** is the director's decision. It would
be one flag in the 1.0 draft's `features.json` (say `dated_openings`), false in
0.7–0.9 and in `FEATURE_DEFAULTS`, in both engines:

- under `world_calendar`, `riding_open(f, y)` becomes `in_play(f, y) and
  y >= opens_year(f)`;
- `foundable` becomes `crown_may_found(f, y) and y >= opens_year(f)`;
- `_accessions` announces a unit as it opens, which is the quiet event on the
  world's turn the preview wants;
- the refusal message names the opening year.

No committed game plays 1.0, so its tables and flags may still change
(CLAUDE.md, "Rules 1.0 (draft)"). With the flag in place, steps 3 and 4 of the
brief (the preview and the trial table) can run on this set as it stands.

## What was built

| Piece | Where |
|---|---|
| The pin: Meridian `v1.0.5`, `hexes.r4.v1.2.json.gz` (`163019e1…2d7`), `layers/hexes.r4.v1.2.topojson.gz` (`817ccf7d…79`), `hexes.r5.v1.json.gz` (`2b0e76bf…1e`), `layers/hexes.r5.v1.topojson.gz` (`95f864b1…e7`), refused on any other hash, format, version or unit | `scripts/fetch_meridian.py --board`, `data/reference/meridian/hex-v1.0.5/raw/` |
| The reference set `meridian-hex-v1.0.5`, in the six table shapes every set has | `scripts/build_world_hexboard.py`, `data/reference/meridian/hex-v1.0.5/` |
| Its record: every unit's role, name source and opening-year parts | `units.csv`, `build_report.json` |
| Borders by year | `jurisdictions.geojson` |
| The rules that turn the tables into integers | docs/DETERMINISM.md, "The hex board on v1.0.5" |
| Tests | `tests/test_hexboard.py` |

## The board

**Split parents.** The 16 resolution-4 hexagons of 500,000 people or more are
replaced by their resolution-5 cells: Toronto, Montréal, Vancouver, Ottawa,
Hamilton, Calgary, Surrey, Kitchener, Winnipeg, Longueuil, Strathcona County,
Oshawa, Québec, Haldimand County, Airdrie and London (each named for its
principal place).

**Units: 494.** That is 423 resolution-4 hexagons of 5,000 people or more and
71 city hexes. The city hexes are 16 cores (each parent's most populous cell)
and 55 cells of 25,000 or more.

**Ids.** Ids are nine digits: `PP × 10,000,000 + T`. `T` is the trial's
base-7 reading of a resolution-4 hexagon. For a city hex it is
1,000,000 + its base cell and five digits in base 7, so `(T − 1,000,000) ÷ 7`
gives its parent. The width is fixed and the first two digits are the province,
as before. Both engines and the story layer took nine digits without a change
(the cross-check below).

**Names: 494 unique.**

| Source | Units |
|---|---|
| A core, named for its parent's principal city | 16 |
| The unit's own largest unused place of a town or municipal type | 425 |
| A city hex with no usable place of its own, named for the first unused token of the 2023 riding covering most of its land | 11 |
| Borrowed from the nearest hexagons over land, as in the trial | 42 (36 resolution-4 hexagons, 6 city hexes) |

17 city hexes hold no place of a town or municipal type, as the brief
expected. Five of them are cores (Toronto, Hamilton, Haldimand County, Airdrie
and Strathcona County), which take their parent's name. Of the other 12, seven
are named from a riding. Five of them find their riding's tokens all taken and
borrow: Russell, Arnprior and Smiths Falls for Ottawa cells, Strathmore and
Ghost Lake for Calgary-area cells. Four more city hexes have places, but every
one is taken, so they fall back to a riding: Nepean, Flamborough, Thornhill
and Fort Saskatchewan. Riding coverage is measured once, in floating point, on
Meridian v1.0.3's riding layer (EPSG:3347), and `build_report.json` records
the riding and its share. North Bay is still the one unit with no name token.

**Designations.** 2,133 of 2,663 places can be designations.

## Opening years

A unit's opening year is the latest of these four (`units.csv` keeps each one):

- **(a) Atlas.** The first year its land is under Canada.
- **(b) Settled.** The resolution-4 row's `settledYear`, where it has one. The
  city-hex table carries no dates, so a city hex has none of its own.
- **(c) City year.** For a city hex that is not a core, its parent's city year
  (below).
- **(d) Override.** The director's five new towns: Thompson 1956, Elliot Lake
  1955, Chibougamau 1952, Wabush 1955 and Kitimat 1953. Each is matched by its
  census place, and each lies in exactly one unit.

| Year | Under Canada | In a province | Open by the dates (a–d) |
|---|---|---|---|
| 1867 | 265 | 265 | 220 |
| 1885 | 475 | 367 | 361 |
| 1914 | 478 | 475 | 444 |
| 1945 | 478 | 475 | 469 |
| 1966 | 494 | 491 | 494 |

The last column is what the engines would allow with the dates kept. Today
they allow the first column.

**City years, checked.** The adviser's years agree with The Canadian
Encyclopedia for all but one. Each article is recorded in the script and the
report:

- Toronto 1834
- Montréal 1832 (lapsed 1836, re-incorporated 1840)
- Hamilton 1846
- Ottawa 1855
- London 1855
- Winnipeg 1873
- Vancouver 1886
- Calgary 1894
- Edmonton 1904
- Kitchener (as Berlin) 1912
- Longueuil 1920
- Oshawa 1924

**Corrected: Québec, 1832 to 1833.** The Encyclopedia and the City of Québec's
own chronology date its first charter, and its first council, to 1833. 1832 is
the year the Act received assent. Montréal's Act is of the same date and its
charter also came into force in 1833, but both sources give 1832 as its
incorporation, so 1832 stands. Before 1867 neither changes an opening year.

**A caveat on the sources.** They were read through search results. This
environment's network policy refused the pages themselves, so no page was
opened.

## Links

| | |
|---|---|
| Land links before the cap | 1,235 |
| Land-connected groups | 462, 15, 10, 5, 1, 1 |
| Land links after the cap (53 longer than 6 dropped) | 1,182 |
| Bridges kept over the cap | Fort Frances–Neebing 7, Thompson–The Pas 7, Happy Valley-Goose Bay–Wabush 10, Kapuskasing–Thunder Bay 12, High Level–Yellowknife 13, Terrace–Whitehorse 20 |
| Water links | 91 |
| Groups counting water links | 1 (all 494) |

The groups are the mainland (462), Newfoundland (15), Vancouver Island (10),
Prince Edward Island (5), Les Îles-de-la-Madeleine and Iqaluit. Each reaches
another by water:

- Newfoundland: Springdale–Happy Valley-Goose Bay.
- Vancouver Island: Sidney–White Rock and eight more.
- Prince Edward Island: to New Brunswick and Nova Scotia, eleven links.
- Les Îles-de-la-Madeleine: Three Rivers, the trial's lone-unit rule, 123 km.
- Iqaluit: Thompson–Iqaluit, 61 steps.

So no group needed the new group-joining rule.

**What no water crossing leaves stranded.** Every engine path reads
`adjacency_type = 'land'` only: expansion, claims, disputes, enclosure,
neighbours. So 32 units are out of reach of every house on the mainland, and
of each other's groups:

| Group | Units | How a house can get there |
|---|---|---|
| Newfoundland | 15 | a Crown founding from 1949 |
| Vancouver Island | 10 | a founding from 1871 |
| Prince Edward Island | 5 | a founding from 1873 |
| Les Îles-de-la-Madeleine | 1 | a founding (Quebec) |
| Iqaluit | 1 | **never**: a territory, not a province, for the whole 1867–1966 game |

A house founded in one of these groups is confined to it for the game.

## Borders by year

`jurisdictions.geojson` holds a span of years for each stretch the atlas holds
still: 21 spans from 1867 to today, 1867–1869, 1870, 1871–1872, 1873, and so
on. Each span has:

- the lines between first-order jurisdictions, along hexagon edges;
- each jurisdiction's name, sovereign and status, at the hexagon deepest
  inside it.

A span ends when a line moves, a name changes, or a jurisdiction changes
sovereign or status. Prince Edward Island in 1873 and Newfoundland in 1949 move
no line, but they do end a span.

**First-order.** Each province, territory, colony, Rupert's Land, the
North-Western Territory, the British Arctic Islands and the 1881–1889
Ontario–Manitoba disputed area is first-order. The atlas's districts are
districts of the North-West Territories, with one exception: Keewatin is
apart from the Keewatin Act (1876) until 1905, as Natural Resources Canada's
*Territorial Evolution* has it. Inside a split parent the lines run along the
city hexes. Between a split parent and its neighbour they run along the
resolution-4 edge, the parent's side read from its nearest cell. The
Ontario–Quebec line through Ottawa's cells was drawn and checked by eye. Two
hexagons whose atlas span is a fallback (no atlas unit overlaps them) are
drawn as that nearest unit.

## What does not read well

- **Ottawa's core is the Gatineau cell.** It is in Quebec (id prefix 24) and,
  by the rule, is named Ottawa. The cell holding Ottawa's own place is called
  Carleton, and Gatineau names nothing.
- **Airdrie's core is north Calgary** (its centre is at 51.14° N, inside the city) and is named Airdrie. Airdrie's own cell
  borrows Crossfield.
- **Some cores are named for their county:**
  - Strathcona County's core is Edmonton: its centre lies about 3 km east of
    downtown. It is named Strathcona County.
  - Haldimand County's core, 408,520 people with no place of its own, is
    Hamilton Mountain: its centre is about 7 km south of Hamilton's downtown.
    It is named Haldimand County.
- **The city centres are not named for their cities.** Toronto's place cell is
  Thornhill and Hamilton's is Flamborough, because the name went to the core.
- **Suburbs carry small-town names:**
  - Ottawa's suburbs: Russell, Arnprior, Smiths Falls.
  - A Calgary suburb: Strathmore.
- **A whole riding name as a unit name:** Calgary Signal Hill.
- **Calgary's core is open from 1870,** five years before Fort Calgary,
  because the city-hex table has no dates and the core is not lent its
  parent's.
- **Wikidata's settlement dates are incorporations here and there:**
  - Calmar 1949, Fort St. John 1947, Castlegar and Osoyoos 1946, Camrose,
    Lamont and Onoway 1944, Baie-Comeau 1937.
  - Moose Jaw 1903 and Grand Falls 1920.
  - Greater Sudbury 1893.

  These are the table's dates, used as given.
- **The disputed area closes 1881–1889.** Its sovereign is "Canada (Ontario
  and Manitoba)", so the engine's `in_play` takes its two units out of play
  for those years.
- **Wabush is a Quebec unit.** Its hexagon is mostly Quebec land.
- **"Lloydminster (Part)"** is the census place's name, as in the trial.

## Checks run

- `tests/test_hexboard.py`: 23 pass and 1 is the expected failure above.
- The cross-check under the 1.0 draft on this set, seeds 1867, 2 and 3 over
  100 turns: the two engines are byte-identical.
- The full suite, the cross-check under 0.9 on both riding sets, and the
  referee on every scenario. The results are in the PR.
