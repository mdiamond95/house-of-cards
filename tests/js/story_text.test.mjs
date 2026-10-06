// web/story/text.js: names (full style first, designation after) and sentences.
import { test } from 'node:test';
import assert from 'node:assert/strict';

import { Namer, houseStyle, listWords, period, rankForm, sentence } from '../../web/story/text.js';

const styles = {
  Benjamin: houseStyle({ house: 'Benjamin', peerage: 'Marquis Benjamin of Bellechasse', rank: 'Marquis', place: 'Bellechasse' }),
  Mercier: houseStyle({ house: 'Mercier', peerage: 'Viscount Mercier de Rimouski', rank: 'Viscount', place: 'Rimouski' }),
  'Benjamin 2': houseStyle({ house: 'Benjamin 2', peerage: "Viscount Benjamin of La Pointe-de-l'Île", rank: 'Viscount', place: "La Pointe-de-l'Île" }),
  'Fitzroy-Crane': houseStyle({ house: 'Fitzroy-Crane', peerage: 'Marchioness Fitzroy-Crane of Saanich', rank: 'Marchioness' }),
  'Letendre dit Batoche': houseStyle({ house: 'Letendre dit Batoche', peerage: 'Baron Letendre dit Batoche de la Rivière-Rouge', rank: 'Baron' }),
};
const styleOf = (h) => styles[h] || null;

test('a style is the rank at the time and the rest of the peerage; the designation is the place', () => {
  assert.deepEqual(styles.Benjamin, { title: 'Benjamin of Bellechasse', designation: 'Bellechasse', female: false });
  assert.equal(styles['Fitzroy-Crane'].designation, 'Saanich', 'derived from the peerage when no place is recorded');
  assert.equal(styles['Fitzroy-Crane'].female, true);
  assert.equal(styles['Letendre dit Batoche'].designation, 'Rivière-Rouge');
  assert.equal(houseStyle({ house: 'X', peerage: null }), null);
  assert.equal(rankForm(1, false), 'Viscount');
  assert.equal(rankForm(3, true), 'Marchioness');
  const namer = new Namer(styleOf, (h) => ({ Benjamin: 1 }[h] || 0));
  assert.equal(namer.style('Benjamin'), 'Viscount Benjamin of Bellechasse', 'an earlier rank shows');
});

test('first mention full, later mentions the designation; no "House X" where a style exists', () => {
  const namer = new Namer(styleOf, () => 2);
  assert.equal(namer.name('Benjamin'), 'Earl Benjamin of Bellechasse');
  assert.equal(namer.name('Benjamin'), 'Bellechasse');
  assert.equal(namer.name('Nobody'), 'House Nobody');
});

test('engine lines are renamed across a dispatch, whatever rank they were written at', () => {
  const namer = new Namer(styleOf);
  assert.equal(
    namer.rewrite('Viscount Benjamin of Bellechasse is raised to Marquis.', ['Benjamin']),
    'Viscount Benjamin of Bellechasse is raised to Marquis.',
  );
  assert.equal(
    namer.rewrite('Marquis Benjamin of Bellechasse and Viscount Mercier de Rimouski enter into a compact.', ['Benjamin', 'Mercier']),
    'Bellechasse and Viscount Mercier de Rimouski enter into a compact.',
  );
  assert.equal(
    namer.rewrite("Viscount Benjamin of La Pointe-de-l'Île takes X.", ['Benjamin 2', 'Benjamin']),
    "Viscount Benjamin of La Pointe-de-l'Île takes X.",
    'a cadet whose title starts like its parent\'s is told apart',
  );
});

test('sentences: the engine line without its season, or one made from typed facts; always a period', () => {
  const namer = new Namer(styleOf);
  assert.equal(sentence({ turn: 4, kind: 'expansion', houses: ['Mercier'], line: 'Season 4 · Viscount Mercier de Rimouski takes Repentigny' }, namer),
    'Viscount Mercier de Rimouski takes Repentigny.');
  assert.equal(sentence({ turn: 4, kind: 'failed', houses: ['Mercier'], outcome: 'Expand' }, namer),
    'Rimouski tries to expand and fails.');
  assert.equal(period('Done!'), 'Done!');
  assert.equal(listWords(['a', 'b', 'c']), 'a, b and c');
});

test('merged acts are one sentence naming every party', () => {
  const ranks = { Mercier: 1, Benjamin: 1 };
  const fresh = () => new Namer(styleOf, (h) => ranks[h] || 0);
  const ridingName = (fed) => ({ 24001: 'Berthier—Maskinongé', 24002: 'Joliette', 24003: 'Repentigny' }[fed]);
  const cession = {
    turn: 9, kind: 'riding_passes', merge: 'cession', houses: ['Mercier', 'Benjamin'],
    parts: [
      { turn: 9, kind: 'riding_passes', houses: ['Mercier', 'Benjamin'], ridings: ['24001'], outcome: 'cession' },
      { turn: 9, kind: 'reconciled', houses: ['Mercier', 'Benjamin'], outcome: 'cession' },
    ],
  };
  assert.equal(sentence(cession, fresh(), ridingName),
    'Viscount Mercier de Rimouski cedes Berthier—Maskinongé to Viscount Benjamin of Bellechasse, settling the grievance between them.');
  const partition = {
    turn: 9, kind: 'partition', merge: 'partition', houses: ['Benjamin', 'Benjamin 2'],
    parts: [
      { turn: 9, kind: 'partition', houses: ['Benjamin', 'Benjamin 2'], ridings: ['24002', '24003'] },
      { turn: 9, kind: 'succession_clean', houses: ['Benjamin'], line: 'Season 9 · Emanuel Benjamin succeeds to Viscount Benjamin of Bellechasse.' },
    ],
  };
  assert.equal(sentence(partition, fresh(), ridingName),
    "Emanuel Benjamin succeeds to Viscount Benjamin of Bellechasse, and a junior line is founded as Baron Benjamin of La Pointe-de-l'Île by partition from Bellechasse, taking Joliette and Repentigny.");
  const disorderly = {
    turn: 9, kind: 'succession_disorderly', merge: 'disorderly', houses: ['Mercier', 'Benjamin'],
    parts: [
      { turn: 9, kind: 'succession_disorderly', houses: ['Mercier'], line: 'Season 9 · Viscount Mercier de Rimouski passes in disorder to Jean Mercier.' },
      { turn: 9, kind: 'riding_lost', houses: ['Mercier'], ridings: ['24003'], outcome: 'disorderly succession' },
      { turn: 9, kind: 'quarrel', houses: ['Mercier', 'Benjamin'], outcome: 'disorderly succession' },
    ],
  };
  assert.equal(sentence(disorderly, fresh(), ridingName),
    'Viscount Mercier de Rimouski passes in disorder to Jean Mercier; Rimouski gives up Repentigny to the Crown and falls out with Viscount Benjamin of Bellechasse.');
});
