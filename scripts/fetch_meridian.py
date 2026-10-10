#!/usr/bin/env python3
"""Download Meridian's riding table and layer at a pinned release tag.

    python scripts/fetch_meridian.py            fetch, check, write raw/ and SOURCE.md
    python scripts/fetch_meridian.py --check    check the committed files, fetch nothing
    python scripts/fetch_meridian.py --board [--check]
                                                the same for the hex board's pin (v1.0.5, five files)

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

# The hex board's pin (scripts/build_world_hexboard.py, docs/hex-trial/v2/).
# Meridian v1.0.5 answers the trial: the resolution-4 table regenerated with the
# large lakes as water, straits read as water and settlement dates
# (hexes.r4.v1.2), and the city hexes, the resolution-5 cells of the hexagons of
# 100,000 people or more (hexes.r5.v1), each with its clipped layer. All four
# hashes were given by the director when the pin was set. Same rules: a tag,
# never `main`; format, version and unit checked; any other hash refused.
BOARD_TAG = "v1.0.5"
BOARD_BASE_URL = f"https://raw.githubusercontent.com/{REPOSITORY}/{BOARD_TAG}/"
BOARD_OUT_DIR = ROOT / "data" / "reference" / "meridian" / f"hex-{BOARD_TAG}"
BOARD_RAW_DIR = BOARD_OUT_DIR / "raw"
BOARD_FILES = (
    (
        "data/build/hexes.r4.v1.2.json.gz",
        "hexes.r4.v1.2.json.gz",
        "163019e1cbf8bd97b4df568e58d006f2caf8b7503df40ce13e414ea74ee052d7",
    ),
    (
        "data/build/layers/hexes.r4.v1.2.topojson.gz",
        "hexes.r4.v1.2.topojson.gz",
        "817ccf7d03c18e6bee8cd093ce98bd2f0473b979412c9e9547ca0c114942c279",
    ),
    (
        "data/build/hexes.r5.v1.json.gz",
        "hexes.r5.v1.json.gz",
        "2b0e76bf0c8cba89df845f5d42fe7403a2001661a44230e4b9b762288cf75d1e",
    ),
    (
        "data/build/layers/hexes.r5.v1.topojson.gz",
        "hexes.r5.v1.topojson.gz",
        "95f864b1623ecbf445a22f6e54dcec4a17190982def486db34c148d43bb791e7",
    ),
    # The mesh at v1.0.5: each resolution-5 cell's census subdivision, which
    # names the city hexes. Its hash was recorded on the first fetch at this
    # tag (10 October 2026) and is pinned from then on, as the riding layer's
    # was: a released file never changes (Meridian versioning rule 7).
    (
        "data/build/mesh.v1.json.gz",
        "mesh.v1.json.gz",
        "f29ac1afe20ff33caa0cf6928f7979101617a71455210ba564a8a7bc86725677",
    ),
)
BOARD_MESH = "mesh.v1.json.gz"
MESH_FORMAT, MESH_VERSION, MESH_RESOLUTION = "meridian.mesh", "v1", 5
# The two tables, each with the unit it must declare, and their layers.
BOARD_TABLES = {"hexes.r4.v1.2.json.gz": "h3_r4", "hexes.r5.v1.json.gz": "h3_r5"}
BOARD_R4_TABLE, BOARD_R5_TABLE = "hexes.r4.v1.2.json.gz", "hexes.r5.v1.json.gz"
BOARD_R4_LAYER, BOARD_R5_LAYER = "hexes.r4.v1.2.topojson.gz", "hexes.r5.v1.topojson.gz"


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


def read_board_table(name, raw_dir=BOARD_RAW_DIR, parse_float=None):
    """One of the hex board's committed tables (v1.0.5): `BOARD_R4_TABLE`
    (`h3_r4`) or `BOARD_R5_TABLE` (`h3_r5`), hash- and format-checked."""
    data = (Path(raw_dir) / name).read_bytes()
    check_hash(name, data, dict((f[1], f[2]) for f in BOARD_FILES)[name], BOARD_TAG)
    kwargs = {} if parse_float is None else {"parse_float": parse_float}
    return check_table(json.loads(gzip.decompress(data).decode("utf-8"), **kwargs), BOARD_TABLES[name])


def read_board_mesh(raw_dir=BOARD_RAW_DIR):
    """The hex board's committed mesh (v1.0.5), hash-checked, and refused unless
    its format, version and resolution are `meridian.mesh`, `v1` and 5."""
    data = (Path(raw_dir) / BOARD_MESH).read_bytes()
    check_hash(BOARD_MESH, data, dict((f[1], f[2]) for f in BOARD_FILES)[BOARD_MESH], BOARD_TAG)
    mesh = json.loads(gzip.decompress(data).decode("utf-8"))
    got = (mesh.get("format"), mesh.get("version"), mesh.get("h3Resolution"))
    if got != (MESH_FORMAT, MESH_VERSION, MESH_RESOLUTION):
        raise MeridianError(f"mesh is {got}, expected {(MESH_FORMAT, MESH_VERSION, MESH_RESOLUTION)}")
    return mesh


def read_board_layer(name, raw_dir=BOARD_RAW_DIR, parse_float=None):
    """One of the hex board's committed clipped layers (v1.0.5), hash-checked."""
    data = (Path(raw_dir) / name).read_bytes()
    check_hash(name, data, dict((f[1], f[2]) for f in BOARD_FILES)[name], BOARD_TAG)
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


