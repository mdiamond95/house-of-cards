// What a dispatch says (docs/STORY_DESIGN.md §3.2): names and sentences.
//
// Names. The first mention of a house in a dispatch is its full style
// ("Viscount Benjamin of Bellechasse"); every later mention in the same
// dispatch is its designation alone ("Bellechasse"). A Namer is made per
// dispatch and remembers who has been named. A style is the rank the house
// holds at the time plus the rest of its peerage, so an elevation shows.
// Only a house with no recorded peerage is ever called "House X".
//
// Sentences. A beat the engine wrote a line for keeps the engine's words,
// with the season prefix dropped and its house mentions renamed by the rule
// above. A beat merged from two events of one act (beats.js mergeActs), and an
// action that left no line, get a sentence made from the beat's typed facts
// alone (hard rule 1). Every sentence ends with a period.
//
// Pure: no DOM, no engine.

import { RANK_LADDER } from './beats.js';
import { inUnitWords, unitNoun } from './words.js';

const FEMALE = new Set(RANK_LADDER.map((forms) => forms[1]));
const PARTICLES = ['of ', 'de la ', 'de ', "d'", 'du '];

// A house's naming record from what the record holds: its peerage as last
// written, the rank word in it, and its seat's place where the engine recorded
// one. `title` is the peerage without its rank word; `designation` is the place.
export function houseStyle({ house, peerage = null, rank = null, place = null }) {
  if (!peerage) return null;
  const space = peerage.indexOf(' ');
  const lead = space === -1 ? peerage : peerage.slice(0, space);
  const known = RANK_LADDER.some((forms) => forms.includes(lead));
  const title = known ? peerage.slice(space + 1) : peerage;
  let designation = place || null;
  if (!designation) {
    let rest = title.startsWith(`${house} `) ? title.slice(house.length + 1) : title;
    for (const particle of PARTICLES) {
      if (rest.startsWith(particle)) { rest = rest.slice(particle.length); break; }
    }
    designation = rest || title;
  }
  return { title, designation, female: FEMALE.has(rank || lead) };
}

// A house's surname: its key less any numeral ("Sinclair 2" bears Sinclair).
// The numeral only tells the record's keys apart; a reader never sees it.
export function surnameOf(house) {
  return String(house).replace(/ \d+$/, '');
}

// What a reader calls each house in a list of them (the standings, the follow
// menu): its surname, or, where another house of the game bears the same
// surname, its peerage less the rank word ("Robinson of Hamilton" and
// "Robinson of Brampton"), which tells the two apart without a numeral.
export function readerNames(houses, styleOf = () => null) {
  const bearers = new Map();
  for (const house of houses) bearers.set(surnameOf(house), (bearers.get(surnameOf(house)) || 0) + 1);
  return new Map(houses.map((house) => {
    const s = styleOf(house);
    return [house, bearers.get(surnameOf(house)) > 1 && s ? s.title : surnameOf(house)];
  }));
}

export function rankForm(index, female) {
  const forms = RANK_LADDER[Math.max(0, Math.min(RANK_LADDER.length - 1, index))];
  return forms[female ? 1 : 0];
}

// Names houses within one dispatch. `styleOf(house)` returns a houseStyle
// record or null; `rankOf(house)` the rank index at the time.
export class Namer {
  constructor(styleOf, rankOf = () => 0) {
    this.styleOf = styleOf;
    this.rankOf = rankOf;
    this.seen = new Set();
  }

  style(house) {
    const s = this.styleOf(house);
    return s ? `${rankForm(this.rankOf(house), s.female)} ${s.title}` : `House ${surnameOf(house)}`;
  }

  designation(house) {
    const s = this.styleOf(house);
    return s ? s.designation : `House ${surnameOf(house)}`;
  }

  // The next mention of `house`: its full style the first time, then its place.
  name(house) {
    if (this.seen.has(house)) return this.designation(house);
    this.seen.add(house);
    return this.style(house);
  }

  // An engine line with its house mentions renamed. Every rank form of each
  // house's title is looked for, since a line written mid-elevation can carry
  // either rank; the first mention in the dispatch keeps the engine's words.
  rewrite(text, houses) {
    const matches = [];
    for (const house of new Set(houses)) {
      const s = this.styleOf(house);
      if (!s) continue;
      for (const forms of RANK_LADDER) {
        for (const form of forms) {
          const needle = `${form} ${s.title}`;
          let at = text.indexOf(needle);
          while (at !== -1) {
            matches.push({ start: at, end: at + needle.length, house });
            at = text.indexOf(needle, at + needle.length);
          }
        }
      }
    }
    matches.sort((a, b) => a.start - b.start || b.end - a.end);
    let out = '';
    let cursor = 0;
    for (const m of matches) {
      if (m.start < cursor) continue;
      out += text.slice(cursor, m.start);
      if (this.seen.has(m.house)) out += this.designation(m.house);
      else {
        this.seen.add(m.house);
        out += text.slice(m.start, m.end);
      }
      cursor = m.end;
    }
    return out + text.slice(cursor);
  }
}

