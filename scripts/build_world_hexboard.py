#!/usr/bin/env python3
"""Build the `meridian-hex-v1.0.5` reference-data version: the hex board.

    python scripts/build_world_hexboard.py

The hex trial's world rebuilt on Meridian v1.0.5 (docs/hex-trial/v2/README.md).
Reads the four files `scripts/fetch_meridian.py --board` committed under
`data/reference/meridian/hex-v1.0.5/raw/` — the resolution-4 table regenerated
with the large lakes as water, straits read as water and settlement dates
(`hexes.r4.v1.2`), the city hexes (`hexes.r5.v1`) and their two clipped layers,
hash- and format-checked on every read — and writes, beside them, the six
tables every reference set has, so both engines read it as they read any:

    ridings.csv               the units: fed_id, name_en, name_fr, province, name_key
    adjacency.csv             unit links, land and water
    places_by_riding.csv      each unit's census places, designation_ok by csdType
    riding_tokens.csv         the usable words of each unit's name (build_places.py)
    riding_stats.csv          integers only, opens_year as below
    riding_jurisdictions.csv  one row per jurisdiction span, in whole years

and, for the record and the map exporters (read by no engine):

    units.csv                 each unit's hexagon, its role, where its name and
                              its opening year came from
    links.csv                 every unit link with its length
    build_report.json         what this build had to decide
    hexes.geojson             every hexagon of the board with its unit and distance
    geometry_simplified.geojson   the units' own hexagons
    borders_shared.geojson    edges two unit hexagons share in one layer
    routes.geojson            every link longer than 1, through its hexagons
    jurisdictions.geojson     for each span of years the atlas holds still, the
                              lines between first-order jurisdictions along
                              hexagon edges, and each jurisdiction's name at a
                              label point

**The board.** A resolution-4 hexagon of 500,000 people or more (16 at v1.0.5)
is *split*: it is replaced on the board by its resolution-5 cells, the city
hexes. Every other resolution-4 hexagon stands as itself. The board's hexagons
are the unsplit resolution-4 rows and the split parents' cells.

**Units.** An unsplit hexagon of 5,000 people or more; and of each split
parent's cells, those of 25,000 or more and its most populous cell, the *core*
(ties to the lower H3 index). 423 + 71 = 494.

**Ids.** `PP × 10,000,000 + T`, nine digits: PP is the federal code of the
row's province, T is the resolution-4 hexagon's base cell and four digits read
as one base-7 number (as in the trial), or for a city hex 1,000,000 plus its
base cell and five digits in base 7 (so a city hex's T − 1,000,000, divided by
7, is its parent's). Fixed width; the first two digits are the province.

**Names**, units by population, largest first, ties by id:
1. a core is named for its parent's principal city, Meridian's principal place
   (the parent's most populous place);
2. every other unit takes its largest unused place of a town type, else of a
   municipal type (the trial's rule);
3. a city hex left without a name takes the first unused name token of the 2023
   riding covering most of its land (data/reference/ riding tokens; coverage
   measured on Meridian v1.0.3's riding layer, the only floating-point measure
   here besides the trial's nearest-unit one, taken once and committed);
4. anything still unnamed borrows, ring by ring over land links, as in the trial.

**Opening year**, the latest of: (a) the first year a span of the unit's land
is under Canada; (b) its resolution-4 row's settledYear, where it has one (the
city-hex table carries no dates); (c) for a city hex that is not a core, its
parent's city year (CITY_YEARS, each with its source); (d) the director's
overrides (OPENING_OVERRIDES), by the census place they name.

**Adjacency.** The trial's rule (build_world_hex.py) on this board: a city hex
links to another by its own neighbour entry, and to an unsplit hexagon by its
entries for that hexagon's cells (land if any is land); unsplit hexagons link
as `hexes.r4.v1.2` links them. A land-connected group of units that no water
link joins to another gets one water link from whichever of its units is
nearest a unit outside it (pyproj's geodesic between H3 centres, as the trial's
lone-unit rule).

No float leaves this script for a table an engine reads (docs/DETERMINISM.md,
"The hex board").
"""

import csv
import json
import sys
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from hoc.names import name_key  # noqa: E402  (after sys.path setup)

import build_places  # noqa: E402
import build_world_hex as bwh  # noqa: E402  (the trial's rules, reused as they stand)
import build_world_meridian as bwm  # noqa: E402
import fetch_meridian as fm  # noqa: E402

KEY = "meridian-hex-v1.0.5"
OUT_DIR = fm.BOARD_OUT_DIR
RAW_DIR = fm.BOARD_RAW_DIR
RIDING_TOKENS = ROOT / "data" / "reference" / "riding_tokens.csv"
RIDINGS = ROOT / "data" / "reference" / "ridings.csv"

MIN_POPULATION = 5000
SPLIT_POPULATION = 500000
CITY_HEX_POPULATION = 25000
LENGTH_CAP = bwh.LENGTH_CAP
CANADA = "Canada"

