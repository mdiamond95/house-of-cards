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

test('two crises at equal weight: the one opening a multi-year event headlines, then the one with more houses', () => {
  const crisis = (event, lead, resist, years) => beat(48, 'crisis', [...lead, ...resist],
    { world: { event, lead, resist, carried: 'lead', ...(years ? { years } : {}) } });
  const weighed = [{ total: 90, mods: [] }, { total: 90, mods: [] }];
  const komagata = crisis('Komagata Maru Incident', ['A', 'B', 'C'], ['D', 'E']);
  const war = crisis('The Great War', ['A'], ['B'], 5);
  assert.equal(select([komagata, war], weighed, weights).headline.beat.world.event, 'The Great War');
  const small = crisis('A small crisis', ['A'], ['B']);
  const large = crisis('A large crisis', ['A', 'C'], ['B', 'D']);
  assert.equal(select([small, large], weighed, weights).headline.beat.world.event, 'A large crisis');
  // Weight still comes first.
  assert.equal(select([komagata, war], [{ total: 95, mods: [] }, { total: 90, mods: [] }], weights)
    .headline.beat.world.event, 'Komagata Maru Incident');
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
  // A storyline pauses Auto on its close only once it has run
  // storylines.pause_closing_beats beats.
  let t = 6;
  while (t < 3 + weights.storylines.pause_closing_beats - 1) {
    s.step(t, [beat(t, 'quarrel', ['A', 'B'], { outcome: 'friction', line: 'q.' })]);
    t += 1;
  }
  const closed = s.step(t, [beat(t, 'reconciled', ['A', 'B'], { line: 'A makes peace with B.' })]);
  assert.equal(closed.pause, true);
  assert.deepEqual(closed.stops, ['The Alpha\u2013Beta rivalry closes']);
  const short = story({ seen: BEAT_KINDS, baseline: { owners: {}, ranks: { A: 0, B: 0 }, removed: [] } });
  short.step(1, [beat(1, 'quarrel', ['A', 'B'], { outcome: 'friction', line: 'q.' })]);
  assert.equal(short.step(2, [beat(2, 'reconciled', ['A', 'B'], { line: 'r.' })]).pause, false,
    'a two-beat storyline closing does not stop Auto');
  const passes = s.step(t + 1, [beat(t + 1, 'riding_passes', ['A', 'B'], { outcome: 'purchase', ridings: ['35001'], owners: { 35001: 'B' }, line: 'B buys X from A.' })]);
  assert.ok(passes.stops.includes('a riding passes between two houses of the cast'));
  const gone = s.step(t + 2, [beat(t + 2, 'removed', ['Z'], { removed: ['Z'], line: 'Z fails.' })]);
  assert.deepEqual(gone.stops, ['Baron Z of Zeta is removed']);
  assert.equal(s.step(t + 3, [beat(t + 3, 'invest', ['A'])]).pause, false);
  const followed = story({ seen: BEAT_KINDS, follow: 'E', baseline: { owners: {}, ranks: {}, removed: [] } });
  const light = followed.step(1, [beat(1, 'expansion', ['E'], { owners: { 35003: 'E' }, line: 'E takes Ottawa Centre.' })]);
  assert.equal(light.headline.weight, 70);
  assert.equal(light.pause, false, 'below the pause threshold');
  const heavy = followed.step(2, [beat(2, 'elevation', ['E'], { ranks: { E: 1 }, outcome: 'Viscount', line: 'E is raised to Viscount.' })]);
  assert.equal(heavy.headline.weight, 120);
  assert.ok(heavy.stops[0].startsWith('a headline of weight 120 about the followed house'));
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

test('rules 1.0: a headline that resolves a scheme says how long it ran, and Plans afoot lists the cast\'s schemes', () => {
  const s = story({ seen: BEAT_KINDS, baseline: { owners: { 35001: 'B', 35002: 'A' }, ranks: { A: 0, B: 0 }, removed: [] } });
  assert.equal(s.plansAfoot(), null, 'no plans for a record without schemes');
  const d = s.step(5, [
    beat(5, 'contest_won', ['A', 'B'], { outcome: 'won', scheme: 4, ridings: ['35001'], owners: { 35001: 'A' }, line: 'Season 5 · Baron A of Alpha wins its claim to Kingston and the Islands against Viscount B of Beta, 9 to 7.' }),
    beat(5, 'scheme_resolved', ['A', 'B'], { outcome: 'Claim a riding', scheme: 4, ran: 4 }),
  ], { plans: [
    { id: 4, house: 'A', scheme: 'Claim a riding', target_house: 'B', riding: 'Perth', turns_remaining: 2, begun: 2, committed: 9 },
    { id: 6, house: 'Q', scheme: 'Secure the line', target_house: null, riding: null, turns_remaining: 1, begun: 5, committed: 2 },
  ] });
  assert.equal(d.headline.ran, 4);
  assert.ok(d.headline.text.endsWith('The scheme (Claim a riding) ran four seasons.'), d.headline.text);
  assert.ok(d.stops.includes('a riding passes between two houses of the cast'), 'a claim won between cast houses pauses Auto');
  const plans = s.plansAfoot();
  assert.deepEqual(plans.map((p) => [p.name, p.scheme, p.target, p.riding, p.turnsRemaining]),
    [['Alpha', 'Claim a riding', 'Beta', 'Perth', 2]], 'only the cast\'s schemes');
});

// ------------------------------------------------- Phase D1: the calendar --

const CALENDAR = {
  start_year: 1867, turns: 4,
  chapters: [
    { id: 'one', name: 'The First', numeral: 'I', start_year: 1867, end_year: 1868 },
    { id: 'two', name: 'The Second', numeral: 'II', start_year: 1869, end_year: 1870 },
  ],
};

test('with a world calendar a turn is a year: the dispatch carries it and kickers count years', () => {
  const s = story({ calendar: CALENDAR, seen: BEAT_KINDS, baseline: { owners: {}, ranks: { A: 0, B: 0 }, removed: [] } });
  assert.equal(s.unit, 'year');
  const first = s.step(1, [beat(1, 'quarrel', ['A', 'B'], { outcome: 'friction', line: 'Season 1 · A and B fall out.' })]);
  assert.equal(first.year, 1867);
  assert.ok(first.kicker.text.endsWith('opens this year'));
  const later = s.step(2, [beat(2, 'quarrel', ['A', 'B'], { outcome: 'friction', line: 'Season 2 · q.' })]);
  assert.ok(later.kicker.text.endsWith('one year running'));
  assert.equal(later.previously.year, 1867);
  const quiet = s.step(3, [beat(3, 'invest', ['A'])]);
  assert.equal(quiet.quietLine, 'A quiet year: one house tended its estates.');
});

test('each chapter ends with an interstitial, and Auto always pauses there', () => {
  const s = story({ calendar: CALENDAR, seen: BEAT_KINDS, baseline: { owners: { 35001: 'A' }, ranks: { A: 0, B: 0 }, removed: [] } });
  const one = s.step(1, [beat(1, 'invest', ['A'])]);
  assert.equal(one.chapter, null);
  assert.equal(one.pause, false);
  const end = s.step(2, [beat(2, 'expansion', ['B'], { owners: { 35002: 'B' }, line: 'Season 2 · B takes Perth.' })]);
  assert.equal(end.pause, true);
  assert.ok(end.stops.includes('the end of Chapter I, The First'));
  assert.deepEqual([end.chapter.numeral, end.chapter.name, end.chapter.start_year, end.chapter.end_year],
    ['I', 'The First', 1867, 1868]);
  assert.deepEqual(end.chapter.standings.map((r) => r.house), ['A', 'B']);
  assert.ok(Array.isArray(end.chapter.closed) && Array.isArray(end.chapter.open));
  // The second chapter's movement is measured from where the first left off.
  s.step(3, [beat(3, 'expansion', ['B'], { owners: { 35003: 'B' }, line: 'Season 3 · B takes Ottawa Centre.' })]);
  const two = s.step(4, [beat(4, 'invest', ['A'])]);
  assert.equal(two.chapter.numeral, 'II');
  const b = two.chapter.standings.find((r) => r.house === 'B');
  assert.deepEqual([b.place, b.was, b.move], [1, 2, 'up']);
});

test('the last turn of a calendar game carries the reckoning and pauses on it', () => {
  const reckoning = {
    last_year: 1870, reckoned: 1871,
    standings: [{ place: 1, house: 'A', prestige: 30, ridings: 3, rank: 'Baron' }],
    houses: [{ house: 'A', status: 'active', place: 1, rank: 'Baron', ridings: 3, peak_prestige: 30,
      peak_year: 1870, contests_won: 0, contests_lost: 0, successions: 0 }],
  };
  const s = story({ calendar: CALENDAR, reckoning, seen: BEAT_KINDS });
  for (let t = 1; t < 4; t += 1) assert.equal(s.step(t, []).reckoning, null);
  const last = s.step(4, []);
  assert.equal(last.reckoning.year, 1871);
  assert.ok(last.stops.includes('the reckoning of 1871'));
  assert.ok(last.reckoning.epilogues[0].text.startsWith('Baron A of Alpha comes to the reckoning first of 1'));
});

test('a crisis is one beat naming both camps, the cast first, and who carried it', () => {
  const s = story({ calendar: CALENDAR, seen: BEAT_KINDS,
    baseline: { owners: { 35001: 'D', 35002: 'B' }, ranks: { A: 0, B: 1, C: 0, D: 2, E: 0 }, removed: [] } });
  const d = s.step(1, [beat(1, 'crisis', ['A', 'C', 'E', 'D', 'B'], {
    outcome: 'resist', line: 'Season 1 · The Great War: 3 houses lead and 2 resist; those who resist carry it.',
    world: { event: 'The Great War', lead: ['A', 'C', 'E'], resist: ['D', 'B'], carried: 'resist', years: 5 },
  })]);
  assert.equal(d.headline.beat.kind, 'crisis');
  assert.equal(d.headline.text, 'The Great War divides the peerage: Alpha, Gamma and Epsilon lead;'
    + ' Delta and Beta resist; those who resist carry it. It is the first of five years.');
  assert.equal(d.inStoryline, false, 'a crisis belongs to no storyline');
});

test('Phase V2: a year handed its playing order is told as a round, with a card per house turn', () => {
  const s = story({ seen: BEAT_KINDS, baseline: { owners: { 35001: 'A', 35002: 'B' }, ranks: { A: 0, B: 1 }, removed: [] } });
  const plans = [{ id: 7, house: 'A', scheme: 'Claim a riding', target_house: 'B', riding: 'Perth', begun: 3, turns_remaining: 2 }];
  const d = s.step(3, [
    beat(3, 'quarrel', ['A', 'B'], { outcome: 'friction', part: 'world' }),
    beat(3, 'scheme_begun', ['A', 'B'], { outcome: 'Claim a riding', scheme: 7, part: 'A' }),
    beat(3, 'era_response', ['B'], { outcome: 'Resist', part: 'B' }),
    beat(3, 'invest', ['B'], { outcome: 'success', part: 'B' }),
  ], { plans, playing: ['A', 'B'], deck: [{ name: 'Laurier Elected', magnitude: 'Significant', crisis: false, years: 1 }] });
  assert.deepEqual(d.round.parts.map((p) => p.id), ['world', 'A', 'B', 'close']);
  assert.equal(d.round.stray.length, 0);
  const a = d.round.parts[1];
  assert.equal(a.card.scheme, 'It is in the first of three years of its claim on Perth.');
  assert.match(a.card.did, /\.$/);
  const b = d.round.parts[2];
  assert.equal(b.pace, 'quiet');
  assert.equal(b.card.did, 'It kept to its estates.');
  assert.equal(b.card.tags.length, 1, 'its answer to the year\'s event is a tag');
  assert.ok(b.card.doneTo, 'the claim begun in its rival\'s turn was done to it');
  // The sheet: rank, ridings, place, scheme, the rivalry, its last turns.
  const sheet = s.sheet('A', { people: [['Alice A', 'f', 'holder', 1, null, 40, 1]], last: 10 });
  assert.equal(sheet.holder.name, 'Alice A');
  assert.equal(sheet.holder.age, 33);
  assert.equal(sheet.ridings, 1);
  assert.match(sheet.scheme, /claim on Perth/);
  assert.deepEqual(sheet.rivals, ['Beta']);
  assert.equal(sheet.history.length, 1);
  // A year without the order is told as before, with no round.
  assert.equal(story().step(1, []).round, null);
});

test('Phase V3: the round carries the year\'s counts, the headline\'s pace and a tag for each answer', () => {
  const s = story({ seen: BEAT_KINDS, baseline: { owners: { 35001: 'A', 35002: 'B' }, ranks: { A: 0, B: 1 }, removed: [] } });
  const d = s.step(3, [
    beat(3, 'era_response', ['B'], { outcome: 'Resist', part: 'B', world: { event: 'Laurier Elected' } }),
    beat(3, 'expansion', ['A'], {
      part: 'A', ridings: ['35003'], owners: { 35003: 'A' }, line: 'Season 3 · Baron A of Alpha sets out to open Ottawa Centre.',
    }),
  ], { plans: null, playing: ['A', 'B'], deck: [{ name: 'Laurier Elected', magnitude: 'Significant', crisis: false, years: 1 }] });
  assert.equal(d.round.countLine, '1 riding taken');
  assert.equal(d.round.headlinePace, 'routine', 'a riding taken is a routine headline: counts lead');
  const [, a, b] = d.round.parts;
  assert.equal(a.pace, 'routine');
  assert.equal(b.pace, 'quiet');
  assert.deepEqual(b.card.tags.map((t) => [t.event, t.word]), [['Laurier Elected', 'resists']]);
  assert.equal(a.card.didFull, 'Baron A of Alpha sets out to open Ottawa Centre.');
  assert.equal(a.card.did, 'Sets out to open Ottawa Centre.', 'the card sentence starts at the verb');
});
