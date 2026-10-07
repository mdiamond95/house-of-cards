// web/story/round.js: the year as a round of turns (Phase V2) — the parts in
// the engine's order, the four paces of Phase V3 (one fixture per kind the
// weights table lists), what stops Auto, the strip's states, a house's card
// (its tags, its camp, its sentences from the verb) and sheet, the year's count
// line, and the label rule.
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
  PACES, autoLength, autoMs, buildRound, countLine, entryPace, heirAt, holderAt, houseCard, houseLine,
  houseSheet, paceRank, placeLabels, schemeLine, schemePhrase, stopsAuto, stripOf, yearCounts,
} from '../../web/story/round.js';
import { houseStyle, verbFirst } from '../../web/story/text.js';

const WEIGHTS = JSON.parse(readFileSync(new URL('../../web/story/weights.json', import.meta.url), 'utf8'));
const THRESHOLDS = WEIGHTS.thresholds;
const PACE = WEIGHTS.pace;
const HOLD = PACE.hold_ms;
const BOARD = { owners: { 35001: 'A', 35002: 'B', 24001: 'C' }, ranks: { A: 1, B: 0, C: 0 }, removed: [] };

let seq = 0;
const entry = (part, kind, houses, weight, extra = {}) => {
  seq += 1;
  return {
    beat: { turn: 9, seq, kind, houses, part, ...extra }, weight, text: `${kind} text.`, alone: `${kind} alone.`,
  };
};

function round(entries, { playing = ['A', 'B', 'C'], deck = [], ...options } = {}) {
  return buildRound({
    turn: 9, entries, playing, deck, board: BOARD, thresholds: THRESHOLDS, pace: PACE, ...options,
  });
}

// The kinds each pace is for, as the director listed them (Phase V3). A house
// turn of one beat of the kind, at a weight far below any threshold.
const FIXTURES = {
  quiet: ['invest', 'cultivate', 'consolidate', 'bide', 'scheme_step', 'scheme_resolved', 'correspondence',
    'era_response', 'major_response', 'failed', 'endowment'],
  routine: ['expansion', 'riding_lost', 'scheme_begun', 'scheme_answered', 'scheme_abandoned', 'name_heir',
    'heir_of_age', 'compact', 'marriage'],
  notable: ['contest_won', 'contest_lost', 'riding_passes', 'succession_clean', 'succession_disorderly',
    'elevation', 'quarrel', 'reconciled', 'partition', 'founding'],
  pause: ['removed', 'fallen', 'crisis', 'reckoning'],
};

test('four paces, lowest first, each with a hold and a flight in the table', () => {
  assert.deepEqual(PACES, ['quiet', 'routine', 'notable', 'pause']);
  assert.deepEqual(PACES.map(paceRank), [0, 1, 2, 3]);
  for (const pace of PACES) {
    assert.ok(Number.isInteger(HOLD[pace]) && Number.isInteger(PACE.flight_ms[pace]), pace);
  }
});

for (const [pace, kinds] of Object.entries(FIXTURES)) {
  for (const kind of kinds) {
    test(`a house turn of ${kind} is ${pace}`, () => {
      const e = entry('A', kind, ['A'], 10);
      assert.equal(entryPace(e, { pace: PACE, thresholds: THRESHOLDS }), pace);
      const r = round([e]);
      assert.equal(r.parts.find((p) => p.id === 'A').pace, pace);
    });
  }
}

test('a beat at the pause weight is a pause whatever it is, and a turn takes its heaviest beat', () => {
  assert.equal(round([entry('A', 'correspondence', ['A'], THRESHOLDS.pause)]).parts[1].pace, 'pause');
  assert.equal(round([entry('A', 'correspondence', ['A'], 39), entry('A', 'invest', ['A'], 0)]).parts[1].pace, 'quiet');
  const mixed = round([entry('A', 'scheme_step', ['A'], 0), entry('A', 'expansion', ['A'], 20),
    entry('A', 'correspondence', ['A'], 5)]);
  assert.equal(mixed.parts[1].pace, 'routine', 'the heaviest by what it was, not by weight');
  const merged = { beat: { turn: 9, seq: 90, kind: 'quarrel', part: 'B', houses: ['A', 'B'], merge: 'contest',
    parts: [{ kind: 'quarrel' }, { kind: 'expansion' }] }, weight: 20, text: 't', alone: 't' };
  assert.equal(round([merged]).parts[2].pace, 'notable', 'a merged act takes its heaviest part');
});

