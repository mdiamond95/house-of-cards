// web/story/round.js: the year as a round of turns (Phase V2) — the parts in
// the engine's order, the three paces, what stops Auto, the strip's states, a
// house's card and sheet, and the label rule.
import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
  FLIGHT_MS, PACE_MS, PACES, autoLength, autoMs, buildRound, heirAt, holderAt, houseCard, houseLine,
  houseSheet, paceOf, placeLabels, schemeLine, schemePhrase, stopsAuto, stripOf,
} from '../../web/story/round.js';

const THRESHOLDS = { pause: 90, quiet: 40, secondary: 20 };
const BOARD = { owners: { 35001: 'A', 35002: 'B', 24001: 'C' }, ranks: { A: 1, B: 0, C: 0 }, removed: [] };

let seq = 0;
const entry = (part, kind, houses, weight, extra = {}) => {
  seq += 1;
  return {
    beat: { turn: 9, seq, kind, houses, part, ...extra }, weight, text: `${kind} text.`, alone: `${kind} alone.`,
  };
};

function round(entries, { playing = ['A', 'B', 'C'], deck = [] } = {}) {
  return buildRound({ turn: 9, entries, playing, deck, board: BOARD, thresholds: THRESHOLDS });
}

test('a pace is quiet below the quiet threshold, pause at the pause threshold, notable between', () => {
  assert.deepEqual(PACES, ['quiet', 'notable', 'pause']);
  assert.equal(paceOf(0, THRESHOLDS), 'quiet');
  assert.equal(paceOf(39, THRESHOLDS), 'quiet');
  assert.equal(paceOf(40, THRESHOLDS), 'notable');
  assert.equal(paceOf(89, THRESHOLDS), 'notable');
  assert.equal(paceOf(90, THRESHOLDS), 'pause');
  assert.equal(paceOf(140, THRESHOLDS), 'pause');
});

test('a round is the world, each house in the engine order, then the close', () => {
  const r = round([
    entry('close', 'founding', ['D'], 40, { ranks: { D: 0 }, ridings: ['12001'], owners: { 12001: 'D' } }),
    entry('C', 'expansion', ['C'], 20, { ridings: ['24002'], owners: { 24002: 'C' } }),
    entry('world', 'crisis', ['A', 'B'], 70),
    entry('A', 'scheme_begun', ['A', 'B'], 60),
    entry('B', 'era_response', ['B'], 5),
  ], { playing: ['C', 'A', 'B'] });
  assert.deepEqual(r.parts.map((p) => p.id), ['world', 'C', 'A', 'B', 'close']);
  assert.deepEqual(r.parts.map((p) => p.kind), ['world', 'house', 'house', 'house', 'close']);
  assert.equal(r.stray.length, 0);
  // Every beat lands in exactly one part.
  assert.equal(r.parts.reduce((n, p) => n + p.entries.length, 0), 5);
  // The board moves part by part: C's riding after C's turn, D's at the close.
  assert.equal(r.parts[0].board.owners['24002'], undefined);
  assert.equal(r.parts[1].board.owners['24002'], 'C');
  assert.equal(r.parts[3].board.owners['12001'], undefined);
  assert.equal(r.parts[4].board.owners['12001'], 'D');
});

test('a beat whose part is not in the round is stray, and a house with no beat still has its turn', () => {
  const r = round([entry('Z', 'expansion', ['Z'], 20), entry('A', 'invest', ['A'], 0)]);
  assert.equal(r.stray.length, 1);
  const b = r.parts.find((p) => p.id === 'B');
  assert.deepEqual(b.entries, []);
  assert.equal(b.pace, 'quiet');
  assert.equal(b.gone, false);
});

test('a house removed earlier in the year is gone when its turn comes', () => {
  const r = round([entry('A', 'fallen', ['B', 'A'], 110, { removed: ['B'] })]);
  const b = r.parts.find((p) => p.id === 'B');
  assert.equal(b.gone, true);
  assert.equal(r.parts.find((p) => p.id === 'C').gone, false);
});

test('the three paces of a house turn; the world and the close are at least notable', () => {
  const r = round([
    entry('A', 'correspondence', ['A', 'B'], 5),
    entry('B', 'scheme_begun', ['B', 'C'], 60),
    entry('C', 'contest_won', ['C', 'A'], 110),
  ], { deck: [{ name: 'Laurier Elected', magnitude: 'Significant', crisis: false, years: 1 }] });
  const pace = Object.fromEntries(r.parts.map((p) => [p.id, p.pace]));
  assert.deepEqual(pace, { world: 'notable', A: 'quiet', B: 'notable', C: 'pause', close: 'notable' });
  assert.deepEqual(r.parts[0].deck.map((e) => e.name), ['Laurier Elected']);
  // A world with nothing to announce and nothing happening is quiet.
  assert.equal(round([]).parts[0].pace, 'quiet');
});

