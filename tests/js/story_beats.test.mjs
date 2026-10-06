// web/story/beats.js: the typed beat form (docs/STORY_DESIGN.md §3.1).
//     node --test tests/js/
import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
  BEAT_KINDS, BOOKKEEPING, compareText, inputFromState, baselineFromState, mergeActs, rankIndex,
  typeEvent, typeTurn,
} from '../../web/story/beats.js';

const none = () => null;
const ev = (kind, houses, delta, extra = {}) => ({ id: 1, kind, houses, delta, line: 'L', ...extra });

test('rank index follows the ladder, gendered forms included, unknown reads 0', () => {
  assert.equal(rankIndex('Baron'), 0);
  assert.equal(rankIndex('Countess'), 2);
  assert.equal(rankIndex('Duchess'), 4);
  assert.equal(rankIndex(null), 0);
  assert.equal(rankIndex('Pope'), 0);
});

test('compareText orders by code unit', () => {
  assert.deepEqual(['b', 'Z', 'a', 'Fraser 2', 'Fraser'].sort(compareText), ['Fraser', 'Fraser 2', 'Z', 'a', 'b']);
});

test('every structured event kind types to a beat kind', () => {
  const cases = [
    [ev('founding', ['A'], { season: 1 }), 'founding'],
    [ev('founding', ['P', 'C'], { nature: 'partition', parent: 'P' }), 'partition'],
    [ev('succession', ['A'], { nature: 'extinction', reason: 'no successor' }), 'removed'],
    [ev('succession', ['A'], { nature: 'disorderly', cause: 'death' }), 'succession_disorderly'],
    [ev('succession', ['A'], { nature: 'clean', cause: 'death' }), 'succession_clean'],
    [ev('transfer', ['A', 'B'], { nature: 'absorption', reason: 'absorption' }), 'riding_passes'],
    [ev('transfer', ['A', 'B'], { riding: 'X', price: 40 }), 'riding_passes'],
    [ev('transfer', ['A', 'B'], { reason: 'cession', riding: 'X' }), 'riding_passes'],
    [ev('transfer', ['A'], { reason: 'disorderly succession', riding: 'X' }), 'riding_lost'],
    [ev('challenge', ['A', 'B'], { outcome: 'won', riding: 'X' }), 'riding_passes'],
    [ev('challenge', ['A', 'B'], { outcome: 'failed' }), 'failed'],
    [ev('elevation', ['A'], { from: 'Baron', to: 'Viscount' }), 'elevation'],
    [ev('expansion', ['A'], { riding: 'X' }), 'expansion'],
    [ev('societal', ['A'], { magnitude: 'Major', response: 'Lead' }), 'major_response'],
    [ev('societal', ['A'], { magnitude: 'Minor', response: 'Lead' }), 'era_response'],
    [ev('relational', ['A', 'B'], { outcome: 'won', marker: '~' }), 'dispute_won'],
    [ev('relational', ['A', 'B'], { outcome: 'lost' }), 'failed'],
    [ev('relational', ['A', 'B'], { marker: 'Sig−', cause: 'friction' }), 'quarrel'],
    [ev('relational', ['A', 'B'], { marker: '~', ceded: 'X' }), 'reconciled'],
    [ev('incursion', ['A'], null), 'other'],
  ];
  for (const [event, kind] of cases) {
    assert.equal(typeEvent(event, none).kind, kind, JSON.stringify(event));
    assert.ok(BEAT_KINDS.includes(kind));
  }
});

test('a bare relation marker is typed by the acting house\'s own action, never by the marker', () => {
  const kin = ev('relational', ['A', 'B'], { marker: 'kin' });
  assert.equal(typeEvent(kin, () => 'Marriage alliance').kind, 'marriage');
  assert.equal(typeEvent(kin, () => 'Correspond').kind, 'correspondence');
  const compact = ev('relational', ['A', 'B'], { marker: '◉+' });
  assert.equal(typeEvent(compact, () => 'Propose compact').kind, 'compact');
  assert.equal(typeEvent(compact, () => 'Correspond').kind, 'correspondence');
  const peace = ev('relational', ['A', 'B'], { marker: '~' });
  assert.equal(typeEvent(peace, () => 'Reconcile').kind, 'reconciled');
  const grievance = ev('relational', ['A', 'B'], { marker: 'Sig−' });
  assert.equal(typeEvent(grievance, () => 'Absorb').kind, 'failed');
  assert.equal(typeEvent(grievance, () => 'Correspond').kind, 'correspondence');
  assert.equal(typeEvent(peace, none).kind, 'other');
  const heir = ev('other', ['A'], { role: 'heir' });
  assert.equal(typeEvent(heir, () => 'Name heir').kind, 'name_heir');
  assert.equal(typeEvent(ev('other', ['A'], {}), () => 'Endow').kind, 'endowment');
});

