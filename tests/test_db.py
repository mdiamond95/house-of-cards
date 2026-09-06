import csv
import importlib.util
import sqlite3
from pathlib import Path

import pytest

from hoc import db

ROOT = Path(__file__).resolve().parent.parent
SEED = ROOT / "data" / "seed"


def _load_seed_module():
    """scripts/ is not a package, so load the loader by path."""
    spec = importlib.util.spec_from_file_location("load_seed", ROOT / "scripts" / "load_seed.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def conn(tmp_path_factory):
    """Rebuild the database from the seed into a temporary path."""
    load_seed = _load_seed_module()
    db_path = tmp_path_factory.mktemp("db") / "hoc.db"
    connection = load_seed.build(db_path)
    yield connection
    connection.close()


def read_seed(name):
    with open(SEED / name, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def test_reference_tables_loaded(conn):
    assert db.one(conn, "SELECT COUNT(*) FROM ridings") == 343
    assert db.one(conn, "SELECT COUNT(*) FROM adjacency") == 894


def test_house_counts(conn):
    assert db.one(conn, "SELECT COUNT(*) FROM houses WHERE status = 'active'") == 33
    assert db.one(conn, "SELECT COUNT(*) FROM houses WHERE status = 'removed'") == 2


def test_current_holdings(conn):
    assert db.one(conn, "SELECT COUNT(*) FROM holdings WHERE released_event_id IS NULL") == 143
    duplicates = db.query(
        conn,
        "SELECT fed_id, COUNT(*) AS n FROM holdings WHERE released_event_id IS NULL"
        " GROUP BY fed_id HAVING n > 1",
    )
    assert not duplicates, [dict(r) for r in duplicates]


def test_every_active_house_has_exactly_one_current_holder(conn):
    offenders = db.query(
        conn,
        "SELECT h.house, COUNT(hd.id) AS n FROM houses h"
        " LEFT JOIN holders hd ON hd.house = h.house AND hd.is_current = 1"
        " WHERE h.status = 'active' GROUP BY h.house HAVING n <> 1",
    )
    assert not offenders, [dict(r) for r in offenders]


def test_house_colours_view_matches_seed(conn):
    expected = {r["house"]: r["primary_hex"] for r in read_seed("houses.csv") if r["status"] == "active"}
    assert len(expected) == 33
    actual = {r["house"]: r["primary_hex"] for r in db.query(conn, "SELECT house, primary_hex FROM v_house_colours")}
    for house, primary_hex in expected.items():
        assert actual[house] == primary_hex, house


def test_climate_is_per_era_cohort(conn):
    cohorts = {r["era_cohort"] for r in db.query(conn, "SELECT DISTINCT era_cohort FROM climate")}
    assert cohorts == {"later-era", "founding-era"}

    current = {r["era_cohort"]: r["cumulative_after"] for r in db.query(conn, "SELECT * FROM v_current_climate")}
    assert set(current) == cohorts
    assert current["founding-era"] == "-1"


def test_every_relation_has_an_event(conn):
    assert db.one(conn, "SELECT COUNT(*) FROM relations") > 0
    assert db.one(conn, "SELECT COUNT(*) FROM relations WHERE event_id IS NULL") == 0
    orphans = db.one(
        conn,
        "SELECT COUNT(*) FROM relations r LEFT JOIN events e ON e.id = r.event_id WHERE e.id IS NULL",
    )
    assert orphans == 0


def test_foreign_keys_are_enforced(conn):
    with pytest.raises(sqlite3.IntegrityError):
        with conn:
            conn.execute(
                "INSERT INTO holdings (house, fed_id, seat_order, hex) VALUES (?, ?, ?, ?)",
                ("Whitcombe", "99999", 99, "#000000"),
            )
