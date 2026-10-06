// web/story/weight.js: story weight and its modifiers (docs/STORY_DESIGN.md §3.1).
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

import { BEAT_KINDS, BOOKKEEPING } from '../../web/story/beats.js';
import { advance, createContext, provinceOf, storylineBonus, weighTurn } from '../../web/story/weight.js';

const weights = JSON.parse(readFileSync(new URL('../../web/story/weights.json', import.meta.url), 'utf8'));
const beat = (turn, kind, houses, extra = {}) => ({ turn, seq: 0, kind, houses, ...extra });
const spent = () => createContext({}, BEAT_KINDS);

test('weights.json: every beat kind has an integer weight; §3.1 values and thresholds hold', () => {
  for (const kind of BEAT_KINDS) assert.ok(Number.isInteger(weights.kinds[kind]), kind);
  for (const kind of BOOKKEEPING) assert.equal(weights.kinds[kind], 0, kind);
  assert.equal(weights.kinds.removed, 100);
  assert.equal(weights.kinds.riding_passes, 80);
  assert.equal(weights.thresholds.pause, 60);
  assert.equal(weights.thresholds.quiet, 40);
  for (const key of Object.keys(weights.storylines)) {
    const v = weights.storylines[key];
    assert.ok(Number.isInteger(v) || (Array.isArray(v) && v.every(Number.isInteger)), key);
  }
  const walk = (value) => {
    if (typeof value === 'number') assert.ok(Number.isInteger(value), `${value} is not an integer`);
    else if (value && typeof value === 'object') Object.values(value).forEach(walk);
  };
  walk({ ...weights, notes: null });
});

test('the base weight is the kind\'s', () => {
  const [w] = weighTurn([beat(5, 'elevation', ['A'])], spent(), { weights });
  assert.equal(w.total, 60);
  assert.deepEqual(w.mods, []);
});

test('+20 when a house of the cast is involved', () => {
  const [w] = weighTurn([beat(5, 'compact', ['A', 'B'])], spent(), { weights, cast: new Set(['B']) });
  assert.equal(w.total, 45);
});

test('+15 for the first of a kind, once', () => {
  const [a, b] = weighTurn([beat(5, 'marriage', ['A', 'B']), beat(5, 'marriage', ['C', 'D'])], createContext(), { weights });
  assert.equal(a.total, 50);
  assert.equal(b.total, 35);
});

test('+15 for the first riding in a province, and not again', () => {
  const ctx = createContext({ 35001: 'X' }, BEAT_KINDS);
  const [ontario, quebec] = weighTurn([
    beat(5, 'expansion', ['A'], { owners: { 35002: 'A' } }),
    beat(5, 'expansion', ['B'], { owners: { 24001: 'B' } }),
  ], ctx, { weights });
  assert.equal(ontario.total, 20);
  assert.equal(quebec.total, 35);
  assert.equal(provinceOf('24001'), '24');
  const next = advance(ctx, [beat(5, 'expansion', ['B'], { owners: { 24001: 'B' } })], 'expansion', weights);
  assert.deepEqual(next.provinces, ['24', '35']);
});

test('storyline position: nothing to open, +10 per earlier beat to +30 to escalate, +25 to close', () => {
  const cfg = weights.storylines;
  assert.equal(storylineBonus([{ role: 'open', earlier: 0 }], cfg), 0);
  assert.equal(storylineBonus([{ role: 'escalate', earlier: 1 }], cfg), 10);
  assert.equal(storylineBonus([{ role: 'escalate', earlier: 2 }], cfg), 20);
  assert.equal(storylineBonus([{ role: 'escalate', earlier: 7 }], cfg), 30);
  assert.equal(storylineBonus([{ role: 'close', earlier: 1 }], cfg), 25);
  assert.equal(storylineBonus([{ role: 'escalate', earlier: 1 }, { role: 'close', earlier: 9 }], cfg), 25,
    'a beat in several storylines takes the largest');
  assert.equal(storylineBonus([{ role: 'escalate', earlier: 5, type: 'frontier' }], cfg), 0,
    'a frontier beat takes no escalation bonus');
  assert.equal(storylineBonus([{ role: 'close', earlier: 5, type: 'frontier' }], cfg), 25);
  const [w] = weighTurn([beat(9, 'compact', ['A', 'B'])], spent(),
    { weights, roles: [[{ role: 'escalate', earlier: 3 }]] });
  assert.deepEqual(w.mods, [['storyline', 30]]);
  assert.equal(w.total, 55);
});

test('a quarrel opening a rivalry outside the cast weighs 30; inside the cast it keeps 50 + 20', () => {
  const opens = [[{ role: 'open', earlier: 0 }]];
  assert.equal(weighTurn([beat(9, 'quarrel', ['A', 'B'])], spent(), { weights, roles: opens })[0].total, 30);
  assert.equal(weighTurn([beat(9, 'quarrel', ['A', 'B'])], spent(), { weights, roles: opens, cast: new Set(['B']) })[0].total, 70);
  assert.equal(weighTurn([beat(9, 'quarrel', ['A', 'B'])], spent(), { weights })[0].total, 50,
    'a quarrel that opens nothing keeps its base');
});

test('the flat callback is gone', () => {
  assert.equal(weights.modifiers.callback, undefined);
  assert.equal(weights.kinds.major_response, 15);
});

test('-15 when the kind headlined the previous turn', () => {
  const ctx = advance(spent(), [], 'quarrel', weights);
  assert.equal(weighTurn([beat(6, 'quarrel', ['A', 'B'])], ctx, { weights })[0].total, 35);
  assert.equal(advance(ctx, [], null, weights).lastHeadline, null);
});

test('double for the followed house, after the additions', () => {
  const [w] = weighTurn([beat(5, 'compact', ['A', 'B'])], spent(), { weights, cast: new Set(['A']), follow: 'B' });
  assert.equal(w.total, 90);
});

test('the bookkeeping actions take no modifier, however involved', () => {
  for (const kind of BOOKKEEPING) {
    const [w] = weighTurn([beat(5, kind, ['A'])], advance(createContext(), [], kind, weights),
      { weights, cast: new Set(['A']), follow: 'A' });
    assert.equal(w.total, 0, kind);
  }
});

test('weighing does not change the context it reads', () => {
  const ctx = createContext({ 35001: 'X' });
  const before = JSON.stringify(ctx);
  weighTurn([beat(1, 'expansion', ['A'], { owners: { 24001: 'A' } })], ctx, { weights });
  assert.equal(JSON.stringify(ctx), before);
});
