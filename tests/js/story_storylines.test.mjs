// web/story/storylines.js: storylines from typed beats alone (§3.4).
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

import { Storylines, storylineName } from '../../web/story/storylines.js';
import { applyBeats, table } from '../../web/story/standings.js';

const weights = JSON.parse(readFileSync(new URL('../../web/story/weights.json', import.meta.url), 'utf8'));
let seq = 0;
const beat = (turn, kind, houses, extra = {}) => ({ turn, seq: seq++, kind, houses, ...extra });

// Steps a tracker the way dispatch.js does, keeping the board alongside.
function harness({ owners = {}, ranks = {}, totals = { 35: 4, 24: 2 }, held = [], watch = false } = {}) {
  const lines = new Storylines({ weights, provinceTotals: totals, held, watch });
  let board = { owners, ranks, removed: [] };
  return {
    lines,
    step(turn, beats) {
      const tableBefore = table(board, weights);
      const cast = new Set(tableBefore.slice(0, weights.cast_size).map((r) => r.house));
      const boardAfter = applyBeats(board, beats);
      const out = lines.step(turn, beats, { cast, boardBefore: board, boardAfter, tableBefore, tableAfter: table(boardAfter, weights) });
      board = boardAfter;
      return out;
    },
  };
}

test('a rivalry opens on a quarrel, escalates on shared beats and closes on a reconciliation', () => {
  const h = harness({ ranks: { A: 0, B: 0 } });
  const opened = h.step(1, [beat(1, 'quarrel', ['B', 'A'], { outcome: 'friction' })]);
  assert.deepEqual(opened.roles, [[{ id: 's1', role: 'open', earlier: 0, type: 'rivalry' }]]);
  const s = h.lines.of('s1');
  assert.deepEqual([s.type, s.houses, s.opened, s.state], ['rivalry', ['A', 'B'], 1, 'rising']);
  h.step(2, [beat(2, 'failed', ['A', 'B'], { outcome: 'Dispute' }), beat(2, 'correspondence', ['A', 'B'])]);
  assert.equal(s.beats.length, 2, 'a letter is not a storyline beat');
  const closing = h.step(3, [beat(3, 'reconciled', ['A', 'B'])]);
  assert.deepEqual(closing.roles[0], [{ id: 's1', role: 'close', earlier: 2, type: 'rivalry' }]);
  assert.deepEqual([s.state, s.outcome, s.closed], ['closed', 'reconciled', 3]);
  assert.equal(storylineName(s, (x) => `Place ${x}`), 'The Place A–Place B rivalry');
});

test('a storyline reaches its climax at the fourth beat, and lapses after fifteen quiet turns', () => {
  const h = harness({ ranks: { A: 0, B: 0 } });
  h.step(1, [beat(1, 'quarrel', ['A', 'B'], { outcome: 'friction' })]);
  h.step(2, [beat(2, 'quarrel', ['A', 'B'], { outcome: 'friction' })]);
  h.step(3, [beat(3, 'failed', ['A', 'B'], { outcome: 'Dispute' })]);
  const climax = h.step(4, [beat(4, 'quarrel', ['A', 'B'], { outcome: 'friction' })]);
  assert.deepEqual(climax.changes, [{ id: 's1', change: 'climax' }]);
  assert.equal(h.step(18, []).changes.length, 0);
  const lapse = h.step(19, []);
  assert.deepEqual(lapse.changes, [{ id: 's1', change: 'closed' }]);
  assert.equal(h.lines.of('s1').outcome, 'lapsed');
});

test('a removal closes every storyline its house is in; a frontier only loses the house', () => {
  const h = harness({ ranks: { A: 0, B: 0, C: 0 }, owners: { 35001: 'A' }, held: ['35'] });
  h.step(1, [beat(1, 'quarrel', ['A', 'B'], { outcome: 'friction' })]);
  h.step(2, [beat(2, 'expansion', ['C'], { owners: { 24001: 'C' } }), beat(2, 'expansion', ['A'], { owners: { 24002: 'A' } })]);
  const frontier = h.lines.all.find((s) => s.type === 'frontier');
  assert.equal(frontier.state, 'closed', 'Quebec is half claimed at two of two');
  const g = harness({ ranks: { A: 0, B: 0, C: 0 }, totals: { 24: 10 } });
  g.step(1, [beat(1, 'quarrel', ['A', 'B'], { outcome: 'friction' })]);
  g.step(2, [beat(2, 'expansion', ['A'], { owners: { 24001: 'A' } }), beat(2, 'expansion', ['C'], { owners: { 24002: 'C' } })]);
  g.step(3, [beat(3, 'removed', ['A'], { owners: { 24001: null }, removed: ['A'] })]);
  const rivalry = g.lines.all.find((s) => s.type === 'rivalry');
  const quebec = g.lines.all.find((s) => s.type === 'frontier');
  assert.deepEqual([rivalry.state, rivalry.outcome], ['closed', 'A removed']);
  assert.deepEqual([quebec.state, quebec.houses], ['rising', ['C']]);
});

