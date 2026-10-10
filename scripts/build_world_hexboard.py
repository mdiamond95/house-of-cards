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

**Names.** A resolution-4 unit takes its largest unused place of a town type,
else of a municipal type, else borrows one ring by ring over land links (the
trial's rule). A city or core hex is named for its municipality (the rule of
commit 064a93c): the mesh's census subdivision for its cell when that holds the
cell's people, else its own largest place, else the neighbouring municipality
by the same people test. Where several units carry one municipality, the unit
holding the municipality's place keeps the plain name and each other adds the
compass word of its bearing from the plain-named unit ("Toronto East"; pyproj's
azimuth, taken once and committed); two on one bearing are told apart by
"Outer", then a numeral. No resolution-4 unit borrows a city's name.

**Opening year**, the latest of: (a) the first year the unit's land is under
Canada; (b) its settledYear (a resolution-4 row's own; a city or core hex's is
that of the municipality it is named for), counted only for land under Canada
after 1867 and only to 1930; (c) for a city hex that is not a core, its
municipality's city year (CITY_YEARS). The director's overrides
(OPENING_OVERRIDES) beat them all.

**Adjacency.** The trial's rule on this board: a city hex links to another by
its own neighbour entry, and to an unsplit hexagon by its entries for that
hexagon's cells (land if any is land); unsplit hexagons link as `hexes.r4.v1.2`
links them. adjacency.csv keeps every land link, a water link of WATER_ROW_MAX
(3) hexagons or fewer, and the director's ferries (FERRIES); links.csv keeps
every link. A land group no water link joins to another gets one water link
from whichever of its units is nearest a unit outside it.

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
import build_world_meridian as bwm  # noqa: E402
import fetch_meridian as fm  # noqa: E402

KEY = "meridian-hex-v1.0.5"
OUT_DIR = fm.BOARD_OUT_DIR
RAW_DIR = fm.BOARD_RAW_DIR

MIN_POPULATION = 5000
SPLIT_POPULATION = 500000
CITY_HEX_POPULATION = 25000
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
    # parent: (core city, its census subdivision, year, source)
    "842b9bdffffffff": ("Toronto", "3520005", 1834, TCE + "toronto"),
    "842baa5ffffffff": ("Montréal", "2466023", 1832, TCE + "montreal"),
    "842bac5ffffffff": ("Québec", "2423027", 1833, TCE + "quebec-city"),
    "842b9b5ffffffff": ("Hamilton", "3525005", 1846, TCE + "hamilton"),
    "842b9b7ffffffff": ("Hamilton", "3525005", 1846, TCE + "hamilton"),
    "842b83bffffffff": ("Ottawa", "3506008", 1855, TCE + "ottawa"),
    "842ab47ffffffff": ("London", "3539036", 1855, TCE + "london-ont-emc"),
    "84271c9ffffffff": ("Winnipeg", "4611040", 1873, TCE + "winnipeg"),
    "8428de9ffffffff": ("Vancouver", "5915022", 1886, TCE + "vancouver"),
    "8428dedffffffff": ("Vancouver", "5915022", 1886, TCE + "vancouver"),
    "8412ccdffffffff": ("Calgary", "4806016", 1894, TCE + "calgary"),
    "8412ea7ffffffff": ("Calgary", "4806016", 1894, TCE + "calgary"),
    "8412ecdffffffff": ("Edmonton", "4811061", 1904, TCE + "edmonton"),
    "842ab49ffffffff": ("Kitchener", "3530013", 1912, TCE + "kitchener-waterloo"),
    "842baa1ffffffff": ("Longueuil", "2458227", 1920, TCE + "longueuil"),
    "842b987ffffffff": ("Oshawa", "3518013", 1924, TCE + "oshawa"),
}
CITY_YEAR_CHANGES = [
    {"city": "Québec", "given": 1832, "used": 1833,
     "why": "TCE and the City of Québec's chronology date the first charter to 1833;"
            " 1832 is the Act's assent", "sources": [
                TCE + "quebec-city",
                "https://www.ville.quebec.qc.ca/citoyens/patrimoine/archives/jalons_historiques/"
                "chronologie_de_la_ville.aspx"]},
]

# The director's opening years, which beat every other part (10 October 2026):
# new towns Meridian withholds (dated 1950 or later) or lacks, and towns whose
# Wikidata date is late or missing. By census subdivision: (csd, place, year).
OPENING_OVERRIDES = (
    ("3553005", "Greater Sudbury / Grand Sudbury", 1883),
    ("5955014", "Dawson Creek", 1932),
    ("4717052", "Meadow Lake", 1931),
    ("6106023", "Yellowknife", 1936),
    ("2496020", "Baie-Comeau", 1937),
    ("2489015", "Malartic", 1939),
    ("5955034", "Fort St. John", 1947),
    ("2499025", "Chibougamau", 1952),
    ("5949005", "Kitimat", 1953),
    ("3557041", "Elliot Lake", 1955),
    ("1010034", "Wabush", 1955),
    ("4622026", "Thompson", 1956),
)
# settledYear counts only for land that came under Canada after 1867, and only
# when it is this year or earlier (the director, 10 October 2026).
SETTLED_FIRST_YEAR = 1867
SETTLED_LAST_YEAR = 1930

