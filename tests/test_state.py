import csv
from pathlib import Path

SEED = Path(__file__).resolve().parent.parent / "data" / "seed"


def load(name):
    with open(SEED / name, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def test_houses_state_covers_every_house():
    houses = {h["house"] for h in load("houses.csv")}
    state = {h["house"] for h in load("houses_state.csv")}
    assert houses == state


def test_unrecovered_rows_are_blank_not_guessed():
    for h in load("houses_state.csv"):
        if h["confidence"] == "none":
            assert h["current_holder"] == "" and h["predecessor"] == "", h["house"]


def test_successions_reference_known_houses():
    houses = {h["house"] for h in load("houses.csv")}
    rows = load("successions.csv")
    assert len(rows) == 22
    for r in rows:
        assert r["house"] in houses, r["house"]


def test_climate_ledger_shape():
    rows = load("climate_ledger.csv")
    eras = {r["era_cohort"] for r in rows}
    assert eras == {"later-era", "founding-era"}
    founding = [r for r in rows if r["era_cohort"] == "founding-era"]
    assert founding[-1]["cumulative_after"] == "-1"


def test_relations_reference_known_houses():
    houses = {h["house"] for h in load("houses.csv")}
    for r in load("relations_seed.csv"):
        assert r["house_a"] in houses and r["house_b"] in houses, r