test('a union between cast houses closes on a falling-out, which opens a rivalry', () => {
  const h = harness({ ranks: { A: 1, B: 1 } });
  h.step(1, [beat(1, 'marriage', ['A', 'B'])]);
  h.step(2, [beat(2, 'quarrel', ['A', 'B'], { outcome: 'friction' })]);
  const [union, rivalry] = h.lines.all;
  assert.deepEqual([union.type, union.state, union.outcome], ['union', 'closed', 'a falling-out']);
  assert.deepEqual([rivalry.type, rivalry.state], ['rivalry', 'rising']);
  const outside = harness({ ranks: {} });
  outside.step(1, [beat(1, 'marriage', ['A', 'B'])]);
  assert.equal(outside.lines.all.length, 0, 'a union is only between houses of the cast');
});

test('a succession question opens on a disorderly succession and closes when an heir is named', () => {
  const h = harness({ ranks: { A: 0 } });
  h.step(1, [beat(1, 'succession_disorderly', ['A'], { outcome: 'death' })]);
  h.step(2, [beat(2, 'riding_lost', ['A'], { outcome: 'debt' })]);
  h.step(3, [beat(3, 'name_heir', ['A'], { outcome: 'heir' })]);
  const s = h.lines.all.find((x) => x.type === 'succession');
  assert.deepEqual([s.beats.length, s.state, s.outcome], [3, 'closed', 'an heir named']);
});

test('a rise opens on entering the top eight below first and closes on reaching first', () => {
  const h = harness({ ranks: { A: 1 }, owners: { 35001: 'A' } });
  h.step(1, [beat(1, 'founding', ['B'], { owners: { 35002: 'B' }, ranks: { B: 0 } })]);
  const rise = h.lines.all.find((s) => s.type === 'rise');
  assert.deepEqual([rise.key, rise.beats.length], ['B', 1]);
  h.step(2, [beat(2, 'elevation', ['B'], { ranks: { B: 2 } })]);
  assert.deepEqual([rise.state, rise.outcome], ['closed', 'reached first']);
});

test('a decline opens when a cast house loses a riding, and closes when it recovers', () => {
  const h = harness({ ranks: { A: 0, B: 0 }, owners: { 35001: 'A', 35002: 'A', 35003: 'B' }, held: ['35'] });
  h.step(1, [beat(1, 'riding_passes', ['A', 'B'], { owners: { 35002: 'B' } })]);
  const decline = h.lines.all.find((s) => s.type === 'decline');
  assert.deepEqual([decline.key, decline.state, decline.mark], ['A', 'rising', 20]);
  h.step(2, [beat(2, 'expansion', ['A'], { owners: { 35004: 'A' } })]);
  assert.deepEqual([decline.state, decline.outcome], ['closed', 'recovered']);
});

test('a cadet inherits nothing, but the partition beat belongs to its parent\'s storylines', () => {
  const h = harness({ ranks: { P: 2, X: 0 }, owners: { 35001: 'P', 35002: 'P', 24001: 'P' }, totals: { 35: 10, 24: 10 }, held: ['35'] });
  h.step(1, [beat(1, 'expansion', ['P'], { owners: { 24002: 'P' } })]);
  h.step(2, [beat(2, 'quarrel', ['P', 'X'], { outcome: 'friction' })]);
  h.step(3, [beat(3, 'partition', ['P', 'C'], { owners: { 24001: 'C', 24002: 'C' }, ranks: { C: 0 } })]);
  const quebec = h.lines.all.find((s) => s.type === 'frontier');
  assert.ok(!quebec.beats.some((e) => e.beat.kind === 'partition'), 'ridings passing to a cadet are no frontier beat');
  assert.ok(!quebec.houses.includes('C'), 'the cadet does not join it');
  const decline = h.lines.all.find((s) => s.type === 'decline' && s.key === 'P');
  assert.ok(decline.beats.some((e) => e.beat.kind === 'partition'), 'the partition belongs to the parent\'s decline');
  const rivalry = h.lines.all.find((s) => s.type === 'rivalry');
  assert.ok(!rivalry.houses.includes('C'));
});

