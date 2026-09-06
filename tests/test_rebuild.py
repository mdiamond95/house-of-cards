"""The committed hoc.db must be reproducible from the seed plus the turn files.

If this fails, either hoc.db was changed by hand or a turn file no longer
replays — both of which break the promise that the files under version control
are the record.
"""

import importlib.util
import sys
from pathlib import Path

import pytest

from hoc import db

ROOT = Path(__file__).resolve().parent.parent
COMMITTED_DB = ROOT / "hoc.db"


def _load_rebuild_module():
    """scripts/ is not a package; rebuild.py also imports load_seed by name."""
    sys.path.insert(0, str(ROOT / "scripts"))
    try:
        spec = importlib.util.spec_from_file_location("rebuild", ROOT / "scripts" / "rebuild.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.remove(str(ROOT / "scripts"))


@pytest.fixture(scope="module")
def rebuilt(tmp_path_factory):
    connection = _load_rebuild_module().rebuild(tmp_path_factory.mktemp("rebuild") / "hoc.db", export=False)
    yield connection
    connection.close()


@pytest.fixture(scope="module")
def committed():
    if not COMMITTED_DB.exists():
        pytest.skip("hoc.db is not committed in this checkout")
    connection = db.connect(COMMITTED_DB)
    yield connection
    connection.close()


def rows(conn, sql):
    return [tuple(row) for row in conn.execute(sql)]


def test_rebuild_replays_every_turn_file(rebuilt):
    turn_files = sorted((ROOT / "turns").glob("[0-9][0-9][0-9][0-9]_*.json"))
    assert turn_files, "no turn files found to replay"
    assert db.one(rebuilt, "SELECT COUNT(*) FROM turns") == len(turn_files)


def test_rebuilt_holdings_match_committed(rebuilt, committed):
    sql = (
        "SELECT house, fed_id, seat_order, hex FROM holdings"
        " WHERE released_event_id IS NULL ORDER BY house, seat_order"
    )
    assert rows(rebuilt, sql) == rows(committed, sql)


def test_rebuilt_holders_match_committed(rebuilt, committed):
    sql = (
        "SELECT house, name, generation, acceded, bio_age_at_accession, predecessor,"
        " heir_apparent, is_current, source, confidence FROM holders"
        " ORDER BY house, is_current, name"
    )
    assert rows(rebuilt, sql) == rows(committed, sql)


def test_rebuilt_clocks_match_committed(rebuilt, committed):
    sql = "SELECT house, personal_year, basis FROM clocks ORDER BY house"
    assert rows(rebuilt, sql) == rows(committed, sql)


def test_rebuilt_climate_matches_committed(rebuilt, committed):
    sql = (
        "SELECT era_cohort, seq, event, magnitude, tag, cumulative_after, source"
        " FROM climate ORDER BY era_cohort, seq"
    )
    assert rows(rebuilt, sql) == rows(committed, sql)


def test_rebuilt_turn_count_and_directives_match_committed(rebuilt, committed):
    sql = "SELECT turn_id, directive, status FROM turns ORDER BY turn_id"
    assert rows(rebuilt, sql) == rows(committed, sql)


def test_rebuilt_house_blocks_match_committed(rebuilt, committed):
    sql = "SELECT house, field, text, source FROM house_blocks ORDER BY house, field"
    assert rows(rebuilt, sql) == rows(committed, sql)
