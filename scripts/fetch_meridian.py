#!/usr/bin/env python3
"""Download Meridian's riding table and layer at a pinned release tag.

    python scripts/fetch_meridian.py            fetch, check, write raw/ and SOURCE.md
    python scripts/fetch_meridian.py --check    check the committed files, fetch nothing
    python scripts/fetch_meridian.py --hexes [--check]
                                                the same for the hex trial's pin (v1.0.4)

Meridian (github.com/mdiamond95/meridian) publishes a *unit table* for the 343
federal ridings of the 2023 Representation Order: population, an allocated GDP,
language and identity shares, urban class, dominant industry, the census places
in each riding, its neighbours, and which jurisdiction it lay under from
1 July 1867 to today. This script takes two files from it, at one release tag,
into `data/reference/meridian/<tag>/raw/`:

    data/build/ridings.v1.json.gz              the unit table
    data/build/layers/ridings.v1.topojson.gz   the riding polygons it was built on

Meridian's consumer rules (docs/interop.md, "Unit tables") are followed here,
and nowhere else needs to: a release tag is pinned, never `main`; the table's
`format`, `version` and `unit` are checked and anything else is refused; rows
are keyed on (unit, id). Both files are hashed against the SHA-256 recorded
below and refused on any other hash. Meridian's versioning rule 7 makes a
released table immutable, so a hash mismatch is never "a newer copy" — it is a
different file, and the build must not go on.

The files are committed. Nothing is fetched at play time, in a CI replay or in
the browser: the network is touched only when this script is run by hand to
move the pin, which is done by adding a new reference-data version (CLAUDE.md,
"World data"), never by re-fetching into an old one.
"""

import argparse
import gzip
import hashlib
import json
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

TAG = "v1.0.3"
REPOSITORY = "mdiamond95/meridian"
BASE_URL = f"https://raw.githubusercontent.com/{REPOSITORY}/{TAG}/"

OUT_DIR = ROOT / "data" / "reference" / "meridian" / TAG
RAW_DIR = OUT_DIR / "raw"
SOURCE_MD = RAW_DIR / "SOURCE.md"

# (path in the Meridian repository, file name here, SHA-256). The table's hash
# was given by the director when the pin was set; the layer's was recorded on
# the first fetch at this tag and is pinned from then on, since a released file
# never changes (Meridian versioning rule 7).
FILES = (
    (
        "data/build/ridings.v1.json.gz",
        "ridings.v1.json.gz",
        "60f048f44c4952638ea941162a646cddadbf6fc11478b6838178dacd307e3eb7",
    ),
    (
        "data/build/layers/ridings.v1.topojson.gz",
        "ridings.v1.topojson.gz",
        "4e0be1c453e5f5cdcaa3216596b21b635ac9115b8c16b2b72958d4fc9beb8d15",
    ),
)

TABLE_FILE = "ridings.v1.json.gz"
LAYER_FILE = "ridings.v1.topojson.gz"

EXPECTED_FORMAT = "meridian.unitTable"
EXPECTED_VERSION = 1
EXPECTED_UNIT = "fed_2023"

# The hex board's pin (the hex trial: scripts/build_world_hex.py). Meridian
# v1.0.4 publishes H3 resolution-4 hexagons as a second unit table, with the
# layer of those hexagons clipped to land. Both hashes were given by the
# director when the pin was set. Same rules as the ridings': a tag, never
# `main`; format, version and unit checked; any other hash refused.
HEX_TAG = "v1.0.4"
HEX_BASE_URL = f"https://raw.githubusercontent.com/{REPOSITORY}/{HEX_TAG}/"
HEX_OUT_DIR = ROOT / "data" / "reference" / "meridian" / f"hex-{HEX_TAG}"
HEX_RAW_DIR = HEX_OUT_DIR / "raw"
HEX_FILES = (
    (
        "data/build/hexes.r4.v1.json.gz",
        "hexes.r4.v1.json.gz",
        "94c2f806ed3ed6315647858b63cc777209c3a97280da7caa98a65734eb455a8a",
    ),
    (
        "data/build/layers/hexes.r4.v1.topojson.gz",
        "hexes.r4.v1.topojson.gz",
        "336cb743b1da8184af2cf515ef75a34312126c09243d15a735c108c855330325",
    ),
)
HEX_TABLE_FILE = "hexes.r4.v1.json.gz"
HEX_LAYER_FILE = "hexes.r4.v1.topojson.gz"
HEX_UNIT = "h3_r4"


class MeridianError(Exception):
    """A Meridian file was not the file this pin names."""


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def check_hash(name, data, expected, tag=TAG):
    actual = sha256(data)
    if actual != expected:
        raise MeridianError(
            f"{name}: SHA-256 {actual}, expected {expected}. Refusing it: a released"
            f" Meridian file never changes, so this is not the file {tag} published."
        )