test('a house taking a riding is not quiet, whatever the weight of the yearly headline', () => {
  const r = round([entry('A', 'expansion', ['A'], 20, { ridings: ['35001'], owners: { 35001: 'A' } })]);
  assert.equal(r.parts[1].pace, 'routine');
});

test('the world is at least routine when it announces anything, a close is as long as its headline merits', () => {
  const deck = [{ name: 'Laurier Elected', magnitude: 'Significant', crisis: false, years: 1 }];
  assert.equal(round([], { deck }).parts[0].pace, 'routine');
  assert.equal(round([]).parts[0].pace, 'quiet', 'a world with nothing to announce');
  assert.equal(round([]).parts[4].pace, 'routine');
  assert.equal(round([], { headlinePace: 'notable' }).parts[4].pace, 'notable');
  assert.equal(round([], { headlinePace: 'pause' }).parts[4].pace, 'notable', 'the turn that paused has stopped Auto');
  assert.equal(round([], { closing: true }).parts[4].pace, 'pause', 'a chapter close');
  assert.equal(round([entry('world', 'crisis', ['A', 'B'], 70)]).parts[0].pace, 'pause');
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

test('Auto holds each pace as the table says: a quiet turn under half a second, a routine one about 1.2 s, a notable one about 3', () => {
  assert.ok(HOLD.quiet < 500);
  assert.ok(HOLD.routine >= 1000 && HOLD.routine <= 1300);
  assert.ok(HOLD.notable >= 2800 && HOLD.notable <= 3200);
  assert.ok(PACE.flight_ms.quiet === 0 && PACE.flight_ms.notable < 1000);
  for (const pace of PACES) assert.ok(PACE.flight_ms[pace] < HOLD[pace] || pace === 'quiet', pace);
  const r = round([entry('A', 'correspondence', ['A'], 5), entry('B', 'expansion', ['B'], 45),
    entry('C', 'elevation', ['C'], 60)]);
  const [, a, b, c] = r.parts;
  assert.equal(autoMs(a, { hold: HOLD }), HOLD.quiet);
  assert.equal(autoMs(a, { hold: HOLD, skipQuiet: true }), 0);
  assert.equal(autoMs(b, { hold: HOLD, skipQuiet: true }), HOLD.routine, 'skip skips quiet turns only');
  assert.equal(autoMs(c, { hold: HOLD, skipQuiet: true }), HOLD.notable);
  assert.equal(autoMs(c, { hold: HOLD, speed: 2 }), HOLD.notable / 2);
  const total = autoLength([r], { hold: HOLD });
  const skipped = autoLength([r], { hold: HOLD, skipQuiet: true });
  assert.ok(skipped.ms < total.ms);
  assert.equal(total.shown, r.parts.length);
  assert.equal(skipped.shown, r.parts.length - 1, 'only A is a quiet house turn');
  assert.deepEqual(total.byPace, { quiet: 2, routine: 2, notable: 1, pause: 0 });
});

test('the strip: the current chip lit, those done dimmed, those to come plain, with end caps', () => {
  const r = round([entry('B', 'expansion', ['B'], 45)]);
  const strip = stripOf(r, 2);
  assert.deepEqual(strip.map((c) => c.id), ['world', 'A', 'B', 'C', 'close']);
  assert.deepEqual(strip.map((c) => c.state), ['done', 'done', 'current', 'todo', 'todo']);
  assert.equal(strip[0].kind, 'world');
  assert.equal(strip[4].kind, 'close');
  assert.equal(strip[2].pace, 'routine');
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

const STYLES = {
  A: { title: 'Ascher of Alma', designation: 'Alma', female: false },
  B: { title: 'Baker of Bellechasse', designation: 'Bellechasse', female: false },
};
const styleOf = (h) => STYLES[h] || null;
const cardOptions = { turn: 9, plans: [], plansBefore: [], styleOf, pace: PACE, thresholds: THRESHOLDS, responses: PACE.responses };

test('a house card says what it did, what was done to it, its scheme; the answer to the event is a tag', () => {
  const r = round([
    entry('A', 'scheme_begun', ['A', 'B'], 60),
    entry('B', 'era_response', ['B'], 5, { outcome: 'Resist', world: { event: 'Laurier Elected' } }),
    entry('B', 'expansion', ['B'], 45),
  ]);
  const b = r.parts.find((p) => p.id === 'B');
  const card = houseCard(b, r.parts.slice(0, 2), cardOptions);
  assert.equal(card.did, 'expansion alone.');
  assert.equal(card.doneTo, 'scheme_begun alone.');
  assert.equal(card.scheme, 'It has no scheme afoot.');
  assert.deepEqual(card.tags, [{ event: 'Laurier Elected', response: 'Resist', word: 'resists', glyph: '▼' }]);
  assert.equal(card.era, undefined, 'the answer is no longer a line of prose');
  const quiet = houseCard(r.parts.find((p) => p.id === 'C'), r.parts.slice(0, 3), { ...cardOptions, plans: null });
  assert.equal(quiet.did, 'It kept to its estates.');
  assert.deepEqual(quiet.tags, []);
  assert.equal(houseLine({ ridings: 4, rank: 'Earl', place: 3, of: 24 }), '4 ridings · Earl · 3rd of 24');
  assert.equal(houseLine({ ridings: 1, rank: 'Baron', place: 11, of: 24 }), '1 riding · Baron · 11th of 24');
});

test('a card tells each act of the turn the map marks, the heaviest first, and not the quiet ones', () => {
  const r = round([
    entry('A', 'correspondence', ['A', 'B'], 5),
    entry('A', 'heir_of_age', ['A'], 20),
    entry('A', 'quarrel', ['A', 'B'], 50),
    entry('A', 'expansion', ['A'], 20),
    entry('A', 'compact', ['A', 'B'], 25),
  ]);
  const card = houseCard(r.parts[1], r.parts.slice(0, 1), cardOptions);
  assert.equal(card.did, 'quarrel alone.');
  assert.equal(card.also.length, 2, 'at most two more');
  assert.deepEqual(card.also, ['compact alone.', 'heir_of_age alone.'], 'routine acts, heaviest first, record order on a tie');
  assert.ok(!card.also.includes('correspondence alone.'));
});

test('a house whose only turn is an answer to the event shows a tag and kept to its estates', () => {
  const r = round([entry('A', 'era_response', ['A'], 5, { outcome: 'Exploit', world: { event: 'National Policy' } })]);
  const card = houseCard(r.parts[1], r.parts.slice(0, 1), cardOptions);
  assert.equal(card.did, 'It kept to its estates.');
  assert.deepEqual(card.tags.map((t) => [t.glyph, t.word, t.event]), [['◆', 'exploits', 'National Policy']]);
  const glyphs = Object.values(PACE.responses).map((x) => x.glyph);
  assert.equal(new Set(glyphs).size, glyphs.length, 'a glyph for each response');
});

test('a crisis keeps its camp on the card, in words', () => {
  const crisis = entry('world', 'crisis', ['A', 'B', 'C'], 70, {
    world: { event: 'Great War', lead: ['A'], resist: ['B'], carried: 'lead', years: 5 },
  });
  const r = round([crisis]);
  const camp = (id) => houseCard(r.parts.find((p) => p.id === id), r.parts.slice(0, 1), cardOptions).camps;
  assert.deepEqual(camp('A'), ['Leads in the Great War crisis.']);
  assert.deepEqual(camp('B'), ['Resists in the Great War crisis.']);
  assert.deepEqual(camp('C'), ['Stands aside in the Great War crisis.']);
  const article = round([entry('world', 'crisis', ['A'], 70, { world: { event: 'The Great War', lead: ['A'], resist: [], carried: 'lead' } })]);
  assert.deepEqual(houseCard(article.parts[1], article.parts.slice(0, 1), cardOptions).camps, ['Leads in the Great War crisis.'],
    'the event\'s own article is not said twice');
});

test('a card says the name once: the sentence starts at the verb, other houses keep their names', () => {
  const peerage = (h) => `Baron ${STYLES[h].title}`;
  const entries = [
    { beat: { turn: 9, seq: 1, kind: 'expansion', houses: ['A'], part: 'A' }, weight: 20,
      text: `${peerage('A')} sets out to open Cumberland—Colchester.`,
      alone: `${peerage('A')} sets out to open Cumberland—Colchester.` },
    { beat: { turn: 9, seq: 2, kind: 'compact', houses: ['B', 'A'], part: 'B' }, weight: 25,
      text: `${peerage('B')} enters into a compact with ${peerage('A')}.`,
      alone: `${peerage('B')} enters into a compact with ${peerage('A')}.` },
  ];
  const r = round(entries);
  const a = houseCard(r.parts[1], r.parts.slice(0, 1), cardOptions);
  assert.equal(a.did, 'Sets out to open Cumberland—Colchester.');
  assert.equal(a.didFull, 'Baron Ascher of Alma sets out to open Cumberland—Colchester.');
  const b = houseCard(r.parts[2], r.parts.slice(0, 2), cardOptions);
  assert.equal(b.did, 'Enters into a compact with Baron Ascher of Alma.');
  assert.equal(b.didFull, 'Baron Baker of Bellechasse enters into a compact with Baron Ascher of Alma.');
  // The rank may differ from the style's (an elevation in the year): any rank form is stripped.
  assert.equal(verbFirst('Earl Ascher of Alma rises to Duke.', 'A', styleOf), 'Rises to Duke.');
  assert.equal(verbFirst('Baroness Ascher of Alma writes.', 'A', styleOf), 'Writes.');
  assert.equal(verbFirst('House Zed takes Delta.', 'Zed', () => null), 'Takes Delta.');
  assert.equal(verbFirst('Baron Baker of Bellechasse takes Delta.', 'A', styleOf), 'Baron Baker of Bellechasse takes Delta.');
  assert.equal(houseStyle({ house: 'A', peerage: 'Baron Ascher of Alma', rank: 'Baron' }).title, 'Ascher of Alma');
  // Two houses for the subject: the card house is the one the verb is told of.
  const joint = 'Baron Ascher of Alma and Baron Baker of Bellechasse enter into a compact.';
  assert.equal(verbFirst(joint, 'A', styleOf), 'Enters into a compact with Baron Baker of Bellechasse.');
  assert.equal(verbFirst(joint, 'B', styleOf), 'Enters into a compact with Baron Ascher of Alma.');
  assert.equal(verbFirst('Baron Ascher of Alma and Baron Baker of Bellechasse fall out over a boundary.', 'B', styleOf),
    'Falls out with Baron Ascher of Alma over a boundary.');
  // Where the house must be named inside a sentence, it is "the house".
  assert.equal(verbFirst('Baron Baker of Bellechasse opens a correspondence with Baron Ascher of Alma.', 'A', styleOf),
    'Baron Baker of Bellechasse opens a correspondence with the house.');
  assert.equal(verbFirst('Mary Ascher, heir to Baron Ascher of Alma, comes of age.', 'A', styleOf),
    'Mary Ascher, heir to the house, comes of age.');
  assert.equal(verbFirst('A letter from Baron Ascher of Alma gives offence to Baron Baker of Bellechasse.', 'A', styleOf),
    'Gives offence to Baron Baker of Bellechasse by letter.');
});

test('the close counts the year, leaving out any that are zero', () => {
  const own = { 35001: 'A', 35002: 'B', 24001: 'C' };
  const entries = [
    entry('A', 'expansion', ['A'], 20, { ridings: ['35003'], owners: { 35003: 'A' } }),
    entry('B', 'expansion', ['B'], 20, { ridings: ['35004', '35005'], owners: { 35004: 'B', 35005: 'B' } }),
    entry('B', 'riding_passes', ['B', 'C'], 80, { ridings: ['24001'], owners: { 24001: 'B' } }),
    entry('C', 'contest_won', ['C', 'A'], 90),
    entry('C', 'contest_won', ['C', 'A'], 90, { outcome: 'rout' }),
    entry('A', 'succession_clean', ['A'], 15),
    entry('B', 'elevation', ['B'], 60),
    entry('close', 'founding', ['D'], 40, { ridings: ['12001'], owners: { 12001: 'D' } }),
    entry('C', 'removed', ['C'], 100, { removed: ['C'] }),
  ];
  assert.deepEqual(yearCounts(entries, own).map((c) => c.text), [
    '3 ridings taken', '1 riding changing hands', '1 contest decided', '1 succession',
    '1 elevation', '1 house founded', '1 house fallen',
  ]);
  assert.equal(countLine(yearCounts(entries.slice(0, 2), own)), '3 ridings taken');
  assert.deepEqual(yearCounts([entry('A', 'correspondence', ['A'], 5)], own), []);
  assert.equal(countLine([]), '');
  // The round carries them, and the pace of the headline it will lead or follow.
  const r = round(entries.slice(0, 3), { headlinePace: 'routine' });
  assert.equal(r.countLine, '3 ridings taken · 1 riding changing hands');
  assert.equal(r.headlinePace, 'routine');
  // A merged act counts by its parts, once: a partition seats a cadet (founded, no riding moved).
  const merged = { beat: { turn: 9, seq: 50, kind: 'partition', merge: 'partition', part: 'A', houses: ['A', 'D'],
    parts: [
      { kind: 'partition', houses: ['A', 'D'], ridings: ['35001'], owners: { 35001: 'D' } },
      { kind: 'succession_clean', houses: ['A'] }] }, weight: 75, text: 't', alone: 't' };
  assert.deepEqual(yearCounts([merged], own).map((c) => c.text), ['1 succession', '1 house founded']);
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
