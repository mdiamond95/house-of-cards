"""Rebuild hoc.db from scratch out of data/reference + the active scenario's seed.

The database is a derived artefact: this script deletes and rebuilds it on every
run, so the audited inputs stay the CSVs. Nothing is invented here — an empty
CSV cell becomes NULL, never a placeholder.

The scenario is the one named in scenarios/current.txt (hoc/scenario.py), so
the same script builds the reconstructed legacy game or an empty autoplay one.

Usage: python scripts/load_seed.py [db_path]
"""

import csv
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from hoc import db, scenario  # noqa: E402  (after sys.path setup)
from hoc.names import name_key  # noqa: E402

REFERENCE = ROOT / "data" / "reference"

TABLES_IN_REPORT_ORDER = [
    "ridings",
    "adjacency",
    "houses",
    "holders",
    "clocks",
    "house_blocks",
    "holdings",
    "successions",
    "events",
    "event_houses",
    "relations",
    "climate",
    "turns",
    "seasons",
    "house_stats",
    "persons",
    "objectives",
    "watch",
    "threads",
    "handoff",
]


def read_csv(path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def blank_to_none(value):
    """An empty cell means 'not recorded', which is NULL — not an empty string."""
    if value is None:
        return None
    value = value.strip()
    return value or None


# Every house resumes at personal 1867 — its last recorded anchor, whether that
# was a founding grant or an accession reset. The personal years elapsed between
# that anchor and the rebuild were not recovered and are not estimated; turns
# advance clocks explicitly from here. See scenarios/legacy/RECONSTRUCTION.md, Decisions.
CLOCK_RESUME_YEAR = 1867
CLOCK_RESUME_BASIS = (
    "resumed from last recorded anchor (personal 1867 at founding or at accession reset);"
    " intervening personal years not recovered — see scenarios/legacy/RECONSTRUCTION.md"
)


def load_ridings(conn):
    rows = read_csv(REFERENCE / "ridings.csv")
    conn.executemany(
        "INSERT INTO ridings (fed_id, name_en, name_fr, province, name_key)"
        " VALUES (:fed_id, :name_en, :name_fr, :province, :name_key)",
        rows,
    )


def load_adjacency(conn):
    rows = read_csv(REFERENCE / "adjacency.csv")
    conn.executemany(
        "INSERT INTO adjacency (fed_id_a, fed_id_b, adjacency_type)"
        " VALUES (:fed_id_a, :fed_id_b, :adjacency_type)",
        rows,
    )


def load_houses(conn, seed):
    for row in read_csv(seed / "houses.csv"):
        conn.execute(
            "INSERT INTO houses (house, peerage, rank, status, primary_hex, secondary_hex, notes)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                row["house"],
                blank_to_none(row["peerage"]),
                blank_to_none(row["rank"]),
                row["status"],
                blank_to_none(row["primary_hex"]),
                blank_to_none(row["secondary_hex"]),
                blank_to_none(row["notes"]),
            ),
        )


def load_holdings(conn, seed):
    """Resolve each seed riding name to a fed_id via name_key. Hard-fail on any
    name that does not resolve — a silently dropped holding would be worse than
    a failed load."""
    fed_by_key = {
        r["name_key"]: r["fed_id"]
        for r in conn.execute("SELECT name_key, fed_id FROM ridings")
    }

    unresolved = []
    rows = read_csv(seed / "holdings.csv")
    for row in rows:
        fed_id = fed_by_key.get(name_key(row["riding"]))
        if fed_id is None:
            unresolved.append(row["riding"])
            continue
        conn.execute(
            "INSERT INTO holdings (house, fed_id, seat_order, hex) VALUES (?, ?, ?, ?)",
            (row["house"], fed_id, int(row["seat_order"]), row["hex"]),
        )

    if unresolved:
        raise SystemExit(
            f"Riding names in {seed}/holdings.csv did not resolve against "
            f"data/reference/ridings.csv: {unresolved}"
        )


def load_holders_and_clocks(conn, seed):
    for row in read_csv(seed / "houses_state.csv"):
        conn.execute(
            "INSERT INTO holders (house, name, generation, acceded, bio_age_at_accession,"
            " predecessor, heir_apparent, is_current, source, confidence, notes)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?)",
            (
                row["house"],
                blank_to_none(row["current_holder"]),
                blank_to_none(row["generation"]),
                blank_to_none(row["acceded"]),
                blank_to_none(row["bio_age_at_accession"]),
                blank_to_none(row["predecessor"]),
                blank_to_none(row["heir_apparent"]),
                blank_to_none(row["source"]),
                blank_to_none(row["confidence"]),
                blank_to_none(row["notes"]),
            ),
        )
        conn.execute(
            "INSERT INTO clocks (house, personal_year, basis) VALUES (?, ?, ?)",
            (row["house"], CLOCK_RESUME_YEAR, CLOCK_RESUME_BASIS),
        )


