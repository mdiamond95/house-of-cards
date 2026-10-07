// web/story/camera.js: views, framing with room for a card, the two modes,
// limits, cards that do not cover their mark, and gestures.
import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
  Camera, Gestures, clampView, flight, frameView, freeRect, limitsFor, panBy, placeCard, toMap, toScreen,
  viewAt, zoomAt,
} from '../../web/story/camera.js';

const PHONE = { w: 390, h: 844 };
const PAD_UP = { w: 820, h: 1180 };
const PAD_SIDE = { w: 1180, h: 820 };
const WORLD = { x: 0, y: 0, w: 1000, h: 800 };
const near = (a, b, eps = 1e-6) => Math.abs(a - b) <= eps;

test('screen and map points round-trip, at a uniform scale', () => {
  const v = viewAt(500, 400, 200, PHONE);
  assert.ok(near(v.h, (200 * 844) / 390));
  const [sx, sy] = toScreen(v, PHONE, [520, 410]);
  const [x, y] = toMap(v, PHONE, [sx, sy]);
  assert.ok(near(x, 520) && near(y, 410));
});

test('zooming keeps the point under the fingers; panning moves the map with them', () => {
  const v = viewAt(500, 400, 200, PHONE);
  const before = toMap(v, PHONE, [100, 300]);
  const z = zoomAt(v, 2, 100, 300, PHONE);
  assert.ok(near(z.w, 100));
  const after = toMap(z, PHONE, [100, 300]);
  assert.ok(near(before[0], after[0]) && near(before[1], after[1]));
  const p = panBy(v, 39, 0, PHONE);
  assert.ok(near(p.x, v.x - 20), 'a finger moving right moves the view left');
});

test('limits keep the map from being lost or zoomed past use', () => {
  const limits = limitsFor(WORLD, PHONE, { minW: 3 });
  const tiny = clampView(viewAt(500, 400, 0.5, PHONE), WORLD, PHONE, limits);
  assert.equal(tiny.w, 3);
  const huge = clampView(viewAt(500, 400, 1e6, PHONE), WORLD, PHONE, limits);
  assert.equal(huge.w, limits.maxW);
  const away = clampView(viewAt(9000, -9000, 100, PHONE), WORLD, PHONE, limits);
  assert.deepEqual([away.x + away.w / 2, away.y + away.h / 2], [1000, 0], 'the centre stays on the map');
});

test('the card takes the bottom of an upright screen and the side of a wide one', () => {
  const up = freeRect(PHONE, { top: 100, bottom: 80 });
  assert.equal(up.right, 390);
  assert.ok(up.bottom < 844 - 80);
  const side = freeRect(PAD_SIDE, { top: 100, bottom: 80 });
  assert.equal(side.bottom, 820 - 80);
  assert.ok(side.right < 1180);
  assert.deepEqual(freeRect(PHONE, { top: 100, bottom: 80, card: false }), { left: 0, top: 100, right: 390, bottom: 764 });
});

test('framing puts the ground in the free rectangle, padded, and never closer than its minimum', () => {
  for (const screen of [PHONE, PAD_UP, PAD_SIDE]) {
    const rect = freeRect(screen, { top: 120, bottom: 80 });
    const ground = [600, 500, 60, 30];
    const v = frameView(ground, screen, rect, WORLD);
    const [x0, y0] = toScreen(v, screen, [600, 500]);
    const [x1, y1] = toScreen(v, screen, [660, 530]);
    assert.ok(x0 >= rect.left && x1 <= rect.right && y0 >= rect.top && y1 <= rect.bottom, JSON.stringify(screen));
    const mid = toScreen(v, screen, [630, 515]);
    assert.ok(near(mid[0], (rect.left + rect.right) / 2, 1e-6) && near(mid[1], (rect.top + rect.bottom) / 2, 1e-6));
  }
  const rect = freeRect(PHONE, { top: 120, bottom: 80 });
  const one = frameView([600, 500, 1, 1], PHONE, rect, WORLD);
  assert.ok(one.w >= 60, 'one small riding is shown with its surroundings');
});