# The year each split parent's metropolitan core was incorporated as a city,
# keyed by the parent's H3 index. Given by the director's adviser from memory
# and checked against The Canadian Encyclopedia (TCE) and the cities' own
# records. Québec is corrected from 1832 to 1833: the Act was assented in 1832,
# but TCE and the City's chronology date its first charter, and its first
# council, to 1833. Montréal's Act is of the same year and its charter came
# into effect in 1833 too, but TCE and the City's archives give incorporation
# as 1832, so 1832 stands. The sources were read through search results; the
# pages themselves could not be opened from the build environment (its network
# policy), which is recorded in build_report.json.
TCE = "https://www.thecanadianencyclopedia.ca/en/article/"
CITY_YEARS = {
    "842b9bdffffffff": ("Toronto", 1834, TCE + "toronto"),
    "842baa5ffffffff": ("Montréal", 1832, TCE + "montreal"),
    "842bac5ffffffff": ("Québec", 1833, TCE + "quebec-city"),
    "842b9b5ffffffff": ("Hamilton", 1846, TCE + "hamilton"),
    "842b9b7ffffffff": ("Hamilton", 1846, TCE + "hamilton"),
    "842b83bffffffff": ("Ottawa", 1855, TCE + "ottawa"),
    "842ab47ffffffff": ("London", 1855, TCE + "london-ont-emc"),
    "84271c9ffffffff": ("Winnipeg", 1873, TCE + "winnipeg"),
    "8428de9ffffffff": ("Vancouver", 1886, TCE + "vancouver"),
    "8428dedffffffff": ("Vancouver", 1886, TCE + "vancouver"),
    "8412ccdffffffff": ("Calgary", 1894, TCE + "calgary"),
    "8412ea7ffffffff": ("Calgary", 1894, TCE + "calgary"),
    "8412ecdffffffff": ("Edmonton", 1904, TCE + "edmonton"),
    "842ab49ffffffff": ("Kitchener", 1912, TCE + "kitchener-waterloo"),
    "842baa1ffffffff": ("Longueuil", 1920, TCE + "longueuil"),
    "842b987ffffffff": ("Oshawa", 1924, TCE + "oshawa"),
}
CITY_YEAR_CHANGES = [
    {"city": "Québec", "given": 1832, "used": 1833,
     "why": "TCE and the City of Québec's chronology date the first charter to 1833;"
            " 1832 is the Act's assent", "sources": [
                TCE + "quebec-city",
                "https://www.ville.quebec.qc.ca/citoyens/patrimoine/archives/jalons_historiques/"
                "chronologie_de_la_ville.aspx"]},
]

# The director's opening years for new towns Meridian withholds (dated 1950 or
# later) or lacks, by census subdivision: (csd, place, province, year).
OPENING_OVERRIDES = (
    ("4622026", "Thompson", "MB", 1956),
    ("3557041", "Elliot Lake", "ON", 1955),
    ("2499025", "Chibougamau", "QC", 1952),
    ("1010034", "Wabush", "NL", 1955),
    ("5949005", "Kitimat", "BC", 1953),
)

# Keewatin was a district apart from the North-West Territories from the
# Keewatin Act (1876) until it was returned to them in 1905 (Natural Resources
# Canada, Territorial Evolution; Statistics Canada). Every other district in
# the atlas is a district of the North-West Territories.
KEEWATIN_APART = ("district_of_keewatin", 1876, 1904)
NWT = "northwest_territories"
LAST_YEAR = 2026


class BoardBuildError(Exception):
    """The tables did not support a rule; the build stops rather than guess."""


# ---------------------------------------------------------------------- ids --


def h3_digits(index, resolution):
    """(base cell, [digits]) of an H3 cell index at `resolution`."""
    value = int(index, 16)
    if (value >> 59) & 0xF != 1:
        raise BoardBuildError(f"{index}: not an H3 cell index")
    if (value >> 52) & 0xF != resolution:
        raise BoardBuildError(f"{index}: resolution {(value >> 52) & 0xF}, expected {resolution}")
    digits = [(value >> (3 * (15 - i))) & 7 for i in range(1, 16)]
    if any(d != 7 for d in digits[resolution:]) or any(d > 6 for d in digits[:resolution]):
        raise BoardBuildError(f"{index}: digits {digits} are not a resolution-{resolution} cell's")
    return (value >> 45) & 0x7F, digits[:resolution]


def h3_sequence(index, resolution):
    base, digits = h3_digits(index, resolution)
    seq = base
    for digit in digits:
        seq = seq * 7 + digit
    return seq


def unit_id(row, resolution):
    t = h3_sequence(row["id"], 4) if resolution == 4 else 1_000_000 + h3_sequence(row["id"], 5)
    return bwh.PROVINCE_CODES[row["province"]] * 10_000_000 + t


# -------------------------------------------------------------------- board --


