"""The portable generator, pinned to literals.

These are the values docs/DETERMINISM.md publishes as worked examples, and the
values web/engine/prng.js must reproduce. They are written out here rather than
computed, because a test that recomputes what it is checking cannot notice the
algorithm changing underneath it: if someone edits hoc/prng.py, these fail
immediately and by name, before the cross-check has to run three hundred
seasons to discover the same thing.
"""

import pytest

from hoc import palette, prng

SEED_1867_SEASON_1 = 4018125158

FIRST_TEN_U32 = [
    2766650784,
    178856183,
    3621254264,
    850972858,
    1308284850,
    1544645602,
    3752021905,
    3387998208,
    2676143205,
    2797899509,
]


def test_the_season_seed_is_fnv1a_over_the_pair():
    assert prng.fnv1a32("1867:1") == SEED_1867_SEASON_1
    assert prng.season_seed(1867, 1) == SEED_1867_SEASON_1
    # Distinct seasons and distinct worlds land far apart.
    assert prng.fnv1a32("1867:2") == 4001347539
    assert prng.fnv1a32("2:1") == 1056972260


def test_splitmix32_fills_the_state():
    assert prng.Prng(SEED_1867_SEASON_1).s == [0x2624FCC3, 0xD9C30FFD, 0x00206683, 0xDD1D0F5A]


def test_the_first_ten_words_for_seed_1867_season_1():
    generator = prng.Prng(SEED_1867_SEASON_1)
    assert [generator.next_u32() for _ in range(10)] == FIRST_TEN_U32


def test_every_word_stays_inside_32_bits():
    """The masking is the whole contract with JavaScript: a value that escaped
    32 bits here would be silently truncated there."""
    generator = prng.Prng(1)
    for _ in range(5000):
        value = generator.next_u32()
        assert 0 <= value <= prng.MASK32
        assert all(0 <= word <= prng.MASK32 for word in generator.s)


def test_rand_float_is_the_word_over_two_to_the_32():
    generator = prng.Prng(SEED_1867_SEASON_1)
    assert generator.rand_float() == FIRST_TEN_U32[0] / 2 ** 32
    assert generator.rand_float() == FIRST_TEN_U32[1] / 2 ** 32


def test_the_first_ten_dice_for_seed_1867_season_1():
    generator = prng.Prng(SEED_1867_SEASON_1)
    assert [generator.rand_int(1, 6) for _ in range(10)] == [1, 6, 3, 5, 1, 5, 2, 1, 4, 6]


def test_rand_int_stays_inside_its_range_and_covers_it():
    generator = prng.Prng(7)
    seen = set()
    for _ in range(10_000):
        value = generator.rand_int(3, 9)
        assert 3 <= value <= 9
        seen.add(value)
    assert seen == set(range(3, 10))


def test_a_single_valued_range_draws_nothing():
    """span == 1 returns without consuming a word: a house with one legal
    option does not spend the season's randomness on a foregone conclusion,
    and both engines have to agree about that or their streams desynchronise."""
    generator = prng.Prng(11)
    before = list(generator.s)
    assert generator.rand_int(4, 4) == 4
    assert generator.s == before


def test_rand_int_is_unbiased_across_a_range_that_does_not_divide_2_32():
    """6 does not divide 2^32, which is exactly when modulo bias appears. The
    rejection sampling in rand_int is what removes it."""
    generator = prng.Prng(99)
    counts = [0] * 6
    draws = 600_000
    for _ in range(draws):
        counts[generator.rand_int(1, 6) - 1] += 1
    expected = draws / 6
    for face, count in enumerate(counts, start=1):
        assert abs(count - expected) < 0.02 * expected, f"face {face}: {count} of {draws}"


def test_an_empty_range_is_refused():
    with pytest.raises(ValueError):
        prng.Prng(1).rand_int(5, 4)


def test_weighted_choice_never_picks_a_zero_weight():
    generator = prng.Prng(3)
    for _ in range(2000):
        assert generator.weighted_choice(["a", "b", "c"], [0, 5, 0]) == "b"


def test_weighted_choice_returns_none_when_nothing_is_possible():
    assert prng.Prng(3).weighted_choice(["a", "b"], [0, 0]) is None
    assert prng.Prng(3).weighted_choice([], []) is None


def test_weighted_choice_follows_the_weights():
    generator = prng.Prng(23)
    counts = {"a": 0, "b": 0}
    for _ in range(60_000):
        counts[generator.weighted_choice(["a", "b"], [300, 100])] += 1
    ratio = counts["a"] / counts["b"]
    assert 2.85 < ratio < 3.15, counts


def test_p_found_matches_the_documented_values():
    assert prng.p_found(343, 343, 0.5) == 0.5
    assert prng.p_found(300, 343, 0.5) == 0.46760976479141225
    assert prng.p_found(0, 343, 0.5) == 0.0


def test_two_generators_on_one_seed_agree_forever():
    a, b = prng.Prng(1867), prng.Prng(1867)
    assert [a.next_u32() for _ in range(1000)] == [b.next_u32() for _ in range(1000)]


# ------------------------------------------------------------ the palette --


def test_hsl_to_hex_is_exact_at_the_corners():
    assert palette.hsl_to_hex(0, 100, 50) == "#ff0000"
    assert palette.hsl_to_hex(120, 100, 50) == "#00ff00"
    assert palette.hsl_to_hex(240, 100, 50) == "#0000ff"
    assert palette.hsl_to_hex(60, 100, 50) == "#ffff00"
    assert palette.hsl_to_hex(0, 0, 0) == "#000000"
    assert palette.hsl_to_hex(0, 0, 100) == "#ffffff"


def test_hsl_to_hex_never_leaves_a_byte():
    """The bug this pins: an out-of-range channel produced '#1fe0000', which
    openpyxl rejected only much later, when the workbook was written."""
    import re

    for hue in range(0, 360, 3):
        for saturation in range(0, 101, 4):
            for lightness in range(0, 101, 4):
                value = palette.hsl_to_hex(hue, saturation, lightness)
                assert re.fullmatch(r"#[0-9a-f]{6}", value), (hue, saturation, lightness, value)


def test_the_palette_is_integers_all_the_way_down():
    hue, saturation, lightness = palette.hex_to_hsl("#4a6f8a")
    assert (hue, saturation, lightness) == (205, 30, 42)
    assert all(isinstance(part, int) for part in (hue, saturation, lightness))
    assert isinstance(palette.hsl_distance_sq((0, 40, 30), (180, 40, 30)), int)
    assert isinstance(palette.farthest_hue([0, 180]), int)


def test_farthest_hue_breaks_ties_low():
    """Both engines depend on this: only a strictly greater gap displaces the
    incumbent, so an empty circle and a symmetric one both answer 0."""
    assert palette.farthest_hue([]) == 0
    assert palette.farthest_hue([90, 270]) == 0
