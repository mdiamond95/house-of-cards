// The map view's camera (docs/STORY_DESIGN.md §3.6, Phase V): where the map
// is looked at from, how a gesture moves it, and where a card goes.
//
// A view is { x, y, w, h } in map units: the part of the map the screen shows.
// The screen is { w, h } in CSS pixels, and the scale is uniform, so a view's
// height always follows from its width and the screen's aspect.
//
// Two modes (`Camera`):
//   follow  the default. Each turn the camera frames the headline's ground,
//           leaving room for its card, and stays there; a turn with nothing to
//           frame leaves it where it is. It never goes back to a home view.
//   free    after any gesture. The camera does not move until the director
//           taps Recentre, which returns to follow and to the last framing.
//
// `Gestures` reads pointer events (one finger to pan, two to pinch, a quick
// tap, a double tap) and says what they mean; the page applies them. Every
// function here is pure arithmetic, so the camera is tested under node.
//
// Pure: no DOM, no clock (times are handed in), no randomness.

// ---------------------------------------------------------------- views ----

export function heightFor(w, screen) {
  return (w * screen.h) / screen.w;
}

export function viewAt(cx, cy, w, screen) {
  const h = heightFor(w, screen);
  return { x: cx - w / 2, y: cy - h / 2, w, h };
}

export function centreOf(view) {
  return [view.x + view.w / 2, view.y + view.h / 2];
}

export function scaleOf(view, screen) {
  return screen.w / view.w;
}

export function toScreen(view, screen, [x, y]) {
  const k = scaleOf(view, screen);
  return [(x - view.x) * k, (y - view.y) * k];
}

export function toMap(view, screen, [sx, sy]) {
  const k = scaleOf(view, screen);
  return [view.x + sx / k, view.y + sy / k];
}

// The widest a view may be: the whole map with a margin, whichever way the
// screen is turned. The narrowest is `minW` map units across the screen.
export function limitsFor(world, screen, { minW = 3, margin = 1.2 } = {}) {
  const fitW = Math.max(world.w, (world.h * screen.w) / screen.h);
  return { minW, maxW: fitW * margin };
}

// A view kept within its limits: no narrower than minW, no wider than maxW,
// and its centre never off the map, so the map cannot be lost.
export function clampView(view, world, screen, limits = limitsFor(world, screen)) {
  const w = Math.min(limits.maxW, Math.max(limits.minW, view.w));
  let [cx, cy] = centreOf(view);
  cx = Math.min(world.x + world.w, Math.max(world.x, cx));
  cy = Math.min(world.y + world.h, Math.max(world.y, cy));
  return viewAt(cx, cy, w, screen);
}

// Zoom by `factor` (above 1 is closer) about the screen point (sx, sy), which
// stays over the same place on the map.
export function zoomAt(view, factor, sx, sy, screen) {
  const [mx, my] = toMap(view, screen, [sx, sy]);
  const w = view.w / factor;
  const k = screen.w / w;
  return { x: mx - sx / k, y: my - sy / k, w, h: heightFor(w, screen) };
}

// Move the map with a finger: dx, dy in screen pixels.
export function panBy(view, dx, dy, screen) {
  const k = scaleOf(view, screen);
  return { ...view, x: view.x - dx / k, y: view.y - dy / k };
}

// The part of the screen the ground is framed in, in follow mode: below the
// top bar and above the bottom bar, less the room the headline's card takes
// — beneath the ground on a phone held upright, beside it on a wider screen.
export function freeRect(screen, { top = 0, bottom = 0, card = true } = {}) {
  const rect = { left: 0, top, right: screen.w, bottom: screen.h - bottom };
  if (!card) return rect;
  if (isLandscape(screen)) {
    rect.right -= Math.min(400, Math.round(screen.w * 0.42));
  } else {
    rect.bottom -= Math.min(280, Math.round((rect.bottom - rect.top) * 0.36));
  }
  return rect;
}

export function isLandscape(screen) {
  return screen.w > screen.h * 1.05;
}

