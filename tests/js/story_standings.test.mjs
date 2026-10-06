// web/story/standings.js: provisional standings folded from beats (§3.3).
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

import { applyBeats, emptyBoard, movement, table } from '../../web/story/standings.js';

const weights = JSON.parse(readFileSync(new URL('../../web/story/weights.json', import.meta.url), 'utf8'));

test('a board folds beats: owners, ranks, removals', () => {
  const board = applyBeats(emptyBoard(), [
    { owners: { 1: 'A', 2: 'A', 3: 'B' }, ranks: { A: 0, B: 1 } },
    { owners: { 2: 'B' } },
    { owners: { 1: null }, removed: ['A'] },
  ]);
  assert.deepEqual(board, { owners: { 2: 'B', 3: 'B' }, ranks: { A: 0, B: 1 }, removed: ['A'] });
});

test('applyBeats leaves its argument alone', () => {
  const board = emptyBoard();
  applyBeats(board, [{ owners: { 1: 'A' }, ranks: { A: 0 } }]);
  assert.deepEqual(board, emptyBoard());
});

test('standing is 10 x ridings + 20 x rank index; ties by ridings then name; removed houses gone', () => {
  const rows = table({
    owners: { 1: 'A', 2: 'A', 3: 'B', 4: 'C', 5: 'D' },
    ranks: { A: 0, B: 1, C: 0, D: 1, E: 2, Gone: 4 },
    removed: ['Gone'],
  }, weights);
  assert.deepEqual(rows.map((r) => [r.house, r.score, r.place]),
    [['E', 40, 1], ['B', 30, 2], ['D', 30, 3], ['A', 20, 4], ['C', 10, 5]]);
});

test('movement: up, down, and new to the top eight', () => {
  const before = table({ owners: { 1: 'A', 2: 'A', 3: 'C' }, ranks: { A: 0, B: 0, C: 0 }, removed: [] }, weights);
  const after = table({ owners: { 1: 'B', 2: 'B', 3: 'A' }, ranks: { A: 0, B: 0, C: 0, D: 3 }, removed: [] }, weights);
  const moves = Object.fromEntries(movement(before, after, weights).map((r) => [r.house, [r.move, r.was]]));
  assert.deepEqual(moves, { D: ['new', null], B: ['up', 3], A: ['down', 1], C: ['down', 2] });
  assert.ok(movement(after, after, weights).every((r) => r.move === 'same'));
});

test('only the top eight are shown', () => {
  const ranks = Object.fromEntries('ABCDEFGHIJ'.split('').map((h) => [h, 0]));
  const rows = table({ owners: {}, ranks, removed: [] }, weights);
  assert.equal(movement(rows, rows, weights).length, 8);
});

test('where the record carries prestige, it is the standing', () => {
  const board = { owners: { 1: 'A', 2: 'A', 3: 'B' }, ranks: { A: 0, B: 0, C: 0 }, removed: [] };
  const rows = table(board, weights, { A: 30, B: 90 });
  assert.deepEqual(rows.map((r) => [r.house, r.score]), [['B', 90], ['A', 30], ['C', 0]]);
});
