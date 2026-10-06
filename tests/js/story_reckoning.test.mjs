// web/story/reckoning.js: the reckoning after a calendar game's last turn,
// and its epilogues, from the record's facts alone (Phase D1).
import { test } from 'node:test';
import assert from 'node:assert/strict';

import { epilogue, reckoningView, styleAt } from '../../web/story/reckoning.js';
import { houseStyle } from '../../web/story/text.js';
import { reckoningHtml } from '../../web/story/view.js';

const styles = {
  Benjamin: houseStyle({ house: 'Benjamin', peerage: 'Marquis Benjamin of Bellechasse', rank: 'Marquis', place: 'Bellechasse' }),
  Mercier: houseStyle({ house: 'Mercier', peerage: 'Viscountess Mercier de Rimouski', rank: 'Viscountess', place: 'Rimouski' }),
  Kent: houseStyle({ house: 'Kent', peerage: 'Baron Kent of Chatham', rank: 'Baron', place: 'Chatham' }),
};
const styleOf = (h) => styles[h] || null;

const facts = {
  last_year: 1966,
  reckoned: 1967,
  standings: [
    { place: 1, house: 'Benjamin', prestige: 214, ridings: 9, rank: 'Marquis' },
    { place: 2, house: 'Mercier', prestige: 150, ridings: 5, rank: 'Earl' },
  ],
  houses: [
    { house: 'Kent', status: 'removed', place: null, rank: 'Baron', ridings: 0, peak_prestige: 120,
      peak_year: 1902, contests_won: 0, contests_lost: 2, successions: 1 },
    { house: 'Mercier', status: 'active', place: 2, rank: 'Earl', ridings: 5, peak_prestige: 160,
      peak_year: 1950, contests_won: 0, contests_lost: 0, successions: 0 },
    { house: 'Benjamin', status: 'active', place: 1, rank: 'Marquis', ridings: 9, peak_prestige: 214,
      peak_year: 1966, contests_won: 3, contests_lost: 1, successions: 4 },
  ],
};

test('a style at the reckoning is the last rank and the title, in the holder\'s form', () => {
  assert.equal(styleAt('Benjamin', 'Marquis', styleOf), 'Marquis Benjamin of Bellechasse');
  assert.equal(styleAt('Mercier', 'Earl', styleOf), 'Countess Mercier de Rimouski');
  assert.equal(styleAt('Nobody', 'Baron', styleOf), 'House Nobody');
});

test('each epilogue is built from the record\'s facts and nothing else', () => {
  const text = epilogue(facts.houses[2], { styleOf, houses: 2 });
  assert.equal(text, 'Marquis Benjamin of Bellechasse comes to the reckoning first of 2, a Marquis of nine ridings.'
    + ' Bellechasse stood highest in 1966, at a prestige of 214. It won three contests and lost one.'
    + ' Its line passed through four successions.');
  const quiet = epilogue(facts.houses[1], { styleOf, houses: 2 });
  assert.ok(quiet.includes('It fought no contest for a riding.'));
  assert.ok(quiet.includes('Its line passed through no succession.'));
  assert.ok(quiet.includes('a Countess of five ridings'));
  const gone = epilogue(facts.houses[0], { styleOf, houses: 2 });
  assert.ok(gone.startsWith('Baron Kent of Chatham did not come to the reckoning'));
  assert.ok(gone.includes('won no contests and lost two'));
});

test('the reckoning view orders the standing houses by place, then the fallen by their peak', () => {
  const view = reckoningView(facts, { styleOf });
  assert.equal(view.year, 1967);
  assert.deepEqual(view.epilogues.map((e) => e.house), ['Benjamin', 'Mercier', 'Kent']);
  assert.deepEqual(view.standings.map((r) => r.name), ['Marquis Benjamin of Bellechasse', 'Countess Mercier de Rimouski']);
  const html = reckoningHtml(view, { colourOf: () => '#123456' });
  assert.ok(html.includes('<h2 class="reckoning-title">The reckoning of 1967</h2>'));
  assert.ok(html.includes('the close of 1966'));
  assert.equal((html.match(/class="epilogue"/g) || []).length, 3);
  assert.ok(html.includes('<td>214</td><td>9</td>'));
});
