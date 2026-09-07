#!/usr/bin/env python3
"""Build data/reference/places_by_riding.csv and riding_tokens.csv.

    python scripts/build_places.py

Rules 0.8 draws a house's territorial designation from its own ground rather
than from a province-wide bank, so it needs to know two things about a riding:
what places are in it, and what its own name is made of.

**places_by_riding.csv** — every Canadian point in Natural Earth's 10m populated
places, assigned to the riding whose polygon contains it. The polygons are the
*unsimplified* clipped geometry: `data/reference/geometry_simplified.geojson`
is drawn for a map and its boundaries have been moved by up to a kilometre,
which is enough to put a town on the wrong side of a line in dense urban
ridings. Clipped rather than raw, for the same reason the map is: the Elections
Canada boundary file runs out into open water, and an uncliped polygon can
swallow a point across a strait.

Natural Earth resolves 255 Canadian places at 10m, so most ridings get none —
which is why the designation draw has four tiers and not one (see hoc/sim.py's
`_designation_candidates`).

**riding_tokens.csv** — the usable words in a riding's own name, which is the
tier that is almost always available. A riding name is a compound of places
joined by em dashes, often qualified by a compass direction that means nothing
as a peerage designation: "Vancouver East" is a place called Vancouver, and a
Baron of "East" would be nonsense. So the name is split on the em dash,
compass words are stripped from either end of each part, "and the Islands"-type
tails are dropped, and what is left is kept if it is four letters or more.

French particles stay intact: "Saint-Jérôme" is one token, not "Saint" and
"Jérôme", because the hyphen is part of the name rather than a separator. That
also means a compass word joined by a hyphen is left alone, and it should be:
of the four tokens that end in one, three — Côte-Nord, Côte-du-Sud and
Rivière-du-Nord — are place names in their own right, and stripping them would
produce a "Côte" and a "Rivière" that name nothing.
"""

import csv
import json
import re
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

RAW_DIR = ROOT / "data" / "reference" / "raw"
PLACES_SHP = RAW_DIR / "ne_10m_populated_places_simple.shp"
RIDINGS_CSV = ROOT / "data" / "reference" / "ridings.csv"
OUT_PLACES = ROOT / "data" / "reference" / "places_by_riding.csv"
OUT_TOKENS = ROOT / "data" / "reference" / "riding_tokens.csv"

# Compass and centrality qualifiers, stripped from either end of a name part.
# These are the words a riding name uses to distinguish one seat from its
# neighbour; none of them is a place, and a peerage "of North" would be absurd.
COMPASS = {
    "east", "west", "north", "south", "centre", "center", "central",
    "nord", "sud", "est", "ouest", "centre-ville",
    "northeast", "northwest", "southeast", "southwest",
    "nord-est", "nord-ouest", "sud-est", "sud-ouest",
    "upper", "lower",
}

# Tails that qualify rather than name: "Kingston and the Islands" is Kingston.
TAIL_PATTERNS = (
    re.compile(r"\s+and\s+the\s+\w+$", re.IGNORECASE),
    re.compile(r"\s+et\s+les\s+\w+$", re.IGNORECASE),
    re.compile(r"\s+and\s+\w+\s+Islands?$", re.IGNORECASE),
)

# The em dash the 2023 Representation Order uses to join the parts of a
# compound riding name. The plain hyphen is *not* a separator: it is part of
# names like Saint-Jérôme and Trois-Rivières.
EM_DASH = "—"

MIN_TOKEN_LETTERS = 4


def letters(text):
    """Letter count, accents folded, so 'Jérôme' counts as six."""
    folded = unicodedata.normalize("NFKD", text)
    return sum(1 for ch in folded if ch.isalpha())


def name_tokens(name_en):
    """The usable designation tokens in a riding's name, in name order."""
    tokens = []
    for part in name_en.split(EM_DASH):
        part = part.strip()
        for pattern in TAIL_PATTERNS:
            part = pattern.sub("", part).strip()
        # Strip compass qualifiers from either end, repeatedly: "North Island"
        # and "Vancouver East" both reduce, and so does "West Nova Scotia East".
        words = part.split()
        while words and words[0].lower().strip(",") in COMPASS:
            words.pop(0)
        while words and words[-1].lower().strip(",") in COMPASS:
            words.pop()
        token = " ".join(words).strip(" ,-")
        if not token or letters(token) < MIN_TOKEN_LETTERS:
            continue
        if token.lower() in COMPASS:
            continue
        if token not in tokens:
            tokens.append(token)
    return tokens


