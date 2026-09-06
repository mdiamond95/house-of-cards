"""Colours for engine-founded houses.

Hard rule 4 still governs what a colour *means*: the primary colour is the
colour of the principal seat, which is the first holding in canonical row order.
This module only decides which colour a new house is given, and it does that
deterministically from the season's seeded RNG so a replay reproduces the map
exactly.

The rule: take the hue furthest from every existing house's primary hue
(max-min-distance on the hue circle), draw a saturation and lightness inside the
muted band the v1 palette sits in, and reject any candidate that lands too close
to an existing primary in plain HSL space. The secondary is the same hue twenty
points lighter, which is what a newly acquired riding is filled with.
"""

import colorsys

__all__ = [
    "hex_to_hsl",
    "hsl_to_hex",
    "hue_distance",
    "hsl_distance",
    "farthest_hue",
    "assign_colours",
    "SATURATION_RANGE",
    "LIGHTNESS_RANGE",
    "SECONDARY_LIGHTNESS_STEP",
    "MIN_DISTANCE",
]

SATURATION_RANGE = (35, 55)  # per cent
LIGHTNESS_RANGE = (25, 40)  # per cent
SECONDARY_LIGHTNESS_STEP = 20  # the secondary is this much lighter

# How far apart two primaries must sit in HSL space, with hue normalised against
# a half-circle so all three axes run 0-1.
#
# This is a target the search stops at, not a guarantee it can always meet: with
# ninety-odd houses the hue circle gives each about four degrees of room (0.022
# on the normalised axis), so the separation has to come from saturation and
# lightness, and measured runs bottom out around 0.07 at a full map. Below that
# the search keeps the best candidate it found rather than failing — a house
# must be founded, and a slightly close colour is a smaller problem than a
# season that cannot complete.
MIN_DISTANCE = 0.06

# How many hue candidates to test around the circle. Two degrees is finer than
# the eye separates at these saturations, and keeps founding cheap in a 300-season run.
HUE_CANDIDATES = 180

MAX_SL_REDRAWS = 25


def hex_to_hsl(value):
    """'#4a6f8a' -> (hue 0-360, saturation 0-100, lightness 0-100)."""
    value = value.lstrip("#")
    r, g, b = (int(value[i:i + 2], 16) / 255 for i in (0, 2, 4))
    h, l, s = colorsys.rgb_to_hls(r, g, b)
    return h * 360, s * 100, l * 100


def hsl_to_hex(hue, saturation, lightness):
    r, g, b = colorsys.hls_to_rgb((hue % 360) / 360, lightness / 100, saturation / 100)
    return "#{:02x}{:02x}{:02x}".format(round(r * 255), round(g * 255), round(b * 255))


def hue_distance(a, b):
    """Shortest way round the circle, 0-180."""
    diff = abs(a - b) % 360
    return min(diff, 360 - diff)


def hsl_distance(a, b):
    """Distance between two (h, s, l) triples with every axis normalised to 0-1.

    Not a perceptual metric — a real ΔE would need a Lab conversion — but at the
    narrow saturation and lightness bands this palette uses, hue does nearly all
    the perceptual work, so this ranks candidates the same way.
    """
    dh = hue_distance(a[0], b[0]) / 180
    ds = (a[1] - b[1]) / 100
    dl = (a[2] - b[2]) / 100
    return (dh * dh + ds * ds + dl * dl) ** 0.5


def farthest_hue(existing_hues, candidates=HUE_CANDIDATES):
    """The hue whose nearest existing neighbour is furthest away.

    With no houses yet the circle is empty and the choice is arbitrary, so this
    returns 0 rather than pretending to measure anything.
    """
    if not existing_hues:
        return 0.0

    best_hue, best_gap = 0.0, -1.0
    for index in range(candidates):
        hue = index * 360 / candidates
        gap = min(hue_distance(hue, other) for other in existing_hues)
        if gap > best_gap:
            best_hue, best_gap = hue, gap
    return best_hue


def assign_colours(existing_primaries, rng):
    """(primary_hex, secondary_hex) for a new house.

    `existing_primaries` is every active house's primary hex; `rng` need only
    provide `randint`, and the engine passes a logging wrapper so the draw shows
    up in the season record.
    """
    existing = [hex_to_hsl(hex_value) for hex_value in existing_primaries if hex_value]
    hue = farthest_hue([h for h, _, _ in existing])

    best = None
    best_distance = -1.0
    for _ in range(MAX_SL_REDRAWS):
        saturation = rng.randint(*SATURATION_RANGE)
        lightness = rng.randint(*LIGHTNESS_RANGE)
        candidate = (hue, saturation, lightness)
        distance = min((hsl_distance(candidate, other) for other in existing), default=1.0)
        if distance > best_distance:
            best, best_distance = candidate, distance
        if distance >= MIN_DISTANCE:
            break

    hue, saturation, lightness = best
    primary = hsl_to_hex(hue, saturation, lightness)
    secondary = hsl_to_hex(hue, saturation, min(100, lightness + SECONDARY_LIGHTNESS_STEP))
    return primary, secondary