// The view that frames `bounds` ([x, y, w, h] in map units) in the screen
// rectangle `rect`, padded by `pad` of the ground's size on each side and never
// closer than `minGround` map units across, nor wider than the limits allow.
export function frameView(bounds, screen, rect, world, {
  pad = 0.35, minGround = 60, limits = limitsFor(world, screen),
} = {}) {
  const [bx, by, bw, bh] = bounds;
  const gw = Math.max(bw * (1 + 2 * pad), minGround);
  const gh = Math.max(bh * (1 + 2 * pad), (minGround * (rect.bottom - rect.top)) / (rect.right - rect.left));
  const rw = rect.right - rect.left;
  const rh = rect.bottom - rect.top;
  let k = Math.min(rw / gw, rh / gh);
  let w = screen.w / k;
  w = Math.min(limits.maxW, Math.max(limits.minW, w));
  k = screen.w / w;
  const cx = bx + bw / 2;
  const cy = by + bh / 2;
  const fx = (rect.left + rect.right) / 2;
  const fy = (rect.top + rect.bottom) / 2;
  return { x: cx - fx / k, y: cy - fy / k, w, h: heightFor(w, screen) };
}

export function unionBounds(boxes) {
  const list = boxes.filter(Boolean);
  if (!list.length) return null;
  let x0 = Infinity; let y0 = Infinity; let x1 = -Infinity; let y1 = -Infinity;
  for (const [x, y, w, h] of list) {
    x0 = Math.min(x0, x); y0 = Math.min(y0, y);
    x1 = Math.max(x1, x + w); y1 = Math.max(y1, y + h);
  }
  return [x0, y0, x1 - x0, y1 - y0];
}

// A flight from view a to view b at t in [0, 1], eased: the width moves
// geometrically, so zooming in and out feel alike, and the centre linearly.
export function flight(a, b, t) {
  const e = t < 0.5 ? 2 * t * t : 1 - ((-2 * t + 2) ** 2) / 2;
  const w = a.w * (b.w / a.w) ** e;
  const [ax, ay] = centreOf(a);
  const [bx, by] = centreOf(b);
  const cx = ax + (bx - ax) * e;
  const cy = ay + (by - ay) * e;
  const h = a.h * (b.h / a.h) ** e;
  return { x: cx - w / 2, y: cy - h / 2, w, h };
}

export function sameView(a, b, tolerance = 1e-6) {
  return Boolean(a && b) && ['x', 'y', 'w', 'h'].every((k) => Math.abs(a[k] - b[k]) <= tolerance * Math.max(1, Math.abs(a[k])));
}

// ---------------------------------------------------------------- modes ----

export class Camera {
  constructor() {
    this.mode = 'follow';
    // The last view follow mode chose: where Recentre goes back to.
    this.goal = null;
  }

  get free() {
    return this.mode === 'free';
  }

  // A turn's framing. Returns the view to fly to, or null to stay where it is:
  // in free mode, and for a turn with nothing to frame.
  frame(view) {
    if (view) this.goal = view;
    return this.mode === 'follow' && view ? view : null;
  }

  // Any gesture hands the camera to the director. True if that changed the mode.
  gesture() {
    const changed = this.mode !== 'free';
    this.mode = 'free';
    return changed;
  }

  // Back to follow mode, and to the last framing (null if there was none yet).
  recentre() {
    this.mode = 'follow';
    return this.goal;
  }
}

// ----------------------------------------------------------------- cards ----

// Where a card of size `card` goes beside an anchor (a point and the radius of
// what is drawn there), inside the screen less `safe` (the bars): beneath it
// on an upright phone, beside it on a wider screen, else wherever it fits
// without covering the anchor; if nowhere does, where there is most room.
export function placeCard({ anchor, card, screen, safe = {}, gap = 12 }) {
  const top = safe.top || 0;
  const bottom = screen.h - (safe.bottom || 0);
  const left = safe.left || 0;
  const right = screen.w - (safe.right || 0);
  // What is drawn at the anchor, to keep clear of: a radius, or half its
  // width (`rx`) and height (`ry`) for a wider thing (a crisis's whole table).
  const rx = anchor.rx ?? anchor.r ?? 0;
  const ry = anchor.ry ?? anchor.r ?? 0;
  const clampX = (x) => Math.max(left, Math.min(right - card.w, x));
  const clampY = (y) => Math.max(top, Math.min(bottom - card.h, y));
  const sides = {
    below: { x: clampX(anchor.x - card.w / 2), y: anchor.y + ry + gap, room: bottom - (anchor.y + ry + gap) - card.h },
    above: { x: clampX(anchor.x - card.w / 2), y: anchor.y - ry - gap - card.h, room: anchor.y - ry - gap - card.h - top },
    right: { x: anchor.x + rx + gap, y: clampY(anchor.y - card.h / 2), room: right - (anchor.x + rx + gap) - card.w },
    left: { x: anchor.x - rx - gap - card.w, y: clampY(anchor.y - card.h / 2), room: anchor.x - rx - gap - card.w - left },
  };
  const order = isLandscape(screen) ? ['right', 'left', 'below', 'above'] : ['below', 'above', 'right', 'left'];
  for (const side of order) {
    if (sides[side].room >= 0) return { x: sides[side].x, y: sides[side].y, side };
  }
  const best = order.reduce((a, b) => (sides[b].room > sides[a].room ? b : a));
  return { x: clampX(sides[best].x), y: clampY(sides[best].y), side: best };
}