def load_ridings():
    with open(RIDINGS_CSV, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def build_tokens(rows):
    out = []
    for row in rows:
        for order, token in enumerate(name_tokens(row["name_en"])):
            out.append({"fed_id": row["fed_id"], "token": token, "token_order": order})
    return out


def build_places(rows):
    """Assign every Canadian populated place to the riding that contains it."""
    import shapefile
    from shapely.geometry import Point
    from shapely.strtree import STRtree

    # The clipped-but-unsimplified polygons, built here rather than read from
    # disk: the repository keeps only simplified geometry, whose boundaries have
    # been moved by up to a kilometre. That is fine for drawing a map and not
    # fine for deciding which riding a town is in. build_geometry.py already
    # knows how to build the land mask and clip; this reuses it rather than
    # keeping a second definition of "the shape of a riding".
    import build_geometry

    print("clipping the ridings to the coastline (this takes a minute)...")
    raw = build_geometry.load_fed_ridings()
    clipped, _ = build_geometry.clip_ridings(raw)
    geoms = [r["geom"] for r in clipped]
    fed_ids = [r["fed_id"] for r in clipped]
    tree = STRtree(geoms)

    # The unclipped polygons, as a fallback. Ten Canadian places — Belleville
    # among them — sit just outside Natural Earth's 10m coastline or inside a
    # clipped lake, and land in no clipped riding at all. They are real towns in
    # real ridings; the clip is a cartographic convenience, and dropping a place
    # because of it would lose a good designation for no reason. Every one of
    # the 255 Canadian places falls inside exactly one unclipped polygon.
    raw_geoms = [r["geom"] for r in raw]
    raw_fed_ids = [r["fed_id"] for r in raw]
    raw_tree = STRtree(raw_geoms)

    sf = shapefile.Reader(str(PLACES_SHP), encoding="utf-8")
    fields = [f[0] for f in sf.fields[1:]]
    name_field = "name" if "name" in fields else "NAME"
    country_field = "adm0_a3" if "adm0_a3" in fields else "ADM0_A3"
    pop_field = "pop_max" if "pop_max" in fields else "POP_MAX"

    assigned, unassigned, offshore = [], [], []
    for index, record in enumerate(sf.records()):
        row = record.as_dict()
        if row.get(country_field) != "CAN":
            continue
        name = (row.get(name_field) or "").strip()
        if not name:
            continue
        point = Point(*sf.shape(index).points[0])
        fed_id = _containing(point, tree, geoms, fed_ids)
        by_coastline = False
        if fed_id is None:
            fed_id = _containing(point, raw_tree, raw_geoms, raw_fed_ids)
            by_coastline = fed_id is not None
        population = row.get(pop_field)
        population = int(population) if isinstance(population, (int, float)) and population > 0 else 0
        if fed_id is None:
            unassigned.append(name)
            continue
        if by_coastline:
            offshore.append(name)
        assigned.append({"fed_id": fed_id, "place": name, "population": population})

    # Largest first inside a riding, then by name: the draw's first tier prefers
    # the biggest place, and a stable order is what makes the draw reproducible.
    assigned.sort(key=lambda r: (r["fed_id"], -r["population"], r["place"]))
    return assigned, unassigned, offshore


def _containing(point, tree, geoms, fed_ids):
    """The fed_id of the first polygon covering `point`, or None."""
    for candidate in tree.query(point):
        position = int(candidate)
        if geoms[position].covers(point):
            return fed_ids[position]
    return None


def write_csv(path, rows, columns):
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=columns, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def main():
    rows = load_ridings()

    tokens = build_tokens(rows)
    write_csv(OUT_TOKENS, tokens, ["fed_id", "token", "token_order"])
    with_tokens = len({t["fed_id"] for t in tokens})
    print(f"{OUT_TOKENS.relative_to(ROOT)}: {len(tokens)} token(s) over {with_tokens} riding(s)")
    missing = [r["name_en"] for r in rows if r["fed_id"] not in {t["fed_id"] for t in tokens}]
    if missing:
        print(f"  warning: {len(missing)} riding(s) yielded no token: {', '.join(missing[:5])}")

    places, unassigned, offshore = build_places(rows)
    write_csv(OUT_PLACES, places, ["fed_id", "place", "population"])
    covered = len({p["fed_id"] for p in places})
    print(
        f"{OUT_PLACES.relative_to(ROOT)}: {len(places)} place(s) in {covered} of"
        f" {len(rows)} riding(s)"
    )
    if offshore:
        print(
            f"  {len(offshore)} place(s) fell outside the clipped coastline and were"
            f" assigned from the unclipped polygon: {', '.join(sorted(offshore))}"
        )
    if unassigned:
        print(
            f"  {len(unassigned)} Canadian place(s) fell in no riding polygon at all:"
            f" {', '.join(sorted(unassigned))}"
        )


if __name__ == "__main__":
    main()
