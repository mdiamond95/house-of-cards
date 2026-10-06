// web/story/dispatch.js: one turn, told (docs/STORY_DESIGN.md §3.2, §3.4).
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

import { BEAT_KINDS } from '../../web/story/beats.js';
import { Story, numberWord, ordinal, replay, select, summarise, summariseStorylines } from '../../web/story/dispatch.js';
import { houseStyle } from '../../web/story/text.js';

const weights = JSON.parse(readFileSync(new URL('../../web/story/weights.json', import.meta.url), 'utf8'));
let seq = 0;
const beat = (turn, kind, houses, extra = {}) => ({ turn, seq: seq++, kind, houses, ...extra });
const PEERAGES = {
  A: ['Baron A of Alpha', 'Baron', 'Alpha'], B: ['Viscount B of Beta', 'Viscount', 'Beta'],
  C: ['Baron C de Gamma', 'Baron', 'Gamma'], D: ['Earl D of Delta', 'Earl', 'Delta'],
  E: ['Baron E of Epsilon', 'Baron', 'Epsilon'], Z: ['Baron Z of Zeta', 'Baron', 'Zeta'],
};
const styleOf = (h) => (PEERAGES[h]
  ? houseStyle({ house: h, peerage: PEERAGES[h][0], rank: PEERAGES[h][1], place: PEERAGES[h][2] }) : null);
const ridings = { 35001: 'Kingston and the Islands', 35002: 'Perth', 35003: 'Ottawa Centre', 24001: 'Abitibi' };
const story = (extra = {}) => new Story({ weights, styleOf, ridings, ...extra });

test('number words and ordinals', () => {
  assert.equal(numberWord(14), 'fourteen');
  assert.equal(numberWord(48), 'forty-eight');
  assert.equal(numberWord(150), '150');
  assert.equal(ordinal(4), 'fourth');
  assert.equal(ordinal(23), '23rd');
  assert.equal(ordinal(13), '13th');
});

test('a turn with nothing at or above the quiet threshold is one quiet line', () => {
  const s = story({ seen: BEAT_KINDS });
  const d = s.step(4, [
    beat(4, 'invest', ['A']), beat(4, 'cultivate', ['B']), beat(4, 'expansion', ['C'], { owners: { 35001: 'C' } }),
  ]);
  assert.equal(d.quiet, true);
  assert.equal(d.headline, null);
  assert.deepEqual(d.secondary, []);
  assert.equal(d.ledger, null);
  assert.equal(d.quietLine, 'A quiet season: three houses tended their estates.');
  assert.equal(new Story({ weights, unit: 'turn' }).step(1, []).quietLine, 'A quiet turn: nothing of note passed.');
});

test('first mention is the full style, later ones the designation, and every line ends in a period', () => {
  const s = story({ seen: BEAT_KINDS, baseline: { owners: {}, ranks: { A: 0, B: 1 }, removed: [] } });
  const d = s.step(5, [
    beat(5, 'removed', ['Z'], { line: 'Season 5 · Baron Z of Zeta fails; its ridings return to the Crown' }),
    beat(5, 'compact', ['A', 'B'], { line: 'Season 5 · Baron A of Alpha and Viscount B of Beta enter into a compact.' }),
    beat(5, 'failed', ['A'], { outcome: 'Expand' }),
  ]);
  assert.equal(d.headline.text, 'Baron Z of Zeta fails; its ridings return to the Crown.');
  const texts = d.secondary.map((x) => x.text);
  assert.deepEqual(texts, [
    'Baron A of Alpha and Viscount B of Beta enter into a compact.',
    'Alpha tries to expand and fails.',
  ]);
  assert.equal(d.ledger, null, 'nothing is left over for the ledger');
  const later = story({ seen: BEAT_KINDS, baseline: { owners: {}, ranks: { A: 0 }, removed: [] } }).step(6, [
    beat(6, 'quarrel', ['A', 'Z'], { outcome: 'friction', line: 'Season 6 · Baron A of Alpha and Baron Z of Zeta fall out over a river.' }),
    beat(6, 'failed', ['A'], { outcome: 'Dispute' }),
  ]);
  assert.equal(later.headline.text, 'Baron A of Alpha and Baron Z of Zeta fall out over a river.');
  assert.deepEqual(later.secondary.map((x) => x.text), ['Alpha presses a claim and is rebuffed.']);
});

test('one act, one beat: a cession and the grievance it settles are one sentence naming every party', () => {
  const s = story({ seen: BEAT_KINDS, baseline: { owners: { 35002: 'A' }, ranks: { A: 0, B: 1 }, removed: [] } });
  const d = s.step(7, [
    beat(7, 'riding_passes', ['A', 'B'], { outcome: 'cession', ridings: ['35002'], owners: { 35002: 'B' }, line: 'Season 7 · Baron A of Alpha gives up Perth (cession).' }),
    beat(7, 'reconciled', ['A', 'B'], { outcome: 'cession', line: 'Season 7 · Baron A of Alpha settles its grievance with Viscount B of Beta by cession.' }),
  ]);
  assert.equal(d.headline.beat.merge, 'cession');
  assert.equal(d.headline.text, 'Baron A of Alpha cedes Perth to Viscount B of Beta, settling the grievance between them.');
  assert.equal(d.record.length, 2, 'the full record keeps both of the engine\'s lines');
});

