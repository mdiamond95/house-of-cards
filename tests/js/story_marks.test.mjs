// web/story/marks.js: a dispatch on the map — which beat becomes which mark,
// where it sits, what the camera frames, the cap, and a quiet year.
import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
  MARK_CAP, MARK_TYPES, MarkContext, SCHEME_LABELS, chipsFor, markOf, marksFor, schemeArrows, seatsAt,
} from '../../web/story/marks.js';

const SEATS = { A: [[0, '35001']], B: [[0, '35002']], C: [[3, '24001'], [7, '24003']], D: [[0, '12001'], [5, null]] };

function ctx(extra = {}) {
  return new MarkContext({
    seats: seatsAt(SEATS, 5),
    seatsBefore: seatsAt(SEATS, 4),
    ridingIds: { Halifax: '12005', Outremont: '24010' },
    standing: ['A', 'B', 'C'],
    claimSchemes: ['Claim a riding', 'Counter-claim'],
    cast: new Set(['A', 'B']),
    ...extra,
  });
}

const told = (beat, weight = 50) => ({ beat: { turn: 5, seq: 0, ...beat }, weight, text: 'T', alone: 'Alone.' });

test('a seat is read from the history at a turn', () => {
  assert.deepEqual([...seatsAt(SEATS, 0)], [['A', '35001'], ['B', '35002'], ['D', '12001']]);
  assert.equal(seatsAt(SEATS, 3).get('C'), '24001');
  assert.equal(seatsAt(SEATS, 7).get('C'), '24003');
  assert.equal(seatsAt(SEATS, 5).has('D'), false, 'a house with no riding has no seat');
});

test('every beat kind of the vocabulary becomes its mark', () => {
  const c = ctx();
  const kinds = [
    [{ kind: 'expansion', houses: ['A'], ridings: ['35009'] }, 'transfer', 'expand'],
    [{ kind: 'riding_passes', houses: ['A', 'B'], ridings: ['35002'] }, 'transfer', 'transfer'],
    [{ kind: 'founding', houses: ['C'], ridings: ['24001'] }, 'seat', 'found'],
    [{ kind: 'succession_clean', houses: ['A'] }, 'seat', 'succeed'],
    [{ kind: 'elevation', houses: ['B'] }, 'seat', 'elevate'],
    [{ kind: 'marriage', houses: ['A', 'B'] }, 'bond', 'match'],
    [{ kind: 'compact', houses: ['A', 'B'] }, 'bond', 'bond'],
    [{ kind: 'quarrel', houses: ['A', 'B'] }, 'strife', 'strife'],
    [{ kind: 'dispute_won', houses: ['A', 'B'] }, 'strife', 'strife'],
    [{ kind: 'accession', houses: [], ridings: ['46001', '46002'] }, 'accession', 'open'],
    [{ kind: 'rush', houses: [], ridings: ['48001', '48002'] }, 'accession', 'open'],
  ];
  for (const [beat, type, glyph] of kinds) {
    const m = markOf(told(beat), c);
    assert.equal(m.type, type, beat.kind);
    assert.equal(m.glyph, glyph, beat.kind);
    assert.ok(MARK_TYPES.includes(m.type));
  }
});

test('land_rush: a rush is drawn on the province\'s open land, labelled as a rush', () => {
  const m = markOf(told({ kind: 'rush', houses: [], ridings: ['48001', '48002'] }), ctx());
  assert.equal(m.label, 'land rush');
  assert.deepEqual(m.ground, ['48001', '48002']);
});

test('a bond and a strife are lines between the two seats, in two styles', () => {
  const bond = markOf(told({ kind: 'marriage', houses: ['A', 'B'] }), ctx());
  const strife = markOf(told({ kind: 'quarrel', houses: ['A', 'B'] }), ctx());
  for (const m of [bond, strife]) {
    assert.equal(m.from, '35001');
    assert.equal(m.to, '35002');
    assert.deepEqual(m.ground, ['35001', '35002'], 'no ridings named: the seats of its houses');
  }
  assert.notEqual(bond.type, strife.type);
});