// A sentence told on its own house's card (Phase V3): the card's header carries
// the peerage, so the sentence starts at the verb and does not say the name
// again. "Baron Ritchie of Frontenac Islands sets out to open Cumberland—
// Colchester." becomes "Sets out to open Cumberland—Colchester."; a sentence
// with two houses for its subject, "X and Y enter into a compact.", becomes
// "Enters into a compact with Y."; and a mention of the house elsewhere in the
// sentence ("heir to Baron Ritchie of Frontenac Islands") becomes "the house".
// Other houses in the sentence keep their names, and a sentence that does not
// name the house is returned as it is.
const JOINT = {
  'enter into': (rest, other) => `Enters into${rest.replace(/\.$/, '')} with ${other}.`,
  'fall out': (rest, other) => `Falls out with ${other}${rest}`,
};

const escapeRe = (text) => text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');

export function verbFirst(text, house, styleOf = () => null) {
  const s = styleOf(house);
  const names = [`House ${surnameOf(house)}`];
  if (s) for (const forms of RANK_LADDER) for (const form of forms) names.push(`${form} ${s.title}`);
  names.sort((a, b) => b.length - a.length);
  const self = names.find((name) => text.includes(name));
  if (!self) return text;
  const joint = (other, verb, tail) => JOINT[verb](tail, other);
  if (text.startsWith(`${self} `)) {
    const rest = text.slice(self.length + 1);
    // Two houses for the subject, this one first.
    const both = rest.match(/^and (.+?) (enter into|fall out)\b(.*)$/);
    if (both) return joint(both[1], both[2], both[3]);
    return capitalise(rest.split(self).join('the house'));
  }
  // Two houses for the subject, this one second.
  const second = text.match(new RegExp(`^(.+?) and ${escapeRe(self)} (enter into|fall out)\\b(.*)$`));
  if (second) return joint(second[1], second[2], second[3]);
  const letter = text.match(new RegExp(`^A letter from ${escapeRe(self)} gives offence to (.+)\\.$`));
  if (letter) return `Gives offence to ${letter[1]} by letter.`;
  return text.split(self).join('the house');
}

export function capitalise(text) {
  return text.charAt(0).toUpperCase() + text.slice(1);
}

export function period(text) {
  const trimmed = text.trim();
  return /[.!?]$/.test(trimmed) ? trimmed : `${trimmed}.`;
}

function unperiod(text) {
  return text.trim().replace(/\.$/, '');
}

export function listWords(items) {
  if (items.length <= 1) return items.join('');
  if (items.length === 2) return `${items[0]} and ${items[1]}`;
  return `${items.slice(0, -1).join(', ')} and ${items[items.length - 1]}`;
}

const FAILED = {
  Expand: 'tries to expand and fails',
  'Propose compact': 'proposes a compact and is refused',
  'Petition elevation': 'petitions the Crown for elevation and is refused',
  'Purchase riding': 'tries to buy a riding and fails',
  'Marriage alliance': 'seeks a marriage alliance and is refused',
  'Cede / swap': 'offers a cession and is refused',
  Reconcile: 'seeks a reconciliation and is refused',
  Dispute: 'presses a claim and is rebuffed',
  Absorb: 'tries to absorb a neighbour and fails',
  'Challenge (11b)': 'makes a challenge and fails',
};

const PLAIN = {
  invest: 'invests in its estates',
  cultivate: 'cultivates influence',
  consolidate: 'rests and consolidates',
  name_heir: 'names an heir',
};

// The engine's own line for a beat, renamed and without its season prefix.
function engineLine(beat, namer) {
  const prefix = `Season ${beat.turn} · `;
  const line = beat.line.startsWith(prefix) ? beat.line.slice(prefix.length) : beat.line;
  return capitalise(namer.rewrite(inUnitWords(line), beat.houses || []));
}

function ridingNames(feds, ridingName) {
  return feds.map((fed) => ridingName(fed) || fed);
}

// Transfers whose engine line already names both houses (Phase D1): a sale,
// an absorption, a cession under a standing claim and a challenge won. Any
// other riding passing between two houses is told from its facts, so the
// sentence says who received it.
const NAMES_BOTH = ['purchase', 'absorption', 'cession under claim', 'challenge'];