# Keewatin was a district apart from the North-West Territories from the
# Keewatin Act (1876) until it was returned to them in 1905 (Natural Resources
# Canada, Territorial Evolution; Statistics Canada). Every other district in
# the atlas is a district of the North-West Territories.
KEEWATIN_APART = ("district_of_keewatin", 1876, 1904)
NWT = "northwest_territories"
LAST_YEAR = 2026


# The trial's rules (docs/DETERMINISM.md, "The hex board", rules 9-13), as
# they were written for meridian-hex-v1.0.4, which this set replaced.
LENGTH_CAP = 6
# The distance between neighbouring H3 resolution-4 centres, about 45 km
# (twice the cell's apothem; interop.md gives "about 45 km across"). Used only
# to state a length, in steps, for a link drawn straight across open sea.
HEX_SPACING_METRES = 45000
# The federal two-digit province codes, the prefix of every FED number.
PROVINCE_CODES = {
    "NL": 10, "PE": 11, "NS": 12, "NB": 13, "QC": 24, "ON": 35, "MB": 46,
    "SK": 47, "AB": 48, "BC": 59, "YT": 60, "NT": 61, "NU": 62,
}
# csdType codes (the table's lookups.csdType). A city, town, village or the
# like: a named settlement.
TOWN_TYPES = (
    "C", "CY", "CV", "CÉ", "T", "TV", "V", "VL", "VN", "VC", "NV", "NVL",
    "SV", "RV", "HAM", "NH",
)
# A general municipal type: a municipality, township, parish, canton, rural or
# district municipality and the like. Not reserves and other First Nations
# lands (IRI, S-É, TC, TK, TAL, TWL, NL, SG, IGD), unorganized areas and their
# subdivisions (NO, SNO), regional district electoral areas (RDA), county
# subdivisions (SC), fire districts (FD), special areas (SA), regions (GR, RG)
# or a Crown colony (CN): those are census bookkeeping or another nation's
# land, not a seat to be styled after.
MUNICIPAL_TYPES = (
    "MÉ", "MU", "M", "MD", "DM", "RM", "TP", "CT", "CU", "P", "PE", "RGM",
    "MRM", "CM", "SM", "RCR", "ID", "LGD", "IM", "RMU", "CC", "CG", "COM",
    "SÉ", "SET",
)
NAMEABLE = TOWN_TYPES + MUNICIPAL_TYPES


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
    return PROVINCE_CODES[row["province"]] * 10_000_000 + t


# ------------------------------------------------- the trial's primitives --


def _candidates(places, types):
    return [p for p in places if p["csdType"] in types]

def own_candidates(row):
    """The places a unit may be named for, in the order they are tried."""
    return _candidates(row["places"], TOWN_TYPES) + _candidates(row["places"], MUNICIPAL_TYPES)

def flood(unit_of_hex, land):
    """{h3: (unit fed_id, distance)} over land links from every unit at once.

    Level by level: a hexagon first reached at distance d takes the lowest unit
    id among the hexagons of distance d − 1 that reach it."""
    owner = {h: (fed, 0) for h, fed in unit_of_hex.items()}
    frontier = sorted(unit_of_hex)
    d = 0
    while frontier:
        d += 1
        offers = {}
        for h in frontier:
            fed = owner[h][0]
            for n in land[h]:
                if n in owner:
                    continue
                if n not in offers or fed < offers[n]:
                    offers[n] = fed
        for n, fed in offers.items():
            owner[n] = (fed, d)
        frontier = sorted(offers)
    return owner

def parent_of(h, owner, land, unit_of_hex):
    """The next hexagon from h towards its own unit: a land neighbour one step
    nearer with the same unit, the lowest H3 index if several."""
    fed, d = owner[h]
    for n in land[h]:
        if n in owner and owner[n] == (fed, d - 1):
            return n
    raise BoardBuildError(f"{h}: no step towards unit {fed}")

def path_home(h, owner, land, unit_of_hex):
    path = [h]
    while owner[path[-1]][1] > 0:
        path.append(parent_of(path[-1], owner, land, unit_of_hex))
    return path

def touching(owner, links):
    """{(a, b): (length, x, y)} for each pair of units whose territories meet
    along one of `links`, a < b, at the least dist(x) + 1 + dist(y), ties by
    the pair of hexagons (x on a's side)."""
    best = {}
    for x in sorted(links):
        if x not in owner:
            continue
        for y in links[x]:
            if y not in owner:
                continue
            ux, dx = owner[x]
            uy, dy = owner[y]
            if ux == uy:
                continue
            if ux < uy:
                a, b, hx, hy = ux, uy, x, y
            else:
                a, b, hx, hy = uy, ux, y, x
            candidate = (dx + 1 + dy, hx, hy)
            if (a, b) not in best or candidate < best[(a, b)]:
                best[(a, b)] = candidate
    return best

