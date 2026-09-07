"""Colours for engine-founded houses, in integer arithmetic only.

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

**Phase 10-1: every number here is an integer.** The module used to run on
`colorsys` and floating-point HSL, which meant the map's colours depended on
CPython's rounding — nothing a second engine could reproduce. Hues are now whole
degrees (0-359), saturation and lightness whole per cent (0-100), the distance
metric is a squared integer distance with no square root, and the HSL-to-hex
conversion is the exact integer form documented in `hsl_to_hex` below.
`web/engine/palette.js` mirrors it operation for operation.
"""

__all__ = [
    "hex_to_hsl",
    "hsl_to_hex",
    "hue_distance",
    "hsl_distance_sq",
    "farthest_hue",
    "assign_colours",
    "SATURATION_RANGE",
    "LIGHTNESS_RANGE",
    "SECONDARY_LIGHTNESS_STEP",
    "MIN_DISTANCE_SQ",
]

SATURATION_RANGE = (35, 55)  # per cent
LIGHTNESS_RANGE = (25, 40)  # per cent
SECONDARY_LIGHTNESS_STEP = 20  # the secondary is this much lighter

# How far apart two primaries must sit, as a **squared** distance on the scale
# `hsl_distance_sq` uses (see below). The old float metric normalised all three
# axes to 0-1 and took a square root, with a threshold of 0.06; squaring that
# gives 0.0036, and this metric's scale is 1_000_000 times the old one's, so the
# same threshold is 3600 here. No square root is taken anywhere, which keeps the
# comparison exact.
#
# This is a target the search stops at, not a guarantee it can always meet: with
# ninety-odd houses the hue circle gives each about four degrees of room, so the
# separation has to come from saturation and lightness, and measured runs bottom
# out well below it at a full map. Below the target the search keeps the best
# candidate it found rather than failing — a house must be founded, and a
# slightly close colour is a smaller problem than a season that cannot complete.
MIN_DISTANCE_SQ = 3600

# How many hue candidates to test around the circle. Two degrees is finer than
# the eye separates at these saturations, and keeps founding cheap in a
# 300-season run. 180 candidates over 360 degrees lands every candidate on an
# even whole degree, so no rounding enters here either.
HUE_CANDIDATES = 180

MAX_SL_REDRAWS = 25


def _hue_from_rgb(r, g, b):
    """Hue in whole degrees from 0-255 channels, by the standard piecewise form.

    Returns 0 for a grey, which has no hue to speak of. The rounding is a single
    `round()` on an exact rational, and every branch is symmetric, so the answer
    does not depend on the order the channels are tested in.
    """
    high = max(r, g, b)
    low = min(r, g, b)
    span = high - low
    if span == 0:
        return 0
    if high == r:
        sixths = ((g - b) / span) % 6
    elif high == g:
        sixths = (b - r) / span + 2
    else:
        sixths = (r - g) / span + 4
    return round(sixths * 60) % 360


def hex_to_hsl(value):
    """'#4a6f8a' -> (hue 0-359, saturation 0-100, lightness 0-100), all integers.

    Saturation and lightness are rounded to whole per cent, which is the same
    resolution the generator draws them at, so a colour survives a round trip
    through hex and back to within the one point the draw itself can express.
    """
    value = value.lstrip("#")
    r, g, b = (int(value[i:i + 2], 16) for i in (0, 2, 4))
    high = max(r, g, b)
    low = min(r, g, b)

    lightness = round((high + low) * 100 / 510)  # (high + low) / 2 / 255, as per cent
    if high == low:
        saturation = 0
    elif high + low <= 255:
        saturation = round((high - low) * 100 / (high + low))
    else:
        saturation = round((high - low) * 100 / (510 - high - low))
    return _hue_from_rgb(r, g, b), saturation, lightness


def _channel(p, q, t):
    """One RGB channel of the standard HSL conversion, as a 0-255 integer.

    `p` and `q` are per-mille-squared quantities carried as exact integers; `t`
    is a hue offset in degrees. Kept in integer arithmetic to the last step so
    the only rounding is the single `round()` that produces the byte.
    """
    t %= 360
    if t < 60:
        value = p + (q - p) * t / 60
    elif t < 180:
        value = q
    elif t < 240:
        value = p + (q - p) * (240 - t) / 60
    else:
        value = p
    return round(value * 255 / 10000)


