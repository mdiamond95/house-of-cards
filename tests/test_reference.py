import csv
from pathlib import Path

import pytest

from hoc.names import name_key

ROOT = Path(__file__).resolve().parent.parent
REFERENCE = ROOT / "data" / "reference"
SEED = ROOT / "data" / "seed"


def load(path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def test_ridings_shape():
    rows = load(REFERENCE / "ridings.csv")
    assert len(rows) == 343
    assert len({r["fed_id"] for r in rows}) == 343
    assert len({r["name_en"] for r in rows}) == 343


def test_every_holding_riding_resolves():
    ridings = load(REFERENCE / "ridings.csv")
    keys = {r["name_key"] for r in ridings}
    holdings = load(SEED / "holdings.csv")

    unresolved = [h["riding"] for h in holdings if name_key(h["riding"]) not in keys]
    if unresolved:
        print("Unresolved holdings.csv riding names:")
        for name in unresolved:
            print(" -", name)
    assert not unresolved, f"{len(unresolved)} holdings.csv riding(s) did not resolve to a ridings.csv row: {unresolved}"


def test_adjacency_edges_reference_known_ridings():
    adjacency_path = REFERENCE / "adjacency.csv"
    if not adjacency_path.exists():
        pytest.skip("adjacency.csv not present — geometry was unavailable this session")

    fed_ids = {r["fed_id"] for r in load(REFERENCE / "ridings.csv")}
    edges = load(adjacency_path)

    seen = set()
    for e in edges:
        a, b = e["fed_id_a"], e["fed_id_b"]
        assert a in fed_ids and b in fed_ids, e
        assert a != b, e
        key = (a, b)
        assert key not in seen, f"duplicate pair {key}"
        seen.add(key)


def test_adjacency_spot_checks():
    adjacency_path = REFERENCE / "adjacency.csv"
    if not adjacency_path.exists():
        pytest.skip("adjacency.csv not present — geometry was unavailable this session")

    name_to_fed = {r["name_en"]: r["fed_id"] for r in load(REFERENCE / "ridings.csv")}
    edges = {(min(e["fed_id_a"], e["fed_id_b"]), max(e["fed_id_a"], e["fed_id_b"])) for e in load(adjacency_path)}

    pairs = [
        ("Halifax", "Halifax West"),
        ("Winnipeg Centre", "Winnipeg North"),
        ("Victoria", "Esquimalt—Saanich—Sooke"),
        ("Regina—Wascana", "Regina—Qu'Appelle"),
    ]
    failures = []
    for a_name, b_name in pairs:
        fed_a, fed_b = name_to_fed[a_name], name_to_fed[b_name]
        key = (min(fed_a, fed_b), max(fed_a, fed_b))
        if key not in edges:
            failures.append((a_name, b_name))

    if failures:
        print("Failed adjacency spot checks:")
        for a_name, b_name in failures:
            print(" -", a_name, "/", b_name)
    assert not failures, f"spot check(s) failed: {failures}"
