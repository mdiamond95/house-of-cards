#!/usr/bin/env python3
"""Build the `meridian-hex-v1.0.4` reference-data version: the hex trial's board.

    python scripts/build_world_hex.py

A trial beside the riding world, not a replacement (docs/hex-trial/README.md).
Reads the two files `scripts/fetch_meridian.py --hexes` committed under
`data/reference/meridian/hex-v1.0.4/raw/` — Meridian v1.0.4's H3 resolution-4
hexagon unit table and its land-clipped layer, hash- and format-checked on every
read — and writes, beside them, the tables a world on this set is built from, in
the shapes every reference set has, so both engines read it as they read any:

    ridings.csv               the units: fed_id, name_en, name_fr, province, name_key
    adjacency.csv             unit links, land and water (the rule below)
    places_by_riding.csv      each unit's census places, designation_ok by csdType
    riding_tokens.csv         the usable words of each unit's name (build_places.py)
    riding_stats.csv          integers only, as build_world_meridian.py makes them
    riding_jurisdictions.csv  one row per jurisdiction span, in whole years
    units.csv                 each unit's H3 index and where its name came from
    links.csv                 every unit link with its length (drawing and report)
    build_report.json         what this build had to decide, for the record

and the drawing files, read by the map exporters and by no engine:

    hexes.geojson             every one of the 6,011 hexagons, clipped to land,
                              with the unit its land floods to and the distance
    geometry_simplified.geojson   the units' own hexagons
    borders_shared.geojson    edges two unit hexagons share
    routes.geojson            every link longer than 1, along its hexagons

**Units.** A row is a unit when its population is at least 5,000 (439 rows at
v1.0.4). Its id is `PP × 1,000,000 + S`: PP is the two-digit federal code of the
row's province (10 Newfoundland and Labrador … 62 Nunavut, as a FED number
begins), and S is the H3 index's base cell and four resolution digits read as
one base-7 number, `base × 7⁴ + d1 × 7³ + d2 × 7² + d3 × 7 + d4` (0–292,920).
It depends on nothing but the hexagon and its province, so it is the same in
every build and every mesh, it is always eight digits (fixed width, so string
order is numeric order, as the engines require of a fed_id), and its first two
digits are its province exactly as a riding's are, which the story layer reads.
The H3 index itself is kept in units.csv.

**Names.** Units are taken in order of population, largest first (ties by id).
Each is named for its largest place whose csdType is a city, town, village or
hamlet (TOWN_TYPES), else its largest place of a general municipal type
(MUNICIPAL_TYPES), skipping a name another unit already carries (compared by
`name_key`). A unit with neither — 34 at v1.0.4, 15 of them holding no census
place at all — borrows, by the director's decision of 8 October 2026: after
every unit that can be named from its own places has been, it takes the
largest unused place of those types from the nearest hexagons over land links,
ring by ring (towns before municipalities within a ring), and units.csv records
the hexagon the name came from. A place's name is never rewritten.

**Designations** draw from the unit's own places, as in every set, but the
name-pattern filter is replaced here by the csdType: `designation_ok` is 1 for
a place of TOWN_TYPES or MUNICIPAL_TYPES that does not span its unit.

**Adjacency.** Only units are in play, and on their own they are 80 separate
pieces, so the land between them is shared out: a flood over land links
through all 6,011 hexagons gives each wilderness hexagon to the nearest unit,
ties to the lower unit id. Two units are land neighbours when their territories
touch along a land link; a link's length is the fewest hexagon steps between
the two units through their own territories (1 when the units' hexagons touch):
the least, over the land links (x, y) where the territories meet, of
dist(x) + 1 + dist(y). Every link of length LENGTH_CAP or less is kept; a
longer one is added, shortest first (ties by id pair), only where it joins two
land-connected groups that would otherwise be apart. Two units whose
territories touch across a water link and not along any land link get a water
link. A unit with no link at all gets one water link to its nearest unit over
any link. All integer, all in id order (docs/DETERMINISM.md, "The hex board").

**No float leaves this script**: numbers are parsed as Decimal and converted
once by the rules build_world_meridian.py states. Geometry is decimal degrees,
for drawing only.
"""

import csv
import gzip
import json
import sys
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from hoc.names import name_key  # noqa: E402  (after sys.path setup)

import build_places  # noqa: E402
import build_world_meridian as bwm  # noqa: E402  (one set of conversion rules)
import fetch_meridian  # noqa: E402

OUT_DIR = fetch_meridian.HEX_OUT_DIR
RAW_DIR = fetch_meridian.HEX_RAW_DIR

