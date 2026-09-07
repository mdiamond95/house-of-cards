"""The JavaScript engine's foundations must agree with Python's, value for value.

`web/engine/selftest.js` prints a deterministic dump of every portable
primitive — the generator, the palette, the CSV reader, the rules typing and
the name banks. This computes the same values in Python and compares them.

This is deliberately finer-grained than `tests/test_crosscheck.py`. The
cross-check tells you *that* two engines diverged at season 87; this tells you
*which primitive* did, which is the difference between an afternoon of
bisecting season files and a named assertion. When both are failing, fix this
one first.

Skips cleanly when node is absent, saying so.
"""

import csv
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from hoc import names as pynames, palette as pypalette, prng as pyprng  # noqa: E402
from hoc.rules_data import load_rules, probability_for_age  # noqa: E402

SELFTEST = ROOT / "web" / "engine" / "selftest.js"

pytestmark = pytest.mark.skipif(
    shutil.which("node") is None, reason="node is not on PATH, so the JavaScript engine cannot run"
)


@pytest.fixture(scope="module")
def js():
    """The JavaScript engine's dump, parsed."""
    if not SELFTEST.exists():
        pytest.skip(f"{SELFTEST.relative_to(ROOT)} does not exist")
    result = subprocess.run(
        ["node", str(SELFTEST), str(ROOT)], cwd=ROOT, capture_output=True, text=True
    )
    if result.returncode != 0:
        pytest.fail(
            f"web/engine/selftest.js exited {result.returncode}:\n{result.stderr[-4000:]}"
        )
    return json.loads(result.stdout)


@pytest.fixture(scope="module")
def rules():
    return load_rules()


class _Draws:
    """The RNG surface the banks and the palette need, on the portable generator."""

    def __init__(self, seed):
        self.p = pyprng.Prng(seed)

    def choice(self, seq):
        return self.p.choice(list(seq))

    def randint(self, lo, hi):
        return self.p.rand_int(lo, hi)


# ----------------------------------------------------------------- the prng --


def test_the_season_seed_and_hash_agree(js):
    section = js["prng"]
    assert section["season_seed"] == pyprng.season_seed(1867, 1)
    assert section["state"] == pyprng.Prng(section["season_seed"]).s
    assert section["fnv"] == [
        pyprng.fnv1a32(text) for text in ("1867:1", "1867:2", "2:1", "0:0", "999999:300")
    ]
    assert section["season_seeds"] == [
        pyprng.season_seed(1867, 1),
        pyprng.season_seed(1867, 2),
        pyprng.season_seed(1, 1),
        pyprng.season_seed(2, 300),
    ]


def test_the_generator_produces_the_same_words(js):
    section = js["prng"]
    generator = pyprng.Prng(section["season_seed"])
    assert section["first_ten"] == [generator.next_u32() for _ in range(10)]


def test_the_derived_draws_agree(js):
    section = js["prng"]
    seed = section["season_seed"]

    floats = pyprng.Prng(seed)
    assert section["floats"] == [floats.rand_float() for _ in range(20)]

    dice = pyprng.Prng(seed)
    assert section["dice"] == [dice.rand_int(1, 6) for _ in range(40)]

    weighted = pyprng.Prng(seed)
    assert section["weighted"] == [
        weighted.weighted_choice(["a", "b", "c", "d"], [300, 0, 250, 75]) for _ in range(40)
    ]

    pair = pyprng.Prng(77)
    assert [tuple(d) for d in section["two_d6"]] == [pair.rand_2d6() for _ in range(10)]


def test_every_range_agrees_including_the_ones_that_reject(js):
    """A range that does not divide 2^32 is where rejection sampling shows, and
    a single-valued range must consume no word at all — get either wrong and the
    two engines' streams desynchronise a few hundred draws later."""
    ranges = pyprng.Prng(4242)
    for entry in js["prng"]["ranges"]:
        drawn = [ranges.rand_int(entry["lo"], entry["hi"]) for _ in range(12)]
        assert entry["drawn"] == drawn, f"range {entry['lo']}..{entry['hi']}"


def test_p_found_agrees_bit_for_bit(js):
    assert js["prng"]["p_found"] == [
        pyprng.p_found(room, 343, 0.5) for room in (343, 300, 1, 0)
    ]


# --------------------------------------------------------------- the palette --


def test_every_hsl_to_hex_conversion_agrees(js):
    expected = [
        pypalette.hsl_to_hex(h, s, l)
        for h in range(0, 360, 7)
        for s in range(0, 101, 5)
        for l in range(0, 101, 5)
    ]
    assert js["palette"]["to_hex"] == expected


def test_hex_to_hsl_and_the_distance_metric_agree(js):
    values = ["#4a6f8a", "#8a4a6f", "#6f8a4a", "#2b2b2b", "#ffffff", "#000000",
              "#123456", "#fedcba", "#010203"]
    assert js["palette"]["to_hsl"] == [list(pypalette.hex_to_hsl(v)) for v in values]
    pairs = [
        ((0, 40, 30), (180, 40, 30)),
        ((10, 35, 25), (350, 55, 40)),
        ((0, 0, 0), (0, 0, 0)),
        ((359, 55, 40), (1, 35, 25)),
    ]
    assert js["palette"]["distance"] == [pypalette.hsl_distance_sq(a, b) for a, b in pairs]
    assert js["palette"]["farthest"] == [
        pypalette.farthest_hue(hues)
        for hues in ([], [0, 180], [90, 270], [10, 20, 30, 200], [0], [359])
    ]