test('at most one era response in a dispatch, and it headlines only when nothing else reaches quiet', () => {
  const s = story({ seen: BEAT_KINDS, baseline: { owners: {}, ranks: { A: 0, B: 0, C: 0, D: 0 }, removed: [] } });
  const d = s.step(8, [
    beat(8, 'major_response', ['A'], { line: 'A meets the war and leads.' }),
    beat(8, 'major_response', ['B'], { line: 'B meets the war and resists.' }),
    beat(8, 'founding', ['E'], { owners: { 35003: 'E' }, ranks: { E: 0 }, line: 'E is created.' }),
  ]);
  assert.equal(d.headline.beat.kind, 'founding');
  assert.equal(d.secondary.filter((x) => x.beat.kind === 'major_response').length, 1);
  const s2 = story({ seen: BEAT_KINDS, follow: 'A', baseline: { owners: {}, ranks: { A: 0 }, removed: [] } });
  const only = s2.step(9, [beat(9, 'major_response', ['A'], { line: 'A meets the war and leads.' }),
    beat(9, 'major_response', ['A'], { line: 'A meets the flu and resists.' })]);
  assert.equal(only.headline.beat.kind, 'major_response', 'an era response may headline a turn with nothing else');
  assert.equal(only.secondary.length, 0);
});

test('select keeps the storyline\'s other beats under the headline, not among the secondaries', () => {
  const beats = [beat(1, 'quarrel', ['A', 'B']), beat(1, 'failed', ['A', 'B']), beat(1, 'expansion', ['C'])];
  const weighed = [{ total: 70, mods: [] }, { total: 40, mods: [] }, { total: 30, mods: [] }];
  const roles = [[{ id: 's1', role: 'open', earlier: 0 }], [{ id: 's1', role: 'escalate', earlier: 1 }], []];
  const chosen = select(beats, weighed, weights, roles);
  assert.equal(chosen.headline.beat.kind, 'quarrel');
  assert.deepEqual(chosen.related.map((e) => e.beat.kind), ['failed']);
  assert.deepEqual(chosen.secondary.map((e) => e.beat.kind), ['expansion']);
});

test('a storyline headline carries a kicker and the storyline\'s previous beat', () => {
  const s = story({ seen: BEAT_KINDS, baseline: { owners: {}, ranks: { A: 0, B: 0 }, removed: [] } });
  const first = s.step(10, [beat(10, 'quarrel', ['A', 'B'], { outcome: 'friction', line: 'Season 10 · Baron A of Alpha and Baron B of Beta fall out.' })]);
  assert.equal(first.kicker.text, 'The Alpha–Beta rivalry · the first beat · opens this season');
  assert.equal(first.previously, null);
  const d = s.step(13, [beat(13, 'dispute_won', ['A', 'B'], { outcome: '⊖', line: 'Season 13 · Baron A of Alpha carries a dispute against Viscount B of Beta.' })]);
  assert.equal(d.kicker.beat, 2);
  assert.ok(d.kicker.text.endsWith('three seasons running'));
  assert.equal(d.previously.turn, 10);
  assert.equal(d.previously.text, 'Alpha and Beta fall out.', 'the previously line follows the naming rule');
});