// Why a house failed, from the record's reason (Phase D1). A house that falls
// to the house that took its seat has its own line, which names that house.
const FAILED_BECAUSE = {
  'no successor': 'its line ended with no successor',
  'cohesion collapse': 'its cohesion collapsed',
};

function failure(beat, namer) {
  const because = FAILED_BECAUSE[beat.outcome];
  return because ? `${namer.name(beat.houses[0])} fails, for ${because}; its ${unitNoun(2)} return to the Crown`
    : `${namer.name(beat.houses[0])} fails; its ${unitNoun(2)} return to the Crown`;
}

// A riding passing between two houses, or to the Crown, from its facts.
function transfer(beat, namer, ridingName) {
  const riding = listWords(ridingNames(beat.ridings || [], ridingName)) || `a ${unitNoun(1)}`;
  const reason = beat.outcome ? ` (${beat.outcome})` : '';
  const giver = namer.name(beat.houses[0]);
  if (beat.kind === 'riding_lost') return `${giver} gives up ${riding} to the Crown${reason}`;
  return `${giver} gives up ${riding} to ${namer.name(beat.houses[1])}${reason}`;
}

// The allies a contest called (Phase D1), in one sentence: who stood with
// each side, and how many declined.
export function alliesSentence(allies, namer) {
  const sides = new Map();
  let declined = 0;
  for (const a of allies) {
    if (!a.joins) { declined += 1; continue; }
    if (!sides.has(a.party)) sides.set(a.party, []);
    sides.get(a.party).push(a.house);
  }
  const clauses = [...sides.entries()].map(([party, houses], i) => {
    const names = listWords(houses.map((h) => namer.designation(h)));
    return i === 0 ? `${names} stood with ${namer.designation(party)}` : `${names} with ${namer.designation(party)}`;
  });
  const refusals = declined
    ? `${numberWords(declined)} ${declined === 1 ? 'ally' : 'allies'} declined to stand` : '';
  if (!clauses.length) return capitalise(refusals);
  return capitalise(clauses.join(', and ')) + (declined ? `; ${refusals}` : '');
}

const COUNT_WORDS = ['no', 'one', 'two', 'three', 'four', 'five', 'six', 'seven', 'eight', 'nine', 'ten'];

function numberWords(n) {
  return n < COUNT_WORDS.length ? COUNT_WORDS[n] : String(n);
}

// A crisis (Phase D1): the event, who led and who resisted — the first few of
// each camp by name, in `order`, and how many more — who carried it, and, for
// a crisis that runs for years, that this is the first of them.
const CRISIS_NAMED = 3;

function camp(houses, namer, order) {
  if (!houses.length) return 'none';
  const sorted = order(houses);
  const named = sorted.slice(0, CRISIS_NAMED).map((h) => namer.designation(h));
  const more = sorted.length - named.length;
  return more > 0 ? `${named.join(', ')} and ${numberWords(more)} other${more === 1 ? '' : 's'}` : listWords(named);
}

// Land opened (Phase D1): the jurisdiction, what it became, and how many
// ridings — named when there are few; the map shows the rest.
const ACCESSION_NAMED = 4;

export function accessionSentence(beat, ridingName) {
  const w = beat.world;
  const feds = beat.ridings || [];
  const n = feds.length;
  const names = n <= ACCESSION_NAMED ? `: ${listWords(ridingNames(feds, ridingName))}` : '';
  const ridings = `${numberWords(n)} ${unitNoun(n)}`;
  return w.change === 'extension'
    ? `${w.jurisdiction} becomes a province, and the Crown may found in ${ridings}${names}.`
    : `${w.jurisdiction} comes under Canada as a ${w.status}, opening ${ridings}${names}.`;
}

// A crisis headline opens with the event's article. The deck's titles mostly
// have none ("North-West Resistance"), so "The" is added, except to a title
// that has one already or names something that takes none: a single word
// ("Confederation") or a numbered act ("Regulation 17").
export function eventTitle(name) {
  if (!name) return 'A crisis';
  if (/^(The|A|An) /.test(name) || !name.includes(' ') || /\d/.test(name)) return name;
  return `The ${name}`;
}

export function crisisSentence(beat, namer, order = (houses) => houses) {
  const w = beat.world;
  const carried = { lead: 'those who lead carry it', resist: 'those who resist carry it' }[w.carried]
    || 'neither side carries it';
  const span = w.years ? ` It is the first of ${numberWords(w.years)} years.` : '';
  return `${eventTitle(w.event)} divides the peerage: ${camp(w.lead, namer, order)} lead;`
    + ` ${camp(w.resist, namer, order)} resist; ${carried}.${span}`;
}

