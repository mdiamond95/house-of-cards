"""Build data/reference/adjacency.csv: land adjacency between 2023 Representation
Order federal electoral districts.

Source geometry: data/reference/raw/FED_CA_2023_EN.shp, in its native projection
EPSG:3347 (Statistics Canada Lambert Conformal Conic, units: metres) — using the
projected CRS directly means buffer/snap tolerances below are plain metres, no
reprojection needed.

Method: two ridings are land-adjacent when they share a real border segment, not
just a point. For each polygon we buffer its boundary line by TOLERANCE_M to make
a thin "border band" that absorbs small digitising gaps between independently
drawn polylines. Two ridings are adjacent when their border bands overlap in an
area corresponding to a shared length above MIN_SHARED_LENGTH_M. A single
corner-touch (three or more ridings meeting at a point) produces a small disc of
area ~= pi * TOLERANCE_M**2 (~707 sq. m at TOLERANCE_M=15), which is far below
the MIN_SHARED_LENGTH_M=75 threshold (band area ~= 2 * TOLERANCE_M * length, so
~2250 sq. m at the threshold) — chosen up front from the geometry of the
problem, not tuned against the spot-check pairs.

Only land adjacency is produced here. Water-only adjacency (e.g. a strait
crossing) is not inferred from geometry and is out of scope for this script —
see CLAUDE.md hard rule 3.
"""

import csv
from pathlib import Path

import shapefile
from shapely.geometry import shape
from shapely.strtree import STRtree

ROOT = Path(__file__).resolve().parent.parent
RAW_SHP = ROOT / "data" / "reference" / "raw" / "FED_CA_2023_EN.shp"
OUT_CSV = ROOT / "data" / "reference" / "adjacency.csv"

TOLERANCE_M = 15
MIN_SHARED_LENGTH_M = 75
MIN_BAND_AREA_M2 = 2 * TOLERANCE_M * MIN_SHARED_LENGTH_M


def load_geometries():
    sf = shapefile.Reader(str(RAW_SHP), encoding="utf-8")
    fed_ids = [str(r.as_dict()["FED_NUM"]) for r in sf.records()]
    geoms = [shape(sf.shape(i).__geo_interface__).buffer(0) for i in range(len(sf))]
    return fed_ids, geoms


def main():
    fed_ids, geoms = load_geometries()
    bands = [g.boundary.buffer(TOLERANCE_M) for g in geoms]

    tree = STRtree(bands)
    edges = set()
    for i, band_i in enumerate(bands):
        for j in tree.query(band_i):
            j = int(j)
            if j <= i:
                continue
            overlap = band_i.intersection(bands[j])
            if overlap.is_empty:
                continue
            if overlap.area >= MIN_BAND_AREA_M2:
                a, b = fed_ids[i], fed_ids[j]
                pair = (a, b) if a < b else (b, a)
                edges.add(pair)

    rows = sorted(edges)
    with open(OUT_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["fed_id_a", "fed_id_b", "adjacency_type"])
        for a, b in rows:
            writer.writerow([a, b, "land"])

    print(f"wrote {len(rows)} land-adjacency edges to {OUT_CSV}")


if __name__ == "__main__":
    main()