def test_a_long_run_of_colour_assignments_agrees(js):
    """The interesting case is a crowded circle: 120 houses is past the point
    where the search stops finding room and starts keeping its best candidate."""
    rng = _Draws(4)
    primaries = []
    expected = []
    for _ in range(120):
        primary, secondary = pypalette.assign_colours(primaries, rng)
        primaries.append(primary)
        expected.append([primary, secondary])
    assert js["palette"]["assigned"] == expected


# ----------------------------------------------------------------- the rules --


def test_the_csv_reader_finds_the_same_rows(js):
    for name, count in js["rules"]["csv_row_counts"].items():
        with open(ROOT / name, newline="", encoding="utf-8") as f:
            assert len(list(csv.reader(f))) == count, name


def test_the_mortality_table_is_typed_the_same(js, rules):
    assert js["rules"]["mortality"] == [
        {
            "ageMin": band.age_min,
            "ageMax": band.age_max,
            "annualProbabilityPct": band.annual_probability_pct,
            "note": band.note,
        }
        for band in rules.mortality
    ]
    ages = [0, 30, 59, 60, 69, 70, 85, 95, 150]
    assert js["rules"]["mortality_at"] == [probability_for_age(rules.mortality, a) for a in ages]


def test_the_action_and_objective_tables_are_typed_the_same(js, rules):
    assert js["rules"]["actions"] == [
        {
            "action": a.action,
            "preconditions": a.preconditions,
            "baseWeight": a.base_weight,
            "modifiers": a.modifiers,
            "target": a.target,
            "success": a.success,
            "failure": a.failure,
            "enclosureBonus": a.enclosure_bonus,
        }
        for a in rules.actions
    ]
    assert js["rules"]["objectives"] == [
        {
            "objective": o.objective,
            "favouredBy": o.favoured_by,
            "satisfiedWhen": o.satisfied_when,
            "actionWeightBonus": o.action_weight_bonus,
        }
        for o in rules.objectives
    ]


def test_every_weight_is_an_integer_in_both_engines(js, rules):
    assert js["rules"]["community_weights"] == [
        [c.community, c.weight, c.region, c.naming_tradition] for c in rules.communities
    ]
    assert js["rules"]["region_weights"] == rules.founding["region_weights"]["initial"]
    assert js["rules"]["rank_weights"] == rules.founding["rank_probabilities"]
    assert js["rules"]["hardens_pct"] == rules.friction["dispute_outcome"]["hardens_probability_pct"]
    assert js["rules"]["sig_minus_pct"] == (
        rules.succession["disorderly_succession"]["sig_minus_probability_pct"]
    )
    assert js["rules"]["riding_loss_pct"] == (
        rules.succession["losing_ridings"]["disorderly_succession"]["probability_pct"]
    )
    for value in list(js["rules"]["region_weights"].values()) + list(js["rules"]["rank_weights"].values()):
        assert isinstance(value, int), value


# ----------------------------------------------------------------- the names --


def _bank_strings(rules):
    strings = [r.surname for r in rules.surnames]
    strings += [r.name for r in rules.given_names]
    strings += [r.place for r in rules.places]
    strings += [c.community for c in rules.communities]
    with open(ROOT / "data" / "reference" / "ridings.csv", newline="", encoding="utf-8") as f:
        strings += [row["name_en"] for row in csv.DictReader(f)]
    return strings


def test_casefolding_agrees_on_every_string_in_every_bank(js, rules):
    """The hazard this exists for: Python's str.casefold() is not JavaScript's
    toLowerCase(). A bank entry carrying ß or a ligature would fold differently
    and the denylist would quietly stop matching it."""
    strings = _bank_strings(rules)
    assert js["names"]["casefold"] == [s.casefold() for s in strings]
    assert js["names"]["name_key"] == [pynames.name_key(s) for s in strings]
    assert js["names"]["fold"] == [pynames._fold(s) for s in strings]


def test_the_french_particle_and_peerage_titles_agree(js):
    places = ["Le Rocher", "La Prairie", "Les Îles", "L'Assomption", "the Red River",
              "Alberni", "Îles-de-la-Madeleine", "Ottawa", "the Le Mans"]
    assert js["names"]["particle"] == [list(pynames.french_particle(p)) for p in places]
    expected = [
        pynames.peerage_title("Baron", "Tremblay", place, tradition)
        for tradition in ("french", "scots", "english", "anishinaabe")
        for place in ("Le Rocher", "Alberni", "L'Assomption", "Les Îles")
    ]
    assert js["names"]["peerage"] == expected


def test_drawing_people_places_and_houses_agrees(js, rules):
    generator = pynames.NameGenerator(rules, _Draws(1867))
    people = [
        list(generator.draw_person(community))
        for community in ("Irish Protestant (Orange)", "Canadien Catholic",
                          "Scottish Highland Catholic", "Cree and Saulteaux")
        for _ in range(30)
    ]
    assert js["names"]["persons"] == people

    place_gen = pynames.NameGenerator(rules, _Draws(99))
    places = [
        place_gen.draw_place(province, ["Glengarry", "Alberni"])
        for province in ("ON", "QC", "NS", "BC", "MB")
        for _ in range(12)
    ]
    assert js["names"]["places"] == places

    house_gen = pynames.NameGenerator(rules, _Draws(5))
    houses = [
        house_gen.draw_house(community, province, rank, [])
        for community, province, rank in (
            ("Canadien Catholic", "QC", "Baron"),
            ("Irish Catholic", "ON", "Viscount"),
            ("Scottish Presbyterian", "NS", "Earl"),
        )
        for _ in range(10)
    ]
    assert js["names"]["houses"] == houses