test('a riding passing between houses is never a frontier beat', () => {
  const h = harness({ ranks: { A: 0, B: 0 }, totals: { 24: 10 } });
  h.step(1, [beat(1, 'expansion', ['A'], { owners: { 24001: 'A' } })]);
  const quebec = h.lines.all.find((s) => s.type === 'frontier');
  h.step(2, [beat(2, 'riding_passes', ['A', 'B'], { owners: { 24001: 'B' } })]);
  assert.equal(quebec.beats.length, 1);
  assert.ok(!quebec.houses.includes('B'));
  h.step(3, [beat(3, 'expansion', ['B'], { owners: { 24002: 'B' } })]);
  assert.equal(quebec.beats.length, 2);
});

test('with the succession watch, a question opens at sixty with no heir and closes when an heir comes of age', () => {
  const h = harness({ ranks: { A: 0 }, watch: true });
  h.step(1, [beat(1, 'heir_wanted', ['A'])]);
  const s = h.lines.all.find((x) => x.type === 'succession');
  assert.deepEqual([s.key, s.state], ['A', 'rising']);
  h.step(2, [beat(2, 'name_heir', ['A'], { outcome: 'heir' })]);
  assert.equal(s.state, 'rising', 'naming an heir is a step, not the answer, when the watch is recorded');
  h.step(9, [beat(9, 'heir_of_age', ['A'])]);
  assert.deepEqual([s.state, s.outcome, s.beats.length], ['closed', 'an heir came of age', 3]);
  const old = harness({ ranks: { A: 0 } });
  old.step(1, [beat(1, 'succession_disorderly', ['A'], { outcome: 'death' })]);
  old.step(2, [beat(2, 'name_heir', ['A'], { outcome: 'heir' })]);
  assert.equal(old.lines.all[0].outcome, 'an heir named', 'a game without the watch still closes on naming');
});

test('rules 1.0: a claim opens the pair\'s rivalry, and a contest, a cession under it or a fall closes it', () => {
  const h = harness({ owners: { 35001: 'B', 35002: 'B' }, ranks: { A: 0, B: 0 } });
  h.step(1, [beat(1, 'scheme_begun', ['A', 'B'], { outcome: 'Claim a riding', scheme: 1 })]);
  const s = h.lines.all[0];
  assert.deepEqual([s.type, s.houses], ['rivalry', ['A', 'B']]);
  h.step(2, [beat(2, 'scheme_step', ['A', 'B'], { outcome: 'Claim a riding', scheme: 1 })]);
  assert.equal(s.beats.length, 1, 'a preparation step is ledger-only');
  h.step(3, [beat(3, 'scheme_answered', ['B', 'A'], { outcome: 'Fortify', scheme: 2 }),
    beat(3, 'ally_joins', ['C', 'A', 'B'], { outcome: 'attacker' })]);
  assert.equal(s.beats.length, 3, 'an answer and an ally escalate it');
  h.step(4, [beat(4, 'contest_lost', ['A', 'B'], { outcome: 'held', scheme: 1 })]);
  assert.deepEqual([s.state, s.outcome], ['closed', 'held in a contest']);
  // Not every scheme between two houses opens a rivalry: a match does not.
  h.step(5, [beat(5, 'scheme_begun', ['A', 'B'], { outcome: 'Dynastic match', scheme: 3 })]);
  assert.equal(h.lines.open.filter((x) => x.type === 'rivalry').length, 0);
  h.step(6, [beat(6, 'scheme_answered', ['B', 'A'], { outcome: 'Counter-claim', scheme: 4 })]);
  const counter = h.lines.open.find((x) => x.type === 'rivalry');
  h.step(7, [beat(7, 'riding_passes', ['A', 'B'], { outcome: 'cession under claim', ridings: ['35009'], owners: {} })]);
  assert.equal(counter.outcome, 'ceded under a claim');
  h.step(8, [beat(8, 'scheme_begun', ['A', 'B'], { outcome: 'Claim a riding', scheme: 5 })]);
  const last = h.lines.open.find((x) => x.type === 'rivalry');
  const won = beat(9, 'contest_won', ['A', 'B'], { outcome: 'won', scheme: 5 });
  const fell = beat(9, 'fallen', ['B', 'A'], { outcome: 'A', removed: ['B'] });
  h.step(9, [{ ...fell, houses: ['A', 'B'], merge: 'claim', parts: [won, fell] }]);
  assert.equal(last.outcome, 'won in a contest');
});
