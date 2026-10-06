#!/usr/bin/env python3
"""Build the `meridian-v1.0.3` reference-data version from Meridian's riding table.

    python scripts/build_world_meridian.py

Reads the two files `scripts/fetch_meridian.py` committed under
`data/reference/meridian/v1.0.3/raw/` (hash- and format-checked on every read)
and writes, beside them, the tables a scenario whose manifest says
`"reference_data": "meridian-v1.0.3"` is built from:

    ridings.csv               the existing shape: fed_id, name_en, name_fr, province, name_key
    adjacency.csv             the existing shape, from each row's `neighbours`
    places_by_riding.csv      the existing shape, plus spans_ridings and designation_ok
    riding_tokens.csv         the existing shape, by the same rule as build_places.py
    riding_stats.csv          new: integers only, one row per riding
    riding_jurisdictions.csv  new: one row per jurisdiction span, in whole years
    build_report.json         what this build had to decide, for the record

**No float leaves this script.** Every number in the table is parsed as a
`decimal.Decimal` — exactly the digits Meridian wrote — and each value an
engine might read is turned into an integer here, once, by the rule in
docs/DETERMINISM.md ("Reference data from Meridian"). Neither engine ever sees
a float from Meridian. Geometry coordinates stay decimal degrees, because a map
is drawn in them, but they too are computed in exact decimal arithmetic and
are read only by the site's map, never by an engine.

**Drawing.** This script writes no geometry. The layer is Meridian's unclipped
file; the map is drawn from the coast-clipped files in `data/reference/`.

**What the table does not have is not made up.** It has no `score.cohesion`
(Meridian omits it for unit tables: a cohesion needs a split, a lens and a
scope, and a riding has none), so there is no cohesion column. `areaKm2` is
land area, clipped to the shoreline, so the column is `land_area_km2`. GDP is
an allocation, not a measurement (the table's `gdpCaveat`), so it is carried
only as a quintile.

**Places.** Each census place appears under exactly one riding — the one its
point falls in — with the whole place's population, so a city larger than the
riding it was filed under (Halifax under Central Nova, Montréal under Papineau)
is marked `spans_ridings = 1`. Such a place is never a designation for that
riding. Many census places are administrative units, not places ("Division
No.  1, Subd. U", "Yarmouth 33"), so `designation_ok` is 1 only for a name a
peerage could be styled after (designation_ok() below; docs/DETERMINISM.md).
`hoc/places.py` and `web/engine/adjacency.js` keep a place as a designation
candidate only when it is 1.
"""

import csv
import gzip
import json
import re
import sys
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from hoc.names import name_key  # noqa: E402  (after sys.path setup)

import build_places  # noqa: E402  (riding-name tokens: one rule for both reference sets)
import fetch_meridian  # noqa: E402

OUT_DIR = fetch_meridian.OUT_DIR
RAW_DIR = fetch_meridian.RAW_DIR

# The years the game's world spans: Confederation to the present day.
FIRST_YEAR = 1867

# Jurisdiction statuses under which a riding's ground was not yet open to a
# Crown grant in the game's sense: chartered to the Hudson's Bay Company, or
# claimed and unorganized. `opens_year` is the first year a riding is neither.
UNOPENED_STATUSES = ("hbc_charter", "unorganized")

TIERS = 5
COORDINATE_PLACES = Decimal("0.000001")  # six decimal places of a degree, ~0.1 m


# ------------------------------------------------------------------ numbers --


