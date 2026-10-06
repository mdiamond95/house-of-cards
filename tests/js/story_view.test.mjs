// web/story/view.js: the dispatch and strip as HTML, the camera's arithmetic,
// and a remembered follow that survives a storage that throws.
import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
  MapCamera, afootHtml, dispatchHtml, escapeHtml, pauseReason, storylineHtml, focusBox, lerpBox, parseBox, readStored, recordHtml,
  stripHtml, unionBox, writeStored,
} from '../../web/story/view.js';

const throwing = {
  getItem() { throw new Error('denied'); },
  setItem() { throw new Error('denied'); },
  removeItem() { throw new Error('denied'); },
};

function memory() {
  const data = new Map();
  return {
    getItem: (k) => (data.has(k) ? data.get(k) : null),
    setItem: (k, v) => data.set(k, String(v)),
    removeItem: (k) => data.delete(k),
  };
}

test('following is remembered where storage works and forgotten quietly where it does not', () => {
  const store = memory();
  assert.equal(writeStored('k', 'Fraser', store), true);
  assert.equal(readStored('k', store), 'Fraser');
  assert.equal(writeStored('k', null, store), true);
  assert.equal(readStored('k', store), null);
  assert.equal(readStored('k', throwing), null);
  assert.equal(writeStored('k', 'Fraser', throwing), false);
  assert.equal(readStored('k', undefined), null);
  assert.equal(writeStored('k', 'Fraser', undefined), false);
});

test('HTML is escaped', () => {
  assert.equal(escapeHtml('<a href="x">&</a>'), '&lt;a href=&quot;x&quot;&gt;&amp;&lt;/a&gt;');
  const html = stripHtml([{ house: '<b>', place: 1, score: 10, move: 'new', was: null }]);
  assert.ok(html.includes('&lt;b&gt;') && !html.includes('<b>'));
});

test('the strip carries place, movement, colour and score, and marks the followed house', () => {
  const html = stripHtml(
    [{ house: 'A', place: 1, score: 30, move: 'up', was: 3 }, { house: 'B', place: 2, score: 20, move: 'down', was: 1 }],
    { colourOf: (h) => (h === 'A' ? '#123456' : null), follow: 'B' },
  );
  assert.ok(html.includes('move-up') && html.includes('▲') && html.includes('(was 3)'));
  assert.ok(html.includes('#123456'));
  assert.ok(html.includes('move-down followed'));
});

test('a quiet dispatch is one line; a told one has headline, secondaries and ledger', () => {
  assert.equal(
    dispatchHtml({ turn: 4, quiet: true, quietLine: 'A quiet season: two houses tended their estates.' }),
    '<h2 class="dispatch-turn">Season 4</h2><p class="dispatch-quiet">A quiet season: two houses tended their estates.</p>',
  );
  const html = dispatchHtml({
    turn: 2,
    quiet: false,
    pause: true,
    headline: { beat: { kind: 'riding_passes' }, weight: 80, text: 'A buys X.' },
    secondary: [{ text: 'B takes Y.' }],
    ledger: 'Elsewhere, one house tended its estates.',
  }, { unit: 'turn' });
  assert.ok(html.startsWith('<h2 class="dispatch-turn">Turn 2</h2>'));
  assert.ok(html.includes('dispatch-headline pause'));
  assert.ok(html.includes('riding passes &middot; weight 80'));
  assert.ok(html.includes('<li>B takes Y.</li>'));
  assert.ok(html.includes('Elsewhere, one house tended its estates.'));
  assert.equal(recordHtml({ record: ['x'] }), '<li>x</li>');
});

test('the focus box is padded, kept in the map\'s proportions and inside it', () => {
  const home = [0, 0, 1000, 500];
  const box = focusBox([500, 250, 10, 10], home);
  assert.ok(Math.abs(box[3] / box[2] - 0.5) < 1e-9, 'same aspect as home');
  assert.ok(box[2] >= 120 - 1e-9, 'no narrower than 12% of home');
  assert.ok(box[0] <= 500 && box[0] + box[2] >= 510);
  const corner = focusBox([0, 0, 5, 5], home);
  assert.deepEqual(corner.slice(0, 2), [0, 0], 'clamped inside the map');
  assert.deepEqual(focusBox([0, 0, 990, 490], home), home, 'nothing to zoom into');
});

test('boxes: union, interpolation, parsing', () => {
  assert.deepEqual(unionBox([[0, 0, 1, 1], [5, 5, 1, 2]]), [0, 0, 6, 7]);
  assert.equal(unionBox([]), null);
  assert.deepEqual(lerpBox([0, 0, 10, 10], [10, 10, 20, 20], 0.5), [5, 5, 15, 15]);
  assert.deepEqual(parseBox('1 2.5 3,4'), [1, 2.5, 3, 4]);
});