def hsl_to_hex(hue, saturation, lightness):
    """Integer HSL -> '#rrggbb', by the exact conversion below.

    Working in hundredths throughout (saturation and lightness arrive as whole
    per cent, so `l * 100` and `s * 100` are exact):

        l, s in 0..10000                       (per cent, times 100)
        q = l + l*s/10000                      if l < 5000     i.e. l * (1 + s)
            l + s - l*s/10000                  otherwise       i.e. l + s - l*s
        p = 2*l - q
        r = channel(p, q, hue + 120)
        g = channel(p, q, hue)
        b = channel(p, q, hue - 120)

    Both branches keep `q` inside 0..10000, so every channel lands inside a
    byte; `_channel` asserts nothing, but `assign_colours` only ever feeds this
    the ranges it draws from, and the round-trip test covers the corners.

    Every division above is by a power of ten on a quantity that is a whole
    number of hundredths, and the only rounding is the final one to a byte.
    `web/engine/palette.js` performs the same operations in the same order;
    JavaScript numbers are IEEE-754 doubles, which represent every integer
    involved here exactly, so the two agree.
    """
    hue = hue % 360
    l = lightness * 100
    s = saturation * 100
    if s == 0:
        grey = round(l * 255 / 10000)
        return "#{:02x}{:02x}{:02x}".format(grey, grey, grey)

    q = l + l * s / 10000 if l < 5000 else l + s - l * s / 10000
    p = 2 * l - q
    r = _channel(p, q, hue + 120)
    g = _channel(p, q, hue)
    b = _channel(p, q, hue - 120)
    return "#{:02x}{:02x}{:02x}".format(r, g, b)


def hue_distance(a, b):
    """Shortest way round the circle, 0-180, in whole degrees."""
    diff = abs(a - b) % 360
    return min(diff, 360 - diff)


def hsl_distance_sq(a, b):
    """Squared distance between two integer (h, s, l) triples.

    The axes are weighted as the old float metric weighted them — hue against a
    half-circle, saturation and lightness against 100, so all three run 0-1 —
    but scaled up by 1000 and left squared, which keeps the whole comparison in
    integers:

        dh = hue_distance(a, b) * 1000 // 180
        ds = (a.s - b.s) * 10
        dl = (a.l - b.l) * 10
        return dh*dh + ds*ds + dl*dl

    Not a perceptual metric — a real ΔE would need a Lab conversion — but at the
    narrow saturation and lightness bands this palette uses, hue does nearly all
    the perceptual work, so this ranks candidates the way the old one did.
    """
    dh = hue_distance(a[0], b[0]) * 1000 // 180
    ds = (a[1] - b[1]) * 10
    dl = (a[2] - b[2]) * 10
    return dh * dh + ds * ds + dl * dl


def farthest_hue(existing_hues, candidates=HUE_CANDIDATES):
    """The hue whose nearest existing neighbour is furthest away, in whole degrees.

    With no houses yet the circle is empty and the choice is arbitrary, so this
    returns 0 rather than pretending to measure anything. Ties go to the lowest
    hue, since the scan runs upward and only a strictly greater gap displaces
    the incumbent — that tie-break is load-bearing and both engines share it.
    """
    if not existing_hues:
        return 0

    best_hue, best_gap = 0, -1
    for index in range(candidates):
        hue = index * 360 // candidates
        gap = min(hue_distance(hue, other) for other in existing_hues)
        if gap > best_gap:
            best_hue, best_gap = hue, gap
    return best_hue


def assign_colours(existing_primaries, rng):
    """(primary_hex, secondary_hex) for a new house.

    `existing_primaries` is every active house's primary hex, in a caller-fixed
    order; `rng` need only provide `randint`, and the engine passes a logging
    wrapper so the draw shows up in the season record.
    """
    existing = [hex_to_hsl(hex_value) for hex_value in existing_primaries if hex_value]
    hue = farthest_hue([h for h, _, _ in existing])

    best = None
    best_distance = -1
    for _ in range(MAX_SL_REDRAWS):
        saturation = rng.randint(*SATURATION_RANGE)
        lightness = rng.randint(*LIGHTNESS_RANGE)
        candidate = (hue, saturation, lightness)
        # An empty map is maximally far from everything: 1000^2 * 3 is beyond
        # any real distance, so the first candidate is kept and the loop stops.
        distance = min(
            (hsl_distance_sq(candidate, other) for other in existing), default=3_000_000
        )
        if distance > best_distance:
            best, best_distance = candidate, distance
        if distance >= MIN_DISTANCE_SQ:
            break

    hue, saturation, lightness = best
    primary = hsl_to_hex(hue, saturation, lightness)
    secondary = hsl_to_hex(hue, saturation, min(100, lightness + SECONDARY_LIGHTNESS_STEP))
    return primary, secondary