test('a claim runs from the claimant\'s seat to the riding, and says how it came out', () => {
  const plans = [{ id: 9, house: 'A', scheme: 'Claim a riding', target_house: 'B', riding: 'Halifax', turns_remaining: 2 }];
  const begun = markOf(told({ kind: 'scheme_begun', houses: ['A', 'B'], outcome: 'Claim a riding', scheme: 9 }), ctx({ plans }));
  assert.equal(begun.type, 'claim');
  assert.equal(begun.from, '35001');
  assert.equal(begun.to, '12005', 'the riding the scheme names, by its name');
  assert.equal(begun.result, null);
  assert.deepEqual(begun.ground, ['12005'], 'its scheme\'s target when it names no riding itself');

  const won = markOf(told({ kind: 'contest_won', houses: ['A', 'B'], ridings: ['12005'], scheme: 9 }),
    ctx({ plansBefore: plans, owners: { 12005: 'A' } }));
  assert.equal(won.result, 'taken');
  assert.equal(won.glyph, 'taken');
  const held = markOf(told({ kind: 'contest_lost', houses: ['A', 'B'], scheme: 9 }), ctx({ plansBefore: plans }));
  assert.equal(held.result, 'held');
  assert.equal(held.to, '12005', 'a claim held is found by its scheme, which has ended');
});

test('a defence draws the threat from the claimant to the defended riding', () => {
  const plans = [{ id: 4, house: 'B', scheme: 'Fortify', target_house: 'A', riding: 'Outremont', turns_remaining: 1 }];
  const m = markOf(told({ kind: 'scheme_answered', houses: ['B', 'A'], outcome: 'Fortify', scheme: 4 }), ctx({ plans }));
  assert.equal(m.type, 'claim');
  assert.equal(m.from, '35001');
  assert.equal(m.to, '24010');
  assert.equal(m.label, SCHEME_LABELS.Fortify);
});

test('a fall is marked at the seat the house had', () => {
  const m = markOf(told({ kind: 'removed', houses: ['D'], removed: ['D'] }), ctx());
  assert.equal(m.type, 'seat');
  assert.equal(m.glyph, 'fall');
  assert.equal(m.at, '12001');
});

test('a crisis marks every standing house\'s seat by its camp and frames the whole table', () => {
  const m = markOf(told({ kind: 'crisis', houses: ['A', 'B'], world: { event: 'War', lead: ['A'], resist: ['B'], carried: 'lead' } }), ctx());
  assert.equal(m.type, 'crisis');
  assert.deepEqual(m.camps.lead, ['35001']);
  assert.deepEqual(m.camps.resist, ['35002']);
  assert.deepEqual(m.camps.aside, ['24001']);
  // Phase V2: each camp's houses, for the page to tint their holdings.
  assert.deepEqual(m.campHouses, { lead: ['A'], resist: ['B'], aside: ['C'] });
  assert.equal(m.groundKind, 'table');
  assert.deepEqual(m.ground, ['35001', '35002', '24001']);
});

test('a beat with no place is a banner, not a mark', () => {
  assert.equal(markOf(told({ kind: 'event_continues', houses: [], world: { event: 'War', year_of: 2, years: 5 } }), ctx()), null);
  const layout = marksFor({ quiet: false, headline: { ...told({ kind: 'reckoning', houses: [] }, 100), text: 'The reckoning.' } }, ctx());
  assert.equal(layout.banner, 'The reckoning.');
  assert.deepEqual(layout.marks, []);
  assert.deepEqual(layout.frame, []);
});