class Board:
    """The mixed board: unsplit resolution-4 hexagons and split parents' cells."""

    def __init__(self, r4, r5):
        self.r4_rows = {row["id"]: row for row in r4["rows"]}
        self.split = {h: row for h, row in self.r4_rows.items() if row["population"] >= SPLIT_POPULATION}
        self.cells = {}
        for cell in r5["rows"]:
            self.cells.setdefault(cell["parent"], []).append(cell)
        for parent in self.split:
            if parent not in self.cells:
                raise BoardBuildError(f"{parent}: split, but the city-hex table has no cells for it")
            total = sum(c["population"] for c in self.cells[parent])
            if total != self.split[parent]["population"]:
                raise BoardBuildError(f"{parent}: cells hold {total}, the parent {self.split[parent]['population']}")
        # Every hexagon of the board: {h3: (row, resolution)}.
        self.nodes = {}
        for h, row in self.r4_rows.items():
            if h not in self.split:
                self.nodes[h] = (row, 4)
        for parent in sorted(self.split):
            for cell in self.cells[parent]:
                self.nodes[cell["id"]] = (cell, 5)
        self.land, self.water = self._links()

    def row(self, h):
        return self.nodes[h][0]

    def _links(self):
        kinds = {}

        def put(a, b, kind):
            pair = (min(a, b), max(a, b))
            if kinds.get(pair) == "land":
                return
            kinds[pair] = kind

        for h, (row, res) in self.nodes.items():
            if res == 4:
                for n in row["neighbours"]:
                    if n["id"] in self.nodes and n["id"] not in self.split:
                        put(h, n["id"], n["kind"])
            else:
                for n in row["neighbours"]:
                    if n["parent"] in self.split:
                        if n["id"] in self.nodes:  # a cell with no land is not a row
                            put(h, n["id"], n["kind"])
                    elif n["parent"] in self.nodes:
                        put(h, n["parent"], n["kind"])
        land = {h: [] for h in self.nodes}
        water = {h: [] for h in self.nodes}
        for (a, b), kind in kinds.items():
            side = land if kind == "land" else water
            side[a].append(b)
            side[b].append(a)
        for side in (land, water):
            for h in side:
                side[h].sort()
        return land, water

    def units(self):
        """[(fed_id, row, resolution, role)] in id order; role is "hex", "core"
        or "city"."""
        out = []
        for h, (row, res) in self.nodes.items():
            if res == 4:
                if row["population"] >= MIN_POPULATION:
                    out.append((unit_id(row, 4), row, 4, "hex"))
        for parent in sorted(self.split):
            cells = self.cells[parent]
            core = min(cells, key=lambda c: (-c["population"], c["id"]))
            for cell in cells:
                if cell is core:
                    out.append((unit_id(cell, 5), cell, 5, "core"))
                elif cell["population"] >= CITY_HEX_POPULATION:
                    out.append((unit_id(cell, 5), cell, 5, "city"))
        out.sort(key=lambda u: u[0])
        if len({u[0] for u in out}) != len(out):
            raise BoardBuildError("two units share an id")
        return out


# -------------------------------------------------------------------- names --


def riding_shapes():
    """{fed_id: shapely geometry in EPSG:3347} from Meridian v1.0.3's riding
    layer, the polygons the 2023 riding table was built on."""
    from pyproj import Transformer
    from shapely.geometry import MultiPolygon, Polygon
    from shapely.ops import transform  # noqa: F401

    layer = fm.read_layer()
    arcs = bwm.decode_arcs(layer)
    project = Transformer.from_crs("EPSG:4326", "EPSG:3347", always_xy=True).transform
    out = {}
    for geom in layer["objects"]["ridings"]["geometries"]:
        polygons = [geom["arcs"]] if geom["type"] == "Polygon" else geom["arcs"]
        shapes = []
        for polygon in polygons:
            rings = [bwm._coords(bwm._ring(arcs, ring)) for ring in polygon]
            shapes.append(Polygon(rings[0], rings[1:]))
        shape = shapes[0] if len(shapes) == 1 else MultiPolygon(shapes)
        out[str(geom["properties"]["fed"])] = transform(project, shape.buffer(0))
    return out


def hex_shape(geometry):
    from pyproj import Transformer
    from shapely.geometry import shape
    from shapely.ops import transform  # noqa: F401

    project = Transformer.from_crs("EPSG:4326", "EPSG:3347", always_xy=True).transform
    return transform(project, shape(geometry).buffer(0))


def covering_riding(geometry, ridings):
    """(fed_id, share per mille) of the 2023 riding holding most of a hexagon's
    land; ties to the lower fed_id. Measured once, in floating point, at build
    time; what it decides is committed in units.csv."""
    land = hex_shape(geometry)
    best = None
    for fed in sorted(ridings):
        shape = ridings[fed]
        if not shape.intersects(land):
            continue
        area = shape.intersection(land).area
        if best is None or area > best[1]:
            best = (fed, area)
    if best is None:
        return None, 0
    return best[0], int(round(1000 * best[1] / land.area))