test('Auto stops on a pause-weight turn, and on the followed house turns and those aimed at it', () => {
  const r = round([
    entry('A', 'scheme_begun', ['A', 'B'], 60),
    entry('B', 'expansion', ['B'], 45),
    entry('C', 'contest_won', ['C', 'A'], 110),
  ]);
  const stops = (follow) => r.parts.filter((p) => stopsAuto(p, { follow })).map((p) => p.id);
  assert.deepEqual(stops(null), ['C']);
  assert.deepEqual(stops('B'), ['A', 'B', 'C']);
  assert.deepEqual(stops('A'), ['A', 'C']);
});

test('Auto shows a quiet turn under half a second, holds a notable one two to three seconds', () => {
  assert.ok(PACE_MS.quiet < 500);
  assert.ok(PACE_MS.notable - FLIGHT_MS >= 2000 && PACE_MS.notable - FLIGHT_MS <= 3000);
  assert.ok(FLIGHT_MS < 1000);
  const r = round([entry('A', 'correspondence', ['A'], 5), entry('B', 'expansion', ['B'], 45)]);
  const [, a, b] = r.parts;
  assert.equal(autoMs(a), PACE_MS.quiet);
  assert.equal(autoMs(a, { skipQuiet: true }), 0);
  assert.equal(autoMs(b, { skipQuiet: true }), PACE_MS.notable);
  assert.equal(autoMs(b, { speed: 2 }), PACE_MS.notable / 2);
  const total = autoLength([r]);
  const skipped = autoLength([r], { skipQuiet: true });
  assert.ok(skipped.ms < total.ms);
  assert.equal(total.shown, r.parts.length);
  assert.equal(skipped.shown, r.parts.length - 2, 'A and C are quiet house turns');
});

test('the strip: the current chip lit, those done dimmed, those to come plain, with end caps', () => {
  const r = round([entry('B', 'expansion', ['B'], 45)]);
  const strip = stripOf(r, 2);
  assert.deepEqual(strip.map((c) => c.id), ['world', 'A', 'B', 'C', 'close']);
  assert.deepEqual(strip.map((c) => c.state), ['done', 'done', 'current', 'todo', 'todo']);
  assert.equal(strip[0].kind, 'world');
  assert.equal(strip[4].kind, 'close');
  assert.equal(strip[2].pace, 'notable');
  assert.deepEqual(stripOf(r, 0).map((c) => c.state), ['current', 'todo', 'todo', 'todo', 'todo']);
});

test('a scheme is told by name and by where it stands', () => {
  const plan = { id: 4, house: 'A', scheme: 'Claim a riding', riding: 'Guelph', target_house: 'B', begun: 8, turns_remaining: 2 };
  assert.equal(schemePhrase(plan), 'claim on Guelph');
  assert.equal(schemePhrase({ scheme: 'Dynastic match', target_house: 'B' }, (h) => `place of ${h}`), 'courtship of place of B');
  assert.equal(schemePhrase({ scheme: 'Win elevation' }), 'suit for elevation');
  assert.equal(schemePhrase({ scheme: 'Fortify' }), 'defence');
  assert.equal(schemeLine('A', 9, [plan], []), 'It is in the second of four years of its claim on Guelph.');
  assert.equal(schemeLine('A', 10, [], [plan]), 'Its claim on Guelph ended this year.');
  assert.equal(schemeLine('A', 10, [], []), 'It has no scheme afoot.');
});

test('a house card says what it did, what was done to it, its answer to the event and its scheme', () => {
  const r = round([
    entry('A', 'scheme_begun', ['A', 'B'], 60),
    entry('B', 'era_response', ['B'], 5),
    entry('B', 'expansion', ['B'], 45),
  ]);
  const b = r.parts.find((p) => p.id === 'B');
  const card = houseCard(b, r.parts.slice(0, 2), { turn: 9, plans: [], plansBefore: [] });
  assert.equal(card.did, 'expansion alone.');
  assert.equal(card.doneTo, 'scheme_begun alone.');
  assert.equal(card.era, 'era_response alone.');
  assert.equal(card.scheme, 'It has no scheme afoot.');
  const quiet = houseCard(r.parts.find((p) => p.id === 'C'), r.parts.slice(0, 3), { turn: 9, plans: null });
  assert.equal(quiet.did, 'It kept to its estates.');
  assert.equal(houseLine({ ridings: 4, rank: 'Earl', place: 3, of: 24 }), '4 ridings · Earl · 3rd of 24');
  assert.equal(houseLine({ ridings: 1, rank: 'Baron', place: 11, of: 24 }), '1 riding · Baron · 11th of 24');
});

const PEOPLE = [
  ['Frederick A', 'm', 'holder', 1, 35, 84, 1],
  ['Richard A', 'm', 'holder', 22, 61, 70, 35],
  ['Ellen A', 'f', 'holder', 40, null, 59, 61],
  ['Mary A', 'f', 'heir', 70, null, 30, null],
];