def to_integer(value):
    """Round half up to a whole number, exactly. `value` is a Decimal or int."""
    return int(Decimal(value).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def permille(value):
    """A 0–1 share as an integer per mille, rounded half up, exactly."""
    value = Decimal(value)
    if value < 0 or value > 1:
        raise ValueError(f"share {value} is outside 0–1")
    return to_integer(value * 1000)


def tiers(rows, key):
    """{fed_id: tier 1–5}, by quintile of key(row), ties broken by fed id.

    Rows are ranked ascending by (value, fed_id); the riding at 0-based rank r
    of n is in tier 1 + (5 × r) // n. Integer arithmetic only, and `value` is
    an exact Decimal or int, so the ranking is the same on every machine.
    Tier 5 is the top fifth.
    """
    ranked = sorted(rows, key=lambda row: (key(row), row["id"]))
    n = len(ranked)
    return {row["id"]: 1 + (TIERS * rank) // n for rank, row in enumerate(ranked)}


# ---------------------------------------------------------------- the tables --


def ridings_rows(table):
    return [
        {
            "fed_id": str(row["id"]),
            "name_en": row["name"],
            "name_fr": row["nameFr"],
            "province": row["province"],
            "name_key": name_key(row["name"]),
        }
        for row in table["rows"]
    ]


def adjacency_rows(table):
    """Every border-sharing pair once, fed_id_a < fed_id_b, in pair order.

    Meridian's `neighbours` are the ridings sharing a border arc in its riding
    layer. It is the same 894-pair set as the land adjacency built from the
    clipped Elections Canada file (tests/test_meridian.py holds it to that), so
    every pair is `land`.
    """
    ids = {row["id"] for row in table["rows"]}
    pairs = set()
    for row in table["rows"]:
        for other in row["neighbours"]:
            if other not in ids:
                raise ValueError(f"{row['id']} names neighbour {other}, which is not a riding")
            if row["id"] not in next(r for r in table["rows"] if r["id"] == other)["neighbours"]:
                raise ValueError(f"neighbours not symmetric: {row['id']} / {other}")
            pairs.add((min(row["id"], other), max(row["id"], other)))
    return [
        {"fed_id_a": str(a), "fed_id_b": str(b), "adjacency_type": "land"}
        for a, b in sorted(pairs)
    ]


# ------------------------------------------------------------ designations --

# The characters a designation may contain: letters (accented included), spaces,
# hyphens, apostrophes (straight or curly) and periods. No digit, comma,
# parenthesis or slash — "Yarmouth 33" and "Division No.  1, Subd. U" are
# census bookkeeping, not places a peerage could be styled after.
DESIGNATION_PUNCTUATION = " -'\u2019."

# Words that mark an administrative unit rather than a place, refused wherever
# they appear as a whole word.
ADMINISTRATIVE_WORDS = (
    "Subd", "Unorganized", "Division", "Part", "Partie", "Area", "No", "District",
    "Region", "Regional", "Improvement", "Special", "County", "Municipality",
    "Municipal", "Rural", "Reserve", "Settlement", "Nation", "Communauté",
)
_ADMINISTRATIVE = re.compile(
    r"(?<!\w)(?:%s)(?!\w)" % "|".join(re.escape(word) for word in ADMINISTRATIVE_WORDS)
)

MAX_DESIGNATION_WORDS = 4


def designation_ok(name, spans_ridings):
    """1 if a place may be a riding's territorial designation, else 0.

    All of: it does not span its riding; it is made only of letters, spaces,
    hyphens, apostrophes and periods; no administrative word appears in it as a
    whole word; it does not end in a space and a single capital letter (a
    lettered subdivision, "Cariboo I"); it has at most four words split on
    spaces. A name that fails is marked, never rewritten into one that would
    pass (CLAUDE.md hard rule 1): "Yarmouth 33" is not "Yarmouth".
    """
    if spans_ridings:
        return 0
    if not name or not all(ch.isalpha() or ch in DESIGNATION_PUNCTUATION for ch in name):
        return 0
    if _ADMINISTRATIVE.search(name):
        return 0
    if len(name) >= 2 and name[-2] == " " and name[-1].isupper():
        return 0
    if len(name.split(" ")) > MAX_DESIGNATION_WORDS:
        return 0
    return 1


def places_rows(table):
    """Every place, in the table's own order: riding by riding, population
    descending, ties as Meridian listed them. That order is the order the
    designation draw reads, and keeping Meridian's means it is never re-decided."""
    out = []
    for row in table["rows"]:
        for place in row["places"]:
            spans = 1 if place["population"] > row["population"] else 0
            out.append({
                "fed_id": str(row["id"]),
                "place": place["name"],
                "population": place["population"],
                "spans_ridings": spans,
                "designation_ok": designation_ok(place["name"], spans),
            })
    return out


def token_rows(ridings):
    return build_places.build_tokens(ridings)


def jurisdiction_rows(table):
    """One row per span, in whole years, and the spans dropped on the way.

    from_year is the year of `from`; to_year is the next span's from_year − 1,
    empty for the span in force today (`to: null`). A span that comes out empty
    — two changes in one year — is dropped and the later one kept, since it is
    the one in force for the rest of that year. Each row's `share` (an area
    overlap, a float) is not carried: nothing in the game reads it.
    """
    out, dropped = [], []
    for row in table["rows"]:
        spans = row["jurisdictions"]
        if spans[0]["from"] != table["meta"]["jurisdictionsFrom"]:
            raise ValueError(f"{row['id']}: first span starts {spans[0]['from']}")
        for here, after in zip(spans, spans[1:]):
            if here["to"] != after["from"]:
                raise ValueError(f"{row['id']}: spans not contiguous at {here['to']}")
        if spans[-1]["to"] is not None:
            raise ValueError(f"{row['id']}: last span ends {spans[-1]['to']}")
        for index, span in enumerate(spans):
            if span.get("fallback"):
                raise ValueError(f"{row['id']}: span from {span['from']} is a fallback")
            from_year = int(span["from"][:4])
            to_year = None if index == len(spans) - 1 else int(spans[index + 1]["from"][:4]) - 1
            if to_year is not None and to_year < from_year:
                dropped.append({"fed_id": row["id"], "from": span["from"], "name": span["name"]})
                continue
            out.append({
                "fed_id": str(row["id"]),
                "from_year": from_year,
                "to_year": "" if to_year is None else to_year,
                "unit": span["unit"],
                "name": span["name"],
                "status": span["status"],
                "sovereign": span["sovereign"],
            })
    return out, dropped


def opens_years(jurisdictions):
    """{fed_id: the first year its status is neither hbc_charter nor unorganized}."""
    out = {}
    for row in jurisdictions:
        if row["status"] not in UNOPENED_STATUSES and row["fed_id"] not in out:
            out[row["fed_id"]] = row["from_year"]
    return out


def stats_rows(table, opens):
    rows = table["rows"]
    wealth = tiers(rows, lambda row: row["score"]["gdp"])
    resource = tiers(rows, lambda row: Decimal(row["score"]["resource_index"]))
    out = []
    for row in rows:
        if row["score"]["population"] != row["population"]:
            raise ValueError(f"{row['id']}: score.population differs from population")
        out.append({
            "fed_id": str(row["id"]),
            "population": row["population"],
            "land_area_km2": to_integer(row["areaKm2"]),
            "wealth_tier": wealth[row["id"]],
            "resource_tier": resource[row["id"]],
            "french_permille": permille(row["shares"]["french"]),
            "indigenous_identity_permille": permille(row["shares"]["indigenous_identity"]),
            "urban_class": int(row["urbanClass"]),
            "industry_dominant": int(row["industryDominant"]),
            "opens_year": opens[str(row["id"])],
        })
    return out


# ------------------------------------------------------------------ geometry --


def decode_arcs(layer):
    """TopoJSON arcs as lists of (lon, lat) Decimals, delta-decoded exactly."""
    sx, sy = (Decimal(v) for v in layer["transform"]["scale"])
    tx, ty = (Decimal(v) for v in layer["transform"]["translate"])
    arcs = []
    for arc in layer["arcs"]:
        x = y = 0
        points = []
        for dx, dy in arc:
            x += int(dx)
            y += int(dy)
            points.append((
                (x * sx + tx).quantize(COORDINATE_PLACES, rounding=ROUND_HALF_UP),
                (y * sy + ty).quantize(COORDINATE_PLACES, rounding=ROUND_HALF_UP),
            ))
        arcs.append(points)
    return arcs


def _ring(arcs, indexes):
    """A ring stitched from arc indexes; ~i is arc i reversed. Consecutive arcs
    share an end point, which is kept once."""
    points = []
    for index in indexes:
        arc = arcs[index] if index >= 0 else list(reversed(arcs[~index]))
        points.extend(arc if not points else arc[1:])
    return points


def _coords(points):
    # The quantized Decimal's shortest float repr is that decimal exactly
    # (six places is well inside a double's 15–17 significant digits).
    return [[float(x), float(y)] for x, y in points]


def geometry(layer, ridings):
    """(features, borders): one feature per riding, and the arcs two ridings share."""
    arcs = decode_arcs(layer)
    names = {int(r["fed_id"]): r["name_en"] for r in ridings}
    users = {}
    features = []
    for geom in layer["objects"]["ridings"]["geometries"]:
        fed = int(geom["properties"]["fed"])
        if fed not in names:
            raise ValueError(f"layer has fed {fed}, which is not a riding")
        polygons = [geom["arcs"]] if geom["type"] == "Polygon" else geom["arcs"]
        if geom["type"] not in ("Polygon", "MultiPolygon"):
            raise ValueError(f"{fed}: geometry type {geom['type']}")
        rings_out = []
        for polygon in polygons:
            rings_out.append([_coords(_ring(arcs, ring)) for ring in polygon])
            for ring in polygon:
                for index in ring:
                    users.setdefault(index if index >= 0 else ~index, set()).add(fed)
        features.append({
            "type": "Feature",
            "properties": {"fed_id": str(fed), "name_en": names[fed]},
            "geometry": (
                {"type": "Polygon", "coordinates": rings_out[0]} if len(rings_out) == 1
                else {"type": "MultiPolygon", "coordinates": rings_out}
            ),
        })
    if sorted(int(f["properties"]["fed_id"]) for f in features) != sorted(names):
        raise ValueError("the layer does not have exactly one geometry per riding")
    features.sort(key=lambda f: f["properties"]["fed_id"])
    # Riding-to-riding borders only — an arc used by two ridings. An arc used by
    # one is coastline or the national border, and is never stroked
    # (hoc/export/map.py).
    borders = [
        {"type": "Feature", "properties": {},
         "geometry": {"type": "LineString", "coordinates": _coords(arcs[index])}}
        for index in sorted(users) if len(users[index]) == 2
    ]
    return features, borders


# ------------------------------------------------------------------- writing --


def write_csv(path, rows, columns, lineterminator="\n"):
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=columns, lineterminator=lineterminator)
        writer.writeheader()
        writer.writerows(rows)


def write_geojson(path, features):
    text = json.dumps({"type": "FeatureCollection", "features": features},
                      ensure_ascii=False, separators=(",", ":"))
    path.write_text(text + "\n", encoding="utf-8")


def build(out_dir=OUT_DIR, raw_dir=RAW_DIR, verbose=True):
    out_dir = Path(out_dir)
    table = fetch_meridian.read_table(raw_dir, parse_float=Decimal)
    layer = json.loads(
        gzip.decompress((Path(raw_dir) / fetch_meridian.LAYER_FILE).read_bytes()).decode("utf-8"),
        parse_float=Decimal,
    )
    fetch_meridian.read_layer(raw_dir)  # hash check

    ridings = ridings_rows(table)
    adjacency = adjacency_rows(table)
    places = places_rows(table)
    tokens = token_rows(ridings)
    jurisdictions, dropped = jurisdiction_rows(table)
    opens = opens_years(jurisdictions)
    stats = stats_rows(table, opens)
    features, borders = geometry(layer, ridings)

    # CRLF, as scripts/build_ridings.py and build_adjacency.py write theirs, so
    # that where the two sets agree their files are byte-identical.
    write_csv(out_dir / "ridings.csv", ridings,
              ["fed_id", "name_en", "name_fr", "province", "name_key"], "\r\n")
    write_csv(out_dir / "adjacency.csv", adjacency,
              ["fed_id_a", "fed_id_b", "adjacency_type"], "\r\n")
    write_csv(out_dir / "places_by_riding.csv", places,
              ["fed_id", "place", "population", "spans_ridings", "designation_ok"])
    write_csv(out_dir / "riding_tokens.csv", tokens, ["fed_id", "token", "token_order"])
    write_csv(out_dir / "riding_stats.csv", stats, [
        "fed_id", "population", "land_area_km2", "wealth_tier", "resource_tier",
        "french_permille", "indigenous_identity_permille", "urban_class",
        "industry_dominant", "opens_year",
    ])
    write_csv(out_dir / "riding_jurisdictions.csv", jurisdictions,
              ["fed_id", "from_year", "to_year", "unit", "name", "status", "sovereign"])
    # No drawing files. Meridian's layer is the unclipped Elections Canada file
    # and fills open water, so this set draws with the coast-clipped geometry in
    # data/reference/ (hoc/export/map.py's _drawing_path). `features` and
    # `borders` are still decoded, to check the layer has exactly the 343
    # ridings and to keep build_report.json's border_arcs as it was.

    usable = {p["fed_id"] for p in places if not p["spans_ridings"]}
    designations = [p for p in places if p["designation_ok"]]
    first_spans = sorted(
        int(r["fed_id"]) for r in ridings
        if any(p["fed_id"] == r["fed_id"] for p in places)
        and next(p for p in places if p["fed_id"] == r["fed_id"])["spans_ridings"]
    )
    report = {
        "source": f"meridian {fetch_meridian.TAG}",
        "ridings": len(ridings),
        "adjacency_pairs": len(adjacency),
        "places": len(places),
        "places_spanning_ridings": sum(p["spans_ridings"] for p in places),
        "ridings_without_places": len(ridings) - len({p["fed_id"] for p in places}),
        "ridings_whose_first_place_spans": len(first_spans),
        "ridings_with_a_usable_place": len(usable),
        "places_designation_ok": len(designations),
        "ridings_with_a_designation_place": len({p["fed_id"] for p in designations}),
        "jurisdiction_spans": len(jurisdictions),
        "jurisdiction_spans_dropped": dropped,
        "opens_year_counts": {
            str(year): sum(1 for v in opens.values() if v == year)
            for year in sorted(set(opens.values()))
        },
        "border_arcs": len(borders),
        "not_carried": {
            "score.cohesion": "absent from Meridian unit tables by design; not invented",
            "score.exposure": "not read by the game",
            "jurisdictions[].share": "a float area overlap; not read by the game",
            "score.gdp": "carried only as wealth_tier; an allocation, not a measurement",
        },
    }
    (out_dir / "build_report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    if verbose:
        rel = out_dir.relative_to(ROOT) if out_dir.is_relative_to(ROOT) else out_dir
        print(f"{rel}: {len(ridings)} ridings, {len(adjacency)} adjacency pairs,"
              f" {len(places)} places ({report['places_spanning_ridings']} spanning their riding),"
              f" {len(usable)} ridings with a usable place, {len(designations)} places fit"
              f" for a designation in {report['ridings_with_a_designation_place']} ridings,"
              f" {len(tokens)} tokens,"
              f" {len(jurisdictions)} jurisdiction spans, {len(borders)} border arcs")
        if dropped:
            print(f"  dropped {len(dropped)} empty span(s): {dropped}")
        else:
            print("  no jurisdiction span was empty after conversion to years")
    return report


def main():
    build()
    return 0


if __name__ == "__main__":
    sys.exit(main())