def check_table(table, unit=EXPECTED_UNIT):
    """Meridian's unit-table consumer rule 4: format, version and unit, or refuse."""
    if table.get("format") != EXPECTED_FORMAT:
        raise MeridianError(f"format {table.get('format')!r}, expected {EXPECTED_FORMAT!r}")
    if table.get("version") != EXPECTED_VERSION:
        raise MeridianError(f"version {table.get('version')!r}, expected {EXPECTED_VERSION}")
    if table.get("unit") != unit:
        raise MeridianError(f"unit {table.get('unit')!r}, expected {unit!r}")
    return table


def read_table(raw_dir=RAW_DIR, parse_float=None):
    """The committed unit table, hash- and format-checked.

    `parse_float` is passed to json: the world builder reads every number as a
    `decimal.Decimal` so that no float is ever formed (docs/DETERMINISM.md,
    "Reference data from Meridian").
    """
    data = (Path(raw_dir) / TABLE_FILE).read_bytes()
    check_hash(TABLE_FILE, data, dict((f[1], f[2]) for f in FILES)[TABLE_FILE])
    kwargs = {} if parse_float is None else {"parse_float": parse_float}
    return check_table(json.loads(gzip.decompress(data).decode("utf-8"), **kwargs))


def read_layer(raw_dir=RAW_DIR):
    data = (Path(raw_dir) / LAYER_FILE).read_bytes()
    check_hash(LAYER_FILE, data, dict((f[1], f[2]) for f in FILES)[LAYER_FILE])
    return json.loads(gzip.decompress(data).decode("utf-8"))


def read_hex_table(raw_dir=HEX_RAW_DIR, parse_float=None):
    """The committed hex unit table (v1.0.4, `h3_r4`), hash- and format-checked."""
    data = (Path(raw_dir) / HEX_TABLE_FILE).read_bytes()
    check_hash(HEX_TABLE_FILE, data, dict((f[1], f[2]) for f in HEX_FILES)[HEX_TABLE_FILE], HEX_TAG)
    kwargs = {} if parse_float is None else {"parse_float": parse_float}
    return check_table(json.loads(gzip.decompress(data).decode("utf-8"), **kwargs), HEX_UNIT)


def read_hex_layer(raw_dir=HEX_RAW_DIR, parse_float=None):
    """The committed clipped hex layer (v1.0.4), hash-checked."""
    data = (Path(raw_dir) / HEX_LAYER_FILE).read_bytes()
    check_hash(HEX_LAYER_FILE, data, dict((f[1], f[2]) for f in HEX_FILES)[HEX_LAYER_FILE], HEX_TAG)
    kwargs = {} if parse_float is None else {"parse_float": parse_float}
    return json.loads(gzip.decompress(data).decode("utf-8"), **kwargs)


def fetch(url):
    with urllib.request.urlopen(url, timeout=60) as response:
        return response.read()


def source_md(table):
    meta = table["meta"]
    lines = [
        f"# Source: Meridian {TAG}, riding unit table",
        "",
        "## What this is",
        "",
        "The two files below, downloaded unmodified by `scripts/fetch_meridian.py` from the",
        f"Meridian repository (`{REPOSITORY}`) at release tag `{TAG}`, and the input to",
        "`scripts/build_world_meridian.py`, which builds the `meridian-v1.0.3` reference-data",
        "version in the directory above this one.",
        "",
        "| File | URL | SHA-256 |",
        "|---|---|---|",
    ]
    for remote, local, digest in FILES:
        lines.append(f"| `{local}` | {BASE_URL}{remote} | `{digest}` |")
    lines += [
        "",
        f"Tag: `{TAG}`. Both hashes are checked on every read and the files are refused on any",
        "other; Meridian's versioning rule 7 makes a released file immutable, so a different",
        "hash is a different file, not a newer copy of this one.",
        "",
        "## What the table declares",
        "",
        f"- format `{table['format']}`, version `{table['version']}`, unit `{table['unit']}`"
        " (checked; anything else is refused)",
        f"- {len(table['rows'])} rows: {meta['unitName']}",
        f"- census year {meta['censusYear']}; GDP method `{meta['gdpMethod']}`, reference year"
        f" {meta['gdpReferenceYear']}, `{meta['gdpPrices']}`",
        f"- jurisdictions from the atlas `{meta['atlasVersion']}`, from {meta['jurisdictionsFrom']}",
        "",
        "**GDP is an allocation, not a measurement.** The table's own caveat, verbatim:",
        "",
        f"> {table['gdpCaveat']}",
        "",
        "## Attribution and licences",
        "",
        "As the table's `meta.sources` gives them:",
        "",
    ]
    for source in meta["sources"]:
        lines.append(
            f"- `{source['source']}`: {source['text']} {source['licence']}, {source['url']}"
        )
    lines += [
        "",
        "## Retrieval",
        "",
        "Fetched over HTTPS from `raw.githubusercontent.com`, which serves `.gz` as plain bytes;",
        "the files are stored exactly as served. Nothing is fetched at play time, in CI or in the",
        "browser. To move to a newer Meridian release, add a new reference-data version beside",
        "this one (CLAUDE.md, \"World data\"); never re-fetch into this directory.",
        "",
    ]
    return "\n".join(lines)