test('follow mode frames each turn; any gesture frees it until Recentre', () => {
  const camera = new Camera();
  const a = viewAt(100, 100, 50, PHONE);
  const b = viewAt(300, 300, 80, PHONE);
  const c = viewAt(500, 500, 90, PHONE);
  assert.equal(camera.mode, 'follow');
  assert.equal(camera.frame(a), a, 'follow mode flies to each framing');
  assert.equal(camera.frame(null), null, 'nothing to frame: the camera stays, no home view');
  assert.equal(camera.goal, a);
  assert.equal(camera.gesture(), true);
  assert.equal(camera.gesture(), false, 'already free');
  assert.equal(camera.frame(b), null, 'free mode holds still across turns');
  assert.equal(camera.frame(c), null);
  assert.equal(camera.recentre(), c, 'Recentre returns to the latest framing');
  assert.equal(camera.mode, 'follow');
  assert.equal(camera.frame(b), b);
});

test('a flight starts and ends where it should and zooms geometrically', () => {
  const a = viewAt(100, 100, 400, PHONE);
  const b = viewAt(300, 200, 25, PHONE);
  assert.deepEqual(flight(a, b, 0), a);
  const end = flight(a, b, 1);
  for (const k of ['x', 'y', 'w', 'h']) assert.ok(near(end[k], b[k], 1e-9), k);
  assert.ok(near(flight(a, b, 0.5).w, 100, 1e-9), 'halfway in time is halfway in scale');
});

test('a card never covers its mark, and stays inside the bars', () => {
  const safe = { top: 120, bottom: 80, left: 8, right: 8 };
  const card = { w: 340, h: 180 };
  const cases = [
    [PHONE, { x: 195, y: 300, r: 26 }, 'below'],
    [PHONE, { x: 195, y: 650, r: 26 }, 'above'],
    [PAD_SIDE, { x: 400, y: 400, r: 26 }, 'right'],
    [PAD_SIDE, { x: 1000, y: 400, r: 26 }, 'left'],
  ];
  for (const [screen, anchor, side] of cases) {
    const at = placeCard({ anchor, card, screen, safe });
    assert.equal(at.side, side);
    assert.ok(at.x >= safe.left && at.x + card.w <= screen.w - safe.right);
    assert.ok(at.y >= safe.top && at.y + card.h <= screen.h - safe.bottom);
    const coversX = at.x < anchor.x + anchor.r && anchor.x - anchor.r < at.x + card.w;
    const coversY = at.y < anchor.y + anchor.r && anchor.y - anchor.r < at.y + card.h;
    assert.ok(!(coversX && coversY), `${side}: the card covers its mark`);
  }
});

test('gestures: a tap, a double tap, a drag and a pinch', () => {
  const g = new Gestures();
  g.down(1, 100, 100, 0);
  assert.deepEqual(g.up(1, 102, 101, 120), [{ type: 'tap', x: 102, y: 101 }]);
  g.down(1, 104, 100, 250);
  assert.deepEqual(g.up(1, 104, 100, 330), [{ type: 'doubletap', x: 104, y: 100 }]);

  g.down(1, 100, 100, 1000);
  assert.deepEqual(g.move(1, 104, 100), [], 'within the slop: still a tap');
  assert.deepEqual(g.move(1, 130, 110), [{ type: 'start' }, { type: 'pan', dx: 30, dy: 10 }]);
  assert.deepEqual(g.move(1, 140, 110), [{ type: 'pan', dx: 10, dy: 0 }]);
  assert.deepEqual(g.up(1, 140, 110, 1200), [{ type: 'end' }], 'a drag is no tap');

  g.down(1, 100, 100, 2000);
  g.down(2, 200, 100, 2001);
  const [start, pinch] = g.move(2, 300, 100);
  assert.equal(start.type, 'start');
  assert.equal(pinch.type, 'pinch');
  assert.ok(near(pinch.factor, 2));
  assert.deepEqual([pinch.x, pinch.y, pinch.dx, pinch.dy], [200, 100, 50, 0]);
  assert.deepEqual(g.up(2, 300, 100, 2100), [], 'one finger still down');
  assert.deepEqual(g.move(1, 110, 100), [{ type: 'pan', dx: 10, dy: 0 }], 'the other finger pans on without a jump');
  assert.deepEqual(g.up(1, 110, 100, 2200), [{ type: 'end' }]);
});