def name_units(board, units, geometries):
    """{fed_id: {name, source, csd, riding, from_h3}}."""
    order = sorted(units, key=lambda u: (-u[1]["population"], u[0]))
    taken, names = set(), {}

    def take(fed, name, **how):
        taken.add(name_key(name))
        names[fed] = {"name": name, "csd": "", "riding": "", "from_h3": "", **how}

    for fed, row, res, role in order:
        if role == "core":
            parent = board.r4_rows[row["parent"]]
            if not parent["places"]:
                raise BoardBuildError(f"{row['parent']}: a split parent with no place")
            principal = parent["places"][0]
            if name_key(principal["name"]) in taken:
                raise BoardBuildError(f"{principal['name']}: two cores, one name")
            take(fed, principal["name"], source="parent's principal city", csd=principal["csd"])
    deferred = []
    for fed, row, res, role in order:
        if fed in names:
            continue
        pick = next((p for p in bwh.own_candidates(row) if name_key(p["name"]) not in taken), None)
        if pick is None:
            deferred.append((fed, row, res, role))
            continue
        take(fed, pick["name"], source="own place", csd=pick["csd"])
    tokens = {}
    with open(RIDING_TOKENS, newline="", encoding="utf-8") as f:
        for t in csv.DictReader(f):
            tokens.setdefault(t["fed_id"], []).append((int(t["token_order"]), t["token"]))
    with open(RIDINGS, newline="", encoding="utf-8") as f:
        riding_names = {r["fed_id"]: r["name_en"] for r in csv.DictReader(f)}
    shapes = riding_shapes() if any(role != "hex" for *_, role in deferred) else {}
    coverage = {}
    borrowers = []
    for fed, row, res, role in deferred:
        if role == "city":
            riding, share = covering_riding(geometries[row["id"]], shapes)
            coverage[fed] = {"riding": riding, "riding_name": riding_names.get(riding, ""),
                             "share_permille": share}
            pick = next((tok for _, tok in sorted(tokens.get(riding, []))
                         if name_key(tok) not in taken), None)
            if pick is not None:
                take(fed, pick, source="riding token", riding=riding)
                continue
        borrowers.append((fed, row, res, role))
    unnamed = []
    for fed, row, res, role in borrowers:
        pick = None
        seen = {row["id"]}
        ring = [row["id"]]
        while ring and pick is None:
            nxt = []
            for h in ring:
                for n in board.land[h]:
                    if n not in seen:
                        seen.add(n)
                        nxt.append(n)
            ring = sorted(nxt)
            for types in (bwh.TOWN_TYPES, bwh.MUNICIPAL_TYPES):
                pool = [
                    (-p["population"], h, i, p)
                    for h in ring for i, p in enumerate(board.row(h)["places"])
                    if p["csdType"] in types and name_key(p["name"]) not in taken
                ]
                if pool:
                    _, h, _, p = min(pool, key=lambda t: t[:3])
                    pick = (p, h)
                    break
        if pick is None:
            unnamed.append(row["id"])
            continue
        p, h = pick
        take(fed, p["name"], source="borrowed", csd=p["csd"], from_h3=h)
    if unnamed:
        raise BoardBuildError(f"no name for these units: {', '.join(unnamed)}")
    return names, coverage


# ------------------------------------------------------------ opening years --


def first_canadian_year(spans):
    for span in spans:
        if span["sovereign"] == CANADA:
            return span["from_year"]
    return None


def opening_years(board, units, jurisdictions):
    """{fed_id: {opens_year, atlas, settled, city, override}}."""
    spans = {}
    for j in jurisdictions:
        spans.setdefault(j["fed_id"], []).append(j)
    overrides = {}
    for csd, place, province, year in OPENING_OVERRIDES:
        hits = [fed for fed, row, _, _ in units
                if any(p["csd"] == csd and p["name"] == place for p in row["places"])]
        if len(hits) != 1:
            raise BoardBuildError(f"override {place} ({csd}): in {len(hits)} units")
        overrides[hits[0]] = (place, year)
    out = {}
    for fed, row, res, role in units:
        atlas = first_canadian_year(spans[str(fed)])
        if atlas is None:
            raise BoardBuildError(f"{fed}: never under Canada")
        settled = row.get("settledYear") if res == 4 else None
        city = CITY_YEARS[row["parent"]][1] if role == "city" else None
        override = overrides.get(fed, (None, None))[1]
        years = [y for y in (atlas, settled, city, override) if y is not None]
        out[fed] = {"opens_year": max(years), "atlas": atlas, "settled": settled,
                    "city": city, "override": override}
    return out


# ------------------------------------------------------------- the tables --


def stats_with_opening(units, opening):
    table = {"rows": []}
    for fed, row, _, _ in units:
        copy = dict(row)
        copy["id"] = fed
        table["rows"].append(copy)
    return bwm.stats_rows(table, {str(fed): o["opens_year"] for fed, o in opening.items()})


# ---------------------------------------------------------------- borders --


def first_order(span, year):
    """(key, name) of the first-order jurisdiction a span belongs to in `year`."""
    if span["status"] == "district" and span["sovereign"] == CANADA:
        unit, start, end = KEEWATIN_APART
        if span["unit"] == unit and start <= year <= end:
            return span["unit"], span["name"]
        return NWT, None
    return span["unit"], span["name"]


def span_at(spans, year):
    for s in spans:
        if s["from_year"] <= year and (s["to_year"] == "" or year <= s["to_year"]):
            return s
    return None


def nwt_name(all_spans, year):
    """The atlas's own name for the North-West Territories in `year`: the name
    of its latest span begun by then."""
    best = None
    for s in all_spans:
        if s["unit"] == NWT and s["from_year"] <= year:
            if best is None or s["from_year"] > best[0]:
                best = (s["from_year"], s["name"])
    return best[1] if best else "North-West Territories"


def by_year(board, node_spans, all_spans):
    """[(from_year, to_year, {h3: (key, name, sovereign, status)})] over the
    years the first-order map holds still, 1867 to today: a span ends when a
    line moves, a name changes or a jurisdiction changes sovereign or status
    (Prince Edward Island in 1873, Newfoundland in 1949)."""
    out = []
    for year in range(bwm.FIRST_YEAR, LAST_YEAR + 1):
        nwt = nwt_name(all_spans, year)
        assign = {}
        for h in sorted(board.nodes):
            s = span_at(node_spans[h], year)
            if s is None:
                continue
            key, name = first_order(s, year)
            assign[h] = (key, name if name is not None else nwt, s["sovereign"],
                         "territory" if key == NWT else s["status"])
        if out and out[-1][2] == assign:
            out[-1][1] = year
        else:
            out.append([year, year, assign])
    out[-1][1] = None
    return [tuple(x) for x in out]