test('the headline and at most five others are marked, by weight; the rest are counted', () => {
  const others = [];
  for (let i = 0; i < 9; i += 1) others.push(told({ kind: 'expansion', houses: ['A'], ridings: [`350${10 + i}`], seq: i + 1 }, 20 + i));
  const d = {
    quiet: false,
    headline: told({ kind: 'riding_passes', houses: ['A', 'B'], ridings: ['35002'] }, 90),
    related: [], secondary: others.slice(0, 3), others: others.slice(3),
  };
  const layout = marksFor(d, ctx());
  assert.equal(MARK_CAP, 5);
  assert.equal(layout.marks.length, 1 + MARK_CAP);
  assert.equal(layout.more, 9 - MARK_CAP);
  assert.equal(layout.marks[0].headline, true);
  assert.deepEqual(layout.marks.slice(1).map((m) => m.weight), [28, 27, 26, 25, 24], 'the heaviest, heaviest first');
  assert.deepEqual(layout.frame, ['35002'], 'the camera frames the ridings the headline names');
  assert.deepEqual(layout.marks.map((m) => m.id), ['m1', 'm2', 'm3', 'm4', 'm5', 'm6']);
});

test('one crisis\'s camps a turn: a second crisis is counted, not drawn', () => {
  const crisis = (event) => told({ kind: 'crisis', houses: ['A'], world: { event, lead: ['A'], resist: [], carried: 'lead' } }, 70);
  const layout = marksFor({ quiet: false, headline: crisis('One'), related: [], secondary: [crisis('Two')], others: [] }, ctx());
  assert.equal(layout.marks.length, 1);
  assert.equal(layout.more, 1);
});

test('a quiet year shows no marks and no scheme arrows, only its chip', () => {
  const plans = [{ id: 1, house: 'A', scheme: 'Open the frontier', target_house: null, riding: 'Halifax', turns_remaining: 1 }];
  const layout = marksFor({ quiet: true, headline: null, running: [] }, ctx({ plans }));
  assert.deepEqual(layout.marks, []);
  assert.deepEqual(layout.schemes, []);
  assert.deepEqual(layout.chips, [{ kind: 'quiet', text: 'a quiet year' }]);
});

test('an event still running is a standing chip', () => {
  assert.deepEqual(chipsFor({ running: [{ event: 'The Great War', year: 3, years: 5 }] }),
    [{ kind: 'event', text: 'The Great War, year 3 of 5' }]);
});

test('schemes afoot of the cast are faint arrows; none twice, none without a target', () => {
  const plans = [
    { id: 1, house: 'A', scheme: 'Open the frontier', target_house: null, riding: 'Halifax', turns_remaining: 1 },
    { id: 2, house: 'B', scheme: 'Break a rival', target_house: 'A', riding: null, turns_remaining: 2 },
    { id: 3, house: 'C', scheme: 'Dynastic match', target_house: 'A', riding: null, turns_remaining: 2 },
    { id: 4, house: 'A', scheme: 'Win elevation', target_house: null, riding: null, turns_remaining: 2 },
  ];
  const arrows = schemeArrows(ctx({ plans }));
  assert.deepEqual(arrows.map((a) => [a.id, a.from, a.to]), [[1, '35001', '12005'], [2, '35002', '35001']],
    'C is outside the cast; elevation has no target');
  assert.deepEqual(schemeArrows(ctx({ plans, follow: 'C' })).map((a) => a.id), [3, 1, 2], 'the followed house first');
  assert.deepEqual(schemeArrows(ctx({ plans }), new Set([1])).map((a) => a.id), [2], 'a scheme already marked');
});

test('the camera frames a headline\'s ridings, else its scheme\'s target, else its houses\' seats', () => {
  const ridings = markOf(told({ kind: 'expansion', houses: ['A'], ridings: ['35009'] }), ctx());
  assert.deepEqual([ridings.ground, ridings.groundKind], [['35009'], 'ridings']);
  const plans = [{ id: 7, house: 'A', scheme: 'Open the frontier', target_house: null, riding: 'Halifax', turns_remaining: 2 }];
  const target = markOf(told({ kind: 'scheme_begun', houses: ['A'], outcome: 'Open the frontier', scheme: 7 }), ctx({ plans }));
  assert.deepEqual([target.ground, target.groundKind], [['12005'], 'target']);
  const seats = markOf(told({ kind: 'elevation', houses: ['B'] }), ctx());
  assert.deepEqual([seats.ground, seats.groundKind], [['35002'], 'seats']);
});