def hex_source_md(table):
    """SOURCE.md for the hex pin: the same record as the ridings' SOURCE.md."""
    meta = table["meta"]
    lines = [
        f"# Source: Meridian {HEX_TAG}, H3 resolution-4 hexagon unit table",
        "",
        "## What this is",
        "",
        "The two files below, downloaded unmodified by `scripts/fetch_meridian.py --hexes` from",
        f"the Meridian repository (`{REPOSITORY}`) at release tag `{HEX_TAG}`, and the input to",
        "`scripts/build_world_hex.py`, which builds the `meridian-hex-v1.0.4` reference-data",
        "version (the hex trial) in the directory above this one.",
        "",
        "| File | URL | SHA-256 |",
        "|---|---|---|",
    ]
    for remote, local, digest in HEX_FILES:
        lines.append(f"| `{local}` | {HEX_BASE_URL}{remote} | `{digest}` |")
    lines += [
        "",
        f"Tag: `{HEX_TAG}`. Both hashes are checked on every read and the files are refused on any",
        "other; Meridian's versioning rule 7 makes a released file immutable.",
        "",
        "## What the table declares",
        "",
        f"- format `{table['format']}`, version `{table['version']}`, unit `{table['unit']}`"
        " (checked; anything else is refused)",
        f"- {len(table['rows'])} rows: {meta['unitName']}",
        f"- H3 resolution {meta['h3Resolution']}, mesh `{meta['meshVersion']}`, layer `{meta['layer']}`",
        f"- census year {meta['censusYear']}; GDP method `{meta['gdpMethod']}`, reference year"
        f" {meta['gdpReferenceYear']}, `{meta['gdpPrices']}`",
        f"- jurisdictions from the atlas `{meta['atlasVersion']}`, from {meta['jurisdictionsFrom']}",
        "",
        "**GDP is an allocation, not a measurement.** The table's own caveat, verbatim:",
        "",
        f"> {table['gdpCaveat']}",
        "",
        "## Attribution and licences",
        "",
        "As the table's `meta.sources` gives them:",
        "",
    ]
    for source in meta["sources"]:
        lines.append(
            f"- `{source['source']}`: {source['text']} {source['licence']}, {source['url']}"
        )
    lines += [
        "",
        "## Retrieval",
        "",
        "Fetched over HTTPS from `raw.githubusercontent.com`, which serves `.gz` as plain bytes;",
        "the files are stored exactly as served. Nothing is fetched at play time, in CI or in the",
        "browser.",
        "",
    ]
    return "\n".join(lines)


def fetch_hexes():
    HEX_RAW_DIR.mkdir(parents=True, exist_ok=True)
    fetched = {}
    for remote, local, digest in HEX_FILES:
        url = HEX_BASE_URL + remote
        data = fetch(url)
        check_hash(local, data, digest, HEX_TAG)
        fetched[local] = data
        print(f"fetched {url} ({len(data):,} bytes, sha256 ok)")
    table = check_table(
        json.loads(gzip.decompress(fetched[HEX_TABLE_FILE]).decode("utf-8")), HEX_UNIT
    )
    for local, data in fetched.items():
        (HEX_RAW_DIR / local).write_bytes(data)
    (HEX_RAW_DIR / "SOURCE.md").write_text(hex_source_md(table), encoding="utf-8")
    print(f"wrote {HEX_RAW_DIR.relative_to(ROOT)}/ and SOURCE.md")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--check", action="store_true", help="check the committed files only")
    parser.add_argument("--hexes", action="store_true",
                        help=f"the hex trial's pin ({HEX_TAG}, {HEX_UNIT}) instead of the ridings'")
    args = parser.parse_args(argv)

    try:
        if args.hexes:
            if args.check:
                table = read_hex_table()
                read_hex_layer()
                print(f"{HEX_RAW_DIR.relative_to(ROOT)}: both files match {HEX_TAG};"
                      f" {len(table['rows'])} rows")
            else:
                fetch_hexes()
            return 0
        if args.check:
            table = read_table()
            read_layer()
            print(f"{RAW_DIR.relative_to(ROOT)}: both files match {TAG}; {len(table['rows'])} rows")
            return 0

        RAW_DIR.mkdir(parents=True, exist_ok=True)
        fetched = {}
        for remote, local, digest in FILES:
            url = BASE_URL + remote
            data = fetch(url)
            check_hash(local, data, digest)
            fetched[local] = data
            print(f"fetched {url} ({len(data):,} bytes, sha256 ok)")
        table = check_table(json.loads(gzip.decompress(fetched[TABLE_FILE]).decode("utf-8")))
        for local, data in fetched.items():
            (RAW_DIR / local).write_bytes(data)
        SOURCE_MD.write_text(source_md(table), encoding="utf-8")
        print(f"wrote {RAW_DIR.relative_to(ROOT)}/ and SOURCE.md")
        return 0
    except MeridianError as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