def label_points(board, assign):
    """{key: h3}: the hexagon deepest inside each jurisdiction (most steps
    from any hexagon on its edge or the coast), ties nearest the mean of its
    hexagons' land points, then by index."""
    edge = []
    for h, (key, *_) in assign.items():
        row, res = board.nodes[h]
        degree = len(row["neighbours"]) if res == 4 else sum(
            1 for n in row["neighbours"] if n["id"] in board.nodes)
        nbrs = board.land[h] + board.water[h]
        if degree < 6 or any(assign.get(n, (None,))[0] != key for n in nbrs):
            edge.append(h)
    depth = {h: 0 for h in edge}
    frontier = sorted(edge)
    while frontier:
        nxt = []
        for h in frontier:
            for n in board.land[h] + board.water[h]:
                if n in assign and n not in depth and assign[n][0] == assign[h][0]:
                    depth[n] = depth[h] + 1
                    nxt.append(n)
        frontier = sorted(set(nxt))
    members = {}
    for h, (key, *_) in assign.items():
        members.setdefault(key, []).append(h)
    out = {}
    for key, hexes in sorted(members.items()):
        pts = [tuple(Decimal(v) for v in board.row(h)["landPoint"]) for h in hexes]
        mx = sum(p[0] for p in pts) / len(pts)
        my = sum(p[1] for p in pts) / len(pts)
        out[key] = min(
            hexes,
            key=lambda h: (-depth.get(h, 0),
                           (Decimal(board.row(h)["landPoint"][0]) - mx) ** 2
                           + (Decimal(board.row(h)["landPoint"][1]) - my) ** 2, h))
    return out


def layer_edges(layer):
    """{arc index: [h3, ...]} for a clipped layer, and its decoded arcs."""
    arcs = bwm.decode_arcs(layer)
    users = {}
    for geom in layer["objects"]["hexes"]["geometries"]:
        if geom.get("type") is None:
            continue
        polygons = [geom["arcs"]] if geom["type"] == "Polygon" else geom["arcs"]
        for polygon in polygons:
            for ring in polygon:
                for index in ring:
                    users.setdefault(index if index >= 0 else ~index, []).append(geom["properties"]["id"])
    return arcs, users


