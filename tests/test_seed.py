import csv
import re
from pathlib import Path

SEED = Path(__file__).resolve().parent.parent / "data" / "seed"
HEX = re.compile(r"^#[0-9A-F]{6}$")


def load(name):
    with open(SEED / name, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def test_holdings_shape():
    rows = load("holdings.csv")
    assert len(rows) == 143
    ridings = [r["riding"] for r in rows]
    assert len(set(ridings)) == 143, "duplicate riding"
    assert len({r["peerage"] for r in rows}) == 33
    for r in rows:
        assert HEX.match(r["hex"]), r
        assert r["peerage"].startswith(r["rank"] + " "), r


def test_seat_order_is_contiguous():
    by_house = {}
    for r in load("holdings.csv"):
        by_house.setdefault(r["house"], []).append(int(r["seat_order"]))
    for house, orders in by_house.items():
        assert orders == list(range(1, len(orders) + 1)), house


def test_houses_match_holdings():
    holdings = load("holdings.csv")
    houses = load("houses.csv")
    active = [h for h in houses if h["status"] == "active"]
    removed = [h for h in houses if h["status"] == "removed"]
    assert len(active) == 33 and len(removed) == 2
    counts = {}
    firsts = {}
    for r in holdings:
        counts[r["house"]] = counts.get(r["house"], 0) + 1
        if r["seat_order"] == "1":
            firsts[r["house"]] = (r["riding"], r["hex"])
    for h in active:
        assert int(h["riding_count"]) == counts[h["house"]], h["house"]
        assert (h["principal_seat"], h["primary_hex"]) == firsts[h["house"]], h["house"]
        if h["secondary_hex"]:
            assert HEX.match(h["secondary_hex"]), h["house"]


def test_no_plain_hyphen_where_em_dash_expected():
    bad = {"Toronto-Danforth", "Columbia-Kootenay-Southern Rockies", "Similkameen-South Okanagan-West Kootenay"}
    assert not bad & {r["riding"] for r in load("holdings.csv")}
