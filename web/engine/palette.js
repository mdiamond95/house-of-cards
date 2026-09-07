// Colours for engine-founded houses, in integer arithmetic only.
//
// A mirror of hoc/palette.py, operation for operation. Read that file for what
// the rule means; read docs/DETERMINISM.md for why none of it is allowed to
// touch a float.

export const SATURATION_RANGE = [35, 55];
export const LIGHTNESS_RANGE = [25, 40];
export const SECONDARY_LIGHTNESS_STEP = 20;
export const MIN_DISTANCE_SQ = 3600;
export const HUE_CANDIDATES = 180;
export const MAX_SL_REDRAWS = 25;

// JavaScript's % keeps the sign of the dividend and Python's does not, which
// would silently break every hue wrap in this file. Everything here goes
// through this instead of the bare operator.
function mod(value, n) {
  return ((value % n) + n) % n;
}

// Python's round() is banker's rounding (0.5 goes to the nearest even) and
// JavaScript's Math.round() rounds half up, so they disagree on exactly the
// half-integers this file produces. This is Python's rule, spelled out.
function roundHalfEven(value) {
  const floor = Math.floor(value);
  const diff = value - floor;
  if (diff > 0.5) return floor + 1;
  if (diff < 0.5) return floor;
  return floor % 2 === 0 ? floor : floor + 1;
}

function hueFromRgb(r, g, b) {
  const high = Math.max(r, g, b);
  const low = Math.min(r, g, b);
  const span = high - low;
  if (span === 0) return 0;
  let sixths;
  if (high === r) sixths = mod((g - b) / span, 6);
  else if (high === g) sixths = (b - r) / span + 2;
  else sixths = (r - g) / span + 4;
  return mod(roundHalfEven(sixths * 60), 360);
}

// '#4a6f8a' -> [hue 0-359, saturation 0-100, lightness 0-100], all integers.
export function hexToHsl(value) {
  const hex = value.startsWith('#') ? value.slice(1) : value;
  const r = parseInt(hex.slice(0, 2), 16);
  const g = parseInt(hex.slice(2, 4), 16);
  const b = parseInt(hex.slice(4, 6), 16);
  const high = Math.max(r, g, b);
  const low = Math.min(r, g, b);

  const lightness = roundHalfEven(((high + low) * 100) / 510);
  let saturation;
  if (high === low) saturation = 0;
  else if (high + low <= 255) saturation = roundHalfEven(((high - low) * 100) / (high + low));
  else saturation = roundHalfEven(((high - low) * 100) / (510 - high - low));
  return [hueFromRgb(r, g, b), saturation, lightness];
}

function channel(p, q, t) {
  const tt = mod(t, 360);
  let value;
  if (tt < 60) value = p + ((q - p) * tt) / 60;
  else if (tt < 180) value = q;
  else if (tt < 240) value = p + ((q - p) * (240 - tt)) / 60;
  else value = p;
  return roundHalfEven((value * 255) / 10000);
}

function twoDigits(value) {
  return value.toString(16).padStart(2, '0');
}

// Integer HSL -> '#rrggbb'. See hoc/palette.py for the derivation.
export function hslToHex(hue, saturation, lightness) {
  const h = mod(hue, 360);
  const l = lightness * 100;
  const s = saturation * 100;
  if (s === 0) {
    const grey = roundHalfEven((l * 255) / 10000);
    return `#${twoDigits(grey)}${twoDigits(grey)}${twoDigits(grey)}`;
  }
  const q = l < 5000 ? l + (l * s) / 10000 : l + s - (l * s) / 10000;
  const p = 2 * l - q;
  return `#${twoDigits(channel(p, q, h + 120))}${twoDigits(channel(p, q, h))}${twoDigits(
    channel(p, q, h - 120),
  )}`;
}

export function hueDistance(a, b) {
  const diff = mod(Math.abs(a - b), 360);
  return Math.min(diff, 360 - diff);
}

// Squared distance between two integer (h, s, l) triples, scaled by 1000.
export function hslDistanceSq(a, b) {
  const dh = Math.floor((hueDistance(a[0], b[0]) * 1000) / 180);
  const ds = (a[1] - b[1]) * 10;
  const dl = (a[2] - b[2]) * 10;
  return dh * dh + ds * ds + dl * dl;
}

// The hue whose nearest existing neighbour is furthest away. Ties go to the
// lowest hue: only a strictly greater gap displaces the incumbent, and both
// engines depend on that.
export function farthestHue(existingHues, candidates = HUE_CANDIDATES) {
  if (existingHues.length === 0) return 0;
  let bestHue = 0;
  let bestGap = -1;
  for (let index = 0; index < candidates; index += 1) {
    const hue = Math.floor((index * 360) / candidates);
    let gap = Infinity;
    for (const other of existingHues) gap = Math.min(gap, hueDistance(hue, other));
    if (gap > bestGap) {
      bestHue = hue;
      bestGap = gap;
    }
  }
  return bestHue;
}

// [primaryHex, secondaryHex] for a new house. `rng` need only provide randint.
export function assignColours(existingPrimaries, rng) {
  const existing = existingPrimaries.filter(Boolean).map(hexToHsl);
  const hue = farthestHue(existing.map((triple) => triple[0]));

  let best = null;
  let bestDistance = -1;
  for (let attempt = 0; attempt < MAX_SL_REDRAWS; attempt += 1) {
    const saturation = rng.randint(SATURATION_RANGE[0], SATURATION_RANGE[1]);
    const lightness = rng.randint(LIGHTNESS_RANGE[0], LIGHTNESS_RANGE[1]);
    const candidate = [hue, saturation, lightness];
    let distance = 3000000;
    for (const other of existing) distance = Math.min(distance, hslDistanceSq(candidate, other));
    if (distance > bestDistance) {
      best = candidate;
      bestDistance = distance;
    }
    if (distance >= MIN_DISTANCE_SQ) break;
  }

  const [h, s, l] = best;
  return [hslToHex(h, s, l), hslToHex(h, s, Math.min(100, l + SECONDARY_LIGHTNESS_STEP))];
}