// -------------------------------------------------------------- gestures ----

// Reads pointer events and says what they mean. Each method takes a pointer id,
// its screen position and a time in ms, and returns a list of events:
//   { type: 'start' }                      the first movement of a gesture
//   { type: 'pan', dx, dy }                one finger (or the mouse) moved
//   { type: 'pinch', factor, x, y, dx, dy } two fingers: zoom by factor about
//                                          their midpoint, which moved dx, dy
//   { type: 'tap', x, y }                  a press and release that did not move
//   { type: 'doubletap', x, y }            a second tap soon after the first
//   { type: 'end' }                        the last finger of a gesture lifted
export class Gestures {
  constructor({ slop = 10, tapMs = 500, doubleMs = 320, doubleSlop = 30 } = {}) {
    Object.assign(this, { slop, tapMs, doubleMs, doubleSlop });
    this.pointers = new Map();
    this.moved = false;
    this.multi = false;
    this.started = 0;
    this.origin = null;
    this.lastTap = null;
  }

  down(id, x, y, t) {
    if (!this.pointers.size) {
      this.moved = false;
      this.multi = false;
      this.started = t;
      this.origin = [x, y];
    }
    this.pointers.set(id, [x, y]);
    if (this.pointers.size > 1) this.multi = true;
    return [];
  }

  move(id, x, y) {
    const was = this.pointers.get(id);
    if (!was) return [];
    const out = [];
    if (!this.moved) {
      const [ox, oy] = this.origin;
      if (!this.multi && Math.hypot(x - ox, y - oy) < this.slop) {
        return [];
      }
      this.moved = true;
      out.push({ type: 'start' });
    }
    if (this.pointers.size >= 2) {
      const [a, b] = [...this.pointers.keys()].slice(0, 2);
      const pa = this.pointers.get(a);
      const pb = this.pointers.get(b);
      const before = Math.hypot(pa[0] - pb[0], pa[1] - pb[1]);
      const mid = [(pa[0] + pb[0]) / 2, (pa[1] + pb[1]) / 2];
      this.pointers.set(id, [x, y]);
      const qa = this.pointers.get(a);
      const qb = this.pointers.get(b);
      const after = Math.hypot(qa[0] - qb[0], qa[1] - qb[1]);
      const mid2 = [(qa[0] + qb[0]) / 2, (qa[1] + qb[1]) / 2];
      out.push({
        type: 'pinch', factor: before > 0 ? after / before : 1,
        x: mid2[0], y: mid2[1], dx: mid2[0] - mid[0], dy: mid2[1] - mid[1],
      });
      return out;
    }
    this.pointers.set(id, [x, y]);
    out.push({ type: 'pan', dx: x - was[0], dy: y - was[1] });
    return out;
  }

  up(id, x, y, t) {
    if (!this.pointers.has(id)) return [];
    this.pointers.delete(id);
    if (this.pointers.size) return [];
    if (this.moved || this.multi) {
      this.lastTap = null;
      return this.moved ? [{ type: 'end' }] : [];
    }
    if (t - this.started > this.tapMs) {
      this.lastTap = null;
      return [];
    }
    const last = this.lastTap;
    if (last && t - last.t <= this.doubleMs && Math.hypot(x - last.x, y - last.y) <= this.doubleSlop) {
      this.lastTap = null;
      return [{ type: 'doubletap', x, y }];
    }
    this.lastTap = { x, y, t };
    return [{ type: 'tap', x, y }];
  }

  cancel(id) {
    this.pointers.delete(id);
    if (!this.pointers.size && this.moved) return [{ type: 'end' }];
    return [];
  }
}