def border_segments(board, l4, l5):
    """[(h3 a, h3 b, coordinates)]: every hexagon edge of the board between two
    of its hexagons, a < b, as drawn. Within a layer, the arc two hexagons
    share. Between a split parent and an unsplit hexagon the two layers share
    no arc, so the resolution-4 arc between the parent and the hexagon is used,
    the parent's side taken by the cell nearest the arc's middle."""
    arcs4, users4 = layer_edges(l4)
    arcs5, users5 = layer_edges(l5)
    out = []
    for index in sorted(users5):
        hexes = sorted(set(users5[index]))
        if len(hexes) == 2 and all(h in board.nodes for h in hexes):
            out.append((hexes[0], hexes[1], bwm._coords(arcs5[index])))
    for index in sorted(users4):
        hexes = sorted(set(users4[index]))
        if len(hexes) != 2:
            continue
        a, b = hexes
        if a in board.split and b in board.split:
            continue  # drawn from the cells
        if a in board.split or b in board.split:
            parent, other = (a, b) if a in board.split else (b, a)
            if other not in board.nodes:
                continue
            arc = arcs4[index]
            mid = arc[len(arc) // 2]
            cell = min(
                board.cells[parent],
                key=lambda c: ((Decimal(c["centroid"][0]) - mid[0]) ** 2
                               + (Decimal(c["centroid"][1]) - mid[1]) ** 2, c["id"]))
            if cell["id"] not in board.nodes:
                continue
            x, y = sorted((cell["id"], other))
            out.append((x, y, bwm._coords(arc)))
        elif a in board.nodes and b in board.nodes:
            out.append((a, b, bwm._coords(arcs4[index])))
    return out


def jurisdiction_features(board, node_spans, all_spans, segments):
    features, years = [], []
    for start, end, assign in by_year(board, node_spans, all_spans):
        lines = {}
        for a, b, coords in segments:
            if a not in assign or b not in assign:
                continue
            ka, kb = assign[a][0], assign[b][0]
            if ka == kb:
                continue
            pair = tuple(sorted((ka, kb)))
            lines.setdefault(pair, []).append(coords)
        for (ka, kb), parts in sorted(lines.items()):
            features.append({
                "type": "Feature",
                "properties": {"kind": "border", "from_year": start, "to_year": end,
                               "a": ka, "b": kb},
                "geometry": {"type": "MultiLineString", "coordinates": parts},
            })
        names = {}
        for h, (key, name, sovereign, status) in sorted(assign.items()):
            names.setdefault(key, (name, sovereign, status))
        for key, h in sorted(label_points(board, assign).items()):
            lon, lat = board.row(h)["landPoint"]
            name, sovereign, status = names[key]
            features.append({
                "type": "Feature",
                "properties": {"kind": "label", "from_year": start, "to_year": end,
                               "jurisdiction": key, "name": name, "sovereign": sovereign,
                               "status": status, "h3": h},
                "geometry": {"type": "Point", "coordinates": [float(Decimal(lon)), float(Decimal(lat))]},
            })
        years.append({"from_year": start, "to_year": end,
                      "jurisdictions": sorted({v[1] for v in assign.values()})})
    return features, years


# ------------------------------------------------------------------ links --


def join_groups(units, links, rows):
    """Give each land group no water link reaches another one water link: from
    its unit nearest any unit outside it to that unit."""
    ids = sorted(fed for fed, *_ in units)
    land = bwh.Groups(ids)
    for l in links:
        if l["kind"] == "land":
            land.union(l["a"], l["b"])
    added = []
    while True:
        board = bwh.Groups(ids)
        for l in links:
            board.union(l["a"], l["b"])
        groups = {}
        for fed in ids:
            groups.setdefault(board.find(fed), []).append(fed)
        if len(groups) == 1:
            return added
        smallest = min(groups.values(), key=lambda g: (len(g), g[0]))
        inside = set(smallest)
        outside = [(fed, row) for fed, row, *_ in units if fed not in inside]
        best = None
        for fed in smallest:
            row = next(r for f, r, *_ in units if f == fed)
            other, metres = bwh.nearest_unit(row["id"], outside, rows)
            if best is None or (metres, fed, other) < best:
                best = (metres, fed, other)
        metres, fed, other = best
        a, b = min(fed, other), max(fed, other)
        hexes = {f: r["id"] for f, r, *_ in units}
        links.append({"a": a, "b": b, "kind": "water",
                      "length": -(-metres // bwh.HEX_SPACING_METRES),
                      "path": [hexes[a], hexes[b]]})
        links.sort(key=lambda l: (l["a"], l["b"]))
        added.append({"group_size": len(smallest), "a": a, "b": b, "metres": metres})


def link_report(units, links, report):
    ids = sorted(fed for fed, *_ in units)
    land = bwh.Groups(ids)
    for l in links:
        if l["kind"] == "land":
            land.union(l["a"], l["b"])
    groups = {}
    for fed in ids:
        groups.setdefault(land.find(fed), []).append(fed)
    water_between = {}
    for l in links:
        ga, gb = land.find(l["a"]), land.find(l["b"])
        if l["kind"] == "water" and ga != gb:
            water_between.setdefault(ga, set()).add(gb)
            water_between.setdefault(gb, set()).add(ga)
    return groups, water_between


# ------------------------------------------------------------------- build --


def build(out_dir=OUT_DIR, raw_dir=RAW_DIR, verbose=True):
    out_dir = Path(out_dir)
    r4 = fm.read_board_table(fm.BOARD_R4_TABLE, raw_dir, parse_float=Decimal)
    r5 = fm.read_board_table(fm.BOARD_R5_TABLE, raw_dir, parse_float=Decimal)
    l4 = fm.read_board_layer(fm.BOARD_R4_LAYER, raw_dir, parse_float=Decimal)
    l5 = fm.read_board_layer(fm.BOARD_R5_LAYER, raw_dir, parse_float=Decimal)
    board = Board(r4, r5)
    if sorted(CITY_YEARS) != sorted(board.split):
        raise BoardBuildError(f"split parents {sorted(board.split)} are not CITY_YEARS' {sorted(CITY_YEARS)}")
    units = board.units()

    g4, _, users4 = bwh.hex_geometries(l4)
    g5, _, users5 = bwh.hex_geometries(l5)
    geometries = {h: (g4 if res == 4 else g5).get(h) for h, (_, res) in board.nodes.items()}

    names, coverage = name_units(board, units, geometries)
    pair_units = [(fed, row) for fed, row, *_ in units]
    rows_by_node = {h: row for h, (row, _) in board.nodes.items()}
    links, owner, lreport = bwh.build_links(pair_units, board.land, board.water, rows_by_node)
    joined = join_groups(units, links, rows_by_node)
    groups, water_between = link_report(units, links, lreport)

    ridings = [
        {"fed_id": str(fed), "name_en": names[fed]["name"], "name_fr": names[fed]["name"],
         "province": row["province"], "name_key": name_key(names[fed]["name"])}
        for fed, row, *_ in units
    ]
    adjacency = [
        {"fed_id_a": str(l["a"]), "fed_id_b": str(l["b"]), "adjacency_type": l["kind"]}
        for l in links
    ]
    places = bwh.places_rows(pair_units)
    tokens = build_places.build_tokens(ridings)
    jurisdictions, dropped = bwm.jurisdiction_rows(
        {"meta": r4["meta"], "rows": [{"id": fed, "jurisdictions": row["jurisdictions"]}
                                      for fed, row in pair_units]})
    opening = opening_years(board, units, jurisdictions)
    stats = stats_with_opening(units, opening)

    # For drawing, every hexagon of the board is read, units or not. A span
    # the atlas marks as a fallback (no unit overlaps the hexagon's land; the
    # nearest was taken) is drawn as that nearest unit and counted.
    fallbacks = []
    for h in sorted(board.nodes):
        for span in board.row(h)["jurisdictions"]:
            if span.get("fallback"):
                fallbacks.append({"h3": h, "from": span["from"], "name": span["name"]})
    node_rows, _ = bwm.jurisdiction_rows(
        {"meta": r4["meta"], "rows": [
            {"id": h, "jurisdictions": [{k: v for k, v in span.items() if k != "fallback"}
                                        for span in board.row(h)["jurisdictions"]]}
            for h in sorted(board.nodes)]})
    node_spans = {}
    for j in node_rows:
        node_spans.setdefault(j["fed_id"], []).append(j)
    segments = border_segments(board, l4, l5)
    juris_features, juris_years = jurisdiction_features(board, node_spans, node_rows, segments)

    unit_rows = []
    for fed, row, res, role in units:
        n, o = names[fed], opening[fed]
        unit_rows.append({
            "fed_id": str(fed), "h3": row["id"], "resolution": res, "role": role,
            "parent_h3": row.get("parent", ""), "name_source": n["source"],
            "name_csd": n["csd"], "name_riding": n["riding"], "named_from_h3": n["from_h3"],
            "opens_year": o["opens_year"], "open_atlas": o["atlas"],
            "open_settled": "" if o["settled"] is None else o["settled"],
            "open_city": "" if o["city"] is None else o["city"],
            "open_override": "" if o["override"] is None else o["override"],
        })
    link_rows = [
        {"fed_id_a": str(l["a"]), "fed_id_b": str(l["b"]), "adjacency_type": l["kind"],
         "length": l["length"], "hexes": len(l["path"])}
        for l in links
    ]

    # Drawing: every hexagon of the board, the units', and routes through the
    # land points (each hexagon's principal land, where its links are read).
    unit_hexes = {row["id"]: fed for fed, row, *_ in units}
    backdrop = []
    for h in sorted(board.nodes):
        fed, dist = owner.get(h, (None, None))
        backdrop.append({
            "type": "Feature",
            "properties": {"h3": h, "res": board.nodes[h][1],
                           "unit": None if fed is None else str(fed), "dist": dist},
            "geometry": geometries[h],
        })
    unit_features = [
        {"type": "Feature",
         "properties": {"fed_id": str(fed), "name_en": names[fed]["name"], "res": res, "role": role},
         "geometry": geometries[row["id"]]}
        for fed, row, res, role in units
    ]
    borders = [
        {"type": "Feature", "properties": {},
         "geometry": {"type": "LineString", "coordinates": coords}}
        for a, b, coords in segments if a in unit_hexes and b in unit_hexes
    ]

    def point(h):
        lon, lat = board.row(h)["landPoint"]
        return [float(Decimal(lon)), float(Decimal(lat))]

    routes = [
        {"type": "Feature",
         "properties": {"fed_id_a": str(l["a"]), "fed_id_b": str(l["b"]), "kind": l["kind"],
                        "length": l["length"]},
         "geometry": {"type": "LineString", "coordinates": [point(h) for h in l["path"]]}}
        for l in links if l["length"] > 1
    ]

    out_dir.mkdir(parents=True, exist_ok=True)
    bwm.write_csv(out_dir / "ridings.csv", ridings,
                  ["fed_id", "name_en", "name_fr", "province", "name_key"], "\r\n")
    bwm.write_csv(out_dir / "adjacency.csv", adjacency,
                  ["fed_id_a", "fed_id_b", "adjacency_type"], "\r\n")
    bwm.write_csv(out_dir / "places_by_riding.csv", places,
                  ["fed_id", "place", "population", "spans_ridings", "designation_ok"])
    bwm.write_csv(out_dir / "riding_tokens.csv", tokens, ["fed_id", "token", "token_order"])
    bwm.write_csv(out_dir / "riding_stats.csv", stats, [
        "fed_id", "population", "land_area_km2", "wealth_tier", "resource_tier",
        "french_permille", "indigenous_identity_permille", "urban_class",
        "industry_dominant", "opens_year",
    ])
    bwm.write_csv(out_dir / "riding_jurisdictions.csv", jurisdictions,
                  ["fed_id", "from_year", "to_year", "unit", "name", "status", "sovereign"])
    bwm.write_csv(out_dir / "units.csv", unit_rows, list(unit_rows[0]))
    bwm.write_csv(out_dir / "links.csv", link_rows,
                  ["fed_id_a", "fed_id_b", "adjacency_type", "length", "hexes"])
    bwm.write_geojson(out_dir / "hexes.geojson", backdrop)
    bwm.write_geojson(out_dir / "geometry_simplified.geojson", unit_features)
    bwm.write_geojson(out_dir / "borders_shared.geojson", borders)
    bwm.write_geojson(out_dir / "routes.geojson", routes)
    bwm.write_geojson(out_dir / "jurisdictions.geojson", juris_features)
    (out_dir / "set.json").write_text(json.dumps({
        "key": KEY,
        "unit_word": {"singular": "holding", "plural": "holdings"},
        "hexes": True,
        "city_hexes": True,
        "jurisdictions": "jurisdictions.geojson",
    }, indent=2) + "\n", encoding="utf-8")

    # ---- the report ----
    spans_by_unit = {}
    for j in jurisdictions:
        spans_by_unit.setdefault(j["fed_id"], []).append(j)

    def count(year, test):
        return sum(1 for fed, *_ in units if test(fed, year))

    def in_play(fed, year):
        s = span_at(spans_by_unit[str(fed)], year)
        return s is not None and s["sovereign"] == CANADA

    def in_province(fed, year):
        s = span_at(spans_by_unit[str(fed)], year)
        return s is not None and s["sovereign"] == CANADA and s["status"] == "province"

    def is_open(fed, year):
        return in_play(fed, year) and opening[fed]["opens_year"] <= year

    years = (1867, 1870, 1871, 1873, 1885, 1905, 1914, 1945, 1949, 1966)
    by_name = {fed: names[fed]["name"] for fed in names}
    group_list = sorted(groups.values(), key=lambda g: (-len(g), g[0]))
    report = {
        "source": f"meridian {fm.BOARD_TAG} (h3_r4 hexes.r4.v1.2, h3_r5 hexes.r5.v1)",
        "rows": {"h3_r4": len(r4["rows"]), "h3_r5": len(r5["rows"])},
        "board_hexagons": len(board.nodes),
        "split_parents": [
            {"h3": h, "principal_place": board.split[h]["places"][0]["name"],
             "population": board.split[h]["population"], "cells": len(board.cells[h]),
             "units": sum(1 for fed, row, res, role in units if res == 5 and row["parent"] == h)}
            for h in sorted(board.split, key=lambda h: -board.split[h]["population"])
        ],
        "units": len(units),
        "units_by_role": {r: sum(1 for *_, role in units if role == r) for r in ("hex", "core", "city")},
        "names_by_source": {
            s: sum(1 for n in names.values() if n["source"] == s)
            for s in ("parent's principal city", "own place", "riding token", "borrowed")
        },
        "city_hexes_without_a_place_of_their_own": sum(
            1 for fed, row, res, role in units if res == 5 and not bwh.own_candidates(row)),
        "names_from_a_riding": [
            {"fed_id": str(fed), "name": names[fed]["name"], **coverage[fed]}
            for fed in sorted(coverage) if names[fed]["source"] == "riding token"
        ],
        "names_borrowed": [
            {"fed_id": str(fed), "name": names[fed]["name"], "from": names[fed]["from_h3"],
             "role": next(role for f, *_, role in units if f == fed)}
            for fed in sorted(names) if names[fed]["source"] == "borrowed"
        ],
        "cores": [
            {"fed_id": str(fed), "name": names[fed]["name"], "parent": row["parent"],
             "own_places": [p["name"] for p in row["places"][:3]]}
            for fed, row, res, role in units if role == "core"
        ],
        "units_without_a_token": [r["fed_id"] for r in ridings
                                  if not any(t["fed_id"] == r["fed_id"] for t in tokens)],
        "places": len(places),
        "places_designation_ok": sum(p["designation_ok"] for p in places),
        "city_years": [
            {"parent": h, "city": c, "year": y, "source": src}
            for h, (c, y, src) in sorted(CITY_YEARS.items())
        ],
        "city_years_changed": CITY_YEAR_CHANGES,
        "city_years_sources_read": "through search results; the build environment's network"
                                   " policy refused the pages themselves",
        "opening_overrides": [
            {"place": place, "csd": csd, "year": year,
             "unit": next(str(f) for f in opening if opening[f]["override"] == year
                          and any(p["csd"] == csd for p in next(r for ff, r, *_ in units if ff == f)["places"])),
             }
            for csd, place, province, year in OPENING_OVERRIDES
        ],
        "opens_year_counts": {
            str(y): sum(1 for o in opening.values() if o["opens_year"] == y)
            for y in sorted({o["opens_year"] for o in opening.values()})
        },
        "opened_later_than_the_atlas": [
            {"fed_id": str(fed), "name": by_name[fed], "atlas": o["atlas"], "opens_year": o["opens_year"],
             "by": [k for k in ("settled", "city", "override") if o[k] == o["opens_year"] and o[k] != o["atlas"]]}
            for fed, o in sorted(opening.items()) if o["opens_year"] > o["atlas"]
        ],
        "units_by_year": {
            str(y): {"under_canada": count(y, in_play), "in_a_province": count(y, in_province),
                     "open": count(y, is_open)}
            for y in years
        },
        "jurisdiction_spans": len(jurisdictions),
        "jurisdiction_spans_dropped": dropped,
        "drawing_fallback_spans": fallbacks,
        "links": lreport,
        "land_groups": [
            {"size": len(g), "units": [by_name[f] for f in g][:20],
             "water_links_to": sorted(len(groups[o]) for o in water_between.get(g[0], ()))}
            for g in group_list
        ],
        "water_links_added_to_join_groups": [
            {**j, "a_name": by_name[j["a"]], "b_name": by_name[j["b"]]} for j in joined
        ],
        "links_total": {"land": sum(1 for l in links if l["kind"] == "land"),
                        "water": sum(1 for l in links if l["kind"] == "water")},
        "routes": len(routes),
        "atlas_years": juris_years,
        "not_carried": {
            "score.cohesion": "absent from Meridian unit tables by design; not invented",
            "score.exposure": "not read by the game",
            "jurisdictions[].share": "a float area overlap; not read by the game",
            "score.gdp": "carried only as wealth_tier; an allocation, not a measurement",
            "ecozone": "not read by the game",
            "settledPlace, settledSource, cityYear, citySource": "read into opens_year only",
        },
    }
    (out_dir / "build_report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    if verbose:
        b = lreport["before_cap"]
        print(f"{len(units)} units {report['units_by_role']}; names {report['names_by_source']}")
        print(f"land links before the cap {b['land_links']}, groups {b['land_groups']};"
              f" after: {report['links_total']}, groups joined by water: {len(joined)} added")
        print(f"units by year: {report['units_by_year']}")
        print(f"atlas spans: {len(juris_years)}")
    return report


def main():
    try:
        build()
    except BoardBuildError as exc:
        print(f"stopped: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
