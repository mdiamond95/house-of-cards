"""The browser must pick the committed game up exactly where Python put it down.

Phase 10-2. `outputs/site/play.html` resumes the live world from
`outputs/site/data/world.json`, so two things have to be true and neither is
obvious:

* **The snapshot is complete.** It deliberately drops released holdings, dead
  people and per-season history, because the engine never reads them
  (`hoc/export/world.py` says so). If that judgement is wrong anywhere, a world
  resumed from the snapshot diverges from one that never stopped — usually
  within a few seasons, and always in a way this test catches.
* **Interventions land identically.** A director's operation applied in the
  browser has to leave the same mark as the same operation applied through
  `hoc/turn.py`, or a game played in the page could not be replayed in Python.

Both are checked the only way worth checking them: play both engines and
compare the season files byte for byte.

node is required. These do not skip when node is present.
"""

import json
import shutil
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import crosscheck  # noqa: E402
import load_seed  # noqa: E402

from hoc import scenario, sim  # noqa: E402
from hoc.export import world as world_export  # noqa: E402

pytestmark = pytest.mark.skipif(
    shutil.which("node") is None,
    reason="node is not on PATH, so the JavaScript engine cannot run",
)

SNAPSHOT_AT = 60
RESUME_SEASONS = 30


def _world(tmp_path, seed, seasons):
    """A Python world played `seasons` seasons, writing no season files."""
    conn = load_seed.build(tmp_path / f"w{seed}.db", seed=scenario.seed_dir("new"))
    world = sim.World(conn, world_seed=seed, seasons_dir=None)
    world.initialise(seed)
    if seasons > 1:
        world.run(seasons - 1)
    return conn, world


# ------------------------------------------------------- the snapshot itself --


def test_the_snapshot_carries_every_table_the_engine_reads(tmp_path):
    conn, _ = _world(tmp_path, 1867, 20)
    snapshot = world_export.world_snapshot(conn)
    conn.close()

    for key in (
        "houses", "houseStats", "holdings", "persons", "clocks", "objectives",
        "relations", "events", "climate", "friction", "seasons", "nextId",
    ):
        assert key in snapshot, key
    assert snapshot["snapshot_version"] == world_export.SNAPSHOT_VERSION
    assert snapshot["rules_version"] == sim.RULES_VERSION
    assert snapshot["world_seed"] == 1867
    assert snapshot["season"] == 20
    assert snapshot["houses"], "a 20-season world has houses"


def test_the_snapshot_drops_only_what_the_engine_never_reads(tmp_path):
    """Released holdings and dead people are history, and the site's timeline
    already carries history. If either ever became load-bearing, the resume
    cross-check below would fail — this test just pins the intent."""
    # Season 100, not 60: seed 1867 has released no holding by season 60, so a
    # snapshot there would prove nothing about dropping them.
    conn, _ = _world(tmp_path, 1867, 100)
    snapshot = world_export.world_snapshot(conn)

    released = conn.execute(
        "SELECT COUNT(*) AS n FROM holdings WHERE released_event_id IS NOT NULL"
    ).fetchone()["n"]
    dead = conn.execute("SELECT COUNT(*) AS n FROM persons WHERE alive = 0").fetchone()["n"]
    live_holdings = conn.execute(
        "SELECT COUNT(*) AS n FROM holdings WHERE released_event_id IS NULL"
    ).fetchone()["n"]
    conn.close()

    assert released > 0 and dead > 0, "100 seasons should have produced both"
    assert len(snapshot["holdings"]) == live_holdings
    assert all(person["id"] for person in snapshot["persons"])
    # The counters still point past the rows that were dropped.
    assert snapshot["nextId"]["holdings"] > live_holdings
    assert snapshot["nextId"]["persons"] > len(snapshot["persons"])


