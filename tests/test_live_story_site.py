"""Phase D2: the live site for a game under rules 1.0's `world_calendar` on the
hex board (docs/STORY_DESIGN.md §7; docs/hex-trial/v2/README.md).

The home page is the map Replay of the live game, beside Storylines and, after
its last turn, the Reckoning; the plain map is map.html. Every page says years
rather than seasons, the set's word for a unit ("holdings"), and one climate
ledger. A riding game under a personal clock keeps the site it had.
"""

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import load_seed  # noqa: E402
from hoc import rules_data, scenario, sim  # noqa: E402
from hoc.export import site  # noqa: E402

HEX = "meridian-hex-v1.0.5"
# Header-only seed files, read before any test points the scenarios elsewhere.
SEED = {f.name: f.read_text(encoding="utf-8")
        for f in (scenario.SCENARIOS_DIR / "dominion" / "seed").iterdir()}


def _live_game(tmp_path, monkeypatch, turns):
    """A live scratch scenario on the hex board under 1.0, played `turns` years."""
    root = tmp_path / "scenarios"
    game = root / "trial"
    game.mkdir(parents=True)
    (game / "seed").mkdir()
    for name, text in SEED.items():
        (game / "seed" / name).write_text(text, encoding="utf-8")
    (game / "scenario.json").write_text(json.dumps({
        "name": "trial", "title": "A Trial Game", "status": "live", "kind": "autoplay",
        "reference_data": HEX, "rules_version": "1.0", "seed": 1905, "started_season": 1,
    }), encoding="utf-8")
    (root / "current.txt").write_text("trial\n", encoding="utf-8")
    monkeypatch.setattr(scenario, "SCENARIOS_DIR", root)
    monkeypatch.setattr(scenario, "CURRENT_FILE", root / "current.txt")
    conn = load_seed.build(tmp_path / "hoc.db", seed=scenario.blank_seed_dir(), reference_data=HEX)
    world = sim.World(conn, rules=rules_data.load_rules(version="1.0"), world_seed=1905,
                      seasons_dir=game / "seasons")
    with conn:
        world.initialise(1905)
        while world.season_no < turns:
            world.run_season()
    return conn


def _read(out, name):
    return (out / "site" / name).read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def three_years(tmp_path_factory):
    mp = pytest.MonkeyPatch()
    tmp = tmp_path_factory.mktemp("live-story")
    conn = _live_game(tmp, mp, 3)
    out = tmp / "out"
    site.write_site(conn, out_dir=out)
    yield out
    conn.close()
    mp.undo()


def test_the_home_page_is_the_map_replay_of_the_live_game(three_years):
    home = _read(three_years, "index.html")
    assert 'class="mapview"' in home and 'data-hexes="1"' in home
    assert home == _read(three_years, "replay.html")
    for name in ("storylines.html", "replay-text.html", "map.html", "data/beats/index.json"):
        assert (three_years / "site" / name).exists(), name
    assert not (three_years / "site" / "reckoning.html").exists()
    index = json.loads(_read(three_years, "data/beats/index.json"))
    assert index["calendar"]["start_year"] == 1867 and index["round"] is True
    assert index["unit_word"] == {"singular": "holding", "plural": "holdings"}
    nav = _read(three_years, "chronicle.html").split("<nav>", 1)[1].split("</nav>", 1)[0]
    assert [label for label in ("Replay", "Storylines", "Map", "Play", "Holdings", "Archive")
            if f">{label}</a>" in nav] == ["Replay", "Storylines", "Map", "Play", "Holdings", "Archive"]
    assert ">Ridings</a>" not in nav and ">Reckoning</a>" not in nav


def test_every_page_says_years_and_holdings(three_years):
    plain = _read(three_years, "map.html")
    assert "of 494 holdings held" in plain and "Houses by holdings held" in plain
    assert "season 3" not in plain and ">1869<" in plain
    chronicle = _read(three_years, "chronicle.html")
    assert "<h2>1869</h2>" in chronicle and "Every year, newest first." in chronicle
    assert "Season 1 ·" not in chronicle and "<h2>Season" not in chronicle
    assert "one climate" in _read(three_years, "climate.html")
    holdings = _read(three_years, "ridings.html")
    assert "<h1>Holdings</h1>" in holdings and "personal year" not in holdings
    about = _read(three_years, "about.html")
    assert "494 holdings of a hex board" in about and "1966" in about and "personal clock" not in about
    play = _read(three_years, "play.html")
    assert "Next year" in play and "Tap a holding" in play and 'id="play-round"' in play
    assert '"singular": "holding"' in _read(three_years, "play.js")


def test_the_reckoning_appears_after_the_last_turn(tmp_path, monkeypatch):
    conn = _live_game(tmp_path, monkeypatch, 100)
    out = tmp_path / "out"
    site.write_site(conn, out_dir=out)
    conn.close()
    assert (out / "site" / "reckoning.html").exists()
    nav = _read(out, "index.html").split('class="mv-links">', 1)[1].split("</div>", 1)[0]
    assert ">Reckoning</a>" in nav
    with pytest.raises(sim.SimError, match="no turn 101"):
        conn = load_seed.build(tmp_path / "again.db", seed=scenario.blank_seed_dir(), reference_data=HEX)
        world = sim.World(conn, rules=rules_data.load_rules(version="1.0"), world_seed=1905,
                          seasons_dir=tmp_path / "again")
        world.run_season(101)