class Groups:
    """Union-find over unit ids, with the lower id as each group's root."""

    def __init__(self, ids):
        self.parent = {i: i for i in ids}

    def find(self, i):
        while self.parent[i] != i:
            self.parent[i] = self.parent[self.parent[i]]
            i = self.parent[i]
        return i

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra == rb:
            return False
        self.parent[max(ra, rb)] = min(ra, rb)
        return True

    def sizes(self):
        out = {}
        for i in self.parent:
            out[self.find(i)] = out.get(self.find(i), 0) + 1
        return sorted(out.values(), reverse=True)

def nearest_unit(start, units, rows_by_h3):
    """(fed_id, metres) of the unit whose hexagon centre is nearest `start`'s,
    on the WGS84 ellipsoid (pyproj's geodesic), ties to the lower id.

    For a unit the table links to nothing at all (Les Îles-de-la-Madeleine:
    every hexagon round it is open sea, which has no row). It is the only
    measure here taken in floating point, once, at build time; what it decides
    — which unit — is committed as a row of adjacency.csv, and no engine sees
    the distance."""
    from pyproj import Geod

    geod = Geod(ellps="WGS84")
    lon0, lat0 = (float(Decimal(v)) for v in rows_by_h3[start]["centroid"])
    best = None
    for fed, row in units:
        if row["id"] == start:
            continue
        lon, lat = (float(Decimal(v)) for v in row["centroid"])
        metres = round(geod.inv(lon0, lat0, lon, lat)[2])
        if best is None or (metres, fed) < best:
            best = (metres, fed)
    return best[1], best[0]