test('typeTurn moves the board: releases before acquisitions, ranks, removals', () => {
  const beats = typeTurn({
    turn: 7,
    events: [
      { id: 10, kind: 'transfer', houses: ['A', 'B'], delta: { riding: 'X', price: 40 }, line: 'A buys X from B.' },
      { id: 11, kind: 'founding', houses: ['C'], delta: {}, line: 'C is created.' },
      { id: 12, kind: 'transfer', houses: ['A', 'D'], delta: { nature: 'absorption' }, line: 'A absorbs D.' },
      { id: 13, kind: 'elevation', houses: ['A'], delta: { from: 'Baron', to: 'Earl' }, line: 'A is raised.' },
    ],
    actions: [{ house: 'A', action: 'Purchase riding', success: 1 }],
    holdings: [
      { event: 10, fed: '35001', house: 'A', change: 'acquired' },
      { event: 10, fed: '35001', house: 'B', change: 'released' },
      { event: 11, fed: '24001', house: 'C', change: 'acquired' },
      { event: 12, fed: '35002', house: 'D', change: 'released' },
      { event: 12, fed: '35002', house: 'A', change: 'acquired' },
    ],
    ranks: { C: 'Viscountess' },
  });
  assert.deepEqual(beats.map((b) => b.kind), ['riding_passes', 'founding', 'riding_passes', 'elevation']);
  assert.deepEqual(beats[0], {
    turn: 7, seq: 0, kind: 'riding_passes', houses: ['A', 'B'], ridings: ['35001'],
    outcome: 'purchase', line: 'A buys X from B.', owners: { 35001: 'A' },
  });
  assert.deepEqual(beats[1].ranks, { C: 1 });
  assert.deepEqual(beats[2].removed, ['D']);
  assert.deepEqual(beats[3].ranks, { A: 2 });
});

test('actions that left no event become beats; an offending letter is not counted twice', () => {
  const beats = typeTurn({
    turn: 3,
    events: [{ id: 1, kind: 'relational', houses: ['B', 'C'], delta: { marker: 'Sig−', cause: 'correspondence' }, line: 'offence' }],
    actions: [
      { house: 'A', action: 'Invest', success: 1 },
      { house: 'B', action: 'Correspond', success: 0 },
      { house: 'C', action: 'Correspond', success: 0 },
      { house: 'D', action: 'Expand', success: 0 },
      { house: 'E', action: 'Dispute', success: 0 },
      { house: 'F', action: 'Cultivate influence', success: 0 },
      { house: 'G', action: 'Consolidate (rest)', success: 1 },
      { house: 'H', action: 'Name heir', success: 1 },
    ],
    holdings: [],
    ranks: {},
  });
  assert.deepEqual(beats.map((b) => [b.kind, b.houses[0], b.outcome]), [
    ['quarrel', 'B', 'correspondence'],
    ['invest', 'A', 'success'],
    ['correspondence', 'C', 'failed'],
    ['failed', 'D', 'Expand'],
    ['cultivate', 'F', 'failed'],
    ['consolidate', 'G', 'success'],
  ]);
  for (const kind of BOOKKEEPING) assert.ok(BEAT_KINDS.includes(kind));
});

function fakeState() {
  const houses = new Map([
    ['A', { house: 'A', rank: 'Baron', status: 'active' }],
    ['B', { house: 'B', rank: 'Earl', status: 'active' }],
    ['Z', { house: 'Z', rank: 'Viscount', status: 'removed' }],
  ]);
  return {
    houses,
    events: [
      { id: 2, kind: 'expansion', houses: ['A'], mechanicalDelta: { season: 5, riding: 'Y' }, narrative: 'Season 5 · A takes Y.', title: 'A takes Y' },
      { id: 1, kind: 'founding', houses: ['B'], mechanicalDelta: { season: 5 }, narrative: null, title: 'B founded' },
      { id: 3, kind: 'expansion', houses: ['A'], mechanicalDelta: { season: 4 }, narrative: 'old', title: 'old' },
    ],
    holdings: [
      { id: 1, house: 'A', fedId: '35001', acquiredEventId: 0, releasedEventId: null },
      { id: 2, house: 'B', fedId: '35003', acquiredEventId: 1, releasedEventId: null },
      { id: 3, house: 'A', fedId: '35002', acquiredEventId: 2, releasedEventId: null },
    ],
    houseActions: [
      { id: 2, seasonNo: 5, house: 'A', action: 'Expand', success: 1 },
      { id: 1, seasonNo: 4, house: 'A', action: 'Invest', success: 1 },
    ],
  };
}