def board_source_md(tables):
    """SOURCE.md for the hex board's pin: the same record as the others'."""
    r4, r5 = tables[BOARD_R4_TABLE], tables[BOARD_R5_TABLE]
    meta = r4["meta"]
    lines = [
        f"# Source: Meridian {BOARD_TAG}, the hex board",
        "",
        "## What this is",
        "",
        "The five files below, downloaded unmodified by `scripts/fetch_meridian.py --board` from",
        f"the Meridian repository (`{REPOSITORY}`) at release tag `{BOARD_TAG}`, and the input to",
        "`scripts/build_world_hexboard.py`, which builds the `meridian-hex-v1.0.5` reference-data",
        "version (the hex board) in the directory above this one.",
        "",
        "| File | URL | SHA-256 |",
        "|---|---|---|",
    ]
    for remote, local, digest in BOARD_FILES:
        lines.append(f"| `{local}` | {BOARD_BASE_URL}{remote} | `{digest}` |")
    lines += [
        "",
        f"Tag: `{BOARD_TAG}`. Every hash is checked on every read and a file is refused on any",
        "other; Meridian's versioning rule 7 makes a released file immutable.",
        "",
        "## What the tables declare",
        "",
    ]
    for table in (r4, r5):
        m = table["meta"]
        lines += [
            f"- format `{table['format']}`, version `{table['version']}`, unit `{table['unit']}`"
            f" (checked; anything else is refused): {len(table['rows'])} rows, {m['unitName']};"
            f" H3 resolution {m['h3Resolution']}, mesh `{m['meshVersion']}`, layer `{m['layer']}`,"
            f" neighbour rule `{m['neighbourRule']}`",
        ]
    mesh = tables.get(BOARD_MESH)
    if mesh is not None:
        lines.append(
            f"- `{BOARD_MESH}`: format `{mesh['format']}`, version `{mesh['version']}`, H3 resolution"
            f" {mesh['h3Resolution']} (checked; anything else is refused), {len(mesh['cells'])} cells,"
            f" census subdivisions from `{mesh['meta'].get('csd_source')}`. Its hash was recorded on the"
            " first fetch at this tag; the other four were given by the director."
        )
    lines += [
        f"- `{BOARD_R5_TABLE}`'s parent table: `{r5['meta']['parentTable']}`",
        f"- census year {meta['censusYear']}; GDP method `{meta['gdpMethod']}`, reference year"
        f" {meta['gdpReferenceYear']}, `{meta['gdpPrices']}`",
        f"- jurisdictions from the atlas `{meta['atlasVersion']}`, from {meta['jurisdictionsFrom']}",
        f"- settlement dates withheld from {meta['datesWithheldFrom']}; city years on rows of"
        f" {meta['cityPopulation']:,} people or more",
        "",
        "**GDP is an allocation, not a measurement.** The table's own caveat, verbatim:",
        "",
        f"> {r4['gdpCaveat']}",
        "",
        "## Attribution and licences",
        "",
        "As the resolution-4 table's `meta.sources` gives them:",
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


def fetch_board():
    BOARD_RAW_DIR.mkdir(parents=True, exist_ok=True)
    fetched = {}
    for remote, local, digest in BOARD_FILES:
        url = BOARD_BASE_URL + remote
        data = fetch(url)
        check_hash(local, data, digest, BOARD_TAG)
        fetched[local] = data
        print(f"fetched {url} ({len(data):,} bytes, sha256 ok)")
    tables = {
        name: check_table(json.loads(gzip.decompress(fetched[name]).decode("utf-8")), unit)
        for name, unit in BOARD_TABLES.items()
    }
    mesh = json.loads(gzip.decompress(fetched[BOARD_MESH]).decode("utf-8"))
    if (mesh.get("format"), mesh.get("version"), mesh.get("h3Resolution")) != (
            MESH_FORMAT, MESH_VERSION, MESH_RESOLUTION):
        raise MeridianError("the mesh is not meridian.mesh v1 at resolution 5")
    tables[BOARD_MESH] = mesh
    for local, data in fetched.items():
        (BOARD_RAW_DIR / local).write_bytes(data)
    (BOARD_RAW_DIR / "SOURCE.md").write_text(board_source_md(tables), encoding="utf-8")
    print(f"wrote {BOARD_RAW_DIR.relative_to(ROOT)}/ and SOURCE.md")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--check", action="store_true", help="check the committed files only")
    parser.add_argument("--board", action="store_true",
                        help=f"the hex board's pin ({BOARD_TAG}: h3_r4 and h3_r5)")
    args = parser.parse_args(argv)

    try:
        if args.board:
            if args.check:
                counts = []
                for name in BOARD_TABLES:
                    counts.append(f"{name} {len(read_board_table(name)['rows'])} rows")
                for name in (BOARD_R4_LAYER, BOARD_R5_LAYER):
                    read_board_layer(name)
                read_board_mesh()
                print(f"{BOARD_RAW_DIR.relative_to(ROOT)}: all five files match {BOARD_TAG};"
                      f" {', '.join(counts)}")
            else:
                fetch_board()
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