def load_house_blocks(conn, seed):
    """Section 5 house blocks, as far as they have been recovered."""
    for row in read_csv(seed / "house_blocks.csv"):
        conn.execute(
            "INSERT INTO house_blocks (house, field, text, source) VALUES (?, ?, ?, ?)",
            (
                row["house"],
                row["field"],
                blank_to_none(row["text"]),
                blank_to_none(row["source"]),
            ),
        )


def load_successions(conn, seed):
    for row in read_csv(seed / "successions.csv"):
        conn.execute(
            "INSERT INTO successions (seq, house, predecessor, successor, transition,"
            " personal_date, nature, batch, source) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                int(row["seq"]),
                row["house"],
                blank_to_none(row["predecessor"]),
                blank_to_none(row["successor"]),
                blank_to_none(row["transition"]),
                blank_to_none(row["personal_date"]),
                blank_to_none(row["nature"]),
                blank_to_none(row["batch"]),
                blank_to_none(row["source"]),
            ),
        )


def load_climate(conn, seed):
    for row in read_csv(seed / "climate_ledger.csv"):
        conn.execute(
            "INSERT INTO climate (era_cohort, seq, event, magnitude, tag, cumulative_after, source)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                row["era_cohort"],
                int(row["seq"]),
                row["event"],
                blank_to_none(row["magnitude"]),
                blank_to_none(row["tag"]),
                blank_to_none(row["cumulative_after"]),
                blank_to_none(row["source"]),
            ),
        )


def load_relations(conn, seed, created_at):
    """Every relation gets a synthetic 'relational' event so that relations
    always hang off an event, as the event log will expect. These events are
    marked source='reconstructed' to keep them distinguishable from events
    recovered verbatim."""
    for row in read_csv(seed / "relations_seed.csv"):
        cursor = conn.execute(
            "INSERT INTO events (kind, title, source, created_at)"
            " VALUES ('relational', ?, 'reconstructed', ?)",
            (row["event"], created_at),
        )
        event_id = cursor.lastrowid
        for house, role in ((row["house_a"], "house_a"), (row["house_b"], "house_b")):
            conn.execute(
                "INSERT INTO event_houses (event_id, house, role, personal_year)"
                " VALUES (?, ?, ?, NULL)",
                (event_id, house, role),
            )
        conn.execute(
            "INSERT INTO relations (house_a, house_b, marker, event_id, event_text, source)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (
                row["house_a"],
                row["house_b"],
                blank_to_none(row["marker"]),
                event_id,
                blank_to_none(row["event"]),
                blank_to_none(row["source"]),
            ),
        )


def build(db_path, seed=None):
    """Build the database from the given seed directory (default: the active
    scenario's). Returns the open connection."""
    seed = Path(seed) if seed is not None else scenario.seed_dir()
    db_path = Path(db_path)
    if db_path.exists():
        db_path.unlink()

    created_at = datetime.now(timezone.utc).isoformat(timespec="seconds")

    conn = db.connect(db_path)
    db.init_schema(conn)
    with conn:
        load_ridings(conn)
        load_adjacency(conn)
        load_houses(conn, seed)
        load_holdings(conn, seed)
        load_holders_and_clocks(conn, seed)
        load_house_blocks(conn, seed)
        load_successions(conn, seed)
        load_climate(conn, seed)
        load_relations(conn, seed, created_at)
    return conn


def main():
    db_path = Path(sys.argv[1]) if len(sys.argv) > 1 else db.DEFAULT_DB_PATH
    conn = build(db_path)

    print(f"built {db_path} from scenario {scenario.current_name()!r}")
    width = max(len(name) for name in TABLES_IN_REPORT_ORDER)
    for table in TABLES_IN_REPORT_ORDER:
        count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        print(f"  {table.ljust(width)}  {count}")

    for row in conn.execute("SELECT era_cohort, cumulative_after FROM v_current_climate ORDER BY era_cohort"):
        print(f"  climate [{row['era_cohort']}] currently {row['cumulative_after']}")
    conn.close()


if __name__ == "__main__":
    main()