def build_links(units, land, water, rows_by_h3):
    """(links, report). links: [{a, b, kind, length, path}] in (a, b) order,
    path the hexagons from a's to b's."""
    unit_of_hex = {row["id"]: fed for fed, row in units}
    hex_of_unit = {fed: row["id"] for fed, row in units}
    owner = flood(unit_of_hex, land)
    land_touch = touching(owner, land)
    water_touch = {k: v for k, v in touching(owner, water).items() if k not in land_touch}

    ids = sorted(fed for fed, _ in units)
    before = Groups(ids)
    for a, b in land_touch:
        before.union(a, b)

    kept = Groups(ids)
    chosen = {}
    for pair in sorted(land_touch):
        if land_touch[pair][0] <= LENGTH_CAP:
            chosen[pair] = "land"
            kept.union(*pair)
    bridged = []
    for pair in sorted((p for p in land_touch if land_touch[p][0] > LENGTH_CAP),
                       key=lambda p: (land_touch[p][0], p)):
        if kept.union(*pair):
            chosen[pair] = "land"
            bridged.append({"a": pair[0], "b": pair[1], "length": land_touch[pair][0]})
    for pair in water_touch:
        chosen[pair] = "water"

    def path_of(pair, how):
        length, x, y = how
        return list(reversed(path_home(x, owner, land, unit_of_hex))) + path_home(y, owner, land, unit_of_hex)

    links = []
    for pair in sorted(chosen):
        how = land_touch[pair] if chosen[pair] == "land" else water_touch[pair]
        links.append({"a": pair[0], "b": pair[1], "kind": chosen[pair], "length": how[0],
                      "path": path_of(pair, how)})

    linked = {l["a"] for l in links} | {l["b"] for l in links}
    alone = []
    for fed in ids:
        if fed in linked:
            continue
        # Its length is the hexagon steps of a straight line between the two
        # centres: metres over the H3 resolution-4 centre spacing, rounded up.
        other, metres = nearest_unit(hex_of_unit[fed], units, rows_by_h3)
        steps = -(-metres // HEX_SPACING_METRES)
        a, b = min(fed, other), max(fed, other)
        path = [hex_of_unit[a], hex_of_unit[b]]
        links.append({"a": a, "b": b, "kind": "water", "length": steps, "path": path})
        alone.append({"unit": fed, "to": other, "length": steps, "metres": metres})
    links.sort(key=lambda l: (l["a"], l["b"]))

    after = Groups(ids)
    for l in links:
        if l["kind"] == "land":
            after.union(l["a"], l["b"])
    board = Groups(ids)
    for l in links:
        board.union(l["a"], l["b"])
    lengths = {}
    for pair, how in land_touch.items():
        lengths[how[0]] = lengths.get(how[0], 0) + 1
    report = {
        "hexagons": len(land),
        "hexagons_flooded": len(owner),
        "hexagons_unreached_by_land": len(land) - len(owner),
        "before_cap": {
            "land_links": len(land_touch),
            "mean_land_links_per_unit": str(
                (Decimal(2 * len(land_touch)) / len(ids)).quantize(Decimal("0.01"))
            ),
            "land_groups": before.sizes(),
            "land_link_lengths": {str(k): lengths[k] for k in sorted(lengths)},
        },
        "after_cap": {
            "length_cap": LENGTH_CAP,
            "land_links": sum(1 for l in links if l["kind"] == "land"),
            "dropped_over_cap": len(land_touch) - sum(1 for l in links if l["kind"] == "land"),
            "bridges_kept_over_cap": bridged,
            "water_links": sum(1 for l in links if l["kind"] == "water"),
            "units_alone_given_a_water_link": alone,
            "land_groups": after.sizes(),
            "groups_counting_water_links": board.sizes(),
            "mean_links_per_unit": str(
                (Decimal(2 * len(links)) / len(ids)).quantize(Decimal("0.01"))
            ),
        },
    }
    return links, owner, report

def places_rows(units):
    out = []
    for fed, row in units:
        for place in row["places"]:
            spans = 1 if place["population"] > row["population"] else 0
            out.append({
                "fed_id": str(fed),
                "place": place["name"],
                "population": place["population"],
                "spans_ridings": spans,
                "designation_ok": 1 if place["csdType"] in NAMEABLE and not spans else 0,
            })
    return out

def hex_geometries(layer):
    """{h3: GeoJSON geometry or None}, from the clipped layer, exactly decoded."""
    arcs = bwm.decode_arcs(layer)
    out, users = {}, {}
    for geom in layer["objects"]["hexes"]["geometries"]:
        h = geom["properties"]["id"]
        if geom.get("type") is None:
            out[h] = None
            continue
        polygons = [geom["arcs"]] if geom["type"] == "Polygon" else geom["arcs"]
        rings_out = []
        for polygon in polygons:
            rings_out.append([bwm._coords(bwm._ring(arcs, ring)) for ring in polygon])
            for ring in polygon:
                for index in ring:
                    users.setdefault(index if index >= 0 else ~index, set()).add(h)
        out[h] = (
            {"type": "Polygon", "coordinates": rings_out[0]} if len(rings_out) == 1
            else {"type": "MultiPolygon", "coordinates": rings_out}
        )
    return out, arcs, users


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


def place_index(board):
    """{csd: (place, h3 of the board hexagon holding its point)} over the board."""
    out = {}
    for h, (row, _) in board.nodes.items():
        for p in row["places"]:
            out[p["csd"]] = (p, h)
    for parent in board.split:
        for p in board.r4_rows[parent]["places"]:
            if p["csd"] not in out:
                raise BoardBuildError(f"{p['name']}: a split parent's place no cell holds")
    return out


# A city hex's own place names it (rule 2 of `municipality`) only when it holds
# at least this share of the hex's people, as [numerator, denominator].
OWN_PLACE_SHARE = (1, 10)


def municipality(cell, mesh, places):
    """(csd, how) of the municipality a city hex is named for (the rule of
    commit 064a93c, restored by the director on 10 October 2026):

    1. the census subdivision the mesh gives the cell (the one covering most of
       it), when that municipality has at least as many people as the cell, and
       no place of a town type in the cell has more;
    2. else the cell's own most populous place of a town or municipal type,
       when it holds at least OWN_PLACE_SHARE of the cell's people;
    3. else, of the municipalities the mesh gives the cell's neighbouring cells
       in its province, those with at least as many people as the cell: the one
       the most neighbours carry, ties to the more populous, then the lower code;
    4. else None (borrowing names it)."""
    people = cell["population"]
    csd = mesh["csd"][cell["id"]]
    own = [p for p in cell["places"] if p["csdType"] in NAMEABLE]
    towns = [p for p in own if p["csdType"] in TOWN_TYPES]
    mesh_people = places[csd][0]["population"] if csd in places else -1
    if mesh_people >= people and not any(p["population"] > mesh_people for p in towns):
        return csd, "the mesh's municipality"
    if own:
        best = min(own, key=lambda p: (-p["population"], p["csd"]))
        num, den = OWN_PLACE_SHARE
        if best["population"] * den >= people * num:
            return best["csd"], "its own largest place"
    counts = {}
    for n in mesh["neighbours"][cell["id"]]:
        c = mesh["csd"][n]
        if c in places and mesh["province"][n] == cell["province"] and places[c][0]["population"] >= people:
            counts[c] = counts.get(c, 0) + 1
    if counts:
        best = min(counts, key=lambda c: (-counts[c], -places[c][0]["population"], c))
        return best, "a neighbouring municipality"
    return None, None


def mesh_lookup(mesh):
    """The mesh as {"csd", "province", "neighbours"} keyed by H3 index."""
    cells = mesh["cells"]
    return {
        "csd": {c["id"]: c["csd"] for c in cells},
        "province": {c["id"]: c["province"] for c in cells},
        "neighbours": {c["id"]: [cells[i]["id"] for i in c["neighbours"]] for c in cells},
    }


# The eight compass words, clockwise from north, for a bearing in eighths.
COMPASS = ("North", "North-East", "East", "South-East", "South", "South-West", "West", "North-West")


def bearing_word(origin, target):
    """The compass word for the bearing from one hexagon's H3 centre to
    another's: pyproj's WGS84 forward azimuth, taken once at build time, in
    eighths of a turn (a half-eighth rounds clockwise). What it decides is
    committed in ridings.csv; no engine sees it."""
    from pyproj import Geod

    lon0, lat0 = (float(Decimal(v)) for v in origin["centroid"])
    lon1, lat1 = (float(Decimal(v)) for v in target["centroid"])
    azimuth = Geod(ellps="WGS84").inv(lon0, lat0, lon1, lat1)[0] % 360
    return COMPASS[int((azimuth + 22.5) // 45) % 8]


def name_units(board, units, mesh):
    """({fed_id: {name, source, csd, municipality, plain, compass, from_h3}}, city).

    A resolution-4 unit is named as in the trial: its own largest unused place
    of a town type, else of a municipal type, else one borrowed from the
    nearest hexagons. A city or core hex is named for its municipality
    (`municipality`). Where several units carry one municipality's name, the
    unit holding that municipality's own place keeps the plain name (a
    resolution-4 unit holding it is named for it by its own places; failing
    either, the most populous city hex of the municipality takes it), and every
    other adds the compass word of its bearing from the plain-named unit:
    "Toronto East". Where two would still share a word, the one farther in
    hexagon steps (ties to the lower id) is "Outer", and past that a numeral:
    "Toronto Outer East", "Toronto East 3". A name another unit already holds
    is passed over for the next in that order. A city hex with no municipality
    borrows; a resolution-4 unit never borrows a name a city hex's municipality
    gives (an error if it would)."""
    places = place_index(board)
    holder = {csd: h for csd, (_, h) in places.items()}
    order = sorted(units, key=lambda u: (-u[1]["population"], u[0]))
    row_of = {fed: row for fed, row, *_ in units}
    res_of = {fed: res for fed, _, res, _ in units}
    unit_of_hex = {row["id"]: fed for fed, row, *_ in units}
    taken, names = set(), {}

    def take(fed, name, **how):
        if name_key(name) in taken:
            raise BoardBuildError(f"{name}: taken twice")
        taken.add(name_key(name))
        names[fed] = {"name": name, "csd": "", "municipality": "", "plain": "", "compass": "",
                      "from_h3": "", **how}

    city = {fed: municipality(row, mesh, places) for fed, row, res, _ in units if res == 5}
    groups = {}
    for fed in sorted(city):
        if city[fed][0] is not None:
            groups.setdefault(city[fed][0], []).append(fed)
    plain = {}
    for csd, feds in groups.items():
        holding = unit_of_hex.get(holder[csd])
        if holding in feds:
            plain[csd] = holding
        elif holding is not None:
            plain[csd] = None  # another unit holds the place; it is named for it if it can be
        else:
            plain[csd] = min(feds, key=lambda f: (-row_of[f]["population"], f))

    # 1. city hexes keeping their municipality's plain name
    for fed in sorted(city, key=lambda f: (-row_of[f]["population"], f)):
        csd, how = city[fed]
        if csd is not None and plain[csd] == fed:
            take(fed, places[csd][0]["name"], source=how, csd=csd, municipality=places[csd][0]["name"])
    # 2. resolution-4 units by their own places
    deferred = []
    for fed, row, res, role in order:
        if res != 4:
            continue
        pick = next((p for p in own_candidates(row) if name_key(p["name"]) not in taken), None)
        if pick is None:
            deferred.append((fed, row, res, role))
            continue
        take(fed, pick["name"], source="own place", csd=pick["csd"])
    # 3. the other city hexes of a municipality: the compass word, by bearing
    #    from the unit bearing the plain name (the most populous of them takes
    #    the plain name when no unit has it)
    by_key = {name_key(n["name"]): fed for fed, n in names.items()}
    for csd in sorted(groups):
        base = places[csd][0]["name"]
        rest = [f for f in groups[csd] if f not in names]
        if not rest:
            continue
        origin_fed = by_key.get(name_key(base))
        if origin_fed is None:
            origin_fed = min(rest, key=lambda f: (-row_of[f]["population"], f))
            take(origin_fed, base, source=city[origin_fed][1], csd=csd, municipality=base)
            by_key[name_key(base)] = origin_fed
            rest.remove(origin_fed)
        origin = row_of[origin_fed]
        steps = hop_distances(board, origin["id"])
        words = {}
        for fed in rest:
            words.setdefault(bearing_word(origin, row_of[fed]), []).append(fed)
        for word, feds in sorted(words.items()):
            ranked = sorted(feds, key=lambda f: (steps.get(row_of[f]["id"], 10 ** 6), f))
            n = 0
            for fed in ranked:
                while True:
                    name = f"{base} {word}" if n == 0 else (f"{base} Outer {word}" if n == 1 else f"{base} {word} {n + 1}")
                    n += 1
                    if name_key(name) not in taken:
                        break
                take(fed, name, source=city[fed][1] + ", with a compass word", csd=csd,
                     municipality=base, plain=str(origin_fed), compass=name[len(base) + 1:])
                by_key[name_key(name)] = fed
    for fed, row, res, role in order:
        if res == 5 and fed not in names:
            deferred.append((fed, row, res, role))
    # 4. anything left borrows, ring by ring over land links, as in the trial
    city_names = {name_key(places[csd][0]["name"]) for csd in groups}
    unnamed = []
    for fed, row, res, role in sorted(deferred, key=lambda u: (-u[1]["population"], u[0])):
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
            for types in (TOWN_TYPES, MUNICIPAL_TYPES):
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
        if res == 4 and name_key(p["name"]) in city_names:
            raise BoardBuildError(f"{row['id']}: a rural hexagon would borrow the city name {p['name']}")
        take(fed, p["name"], source="borrowed", csd=p["csd"], from_h3=h)
    if unnamed:
        raise BoardBuildError(f"no name for these units: {', '.join(unnamed)}")
    return names, city


def hop_distances(board, start):
    """{h3: steps} from `start` over the board's land and water links."""
    out = {start: 0}
    frontier = [start]
    while frontier:
        nxt = []
        for h in frontier:
            for n in board.land[h] + board.water[h]:
                if n not in out:
                    out[n] = out[h] + 1
                    nxt.append(n)
        frontier = sorted(set(nxt))
    return out


# ------------------------------------------------------------ opening years --


def first_canadian_year(spans):
    for span in spans:
        if span["sovereign"] == CANADA:
            return span["from_year"]
    return None


def settled_years(board):
    """{csd: settled year} for every place the tables date: a row's
    settledYear is its settledPlace's, the earliest of its places. Places a
    row does not name as its settled place carry no date in the tables."""
    out = {}
    for row in board.r4_rows.values():
        place = row.get("settledPlace")
        if place and row.get("settledYear") is not None:
            out[place["csd"]] = row["settledYear"]
    return out


def opening_years(board, units, jurisdictions, names):
    """{fed_id: {opens_year, atlas, settled, settled_counted, city, override}}.

    The latest of the atlas (the first year the unit's land is under Canada),
    its settledYear where that counts, and the city year where it applies; a
    director's override beats them all. A resolution-4 unit's settledYear is
    its row's. A city or core hex takes the dates of the municipality it is
    named for: a core opens at that municipality's settled year, and any other
    city hex at the later of the settled year and the municipality's city year
    (CITY_YEARS), so only the outer city hexes wait for the city year (the
    director, 10 October 2026). settledYear counts only for land that came
    under Canada after 1867, and only when it is 1930 or earlier."""
    spans = {}
    for j in jurisdictions:
        spans.setdefault(j["fed_id"], []).append(j)
    dated = settled_years(board)
    city_years = {csd: year for _, csd, year, _ in CITY_YEARS.values()}
    overrides = {}
    for csd, place, year in OPENING_OVERRIDES:
        hits = [fed for fed, row, _, _ in units
                if any(p["csd"] == csd and p["name"] == place for p in row["places"])]
        if len(hits) != 1:
            raise BoardBuildError(f"override {place} ({csd}): in {len(hits)} units")
        overrides[hits[0]] = year
    out = {}
    for fed, row, res, role in units:
        atlas = first_canadian_year(spans[str(fed)])
        if atlas is None:
            raise BoardBuildError(f"{fed}: never under Canada")
        city_year = None
        if res == 4:
            settled = row.get("settledYear")
        else:
            csd = names[fed]["csd"]
            settled = dated.get(csd)
            if role != "core":
                city_year = city_years.get(csd)
        counted = settled if (settled is not None and atlas > SETTLED_FIRST_YEAR
                              and settled <= SETTLED_LAST_YEAR) else None
        override = overrides.get(fed)
        opens = override if override is not None else max(
            y for y in (atlas, counted, city_year) if y is not None)
        out[fed] = {"opens_year": opens, "atlas": atlas, "settled": settled, "settled_counted": counted,
                    "city": city_year, "override": override}
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
    land = Groups(ids)
    for l in links:
        if l["kind"] == "land":
            land.union(l["a"], l["b"])
    added = []
    while True:
        board = Groups(ids)
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
            other, metres = nearest_unit(row["id"], outside, rows)
            if best is None or (metres, fed, other) < best:
                best = (metres, fed, other)
        metres, fed, other = best
        a, b = min(fed, other), max(fed, other)
        hexes = {f: r["id"] for f, r, *_ in units}
        links.append({"a": a, "b": b, "kind": "water",
                      "length": -(-metres // HEX_SPACING_METRES),
                      "path": [hexes[a], hexes[b]]})
        links.sort(key=lambda l: (l["a"], l["b"]))
        added.append({"group_size": len(smallest), "a": a, "b": b, "metres": metres})


def link_report(units, links, report):
    ids = sorted(fed for fed, *_ in units)
    land = Groups(ids)
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


# The water links adjacency.csv keeps: those of this many hexagons or fewer,
# and the director's ferries. Every water link is in links.csv.
WATER_ROW_MAX = 3
# The director's ferries (10 October 2026), each between the units whose
# hinterlands hold two places' points, by census subdivision: Cape Breton to
# the Newfoundland unit whose hinterland holds Channel-Port aux Basques.
FERRIES = (("1217030", "Cape Breton", "1003034", "Channel-Port aux Basques"),)


def add_ferries(board, units, links, owner, rows):
    """Mark or add each ferry's water link. Returns [{a, b, length, from, to}]."""
    places = place_index(board)
    hex_of = {fed: row["id"] for fed, row, *_ in units}
    out = []
    for csd_a, name_a, csd_b, name_b in FERRIES:
        ends = []
        for csd, name in ((csd_a, name_a), (csd_b, name_b)):
            place, h = places[csd]
            if place["name"] != name or h not in owner:
                raise BoardBuildError(f"ferry: {name} ({csd}) is not in a unit's hinterland")
            ends.append(owner[h][0])
        a, b = min(ends), max(ends)
        link = next((l for l in links if (l["a"], l["b"]) == (a, b)), None)
        if link is None:
            others = [(f, r) for f, r, *_ in units if f == b]
            metres = nearest_unit(hex_of[a], others, rows)[1]
            link = {"a": a, "b": b, "kind": "water", "length": -(-metres // HEX_SPACING_METRES),
                    "path": [hex_of[a], hex_of[b]]}
            links.append(link)
            links.sort(key=lambda l: (l["a"], l["b"]))
        if link["kind"] != "water":
            raise BoardBuildError(f"ferry {name_a}–{name_b}: the two are linked by land")
        link["ferry"] = True
        out.append({"a": a, "b": b, "length": link["length"], "from": name_a, "to": name_b})
    return out


def reachable_groups(units, links):
    """The groups of units joined through the given links, largest first."""
    ids = sorted(fed for fed, *_ in units)
    g = Groups(ids)
    for l in links:
        g.union(l["a"], l["b"])
    out = {}
    for fed in ids:
        out.setdefault(g.find(fed), []).append(fed)
    return sorted(out.values(), key=lambda m: (-len(m), m[0]))


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

    g4, _, users4 = hex_geometries(l4)
    g5, _, users5 = hex_geometries(l5)
    geometries = {h: (g4 if res == 4 else g5).get(h) for h, (_, res) in board.nodes.items()}

    mesh = mesh_lookup(fm.read_board_mesh(raw_dir))
    names, city = name_units(board, units, mesh)
    pair_units = [(fed, row) for fed, row, *_ in units]
    rows_by_node = {h: row for h, (row, _) in board.nodes.items()}
    links, owner, lreport = build_links(pair_units, board.land, board.water, rows_by_node)
    joined = join_groups(units, links, rows_by_node)
    ferries = add_ferries(board, units, links, owner, rows_by_node)
    groups, water_between = link_report(units, links, lreport)
    rows_links = [l for l in links if l["kind"] == "land" or l["length"] <= WATER_ROW_MAX or l.get("ferry")]
    reach = reachable_groups(units, rows_links)

    ridings = [
        {"fed_id": str(fed), "name_en": names[fed]["name"], "name_fr": names[fed]["name"],
         "province": row["province"], "name_key": name_key(names[fed]["name"])}
        for fed, row, *_ in units
    ]
    # adjacency.csv: every land link, a water link of WATER_ROW_MAX hexagons or
    # fewer, and the director's ferries. A longer water link is in links.csv only.
    adjacency = [
        {"fed_id_a": str(l["a"]), "fed_id_b": str(l["b"]), "adjacency_type": l["kind"]}
        for l in rows_links
    ]
    places = places_rows(pair_units)
    tokens = build_places.build_tokens(ridings)
    jurisdictions, dropped = bwm.jurisdiction_rows(
        {"meta": r4["meta"], "rows": [{"id": fed, "jurisdictions": row["jurisdictions"]}
                                      for fed, row in pair_units]})
    opening = opening_years(board, units, jurisdictions, names)
    stats = stats_with_opening(units, opening)
    # Rules 1.0 `block_grants` reads a unit's H3 resolution (4, or 5 for a
    # city hex) from riding_stats.csv, a table both engines already load.
    resolution = {str(fed): res for fed, row, res, role in units}
    for row in stats:
        row["resolution"] = resolution[row["fed_id"]]

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
            "name_csd": n["csd"], "municipality": n["municipality"],
            "mesh_csd": mesh["csd"][row["id"]] if res == 5 else "",
            "compass": n["compass"], "plain_fed_id": n["plain"], "named_from_h3": n["from_h3"],
            "opens_year": o["opens_year"], "open_atlas": o["atlas"],
            "open_settled": "" if o["settled"] is None else o["settled"],
            "open_settled_counts": 1 if o["settled_counted"] is not None else 0,
            "open_city": "" if o["city"] is None else o["city"],
            "open_override": "" if o["override"] is None else o["override"],
        })
    link_rows = [
        {"fed_id_a": str(l["a"]), "fed_id_b": str(l["b"]), "adjacency_type": l["kind"],
         "length": l["length"], "hexes": len(l["path"]),
         "in_adjacency": 1 if l in rows_links else 0, "ferry": 1 if l.get("ferry") else 0}
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
        "industry_dominant", "opens_year", "resolution",
    ])
    bwm.write_csv(out_dir / "riding_jurisdictions.csv", jurisdictions,
                  ["fed_id", "from_year", "to_year", "unit", "name", "status", "sovereign"])
    bwm.write_csv(out_dir / "units.csv", unit_rows, list(unit_rows[0]))
    bwm.write_csv(out_dir / "links.csv", link_rows,
                  ["fed_id_a", "fed_id_b", "adjacency_type", "length", "hexes", "in_adjacency", "ferry"])
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
        return opening[fed]["opens_year"] <= year

    years = (1867, 1870, 1871, 1873, 1885, 1905, 1914, 1945, 1949, 1966)
    place_names = {csd: p["name"] for csd, (p, _) in place_index(board).items()}

    def why(o):
        if o["override"] is not None:
            return "override"
        if o["city"] is not None and o["city"] == o["opens_year"] and o["city"] > o["atlas"]:
            return "city year"
        if o["settled_counted"] is not None and o["settled_counted"] == o["opens_year"] and o["settled_counted"] > o["atlas"]:
            return "settled"
        return "atlas"
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
            src: sum(1 for n in names.values() if n["source"] == src)
            for src in sorted({n["source"] for n in names.values()})
        },
        "city_hexes": [
            {"fed_id": str(fed), "name": names[fed]["name"], "role": role,
             "parent": board.split[row["parent"]]["places"][0]["name"],
             "population": row["population"], "source": names[fed]["source"],
             "municipality": names[fed]["municipality"],
             "plain_unit": by_name.get(int(names[fed]["plain"])) if names[fed]["plain"] else "",
             "opens_year": opening[fed]["opens_year"],
             "settled": opening[fed]["settled"], "city_year": opening[fed]["city"]}
            for fed, row, res, role in sorted(units, key=lambda u: (u[1].get("parent", ""), -u[1]["population"]))
            if res == 5
        ],
        "names_borrowed": [
            {"fed_id": str(fed), "name": names[fed]["name"], "from": names[fed]["from_h3"],
             "role": next(role for f, *_, role in units if f == fed)}
            for fed in sorted(names) if names[fed]["source"] == "borrowed"
        ],
        "units_without_a_token": [r["fed_id"] for r in ridings
                                  if not any(t["fed_id"] == r["fed_id"] for t in tokens)],
        "places": len(places),
        "places_designation_ok": sum(p["designation_ok"] for p in places),
        "city_years": [
            {"parent": h, "city": c, "csd": csd, "year": y, "source": src,
             "city_hexes_opening_by_it": [by_name[f] for f in sorted(opening)
                                          if opening[f]["city"] is not None
                                          and next(r for ff, r, *_ in units if ff == f).get("parent") == h]}
            for h, (c, csd, y, src) in sorted(CITY_YEARS.items())
        ],
        "city_years_changed": CITY_YEAR_CHANGES,
        "city_years_sources_read": "through search results; the build environment's network"
                                   " policy refused the pages themselves",
        "opening_overrides": [
            {"place": place, "csd": csd, "year": year,
             "unit": next(by_name[f] for f in opening if opening[f]["override"] == year
                          and any(p["csd"] == csd for p in next(r for ff, r, *_ in units if ff == f)["places"])),
             }
            for csd, place, year in OPENING_OVERRIDES
        ],
        "opens_year_counts": {
            str(y): sum(1 for o in opening.values() if o["opens_year"] == y)
            for y in sorted({o["opens_year"] for o in opening.values()})
        },
        "open_by_year": {str(y): sum(1 for o in opening.values() if o["opens_year"] <= y)
                         for y in (1867, 1885, 1914, 1945, 1966)},
        "opening_after_1914": [
            {"name": by_name[fed], "province": row["province"], "opens_year": opening[fed]["opens_year"],
             "by": why(opening[fed])}
            for fed, row, *_ in sorted(units, key=lambda u: (opening[u[0]]["opens_year"], by_name[u[0]]))
            if opening[fed]["opens_year"] > 1914
        ],
        "east_opening_after_1867": [
            {"name": by_name[fed], "province": row["province"], "atlas": opening[fed]["atlas"],
             "opens_year": opening[fed]["opens_year"], "by": why(opening[fed])}
            for fed, row, *_ in sorted(units, key=lambda u: (u[1]["province"], opening[u[0]]["opens_year"], by_name[u[0]]))
            if row["province"] in ("ON", "QC", "NS", "NB", "PE") and opening[fed]["opens_year"] > 1867
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
        "water_row_max": WATER_ROW_MAX,
        "water_links_in_adjacency": sum(1 for l in rows_links if l["kind"] == "water"),
        "water_links_in_links_only": sum(1 for l in links if l["kind"] == "water" and l not in rows_links),
        "ferries": [{**f, "a_name": by_name[f["a"]], "b_name": by_name[f["b"]]} for f in ferries],
        "groups_through_adjacency_rows": [
            {"size": len(m), "units": [by_name[f] for f in m][:12]} for m in reach
        ],
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
        print(f"open by year: {report['open_by_year']}")
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