test('the holder and the heir at a turn, with ages', () => {
  assert.deepEqual(holderAt(PEOPLE, 10, 100), { name: 'Frederick A', gender: 'm', age: 59 });
  assert.deepEqual(holderAt(PEOPLE, 35, 100), { name: 'Richard A', gender: 'm', age: 44 });
  assert.equal(holderAt(PEOPLE, 99, 100).name, 'Ellen A');
  assert.equal(heirAt(PEOPLE, 10, 100), null, 'nobody named yet');
  assert.equal(heirAt(PEOPLE, 30, 100).name, 'Richard A');
  assert.equal(heirAt(PEOPLE, 50, 100).name, 'Ellen A');
  assert.equal(heirAt(PEOPLE, 80, 100).name, 'Mary A');
  assert.equal(heirAt(PEOPLE, 80, 100).age, 10);
});

test('a house sheet assembles holder, heir, rank, ridings, place, scheme, allies, rivals and last turns', () => {
  const sheet = houseSheet({
    house: 'A', turn: 50, last: 100, people: PEOPLE, rank: 'Earl', ridings: 4, prestige: 120, place: 2, of: 20,
    plans: [{ house: 'A', scheme: 'Claim a riding', riding: 'Guelph', target_house: 'B', begun: 49, turns_remaining: 1 }],
    allies: ['Halifax'], rivals: ['Guelph'],
    history: [1, 2, 3, 4, 5, 6].map((t) => ({ turn: t, year: 1866 + t, text: `t${t}` })),
    placeOf: (h) => `of ${h}`,
  });
  assert.equal(sheet.holder.name, 'Richard A');
  assert.equal(sheet.heir.name, 'Ellen A');
  assert.equal(sheet.scheme, 'It is in the second of three years of its claim on Guelph.');
  assert.equal(sheet.target, 'of B', 'a claim names its riding; its holder is the target');
  assert.deepEqual(sheet.history.map((h) => h.turn), [6, 5, 4, 3, 2], 'the last five, newest first');
  assert.deepEqual([sheet.allies, sheet.rivals], [['Halifax'], ['Guelph']]);
});

test('labels: each house once, the higher priority first, the lower dropped when there is no room', () => {
  const placed = placeLabels([
    { house: 'B', text: 'Bellechasse', x: 100, y: 100, priority: 3 },
    { house: 'A', text: 'Ascher', x: 104, y: 102, priority: 0 },
    { house: 'C', text: 'Cameron', x: 400, y: 100, priority: 2 },
    { house: 'A', text: 'Ascher', x: 300, y: 300, priority: 1 },
    { house: 'D', text: 'Denison', x: 102, y: 98, priority: 4 },
    { house: 'E', text: 'Eby', x: 101, y: 101, priority: 5 },
    { house: 'F', text: 'Foo', x: 103, y: 99, priority: 6 },
  ]);
  const names = placed.map((l) => l.house);
  assert.deepEqual(names.slice(0, 2), ['A', 'C']);
  assert.equal(names.filter((h) => h === 'A').length, 1, 'once each');
  // Five houses crowd one spot: the higher take the places round it first,
  // and what is dropped is from the lowest.
  assert.deepEqual(names.slice(0, 3), ['A', 'C', 'B']);
  const dropped = ['B', 'D', 'E', 'F'].filter((h) => !names.includes(h));
  assert.ok(dropped.length >= 1 && dropped.every((h) => ['D', 'E', 'F'].includes(h)), JSON.stringify(names));
  const overlaps = (a, b) => a.x0 < b.x1 && b.x0 < a.x1 && a.y0 < b.y1 && b.y0 < a.y1;
  for (const a of placed) for (const b of placed) if (a !== b) assert.ok(!overlaps(a, b));
  // A blocked rectangle (a badge) is kept clear: above it, and the label goes below.
  const clear = placeLabels([{ house: 'A', text: 'Ascher', x: 50, y: 50, priority: 0 }], {
    blocked: [{ x0: 0, y0: 0, x1: 200, y1: 50 }],
  });
  assert.ok(clear[0].y0 > 50);
  // The house whose turn it is is named even when badges crowd its seat, but
  // never over another name.
  const crowd = [{ x0: 0, y0: 0, x1: 400, y1: 400 }];
  assert.equal(placeLabels([{ house: 'A', text: 'Ascher', x: 200, y: 200, priority: 0 }], { blocked: crowd }).length, 0);
  const must = placeLabels([
    { house: 'A', text: 'Ascher', x: 200, y: 200, priority: 0, must: true },
    { house: 'B', text: 'Bellechasse', x: 200, y: 200, priority: 1, must: true },
  ], { blocked: crowd });
  assert.deepEqual(must.map((l) => l.house), ['A', 'B']);
  assert.ok(!(must[0].x0 < must[1].x1 && must[1].x0 < must[0].x1 && must[0].y0 < must[1].y1 && must[1].y0 < must[0].y1));
  // Nowhere to go on screen: dropped.
  assert.deepEqual(placeLabels([{ house: 'A', text: 'Ascher', x: 5, y: 5, priority: 0 }], { screen: { w: 60, h: 400 } }), []);
});
