// web/story/dispatch.js: one turn, told (docs/STORY_DESIGN.md §3.2).
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

import { BEAT_KINDS } from '../../web/story/beats.js';
import { Story, describe, numberWord, replay, select, summarise } from '../../web/story/dispatch.js';

const weights = JSON.parse(readFileSync(new URL('../../web/story/weights.json', import.meta.url), 'utf8'));
let seq = 0;
const beat = (turn, kind, houses, extra = {}) => ({ turn, seq: seq++, kind, houses, ...extra });

test('number words', () => {
  assert.equal(numberWord(1), 'one');
  assert.equal(numberWord(14), 'fourteen');
  assert.equal(numberWord(40), 'forty');
  assert.equal(numberWord(48), 'forty-eight');
  assert.equal(numberWord(150), '150');
});

test('describe keeps the engine\'s line, without the season the heading already gives', () => {
  assert.equal(describe(beat(9, 'expansion', ['A'], { line: 'Season 9 · Baron A takes X.' })), 'Baron A takes X.');
  assert.equal(describe(beat(9, 'quarrel', ['A'], { line: 'Season 9 · a letter from A gives offence to B.' })),
    'A letter from A gives offence to B.');
  assert.equal(describe(beat(9, 'expansion', ['A'], { line: 'Season 10 · elsewhere.' })), 'Season 10 · elsewhere.');
});

test('describe makes a line from typed facts only when the engine wrote none', () => {
  assert.equal(describe(beat(2, 'failed', ['Fraser 2'], { outcome: 'Expand' })), 'House Fraser 2 tries to expand and fails.');
  assert.equal(describe(beat(2, 'correspondence', ['A'], { outcome: 'failed' })), 'House A writes, and no correspondence follows.');
  assert.equal(describe(beat(2, 'invest', ['A']), (h) => `Baron ${h}`), 'Baron A invests in its estates.');
});

test('a turn with nothing at or above the quiet threshold is one quiet line', () => {
  const story = new Story({ weights, seen: BEAT_KINDS });
  const d = story.step(4, [
    beat(4, 'invest', ['A']), beat(4, 'cultivate', ['B']), beat(4, 'expansion', ['C'], { owners: { 35001: 'C' } }),
  ]);
  assert.equal(d.quiet, true);
  assert.equal(d.headline, null);
  assert.deepEqual(d.secondary, []);
  assert.equal(d.ledger, null);
  assert.equal(d.quietLine, 'A quiet season: three houses tended their estates.');
  assert.equal(d.pause, false);
  assert.equal(new Story({ weights, unit: 'turn' }).step(1, []).quietLine, 'A quiet turn: nothing of note passed.');
});

test('a headline, up to three secondaries, and a ledger for the rest', () => {
  const story = new Story({ weights, seen: BEAT_KINDS });
  const beats = [
    beat(5, 'expansion', ['A'], { owners: { 35001: 'A' }, ridings: ['35001'], line: 'A takes X.' }),
    beat(5, 'removed', ['Z'], { line: 'Z fails.' }),
    beat(5, 'founding', ['B'], { owners: { 35002: 'B' }, ranks: { B: 0 }, ridings: ['35002'], line: 'B is created.' }),
    beat(5, 'compact', ['C', 'D'], { line: 'C and D enter into a compact.' }),
    beat(5, 'expansion', ['E'], { owners: { 35003: 'E' }, line: 'E takes Y.' }),
    beat(5, 'expansion', ['F'], { owners: { 35004: 'F' }, line: 'F takes W.' }),
    beat(5, 'invest', ['G']), beat(5, 'invest', ['H']),
  ];
  const d = story.step(5, beats);
  assert.equal(d.headline.beat.kind, 'removed');
  assert.equal(d.headline.text, 'Z fails.');
  assert.equal(d.pause, true);
  // A's expansion is the first riding anyone has held in Ontario: 20 + 15.
  assert.deepEqual(d.secondary.map((s) => [s.beat.kind, s.weight]), [['founding', 40], ['expansion', 35], ['compact', 25]]);
  assert.equal(d.ledger, 'Elsewhere, four houses tended their estates; two more matters are in the full record.');
  assert.equal(d.record.length, 6);
  assert.deepEqual(d.zoom, []);
  assert.deepEqual(d.standings.map((r) => r.house), ['B']);
});

test('the headline\'s ridings are where the map goes', () => {
  const story = new Story({ weights });
  const d = story.step(1, [beat(1, 'founding', ['A'], { owners: { 35001: 'A' }, ranks: { A: 1 }, ridings: ['35001'], line: 'A.' })]);
  assert.deepEqual(d.zoom, ['35001']);
  assert.deepEqual(d.standings.map((r) => [r.house, r.score, r.move]), [['A', 30, 'new']]);
});

test('a kind that headlined last turn is marked down this turn', () => {
  const story = new Story({ weights, seen: BEAT_KINDS });
  const first = story.step(1, [beat(1, 'quarrel', ['A', 'B'], { line: 'q1' })]);
  assert.equal(first.headline.weight, 50);
  const second = story.step(2, [beat(2, 'quarrel', ['C', 'D'], { line: 'q2' })]);
  assert.equal(second.quiet, true, '50 - 15 is below the quiet threshold');
});

test('following changes the weights, never the board', () => {
  const turns = [[1, [
    beat(1, 'founding', ['A'], { owners: { 1: 'A' }, ranks: { A: 0 }, line: 'A.' }),
    beat(1, 'founding', ['B'], { owners: { 2: 'B' }, ranks: { B: 0 }, line: 'B.' }),
  ]]];
  const plain = replay(turns, { weights });
  const followed = replay(turns, { weights, follow: 'B' });
  assert.equal(plain[0].headline.beat.houses[0], 'A');
  assert.equal(followed[0].headline.beat.houses[0], 'B');
  assert.deepEqual(plain[0].standings, followed[0].standings);
});

test('rebase replaces the board and keeps the memory; still() is the strip with no movement', () => {
  const story = new Story({ weights });
  story.step(1, [beat(1, 'quarrel', ['A', 'B'], { line: 'q' })]);
  story.rebase({ owners: { 1: 'A' }, ranks: { A: 2 }, removed: [] });
  assert.equal(story.context.lastHeadline, 'quarrel');
  assert.deepEqual(story.still(), [{ house: 'A', holdings: 1, rank: 2, score: 50, place: 1, move: 'same', was: 1 }]);
});

test('select orders by weight, then by the beat\'s place in the turn', () => {
  const beats = [beat(1, 'a', []), beat(1, 'b', []), beat(1, 'c', [])];
  const chosen = select(beats, [{ total: 50, mods: [] }, { total: 60, mods: [] }, { total: 60, mods: [] }], weights);
  assert.equal(chosen.headline.beat.kind, 'b');
  assert.equal(chosen.secondary[0].beat.kind, 'c');
});

test('summarise counts headlines by kind and spots bookkeeping', () => {
  const s = summarise([
    { quiet: true },
    { quiet: false, pause: true, headline: { beat: { kind: 'quarrel' } } },
    { quiet: false, pause: false, headline: { beat: { kind: 'quarrel' } } },
    { quiet: false, pause: false, headline: { beat: { kind: 'invest' } } },
  ]);
  assert.deepEqual(s, {
    turns: 4, headlines: 3, quiet: 1, paused: 1, byKind: { quarrel: 2, invest: 1 },
    largestSharePerMille: 666, bookkeepingHeadlines: 1,
  });
});
