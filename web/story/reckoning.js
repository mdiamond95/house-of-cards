// The reckoning (docs/STORY_DESIGN.md §5, Phase D1): after the last turn of a
// game played with a world calendar, the final table and, for every house ever
// of the top eight, a short epilogue built by template from the reckoning
// record's facts alone (hard rule 1) — its place, rank and ridings at the end,
// its highest prestige and the year of it, the contests it won and lost, and
// its successions. Nothing here reads the engine or invents a fact.
//
// Pure: no DOM, no engine.

import { rankIndex } from './beats.js';
import { rankForm } from './text.js';

const ORDINALS = ['zeroth', 'first', 'second', 'third', 'fourth', 'fifth', 'sixth', 'seventh',
  'eighth', 'ninth', 'tenth', 'eleventh', 'twelfth', 'thirteenth', 'fourteenth', 'fifteenth',
  'sixteenth', 'seventeenth', 'eighteenth', 'nineteenth', 'twentieth'];
const WORDS = ['no', 'one', 'two', 'three', 'four', 'five', 'six', 'seven', 'eight', 'nine', 'ten',
  'eleven', 'twelve'];

function ordinalWord(n) {
  if (n < ORDINALS.length) return ORDINALS[n];
  const tail = n % 100 >= 11 && n % 100 <= 13 ? 'th' : ({ 1: 'st', 2: 'nd', 3: 'rd' }[n % 10] || 'th');
  return `${n}${tail}`;
}

function word(n) {
  return n < WORDS.length ? WORDS[n] : String(n);
}

function count(n, noun) {
  return `${word(n)} ${noun}${n === 1 ? '' : 's'}`;
}

// A house's full style at the reckoning: its last rank and its title.
export function styleAt(house, rank, styleOf) {
  const s = styleOf(house);
  return s ? `${rankForm(rankIndex(rank), s.female)} ${s.title}` : `House ${house}`;
}

// One house's epilogue, from its facts in the reckoning record.
export function epilogue(fact, { styleOf, houses }) {
  const name = styleAt(fact.house, fact.rank, styleOf);
  const s = styleOf(fact.house);
  const it = s ? s.designation : fact.house;
  const rankWord = rankForm(rankIndex(fact.rank), s ? s.female : false);
  const article = /^[AEIOU]/.test(rankWord) ? 'an' : 'a';
  const opening = fact.status === 'active' && fact.place !== null
    ? `${name} comes to the reckoning ${ordinalWord(fact.place)} of ${houses}, ${article} ${rankWord}`
      + ` of ${count(fact.ridings, 'riding')}.`
    : `${name} did not come to the reckoning: the house was gone before it.`;
  const peak = `${it} stood highest in ${fact.peak_year}, at a prestige of ${fact.peak_prestige}.`;
  const fought = fact.contests_won + fact.contests_lost === 0
    ? 'It fought no contest for a riding.'
    : `It won ${count(fact.contests_won, 'contest')} and lost ${fact.contests_lost === 0 ? 'none' : word(fact.contests_lost)}.`;
  const line = fact.successions === 0
    ? 'Its line passed through no succession.'
    : `Its line passed through ${count(fact.successions, 'succession')}.`;
  return `${opening} ${peak} ${fought} ${line}`;
}

// The reckoning as the pages show it: the final table, and the epilogues —
// houses still standing by final place, then the fallen by their peak.
export function reckoningView(facts, { styleOf }) {
  const houses = facts.standings.length;
  const standings = facts.standings.map((row) => ({
    ...row, name: styleAt(row.house, row.rank, styleOf),
  }));
  const ordered = [...facts.houses].sort((a, b) => {
    const pa = a.place === null ? Infinity : a.place;
    const pb = b.place === null ? Infinity : b.place;
    if (pa !== pb) return pa - pb;
    if (a.peak_prestige !== b.peak_prestige) return b.peak_prestige - a.peak_prestige;
    return a.house < b.house ? -1 : a.house > b.house ? 1 : 0;
  });
  return {
    year: facts.reckoned,
    lastYear: facts.last_year,
    standings,
    epilogues: ordered.map((fact) => ({
      house: fact.house,
      name: styleAt(fact.house, fact.rank, styleOf),
      place: fact.place,
      text: epilogue(fact, { styleOf, houses }),
    })),
  };
}
