"""Rules-engine tests, drawn from cases actually logged in the game.

Each test gets a database rebuilt from the seed into a temporary path, so a test
that writes cannot leak into another.
"""

import importlib.util

import pytest

from hoc import rules
from hoc.rules import RuleError

ROOT = __import__("pathlib").Path(__file__).resolve().parent.parent


def _load_seed_module():
    spec = importlib.util.spec_from_file_location("load_seed", ROOT / "scripts" / "load_seed.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def conn(tmp_path):
    connection = _load_seed_module().build(tmp_path / "hoc.db")
    yield connection
    connection.close()


# ------------------------------------------------------------------ helpers --


def riding_name(conn, fed_id):
    return conn.execute("SELECT name_en FROM ridings WHERE fed_id = ?", (fed_id,)).fetchone()["name_en"]


def unclaimed_fed_ids(conn):
    return [
        row["fed_id"]
        for row in conn.execute(
            "SELECT fed_id FROM ridings WHERE fed_id NOT IN"
            " (SELECT fed_id FROM holdings WHERE released_event_id IS NULL) ORDER BY fed_id"
        )
    ]


def neighbours_of_house(conn, house):
    """Every riding sharing an adjacency edge with a current holding of `house`."""
    return {
        row["fed_id"]
        for row in conn.execute(
            "SELECT CASE WHEN a.fed_id_a = h.fed_id THEN a.fed_id_b ELSE a.fed_id_a END AS fed_id"
            " FROM adjacency a JOIN holdings h"
            "   ON h.released_event_id IS NULL AND h.house = ?"
            "  AND (a.fed_id_a = h.fed_id OR a.fed_id_b = h.fed_id)",
            (house,),
        )
    }


def current_holdings(conn, house):
    return conn.execute(
        "SELECT * FROM holdings WHERE house = ? AND released_event_id IS NULL ORDER BY seat_order",
        (house,),
    ).fetchall()


def an_event(conn, kind="other", houses=("Whitcombe",), title="test event"):
    return rules.record_event(conn, kind, title, list(houses))


# --------------------------------------------------------------- expansion --


def test_expansion_into_own_holding_is_occupied(conn):
    check = rules.validate_expansion(conn, "Macleod", "Bow River")
    assert not check.ok
    assert "occupied by Macleod" in check.reason


def test_expansion_into_a_retired_riding_name_is_unknown(conn):
    # West Nova no longer exists under the 2023 Representation Order; the
    # current riding is Acadie—Annapolis (CLAUDE.md hard rule 2).
    check = rules.validate_expansion(conn, "Lockhart", "West Nova")
    assert not check.ok
    assert check.reason == "unknown riding"
    assert check.fed_id is None


def test_land_adjacent_expansion_is_ok_and_unflagged(conn):
    unclaimed = set(unclaimed_fed_ids(conn))
    target = sorted(unclaimed & neighbours_of_house(conn, "Whitcombe"))[0]

    check = rules.validate_expansion(conn, "Whitcombe", riding_name(conn, target))
    assert check.ok
    assert check.fed_id == target
    assert check.warning is None


def test_non_adjacent_expansion_is_rejected(conn):
    unclaimed = unclaimed_fed_ids(conn)
    neighbours = neighbours_of_house(conn, "Whitcombe")
    target = next(fed_id for fed_id in unclaimed if fed_id not in neighbours)

    check = rules.validate_expansion(conn, "Whitcombe", riding_name(conn, target))
    assert not check.ok
    assert check.reason == "not adjacent"


def test_water_only_adjacency_is_allowed_but_flagged(conn):
    # Garland holds Newfoundland and Labrador; every land neighbour of a Garland
    # riding is another Garland riding, so any unclaimed riding is a clean
    # water-only case once an edge is added.
    garland_seat = current_holdings(conn, "Garland")[0]["fed_id"]
    target = next(
        fed_id for fed_id in unclaimed_fed_ids(conn)
        if fed_id not in neighbours_of_house(conn, "Garland")
    )

    a, b = sorted((garland_seat, target))
    conn.execute(
        "INSERT INTO adjacency (fed_id_a, fed_id_b, adjacency_type) VALUES (?, ?, 'water')", (a, b)
    )

    check = rules.validate_expansion(conn, "Garland", riding_name(conn, target))
    assert check.ok
    assert check.warning == "water adjacency only; land preferred"


def test_expand_appends_seat_and_takes_the_secondary_colour(conn):
    target = sorted(set(unclaimed_fed_ids(conn)) & neighbours_of_house(conn, "Whitcombe"))[0]
    name = riding_name(conn, target)

    event_id = an_event(conn, kind="expansion", title=f"Whitcombe into {name}")
    holding_id = rules.expand(conn, "Whitcombe", name, event_id)

    holding = conn.execute("SELECT * FROM holdings WHERE id = ?", (holding_id,)).fetchone()
    assert holding["seat_order"] == 11
    assert holding["hex"] == "#4A7A55"
    assert holding["acquired_event_id"] == event_id
    assert len(current_holdings(conn, "Whitcombe")) == 11

    # The riding is now occupied, so nobody else can take it.
    blocked = rules.validate_expansion(conn, "Stanton-Greville", name)
    assert not blocked.ok
    assert "occupied by Whitcombe" in blocked.reason
    with pytest.raises(RuleError):
        rules.expand(conn, "Stanton-Greville", name, event_id)


def test_transfer_moves_a_riding_and_keeps_the_released_row(conn):
    # Mirrors the historical move: Sudbury passed from Kilmartin to Whitcombe
    # when Kilmartin was retired.
    out_event = an_event(conn, kind="transfer", houses=("Whitcombe", "Kilmartin"), title="Sudbury out")
    rules.transfer_holding(conn, "Whitcombe", "Kilmartin", "Sudbury", out_event)

    assert [h["fed_id"] for h in current_holdings(conn, "Kilmartin")] == ["35103"]
    assert len(current_holdings(conn, "Whitcombe")) == 9

    back_event = an_event(conn, kind="transfer", houses=("Whitcombe", "Kilmartin"), title="Sudbury back")
    new_id = rules.transfer_holding(conn, "Kilmartin", "Whitcombe", "Sudbury", back_event)

    held_now = conn.execute(
        "SELECT * FROM holdings WHERE fed_id = '35103' AND released_event_id IS NULL"
    ).fetchall()
    assert len(held_now) == 1
    assert held_now[0]["id"] == new_id
    assert held_now[0]["house"] == "Whitcombe"
    assert held_now[0]["seat_order"] == 10  # re-acquired at the tail of the order
    assert len(current_holdings(conn, "Whitcombe")) == 10

    released = conn.execute(
        "SELECT * FROM holdings WHERE fed_id = '35103' AND released_event_id IS NOT NULL"
        " ORDER BY id"
    ).fetchall()
    assert [(r["house"], r["released_event_id"]) for r in released] == [
        ("Whitcombe", out_event),
        ("Kilmartin", back_event),
    ]


# -------------------------------------------------------------- succession --


def test_succession_advances_generation_and_resets_the_clock(conn):
    event_id = an_event(conn, kind="succession", houses=("Hall",), title="Hall succession")
    holder_id = rules.succeed(
        conn, "Hall", "Test Heir", "~41", "spring Hall personal 1920", "clean", event_id
    )

    outgoing = conn.execute(
        "SELECT * FROM holders WHERE house = 'Hall' AND name = 'Edward Jacob Hall'"
    ).fetchone()
    assert outgoing["is_current"] == 0

    incoming = conn.execute("SELECT * FROM holders WHERE id = ?", (holder_id,)).fetchone()
    assert incoming["is_current"] == 1
    assert incoming["generation"] == "G3"
    assert incoming["predecessor"] == "Edward Jacob Hall"
    assert incoming["bio_age_at_accession"] == "~41"  # recorded, never recomputed

    clock = conn.execute("SELECT * FROM clocks WHERE house = 'Hall'").fetchone()
    assert clock["personal_year"] == 1867

    assert conn.execute("SELECT COUNT(*) FROM successions").fetchone()[0] == 23
    last = conn.execute("SELECT * FROM successions ORDER BY seq DESC LIMIT 1").fetchone()
    assert last["transition"] == "Edward Jacob Hall→Test Heir"
    assert last["house"] == "Hall"


# ------------------------------------------------------------------ clocks --


def test_advance_clock_requires_a_known_year_first(conn):
    # The loader resumes every clock at personal 1867, so an unknown clock has to
    # be made explicitly unknown here. The guard still matters: a house whose
    # clock is cleared must not be advanced from an assumed start year.
    conn.execute("UPDATE clocks SET personal_year = NULL WHERE house = 'Hall'")
    with pytest.raises(RuleError):
        rules.advance_clock(conn, "Hall", 5)

    rules.set_clock(conn, "Hall", 1867, "director-supplied for test")
    assert rules.advance_clock(conn, "Hall", 5) == 1872
    assert conn.execute("SELECT personal_year FROM clocks WHERE house = 'Hall'").fetchone()[0] == 1872


def test_only_direct_shared_events_sync_clocks(conn):
    societal = rules.record_event(conn, "societal", "A global event", ["Hall", "Delany"])
    with pytest.raises(RuleError):
        rules.sync_clocks(conn, societal, 1901)

    relational = rules.record_event(conn, "relational", "A shared event", ["Hall", "Delany"])
    rules.sync_clocks(conn, relational, 1901)

    years = {
        row["house"]: row["personal_year"]
        for row in conn.execute("SELECT house, personal_year FROM clocks WHERE house IN ('Hall', 'Delany')")
    }
    assert years == {"Hall": 1901, "Delany": 1901}

    placements = {
        row["house"]: row["personal_year"]
        for row in conn.execute("SELECT house, personal_year FROM event_houses WHERE event_id = ?", (relational,))
    }
    assert placements == {"Hall": 1901, "Delany": 1901}


# ----------------------------------------------------------------- climate --


def test_climate_shift_moves_one_cohort_only(conn):
    assert rules.current_climate(conn, "founding-era") == -1
    assert rules.current_climate(conn, "later-era") == 0
    assert rules.cohort_fit(conn, "founding-era", "Conservative") == "fit"

    new_cumulative = rules.climate_shift(
        conn, "founding-era", "Test Event", "Significant", "Progressive", +1
    )

    assert new_cumulative == 0
    assert rules.current_climate(conn, "founding-era") == 0
    assert rules.current_climate(conn, "later-era") == 0  # parallel ledger, untouched
    assert rules.cohort_fit(conn, "founding-era", "Conservative") == "neutral"

    appended = conn.execute(
        "SELECT * FROM climate WHERE era_cohort = 'founding-era' ORDER BY seq DESC LIMIT 1"
    ).fetchone()
    assert appended["seq"] == 10
    assert appended["cumulative_after"] == "0"


# --------------------------------------------------------------- elevation --


def test_elevation_moves_up_the_ladder_only(conn):
    event_id = an_event(conn, kind="elevation", houses=("Wilson",), title="Wilson elevated")

    assert rules.elevate(conn, "Wilson", "Viscountess", event_id) == "Viscountess Wilson of Rockcliffe"
    wilson = conn.execute("SELECT * FROM houses WHERE house = 'Wilson'").fetchone()
    assert wilson["rank"] == "Viscountess"
    assert wilson["peerage"] == "Viscountess Wilson of Rockcliffe"

    with pytest.raises(RuleError):
        rules.elevate(conn, "Hall", "Baron", event_id)  # Earl → Baron is downward

    # Multi-step elevations are allowed, as Sinclair-McKay's Baroness → Countess was.
    assert rules.elevate(conn, "Whitcombe", "Marquis", event_id) == "Marquis Whitcombe of Muskoka"


def test_elevation_does_not_change_colours(conn):
    before = rules.house_colours(conn, "Wilson")
    rules.elevate(conn, "Wilson", "Countess", an_event(conn, kind="elevation", houses=("Wilson",)))
    assert rules.house_colours(conn, "Wilson") == before


# ----------------------------------------------------------------- colours --


def test_house_colours_come_from_the_principal_seat(conn):
    assert rules.house_colours(conn, "Wilson") == ("#7B3F7B", "#B07AB0")
    assert rules.house_colours(conn, "Whitcombe") == ("#2E5E3A", "#4A7A55")


# ------------------------------------------------------------------ events --


def test_record_event_validates_kind_and_records_roles(conn):
    with pytest.raises(RuleError):
        rules.record_event(conn, "coronation", "not a kind", ["Hall"])

    event_id = rules.record_event(
        conn,
        "challenge",
        "Dartmouth—Cole Harbour challenge",
        {"Tupper-Blair": "challenger", "Hall": "defender"},
        era_cohort="later-era",
        mechanical_delta={"outcome": "repulsed"},
    )
    roles = {
        row["house"]: row["role"]
        for row in conn.execute("SELECT house, role FROM event_houses WHERE event_id = ?", (event_id,))
    }
    assert roles == {"Tupper-Blair": "challenger", "Hall": "defender"}

    event = conn.execute("SELECT * FROM events WHERE id = ?", (event_id,)).fetchone()
    assert event["era_cohort"] == "later-era"
    assert event["mechanical_delta"] == '{"outcome": "repulsed"}'