MIN_POPULATION = 5000
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

# The lakes the clipped layer draws as land (Meridian interop.md, "The clipped
# layer"), each as an approximate box of [west, south, east, north] degrees.
# Used for the report only: which routes run through a hexagon whose centre
# lies in one. A box takes in shore as well as water, so this over-reports.
LAKE_BOXES = {
    "Lake Winnipeg": (-99.3, 50.3, -96.2, 53.9),
    "Lake Manitoba": (-99.4, 50.1, -98.0, 51.9),
    "Great Bear Lake": (-126.0, 64.7, -117.0, 67.1),
    "Great Slave Lake": (-117.2, 60.8, -108.8, 62.9),
    "Lake Athabasca": (-111.2, 58.4, -105.8, 59.6),
    "Lake Nipigon": (-89.2, 49.4, -87.9, 50.3),
    "Lac Saint-Jean": (-72.4, 48.4, -71.8, 48.9),
}


class HexBuildError(Exception):
    """The table did not support a rule; the build stops rather than guess."""


# ---------------------------------------------------------------------- ids --


def h3_sequence(index):
    """An H3 resolution-4 cell index as base × 7⁴ + its four digits in base 7."""
    value = int(index, 16)
    if (value >> 59) & 0xF != 1:
        raise HexBuildError(f"{index}: not an H3 cell index")
    if (value >> 52) & 0xF != 4:
        raise HexBuildError(f"{index}: resolution {(value >> 52) & 0xF}, expected 4")
    base = (value >> 45) & 0x7F
    digits = [(value >> (3 * (15 - i))) & 7 for i in range(1, 16)]
    if any(d != 7 for d in digits[4:]) or any(d > 6 for d in digits[:4]):
        raise HexBuildError(f"{index}: digits {digits} are not a resolution-4 cell's")
    seq = base
    for digit in digits[:4]:
        seq = seq * 7 + digit
    return seq


def unit_id(row):
    return PROVINCE_CODES[row["province"]] * 1_000_000 + h3_sequence(row["id"])


# -------------------------------------------------------------------- names --


def _candidates(places, types):
    return [p for p in places if p["csdType"] in types]


def own_candidates(row):
    """The places a unit may be named for, in the order they are tried."""
    return _candidates(row["places"], TOWN_TYPES) + _candidates(row["places"], MUNICIPAL_TYPES)