def test_the_snapshot_round_trips_through_python(tmp_path):
    """Python → snapshot → Python must be the same world. This is the cheapest
    proof that nothing load-bearing was dropped, and it fails loudly and early
    if it was."""
    conn, world = _world(tmp_path, 1867, 40)
    snapshot = json.loads(json.dumps(world_export.world_snapshot(conn)))
    before = world.counts()
    conn.close()

    restored = load_seed.build(tmp_path / "restored.db", seed=scenario.seed_dir("new"))
    with restored:
        world_export.load_snapshot(restored, snapshot)
    rebuilt = sim.World(restored, world_seed=snapshot["world_seed"], seasons_dir=None)

    assert rebuilt.counts() == before
    assert rebuilt.season_no == 40
    assert [row["house"] for row in rebuilt.active_houses()] == snapshot_house_order(snapshot)
    restored.close()


def snapshot_house_order(snapshot):
    """The §6 acting order, computed from the snapshot alone."""
    seats = {}
    for holding in snapshot["holdings"]:
        if holding["seatOrder"] == 1:
            seats[holding["house"]] = holding["fedId"]
    active = [h["house"] for h in snapshot["houses"] if h["status"] == "active"]
    stats = {s["house"]: s for s in snapshot["houseStats"]}
    return sorted(
        active,
        key=lambda house: (stats[house]["foundedSeason"], seats.get(house, ""), house),
    )


def test_a_world_resumed_in_python_plays_on_identically(tmp_path):
    """The Python half of the resume claim: the same seasons, from the database
    and from the snapshot, are the same seasons."""
    straight_dir = tmp_path / "straight"
    resumed_dir = tmp_path / "resumed"
    straight_dir.mkdir()
    resumed_dir.mkdir()

    conn, world = _world(tmp_path, 1867, SNAPSHOT_AT)
    snapshot = json.loads(json.dumps(world_export.world_snapshot(conn)))
    world.seasons_dir = straight_dir
    with conn:
        world.run(RESUME_SEASONS)
    conn.close()

    restored = load_seed.build(tmp_path / "resume.db", seed=scenario.seed_dir("new"))
    with restored:
        world_export.load_snapshot(restored, snapshot)
    resumed = sim.World(restored, world_seed=snapshot["world_seed"], seasons_dir=resumed_dir)
    with restored:
        resumed.run(RESUME_SEASONS)
    restored.close()

    for season in range(SNAPSHOT_AT + 1, SNAPSHOT_AT + RESUME_SEASONS + 1):
        name = f"{season:04d}.json"
        assert (straight_dir / name).read_text(encoding="utf-8") == (
            resumed_dir / name
        ).read_text(encoding="utf-8"), f"season {season} differs after a Python resume"


# ------------------------------------------------------- the resume in JS ----


@pytest.mark.parametrize("seed", [1867, 2])
def test_the_javascript_engine_resumes_the_committed_world(seed):
    """Phase 10-2's central claim: snapshot a Python world at season 60, resume
    it in the browser's engine, and the next thirty seasons are identical."""
    differences = crosscheck.crosscheck_resume(seed, SNAPSHOT_AT, RESUME_SEASONS)
    if differences:
        season, diff = differences[0]
        pytest.fail(
            f"seed {seed}: a world resumed from world.json diverges at season {season}"
            f" ({len(differences)} of {RESUME_SEASONS} differ).\n\n{diff}"
        )


def test_a_late_world_resumes_too():
    """The snapshot at season 60 carries no released holdings and few dead
    people, so it never tests the decision to drop them. This one does: by
    season 120 seed 1867 has released dozens of holdings and buried a hundred
    people, and none of it is in the file the browser loads."""
    differences = crosscheck.crosscheck_resume(1867, 120, RESUME_SEASONS)
    if differences:
        season, diff = differences[0]
        pytest.fail(
            f"a world resumed at season 120 diverges at season {season}"
            f" ({len(differences)} of {RESUME_SEASONS} differ).\n\n{diff}"
        )


# ------------------------------------------------------- the interventions ---