test('Auto pauses on a long cast storyline closing, a removal, a riding between cast houses, a heavy followed headline', () => {
  const s = story({ seen: BEAT_KINDS, baseline: { owners: { 35001: 'A', 35002: 'B' }, ranks: { A: 0, B: 0 }, removed: [] } });
  const opened = s.step(3, [beat(3, 'quarrel', ['A', 'B'], { outcome: 'friction', line: 'A and B fall out.' })]);
  assert.equal(opened.pause, false, 'a storyline opening is shown, not paused on');
  assert.deepEqual(opened.moments.map((m) => m.change), ['opened']);
  s.step(4, [beat(4, 'quarrel', ['A', 'B'], { outcome: 'friction', line: 'q.' })]);
  s.step(5, [beat(5, 'failed', ['A', 'B'], { outcome: 'Dispute' })]);
  const closed = s.step(6, [beat(6, 'reconciled', ['A', 'B'], { line: 'A makes peace with B.' })]);
  assert.equal(closed.pause, true);
  assert.deepEqual(closed.stops, ['The Alpha\u2013Beta rivalry closes']);
  const short = story({ seen: BEAT_KINDS, baseline: { owners: {}, ranks: { A: 0, B: 0 }, removed: [] } });
  short.step(1, [beat(1, 'quarrel', ['A', 'B'], { outcome: 'friction', line: 'q.' })]);
  assert.equal(short.step(2, [beat(2, 'reconciled', ['A', 'B'], { line: 'r.' })]).pause, false,
    'a two-beat storyline closing does not stop Auto');
  const passes = s.step(7, [beat(7, 'riding_passes', ['A', 'B'], { outcome: 'purchase', ridings: ['35001'], owners: { 35001: 'B' }, line: 'B buys X from A.' })]);
  assert.ok(passes.stops.includes('a riding passes between two houses of the cast'));
  const gone = s.step(8, [beat(8, 'removed', ['Z'], { removed: ['Z'], line: 'Z fails.' })]);
  assert.deepEqual(gone.stops, ['Baron Z of Zeta is removed']);
  assert.equal(s.step(9, [beat(9, 'invest', ['A'])]).pause, false);
  const followed = story({ seen: BEAT_KINDS, follow: 'E', baseline: { owners: {}, ranks: {}, removed: [] } });
  const heavy = followed.step(1, [beat(1, 'expansion', ['E'], { owners: { 35003: 'E' }, line: 'E takes Ottawa Centre.' })]);
  assert.equal(heavy.headline.weight, 70);
  assert.ok(heavy.stops[0].startsWith('a headline of weight 70 about the followed house'));
});

test('following changes the weights, never the board', () => {
  const turns = [[1, [
    beat(1, 'founding', ['A'], { owners: { 35001: 'A' }, ranks: { A: 0 }, line: 'A.' }),
    beat(1, 'founding', ['B'], { owners: { 24001: 'B' }, ranks: { B: 0 }, line: 'B.' }),
  ]]];
  const plain = replay(turns, { weights, styleOf, ridings });
  const followed = replay(turns, { weights, styleOf, ridings, follow: 'B' });
  assert.equal(plain[0].headline.beat.houses[0], 'A');
  assert.equal(followed[0].headline.beat.houses[0], 'B');
  assert.deepEqual(plain[0].standings, followed[0].standings);
});

test('Afoot lists open storylines, followed and cast first, and tell() reads one top to bottom', () => {
  const s = story({ seen: BEAT_KINDS, baseline: { owners: {}, ranks: { A: 0, B: 0, C: 0, D: 0 }, removed: [] } });
  s.step(1, [beat(1, 'quarrel', ['A', 'B'], { outcome: 'friction', line: 'Baron A of Alpha and Viscount B of Beta fall out.' })]);
  s.step(2, [beat(2, 'quarrel', ['C', 'D'], { outcome: 'friction', line: 'Baron C de Gamma and Earl D of Delta fall out.' })]);
  s.follow = 'D';
  const afoot = s.afoot();
  assert.deepEqual(afoot.map((x) => x.name), ['The Gamma–Delta rivalry', 'The Alpha–Beta rivalry']);
  const told = s.tell(afoot[1].id);
  assert.deepEqual(told.beats.map((b) => [b.turn, b.text]), [[1, 'Baron A of Alpha and Viscount B of Beta fall out.']]);
  assert.equal(s.tell('nope'), null);
});

test('rebase replaces the board and keeps the memory; still() is the strip with no movement', () => {
  const s = new Story({ weights, seen: BEAT_KINDS });
  s.step(1, [beat(1, 'quarrel', ['A', 'B'], { line: 'q' })]);
  s.rebase({ owners: { 1: 'A' }, ranks: { A: 2 }, removed: [] });
  assert.equal(s.context.lastHeadline, null, 'an outside-cast quarrel at 30 headlines nothing');
  assert.deepEqual(s.still(), [{ house: 'A', holdings: 1, rank: 2, score: 50, place: 1, move: 'same', was: 1 }]);
});

test('summaries: headlines by kind, and the storyline gates', () => {
  const s = summarise([
    { quiet: true },
    { quiet: false, pause: true, headline: { beat: { kind: 'quarrel' } } },
    { quiet: false, pause: false, headline: { beat: { kind: 'invest' } } },
  ]);
  assert.equal(s.largestSharePerMille, 500);
  assert.equal(s.bookkeepingHeadlines, 1);
  const st = story({ seen: BEAT_KINDS, baseline: { owners: {}, ranks: { A: 0, B: 0 }, removed: [] } });
  const ds = [
    st.step(21, [beat(21, 'quarrel', ['A', 'B'], { outcome: 'friction', line: 'q.' })]),
    st.step(22, [beat(22, 'reconciled', ['A', 'B'], { line: 'r.' })]),
  ];
  const g = summariseStorylines(st, ds);
  assert.equal(g.headlinesAfter, 2);
  assert.equal(g.inStorylinePerMille, 1000);
  assert.equal(g.openingPerMille, 500);
  assert.equal(g.closedWithoutOutcome, 0);
  assert.deepEqual(g.byOutcome, { 'rivalry: reconciled': 1 });
});