def name_units(units, rows_by_h3, land_neighbours):
    """{fed_id: (name, csd, named_from_h3 or "")}. units: [(fed_id, row)].

    Pass 1 names every unit it can from its own places; pass 2 lets the rest
    borrow, ring by ring over land links from the unit's hexagon (any link if
    none by land is left), the largest unused town, then municipality, of the
    ring. Both passes take units by population, largest first, ties by id."""
    order = sorted(units, key=lambda u: (-u[1]["population"], u[0]))
    taken = set()
    names, deferred = {}, []
    for fed, row in order:
        pick = next((p for p in own_candidates(row) if name_key(p["name"]) not in taken), None)
        if pick is None:
            deferred.append((fed, row))
            continue
        taken.add(name_key(pick["name"]))
        names[fed] = (pick["name"], pick["csd"], "")
    unnamed = []
    for fed, row in deferred:
        pick = None
        seen = {row["id"]}
        ring = [row["id"]]
        while ring and pick is None:
            nxt = []
            for h in ring:
                for n in land_neighbours[h]:
                    if n not in seen:
                        seen.add(n)
                        nxt.append(n)
            ring = sorted(nxt)
            for types in (TOWN_TYPES, MUNICIPAL_TYPES):
                pool = [
                    (-p["population"], h, i, p)
                    for h in ring for i, p in enumerate(rows_by_h3[h]["places"])
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
        taken.add(name_key(p["name"]))
        names[fed] = (p["name"], p["csd"], h)
    if unnamed:
        raise HexBuildError(f"no place to name these units for: {', '.join(unnamed)}")
    return names


# ---------------------------------------------------------------- adjacency --


def neighbour_maps(rows):
    """({h3: [land-linked h3, ...]}, {h3: [water-linked h3, ...]}), ascending."""
    land, water = {}, {}
    for row in rows:
        land[row["id"]] = sorted(n["id"] for n in row["neighbours"] if n["kind"] == "land")
        water[row["id"]] = sorted(n["id"] for n in row["neighbours"] if n["kind"] == "water")
    return land, water


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
    raise HexBuildError(f"{h}: no step towards unit {fed}")


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


# --------------------------------------------------------------- the tables --


def jurisdiction_table(table, units):
    return {
        "meta": table["meta"],
        "rows": [{"id": fed, "jurisdictions": row["jurisdictions"]} for fed, row in units],
    }


def stats_table(units):
    rows = []
    for fed, row in units:
        copy = dict(row)
        copy["id"] = fed
        rows.append(copy)
    return {"rows": rows}


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


# ------------------------------------------------------------------ drawing --


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


def _centroid(row):
    lon, lat = row["centroid"]
    return [float(Decimal(lon)), float(Decimal(lat))]


def drawing(rows_by_h3, units, names, owner, links, layer):
    geoms, arcs, users = hex_geometries(layer)
    unit_hexes = {row["id"]: fed for fed, row in units}
    backdrop = []
    for h in sorted(rows_by_h3):
        fed, dist = owner.get(h, (None, None))
        backdrop.append({
            "type": "Feature",
            "properties": {"h3": h, "unit": None if fed is None else str(fed), "dist": dist},
            "geometry": geoms[h],
        })
    unit_features = [
        {"type": "Feature",
         "properties": {"fed_id": str(fed), "name_en": names[fed][0]},
         "geometry": geoms[row["id"]]}
        for fed, row in sorted(units)
    ]
    borders = [
        {"type": "Feature", "properties": {},
         "geometry": {"type": "LineString", "coordinates": bwm._coords(arcs[index])}}
        for index in sorted(users)
        if len(users[index]) == 2 and all(h in unit_hexes for h in users[index])
    ]
    routes = [
        {"type": "Feature",
         "properties": {"fed_id_a": str(l["a"]), "fed_id_b": str(l["b"]), "kind": l["kind"],
                        "length": l["length"]},
         "geometry": {"type": "LineString",
                      "coordinates": [_centroid(rows_by_h3[h]) for h in l["path"]]}}
        for l in links if l["length"] > 1
    ]
    return backdrop, unit_features, borders, routes, users


def strait_links(links, users):
    """Unit links whose route crosses a pair of hexagons the table links by
    land but whose land, as the layer draws it, shares no edge: a strait the
    neighbour rule reads as land (interop.md, "The neighbour rule")."""
    shared = {}
    for index, hexes in users.items():
        if len(hexes) == 2:
            a, b = sorted(hexes)
            shared[(a, b)] = True
    out = []
    for l in links:
        if l["kind"] != "land":
            continue
        crossings = [
            (x, y) for x, y in zip(l["path"], l["path"][1:])
            if (min(x, y), max(x, y)) not in shared
        ]
        if crossings:
            out.append({"a": l["a"], "b": l["b"], "length": l["length"],
                        "crossings": [list(c) for c in crossings]})
    return out


def lake_routes(links, rows_by_h3):
    out = {}
    for lake, (w, s, e, n) in LAKE_BOXES.items():
        hits = []
        for l in links:
            for h in l["path"]:
                lon, lat = (Decimal(v) for v in rows_by_h3[h]["centroid"])
                if Decimal(str(w)) <= lon <= Decimal(str(e)) and Decimal(str(s)) <= lat <= Decimal(str(n)):
                    hits.append([l["a"], l["b"], l["kind"], l["length"]])
                    break
        out[lake] = hits
    return out


# ------------------------------------------------------------------- build --


def build(out_dir=OUT_DIR, raw_dir=RAW_DIR, verbose=True):
    out_dir = Path(out_dir)
    table = fetch_meridian.read_hex_table(raw_dir, parse_float=Decimal)
    layer = fetch_meridian.read_hex_layer(raw_dir, parse_float=Decimal)
    rows = table["rows"]
    rows_by_h3 = {row["id"]: row for row in rows}

    units = sorted(
        ((unit_id(row), row) for row in rows if row["population"] >= MIN_POPULATION),
        key=lambda u: u[0],
    )
    if len({fed for fed, _ in units}) != len(units):
        raise HexBuildError("two units share an id")
    land, water = neighbour_maps(rows)
    names = name_units(units, rows_by_h3, land)
    links, owner, link_report = build_links(units, land, water, rows_by_h3)

    ridings = [
        {"fed_id": str(fed), "name_en": names[fed][0], "name_fr": names[fed][0],
         "province": row["province"], "name_key": name_key(names[fed][0])}
        for fed, row in units
    ]
    adjacency = [
        {"fed_id_a": str(l["a"]), "fed_id_b": str(l["b"]), "adjacency_type": l["kind"]}
        for l in links
    ]
    places = places_rows(units)
    tokens = build_places.build_tokens(ridings)
    jurisdictions, dropped = bwm.jurisdiction_rows(jurisdiction_table(table, units))
    opens = bwm.opens_years(jurisdictions)
    stats = bwm.stats_rows(stats_table(units), opens)
    unit_rows = [
        {"fed_id": str(fed), "h3": row["id"], "name_csd": names[fed][1],
         "named_from_h3": names[fed][2]}
        for fed, row in units
    ]
    link_rows = [
        {"fed_id_a": str(l["a"]), "fed_id_b": str(l["b"]), "adjacency_type": l["kind"],
         "length": l["length"], "hexes": len(l["path"])}
        for l in links
    ]
    backdrop, unit_features, borders, routes, users = drawing(
        rows_by_h3, units, names, owner, links, layer
    )

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
    bwm.write_csv(out_dir / "units.csv", unit_rows, ["fed_id", "h3", "name_csd", "named_from_h3"])
    bwm.write_csv(out_dir / "links.csv", link_rows,
                  ["fed_id_a", "fed_id_b", "adjacency_type", "length", "hexes"])
    bwm.write_geojson(out_dir / "hexes.geojson", backdrop)
    bwm.write_geojson(out_dir / "geometry_simplified.geojson", unit_features)
    bwm.write_geojson(out_dir / "borders_shared.geojson", borders)
    bwm.write_geojson(out_dir / "routes.geojson", routes)
    (out_dir / "set.json").write_text(json.dumps({
        "key": "meridian-hex-v1.0.4",
        "unit_word": {"singular": "holding", "plural": "holdings"},
        "hexes": True,
    }, indent=2) + "\n", encoding="utf-8")

    def in_province(year):
        return sum(
            1 for fed, _ in units
            if any(j["fed_id"] == str(fed) and j["from_year"] <= year
                   and (j["to_year"] == "" or year <= j["to_year"])
                   and j["status"] == "province" and j["sovereign"] == "Canada"
                   for j in jurisdictions)
        )

    borrowed = [
        {"fed_id": r["fed_id"], "name": names[int(r["fed_id"])][0], "from": r["named_from_h3"],
         "own_places": len(rows_by_h3[r["h3"]]["places"])}
        for r in unit_rows if r["named_from_h3"]
    ]
    report = {
        "source": f"meridian {fetch_meridian.HEX_TAG} ({fetch_meridian.HEX_UNIT})",
        "rows": len(rows),
        "units": len(units),
        "min_population": MIN_POPULATION,
        "units_named_from_their_own_places": len(units) - len(borrowed),
        "units_named_from_a_neighbouring_hexagon": borrowed,
        "units_without_a_token": [r["fed_id"] for r in ridings
                                  if not any(t["fed_id"] == r["fed_id"] for t in tokens)],
        "places": len(places),
        "places_designation_ok": sum(p["designation_ok"] for p in places),
        "units_with_a_designation_place": len({p["fed_id"] for p in places if p["designation_ok"]}),
        "units_in_a_province": {str(y): in_province(y) for y in (1867, 1870, 1871, 1873, 1905, 1949)},
        "opens_year_counts": {
            str(year): sum(1 for v in opens.values() if v == year)
            for year in sorted(set(opens.values()))
        },
        "jurisdiction_spans": len(jurisdictions),
        "jurisdiction_spans_dropped": dropped,
        "links": link_report,
        "routes": len(routes),
        "known_and_accepted": {
            "strait_links": strait_links(links, users),
            "routes_through_lakes_drawn_as_land": lake_routes(links, rows_by_h3),
        },
        "not_carried": {
            "score.cohesion": "absent from Meridian unit tables by design; not invented",
            "score.exposure": "not read by the game",
            "jurisdictions[].share": "a float area overlap; not read by the game",
            "score.gdp": "carried only as wealth_tier; an allocation, not a measurement",
            "ecozone": "not read by the game",
        },
    }
    (out_dir / "build_report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    if verbose:
        lr = link_report
        print(f"{len(units)} units; {lr['before_cap']['land_links']} land links before the cap"
              f" (mean {lr['before_cap']['mean_land_links_per_unit']}), groups"
              f" {lr['before_cap']['land_groups'][:4]}; after: {lr['after_cap']['land_links']} land,"
              f" {lr['after_cap']['water_links']} water, land groups"
              f" {lr['after_cap']['land_groups'][:4]}, board {lr['after_cap']['groups_counting_water_links']}")
        print(f"names borrowed: {len(borrowed)}; in a province: {report['units_in_a_province']}")
    return report


def main():
    try:
        build()
    except HexBuildError as exc:
        print(f"stopped: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
