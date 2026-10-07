"""Rules 1.0 `round_record` (Phase V2, docs/STORY_DESIGN.md §3.6).

With the flag on, every engine event's delta carries `part` — "world", the house
whose turn it is, or "close" — and every season record carries `order`, the
playing order fixed at the start of the house turns. The story layer reads them
to tell a year as it is played: the world's turn, each house's, the close.

The flag records and decides nothing. That is the first test here: three seeds,
a whole game each, played with the flag on and off, and identical once the two
fields are taken out. The cross-check (tests/test_crosscheck.py) holds the two
engines to the fields themselves, since scripts/crosscheck.py compares every
engine event as well as every season file.
"""

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import load_seed  # noqa: E402

from hoc import rules_data, scenario, sim  # noqa: E402
from hoc.sim import canonical_json  # noqa: E402

MERIDIAN = "meridian-v1.0.3"
TURNS = 100
SEEDS = (1867, 2, 3)

_games = {}


def _game(tmp_path_factory, seed, on):
    """(season records, engine events) of a whole 1.0 game, played once."""
    key = (seed, on)
    if key not in _games:
        path = tmp_path_factory.mktemp(f"round-{seed}-{int(on)}") / "w.db"
        conn = load_seed.build(path, seed=scenario.blank_seed_dir(), reference_data=MERIDIAN)
        rules = rules_data.load_rules(version="1.0")
        rules.features["round_record"] = on
        world = sim.World(conn, rules=rules, world_seed=seed)
        with conn:
            records = [world.initialise(seed)]
            records += [world.run_season() for _ in range(TURNS - 1)]
        events = [
            (row["id"], row["kind"], row["title"], json.loads(row["mechanical_delta"]))
            for row in conn.execute(
                "SELECT id, kind, title, mechanical_delta FROM events"
                " WHERE source = 'engine' ORDER BY id"
            )
        ]
        conn.close()
        _games[key] = (json.loads(canonical_json(records)), events)
    return _games[key]


def test_the_flag_is_on_in_the_draft_only():
    assert rules_data.FEATURE_DEFAULTS["round_record"] is False
    assert rules_data.load_features("1.0")["round_record"] is True
    for old in ("0.7", "0.8", "0.9"):
        assert rules_data.load_features(old)["round_record"] is False


@pytest.mark.parametrize("seed", SEEDS)
def test_the_flag_records_and_decides_nothing(tmp_path_factory, seed):
    on_records, on_events = _game(tmp_path_factory, seed, True)
    off_records, off_events = _game(tmp_path_factory, seed, False)
    assert len(on_records) == len(off_records) == TURNS

    for on, off in zip(on_records, off_records):
        assert "order" in on and "order" not in off
        on = dict(on)
        on.pop("order")
        assert on == off, f"season {off['season']} differs beyond `order`"

    assert len(on_events) == len(off_events)
    for (on_id, on_kind, on_title, on_delta), off_event in zip(on_events, off_events):
        assert "part" in on_delta and "part" not in off_event[3]
        on_delta = dict(on_delta)
        on_delta.pop("part")
        assert (on_id, on_kind, on_title, on_delta) == off_event


def test_every_event_has_a_part_in_the_order_of_play(tmp_path_factory):
    records, events = _game(tmp_path_factory, 1867, True)
    order = {record["season"]: record["order"] for record in records}
    assert order[1] == []

    runs = {}
    for _id, _kind, _title, delta in events:
        part = delta.get("part")
        assert part is not None, f"event {_id} has no part"
        season = delta["season"]
        seq = runs.setdefault(season, [])
        if not seq or seq[-1] != part:
            seq.append(part)

    for season, seq in runs.items():
        houses = [part for part in seq if part not in ("world", "close")]
        # No house's part appears twice in a year: each house has one turn.
        assert len(houses) == len(set(houses)), f"season {season}: {seq}"
        # Every house part is a house in the order, and in the order's order.
        assert all(house in order[season] for house in houses), f"season {season}"
        positions = [order[season].index(house) for house in houses]
        assert positions == sorted(positions), f"season {season}: {seq}"
        # The world's turn comes first and the close last.
        expected = (["world"] if "world" in seq else []) + houses + (["close"] if "close" in seq else [])
        assert seq == expected, f"season {season}: {seq}"


def test_the_order_is_the_houses_active_when_the_house_turns_began(tmp_path_factory):
    records, _events = _game(tmp_path_factory, 1867, True)
    for previous, record in zip(records, records[1:]):
        order = record["order"]
        assert len(order) == len(set(order))
        # Every house in play when the house turns began has a place in the
        # order, whether or not it lived to act. Nothing in the world's turn
        # founds or removes a house, so that is every house the last season
        # left active.
        assert len(order) == previous["houses_after"], f"season {record['season']}"