// A sentence for a beat. `ridingName(fed)` names a riding; `order(houses)`
// puts a crisis's camps in the order to name them (standings, in a dispatch).
export function sentence(beat, namer, ridingName = (fed) => fed, { order } = {}) {
  if (beat.merge) return period(mergedSentence(beat, namer, ridingName));
  if (beat.kind === 'crisis' && beat.world) return crisisSentence(beat, namer, order);
  if (beat.kind === 'accession' && beat.world) return accessionSentence(beat, ridingName);
  if (beat.kind === 'removed' && (beat.houses || []).length) return period(failure(beat, namer));
  if ((beat.kind === 'riding_passes' && (beat.houses || []).length >= 2 && !NAMES_BOTH.includes(beat.outcome))
      || (beat.kind === 'riding_lost' && (beat.houses || []).length)) {
    return period(transfer(beat, namer, ridingName));
  }
  if (beat.line) return period(engineLine(beat, namer));
  const who = beat.houses && beat.houses.length ? namer.name(beat.houses[0]) : 'A house';
  if (beat.kind === 'failed') return `${who} ${FAILED[beat.outcome] || 'tries and fails'}.`;
  if (beat.kind === 'correspondence' && beat.outcome === 'failed') {
    return `${who} writes, and no correspondence follows.`;
  }
  if (PLAIN[beat.kind]) return `${who} ${PLAIN[beat.kind]}.`;
  return `${who}: ${beat.kind.replace(/_/g, ' ')}.`;
}

function part(beat, kind) {
  return (beat.parts || []).find((p) => p.kind === kind);
}

function mergedSentence(beat, namer, ridingName) {
  const parts = beat.parts || [];
  switch (beat.merge) {
    case 'cession': {
      const transfer = part(beat, 'riding_passes');
      const [giver, receiver] = transfer.houses;
      const riding = listWords(ridingNames(transfer.ridings || [], ridingName)) || `a ${unitNoun(1)}`;
      const g = namer.name(giver);
      const r = namer.name(receiver);
      return `${g} cedes ${riding} to ${r}, settling the grievance between them`;
    }
    case 'partition': {
      const partition = part(beat, 'partition');
      const succession = part(beat, 'succession_clean');
      const [parent, cadet] = partition.houses;
      const lead = succession && succession.line
        ? unperiod(engineLine(succession, namer))
        : `${namer.name(parent)} passes to its heir`;
      const taken = ridingNames(partition.ridings || [], ridingName);
      const taking = taken.length ? `, taking ${listWords(taken)}` : '';
      return `${lead}, and a junior line is founded as ${namer.name(cadet)} by partition from`
        + ` ${namer.name(parent)}${taking}`;
    }
    case 'disorderly': {
      const succession = part(beat, 'succession_disorderly');
      const house = succession.houses[0];
      let text = succession.line ? unperiod(engineLine(succession, namer)) : `${namer.name(house)} passes in disorder`;
      const lost = part(beat, 'riding_lost');
      const quarrel = part(beat, 'quarrel');
      const clauses = [];
      if (lost) clauses.push(`gives up ${listWords(ridingNames(lost.ridings || [], ridingName)) || `a ${unitNoun(1)}`} to the Crown`);
      if (quarrel) clauses.push(`falls out with ${namer.name(quarrel.houses[1])}`);
      if (clauses.length) text += `; ${namer.designation(house)} ${listWords(clauses)}`;
      return text;
    }
    case 'collapse': {
      const removed = part(beat, 'removed');
      const first = sentence(parts[0], namer, ridingName);
      const because = FAILED_BECAUSE[removed.outcome];
      return `${unperiod(first)}; then ${namer.name(removed.houses[0])} fails${because ? `, for ${because}` : ''},`
        + ` and its ${unitNoun(2)} return to the Crown`;
    }
    case 'claim': {
      const told = parts.map((p) => unperiod(sentence(p, namer, ridingName))).join('; ');
      return beat.allies && beat.allies.length ? `${told}. ${alliesSentence(beat.allies, namer)}` : told;
    }
    case 'contest': {
      const quarrel = part(beat, 'quarrel');
      const [loser, winner] = quarrel.houses;
      const expansion = part(beat, 'expansion');
      if (expansion) {
        const riding = listWords(ridingNames(expansion.ridings || [], ridingName)) || `a ${unitNoun(1)}`;
        const w = namer.name(winner);
        return `${w} takes ${riding} from under ${namer.name(loser)}, who carries the grievance`;
      }
      const line = quarrel.line ? unperiod(engineLine(quarrel, namer)) : `${namer.name(loser)} loses a contested ${unitNoun(1)} to ${namer.name(winner)}`;
      return `${line}, and carries the grievance`;
    }
    default:
      return parts.map((p) => unperiod(sentence(p, namer, ridingName))).join('; ');
  }
}