test('inputFromState reads one season from the engine\'s tables, in id order', () => {
  const input = inputFromState(fakeState(), 5);
  assert.deepEqual(input.events.map((e) => e.id), [1, 2]);
  assert.equal(input.events[0].line, 'B founded', 'a title stands in for a missing line');
  assert.deepEqual(input.actions, [{ house: 'A', action: 'Expand', success: 1 }]);
  assert.deepEqual(input.holdings, [
    { event: 1, fed: '35003', house: 'B', change: 'acquired' },
    { event: 2, fed: '35002', house: 'A', change: 'acquired' },
  ]);
  assert.deepEqual(input.ranks, { B: 'Earl' });
  assert.deepEqual(typeTurn(input).map((b) => b.kind), ['founding', 'expansion']);
});

test('baselineFromState is the board as the engine holds it', () => {
  assert.deepEqual(baselineFromState(fakeState()), {
    owners: { 35001: 'A', 35003: 'B', 35002: 'A' },
    ranks: { A: 0, B: 2, Z: 1 },
    removed: ['Z'],
  });
});

test('mergeActs: one act, one beat, carrying every part', () => {
  const b = (seq, kind, houses, extra = {}) => ({ turn: 9, seq, kind, houses, ...extra });
  const merged = mergeActs([
    b(0, 'riding_passes', ['A', 'B'], { outcome: 'cession', ridings: ['24001'], owners: { 24001: 'B' }, line: 'x' }),
    b(1, 'quarrel', ['C', 'D'], { outcome: 'friction', line: 'y' }),
    b(2, 'reconciled', ['A', 'B'], { outcome: 'cession', line: 'z' }),
    b(3, 'partition', ['P', 'Q'], { owners: { 35001: 'Q' }, ranks: { Q: 0 }, ridings: ['35001'] }),
    b(4, 'succession_clean', ['P'], { outcome: 'death' }),
    b(5, 'succession_disorderly', ['R'], { outcome: 'death' }),
    b(6, 'quarrel', ['R', 'S'], { outcome: 'disorderly succession' }),
    b(7, 'riding_lost', ['R'], { outcome: 'disorderly succession', ridings: ['35002'], owners: { 35002: null } }),
    b(8, 'succession_clean', ['T'], { outcome: 'death' }),
    b(9, 'removed', ['T'], { outcome: 'cohesion collapse', removed: ['T'] }),
    b(10, 'quarrel', ['U', 'V'], { outcome: 'contested expansion' }),
    b(11, 'expansion', ['V'], { ridings: ['35003'], owners: { 35003: 'V' } }),
    b(12, 'invest', ['W'], { outcome: 'success' }),
  ]);
  assert.deepEqual(merged.map((x) => [x.kind, x.merge || null]), [
    ['riding_passes', 'cession'], ['quarrel', null], ['partition', 'partition'],
    ['succession_disorderly', 'disorderly'], ['removed', 'collapse'], ['quarrel', 'contest'], ['invest', null],
  ]);
  assert.deepEqual(merged[0].houses, ['A', 'B']);
  assert.deepEqual(merged[0].owners, { 24001: 'B' });
  assert.equal(merged[0].parts.length, 2);
  assert.deepEqual(merged[3].houses, ['R', 'S']);
  assert.deepEqual(merged[3].owners, { 35002: null });
  assert.deepEqual(merged[4].removed, ['T']);
  assert.deepEqual(merged[5].owners, { 35003: 'V' });
  const lost = mergeActs([b(0, 'quarrel', ['U', 'V'], { outcome: 'contested expansion' }), b(1, 'failed', ['U'], { outcome: 'Expand' })]);
  assert.deepEqual(lost.map((x) => x.merge), ['contest']);
  const alone = [b(0, 'riding_passes', ['A', 'B'], { outcome: 'cession' })];
  assert.deepEqual(mergeActs(alone), alone, 'a part with no partner passes through');
});
