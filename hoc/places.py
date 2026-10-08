"""The reference tables the engine reads from CSV rather than from `hoc.db`.

Rules 0.7 drew a house's designation from a province-wide bank, so a Baron
seated in Halifax could be styled "of Kamloops" as readily as "of Dartmouth" —
the bank knew the province and nothing else. Rules 0.8 draws from the seat's own
ground instead, and this module is the data that makes that possible.

Two tables in every reference-data set:

* `places_by_riding.csv` — populated places, each assigned to the riding its
  point falls in, largest population first. In `ne-2026` they are Natural
  Earth's 255 Canadian places across 111 ridings, which is thin — hence the
  tiers rather than a single source. In `meridian-v1.0.3` they are the census
  subdivisions, with a `spans_ridings` column: 1 when the place's population
  exceeds its riding's, as a city filed under the riding its point fell in does
  (Halifax under Central Nova). Such a place is never a designation for that
  riding. It also has a `designation_ok` column, 1 only for a name a peerage
  could be styled after — not "Division No.  1, Subd. U" or "Yarmouth 33"
  (scripts/build_world_meridian.py, docs/DETERMINISM.md). Only a place with
  designation_ok = 1 is kept here, on load, in both engines, so it is the only
  kind either designation tier (the seat's own, or its neighbours') can offer.
  `ne-2026` has neither column and loses nothing.
* `riding_tokens.csv` — the usable words in a riding's own name, in name order.
  Every riding has at least one, which is what makes the draw always able to
  answer.

Two more in `meridian-v1.0.3` only, loaded so that both engines hold them but
read by nothing yet:

* `riding_stats.csv` — per-riding integers (population, tiers, shares per
  mille, urban class, industry, opens_year).
* `riding_jurisdictions.csv` — the jurisdiction a riding lay under, by year.

Read from the CSVs rather than from `hoc.db`, deliberately: `web/engine/` reads
the same files, so both engines see identical bytes in identical order and
the row ordering the draws depend on cannot diverge between them
(docs/DETERMINISM.md).

Which set is read is the caller's to say — a World passes the directory its
database was built from (`reference_dir_for`). The default is `ne-2026`, the set
both frozen games were played on.
"""

import csv
from pathlib import Path

__all__ = [
    "places_by_riding", "tokens_by_riding", "riding_stats", "riding_jurisdictions",
    "reference_dir_for", "DEFAULT_REFERENCE_DIR", "PLACES_PATH", "TOKENS_PATH",
    "jurisdiction_at", "jurisdiction_label", "set_info",
]

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_REFERENCE_DIR = REPO_ROOT / "data" / "reference"
REFERENCE_DIR = DEFAULT_REFERENCE_DIR
PLACES_PATH = DEFAULT_REFERENCE_DIR / "places_by_riding.csv"
TOKENS_PATH = DEFAULT_REFERENCE_DIR / "riding_tokens.csv"

STATS_FILE = "riding_stats.csv"
JURISDICTIONS_FILE = "riding_jurisdictions.csv"

# (kind, resolved directory) -> table. A reference set never changes during a
# run, and a process may read more than one set (a rebuild, then the archive).
_cache = {}


def _dir(reference_dir):
    return DEFAULT_REFERENCE_DIR if reference_dir is None else Path(reference_dir)


def _rows(path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _cached(kind, reference_dir, build):
    key = (kind, str(_dir(reference_dir).resolve()))
    if key not in _cache:
        _cache[key] = build(_dir(reference_dir))
    return _cache[key]


def _group(rows, key, value):
    """{fed_id: [value, ...]} in file order — the order the draws depend on."""
    out = {}
    for row in rows:
        out.setdefault(row[key], []).append(row[value])
    return out


def reference_dir_for(conn):
    """The reference directory a database was built from (its `reference_data`
    row, written by scripts/load_seed.py), or the default for a database that
    predates the table or never had a row."""
    try:
        row = conn.execute("SELECT path FROM reference_data").fetchone()
    except Exception:  # sqlite3.OperationalError: a database without the table
        return DEFAULT_REFERENCE_DIR
    return DEFAULT_REFERENCE_DIR if row is None else REPO_ROOT / row[0]


def set_info(reference_dir=None):
    """What a reference set says about itself in its set.json, or {} for a
    set without one (both riding sets). The hex trial's names its unit
    ("holding", `unit_word`) and says it is a hex board (`hexes`). Read by the
    exporters for display, never by an engine."""
    def build(directory):
        path = directory / "set.json"
        if not path.exists():
            return {}
        import json

        return json.loads(path.read_text(encoding="utf-8"))
    return _cached("set", reference_dir, build)


def places_by_riding(reference_dir=None):
    """fed_id -> place names, largest population first (the file's own order),
    keeping only those that may be a designation: none that spans its riding,
    and, where the set marks it, only designation_ok = 1."""
    def build(directory):
        rows = [
            row for row in _rows(directory / "places_by_riding.csv")
            if row.get("spans_ridings", "0") != "1" and row.get("designation_ok", "1") == "1"
        ]
        return _group(rows, "fed_id", "place")
    return _cached("places", reference_dir, build)


def tokens_by_riding(reference_dir=None):
    """fed_id -> the usable words of the riding's name, in name order."""
    return _cached(
        "tokens", reference_dir,
        lambda directory: _group(_rows(directory / "riding_tokens.csv"), "fed_id", "token"),
    )


def riding_stats(reference_dir=None):
    """fed_id -> {column: int}, or {} for a set without the table."""
    def build(directory):
        path = directory / STATS_FILE
        if not path.exists():
            return {}
        return {
            row["fed_id"]: {k: int(v) for k, v in row.items() if k != "fed_id"}
            for row in _rows(path)
        }
    return _cached("stats", reference_dir, build)


def riding_jurisdictions(reference_dir=None):
    """fed_id -> [{from_year, to_year, unit, name, status, sovereign}, ...] in
    year order, to_year None for the span in force today; {} for a set without
    the table."""
    def build(directory):
        path = directory / JURISDICTIONS_FILE
        if not path.exists():
            return {}
        out = {}
        for row in _rows(path):
            out.setdefault(row["fed_id"], []).append({
                "from_year": int(row["from_year"]),
                "to_year": int(row["to_year"]) if row["to_year"] else None,
                "unit": row["unit"],
                "name": row["name"],
                "status": row["status"],
                "sovereign": row["sovereign"],
            })
        return out
    return _cached("jurisdictions", reference_dir, build)


def jurisdiction_at(spans, year):
    """The name of the jurisdiction in force in `year`, from one riding's spans
    (riding_jurisdictions()), or None. hoc/sim.py's jurisdiction_name, for the
    exporters, which read a riding's jurisdiction for display and nothing else."""
    for span in spans or ():
        if span["from_year"] <= year and (span["to_year"] is None or year <= span["to_year"]):
            return span["name"]
    return None


def jurisdiction_label(spans, year):
    """jurisdiction_at, but only when it is named differently from the
    jurisdiction in force today — "Rupert's Land", not "Ontario" again."""
    then = jurisdiction_at(spans, year)
    now = spans[-1]["name"] if spans else None
    return then if then is not None and then != now else None