def _scripted_interventions(seed=1867, at=29):
    """A script touching every §12 operation, aimed at real houses.

    Built by peeking at a short run so the house names and the granted riding
    exist: an intervention naming a house that was never founded proves nothing.
    """
    workspace = Path(tempfile.mkdtemp(prefix="hoc-script-"))
    try:
        conn = load_seed.build(workspace / "peek.db", seed=scenario.seed_dir("new"))
        world = sim.World(conn, world_seed=seed, seasons_dir=None)
        world.initialise(seed)
        world.run(at)
        houses = [row["house"] for row in world.active_houses()]
        free = conn.execute(
            "SELECT r.name_en FROM ridings r WHERE r.province = 'ON' AND NOT EXISTS"
            " (SELECT 1 FROM holdings h WHERE h.fed_id = r.fed_id"
            "  AND h.released_event_id IS NULL) ORDER BY r.name_en LIMIT 1"
        ).fetchone()["name_en"]
        conn.close()
    finally:
        shutil.rmtree(workspace, ignore_errors=True)

    first, second = houses[0], houses[1]
    return [
        {"after_season": 10, "title": "Objective set", "operations": [
            {"op": "set_objective", "house": first, "objective": "Seek elevation",
             "reason": "cross-check"}]},
        {"after_season": 15, "title": "Objective vetoed", "operations": [
            {"op": "veto_objective", "house": first, "objective": "Seek elevation",
             "reason": "cross-check"}]},
        {"after_season": 20, "title": "Action forced", "operations": [
            {"op": "force_action", "house": first, "action": "Invest",
             "reason": "cross-check"}]},
        {"after_season": 25, "title": "Stat adjusted", "operations": [
            {"op": "adjust_stat", "house": first, "stat": "capital", "delta": 30,
             "reason": "cross-check"}]},
        {"after_season": 30, "title": "Clock set and a relation recorded", "operations": [
            {"op": "set_clock", "house": first, "personal_year": 1880, "basis": "cross-check"},
            {"op": "relation", "house_a": first, "house_b": second, "marker": "+",
             "text": "cross-check"}]},
        {"after_season": 40, "title": "A house granted", "operations": [
            {"op": "grant_house", "riding": free, "community": "Irish Catholic",
             "rank": "Baron", "tag": "Mixed", "surname": "Crosscheck",
             "reason": "cross-check"}]},
        {"after_season": 70, "title": "Another stat adjusted", "operations": [
            {"op": "adjust_stat", "house": second, "stat": "cohesion", "delta": -15,
             "reason": "cross-check"}]},
    ]


def test_every_intervention_operation_lands_the_same_in_both_engines():
    """All seven §12 operations, applied at fixed seasons on both sides — through
    hoc/turn.py in Python and World.intervene in JavaScript — and agreement held
    through season 120. The operations are only half of it: each also has to show
    up in the *next* season's `interventions` field identically, which is what
    makes a browser-played game replayable."""
    script = _scripted_interventions()
    differences = crosscheck.crosscheck(1867, 120, script=script)
    if differences:
        season, diff = differences[0]
        pytest.fail(
            f"a scripted intervention diverges at season {season}"
            f" ({len(differences)} of 120 differ).\n\n{diff}"
        )


def test_the_interventions_actually_reach_the_season_record():
    """A cross-check that compared two empty lists would pass and mean nothing."""
    script = _scripted_interventions()
    workspace = Path(tempfile.mkdtemp(prefix="hoc-interv-"))
    try:
        out = workspace / "seasons"
        crosscheck.run_python(1867, 45, out, script=script)
        seen = []
        for season in range(2, 46):
            record = json.loads((out / f"{season:04d}.json").read_text(encoding="utf-8"))
            for entry in record["interventions"]:
                seen.append((season, entry["operation"]))
    finally:
        shutil.rmtree(workspace, ignore_errors=True)

    operations = {operation for _, operation in seen}
    assert operations == {
        "set_objective", "veto_objective", "force_action", "adjust_stat", "grant_house",
    }, seen
    # Each lands in the season after the one it was applied to.
    assert (11, "set_objective") in seen
    assert (41, "grant_house") in seen
