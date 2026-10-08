// web/story/words.js: what a unit of the map is called (the hex trial).
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

import { RIDING, inUnitWords, unitNoun, unitWord, useUnitWord } from '../../web/story/words.js';
import { Story } from '../../web/story/dispatch.js';
import { houseLine, yearCounts } from '../../web/story/round.js';
import { sentence, Namer } from '../../web/story/text.js';
import { epilogue } from '../../web/story/reckoning.js';

const weights = JSON.parse(readFileSync(new URL('../../web/story/weights.json', import.meta.url), 'utf8'));
const HOLDING = { singular: 'holding', plural: 'holdings' };

test('a game says riding unless its index names another word', () => {
  useUnitWord(null);
  assert.equal(unitWord(), RIDING);
  assert.equal(unitNoun(1), 'riding');
  assert.equal(unitNoun(3), 'ridings');
  assert.equal(inUnitWords('loses a riding; its ridings return'), 'loses a riding; its ridings return');
  useUnitWord(HOLDING);
  assert.equal(unitNoun(1), 'holding');
  assert.equal(unitNoun(0), 'holdings');
  useUnitWord({ singular: 'holding' });
  assert.equal(unitWord(), RIDING, 'half a word restores ridings');
});

test('an engine line is put in the set\'s words, whole words only, keeping a capital', () => {
  useUnitWord(HOLDING);
  assert.equal(inUnitWords('Riding lost; its ridings return; Ridingsville stands'),
    'Holding lost; its holdings return; Ridingsville stands');
  useUnitWord(null);
});

test('a Story sets the word from its options, and a new Story without one restores it', () => {
  new Story({ weights, unitWord: HOLDING });
  assert.equal(unitNoun(2), 'holdings');
  new Story({ weights });
  assert.equal(unitNoun(2), 'ridings');
});

test('counts, cards and epilogues use the word', () => {
  new Story({ weights, unitWord: HOLDING });
  assert.equal(houseLine({ ridings: 1, rank: 'Baron', place: null, of: 0 }), '1 holding · Baron');
  const counts = yearCounts([{ beat: { kind: 'expansion', houses: ['A'], owners: { 35001: 'A' } } }], {});
  assert.ok(counts.every((c) => !/riding/.test(c.text)), JSON.stringify(counts));
  const namer = new Namer(() => null);
  const text = sentence({ kind: 'riding_lost', houses: ['A'], ridings: [], turn: 2 }, namer, () => null);
  assert.match(text, /a holding to the Crown/);
  const fact = {
    house: 'A', rank: 'Baron', status: 'active', place: 1, ridings: 2, peak_year: 1900,
    peak_prestige: 50, contests_won: 0, contests_lost: 0, successions: 0,
  };
  assert.match(epilogue(fact, { styleOf: () => null, houses: 9 }), /of two holdings\. .*no contest for a holding/);
  new Story({ weights });
  assert.match(epilogue(fact, { styleOf: () => null, houses: 9 }), /of two ridings\./);
});
