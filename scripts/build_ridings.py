"""Build data/reference/ridings.csv from the 2023 Representation Order shapefile.

Source: data/reference/raw/FED_CA_2023_EN.shp (see raw/SOURCE.md for provenance).
Requires pyshp (`pip install pyshp`) — not one of the repo's stated dependencies
(openpyxl, shapely, pytest); added here to read the .dbf/.shp attribute table
without a full GDAL stack.
"""

import csv
import sys
from pathlib import Path

import shapefile

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from hoc.names import name_key  # noqa: E402  (after sys.path setup)

RAW_SHP = ROOT / "data" / "reference" / "raw" / "FED_CA_2023_EN.shp"
OUT_CSV = ROOT / "data" / "reference" / "ridings.csv"

PROVINCE_BY_CODE = {
    "10": "NL",
    "11": "PE",
    "12": "NS",
    "13": "NB",
    "24": "QC",
    "35": "ON",
    "46": "MB",
    "47": "SK",
    "48": "AB",
    "59": "BC",
    "60": "YT",
    "61": "NT",
    "62": "NU",
}


def main():
    sf = shapefile.Reader(str(RAW_SHP), encoding="utf-8")
    rows = []
    for record in sf.records():
        d = record.as_dict()
        fed_id = str(d["FED_NUM"])
        province = PROVINCE_BY_CODE[fed_id[:2]]
        name_en = d["ED_NAMEE"]
        name_fr = d["ED_NAMEF"]
        rows.append(
            {
                "fed_id": fed_id,
                "name_en": name_en,
                "name_fr": name_fr,
                "province": province,
                "name_key": name_key(name_en),
            }
        )
    rows.sort(key=lambda r: r["fed_id"])

    with open(OUT_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["fed_id", "name_en", "name_fr", "province", "name_key"])
        writer.writeheader()
        writer.writerows(rows)

    print(f"wrote {len(rows)} ridings to {OUT_CSV}")


if __name__ == "__main__":
    main()