test('the camera zooms to a riding and puts the view back exactly as it found it', () => {
  const attrs = { viewBox: '-30.0 327.7 1060.0 538.5' };
  const path = { getBBox: () => ({ x: 500, y: 600, width: 8, height: 6 }) };
  const svg = {
    getAttribute: (k) => attrs[k],
    setAttribute: (k, v) => { attrs[k] = v; },
    querySelector: (sel) => (sel === 'path[data-fed="35001"]' ? path : null),
  };
  const borderAttrs = { 'stroke-width': '0.3774' };
  const borders = { getAttribute: (k) => borderAttrs[k], setAttribute: (k, v) => { borderAttrs[k] = v; } };
  const camera = new MapCamera(svg, { borders, duration: 0, hold: 60000 });
  assert.equal(camera.focus(['nowhere']), false);
  assert.equal(camera.focus(['35001']), true);
  assert.notEqual(attrs.viewBox, '-30.0 327.7 1060.0 538.5');
  assert.ok(Number(borderAttrs['stroke-width']) < 0.3774, 'borders thin as the map zooms');
  camera.reset();
  assert.equal(attrs.viewBox, '-30.0 327.7 1060.0 538.5');
  assert.equal(borderAttrs['stroke-width'], '0.3774');
  camera.focus(['35001']);
  camera.back();
  assert.equal(attrs.viewBox, '-30.0 327.7 1060.0 538.5');
});

test('a storyline headline shows its kicker, its related beats, the previous beat and the moments', () => {
  const d = {
    turn: 13, quiet: false, pause: true,
    headline: { beat: { kind: 'quarrel' }, weight: 70, text: 'A and B fall out.' },
    kicker: { id: 's3', text: 'The Alpha\u2013Beta rivalry \u00b7 the second beat \u00b7 three seasons running' },
    related: [{ text: 'Alpha presses a claim and is rebuffed.' }],
    previously: { turn: 10, text: 'Alpha and Beta fall out.' },
    secondary: [], ledger: null,
    moments: [{ name: 'The Alpha\u2013Beta rivalry', change: 'climax' }],
  };
  const html = dispatchHtml(d);
  assert.ok(html.indexOf('dispatch-kicker') < html.indexOf('dispatch-headline'));
  assert.ok(html.includes('<ul class="dispatch-related"><li>Alpha presses a claim and is rebuffed.</li></ul>'));
  assert.ok(html.includes('Previously, season 10: Alpha and Beta fall out.'));
  assert.ok(html.includes('reaches its climax'));
  assert.equal(pauseReason({ pause: true, stops: ['The Alpha\u2013Beta rivalry closes'] }),
    'Paused: The Alpha\u2013Beta rivalry closes. Press Auto to carry on.');
  assert.equal(pauseReason({ pause: false }), null);
});

test('the Afoot list and a storyline told top to bottom', () => {
  const list = [{ id: 's1', name: 'The rise of Perth', state: 'climax', beats: 4, opened: 3, closed: null }];
  const html = afootHtml(list, { selected: 's1' });
  assert.ok(html.includes('data-storyline="s1"') && html.includes('chosen') && html.includes('since season 3'));
  assert.equal(afootHtml([]), '<li class="meta">Nothing is afoot yet.</li>');
  const told = { name: 'The rise of Perth', state: 'closed', outcome: 'reached first', opened: 3, closed: 9,
    beats: [{ turn: 3, text: 'Perth takes X.' }, { turn: 9, text: 'Perth takes Y.' }] };
  const page = storylineHtml(told, { link: (t) => `replay.html#season-${t}` });
  assert.ok(page.includes('<a href="replay.html#season-9">Season 9</a></span> Perth takes Y.'));
  assert.ok(page.includes('Closed season 9: reached first.'));
  assert.ok(page.includes('2 beats'));
});

test('Plans afoot: each scheme with its house, target and turns remaining', async () => {
  const { plansHtml } = await import('../../web/story/view.js');
  const html = plansHtml([
    { name: 'Alpha', scheme: 'Claim a riding', target: 'Beta', riding: 'Perth & Co', turnsRemaining: 2, followed: true },
    { name: 'Gamma', scheme: 'Secure the line', target: null, riding: null, turnsRemaining: 1, followed: false },
  ]);
  assert.ok(html.includes('class="plan followed"'));
  assert.ok(html.includes('Beta, Perth &amp; Co'));
  assert.ok(html.includes('2 seasons to run') && html.includes('resolves next season'));
  assert.ok(plansHtml([]).includes('No scheme'));
});

test('Phase D1: a calendar dispatch is headed by its year; a chapter and the reckoning have their own sections', async () => {
  const { chapterHtml } = await import('../../web/story/view.js');
  const d = {
    turn: 8, year: 1874, quiet: false, pause: false,
    headline: { text: 'The Long Depression divides the peerage.', weight: 90, beat: { kind: 'crisis' } },
    kicker: null, related: [], previously: { turn: 3, year: 1869, text: 'Earlier.' }, secondary: [], ledger: null, moments: [],
  };
  const html = dispatchHtml(d, { unit: 'year' });
  assert.ok(html.startsWith('<h2 class="dispatch-turn">1874</h2>'));
  assert.ok(html.includes('Previously, 1869: Earlier.'));
  const ch = chapterHtml({
    numeral: 'I', name: 'Confederation', start_year: 1867, end_year: 1885,
    standings: [{ house: 'A', place: 1, score: 40, move: 'up', was: 3 }],
    closed: [{ id: 's1', name: 'The Alpha–Beta rivalry', state: 'closed', outcome: 'reconciled', opened: 2, closed: 9, beats: 4 }],
    open: [],
  }, { start: 1867 });
  assert.ok(ch.includes('Chapter I · Confederation, 1867–1885'));
  assert.ok(ch.includes('The Alpha–Beta rivalry'));
  assert.ok(ch.includes('1868–1875'), 'storylines are dated by year');
  assert.ok(ch.includes('No storyline of the cast is open.'));
});
