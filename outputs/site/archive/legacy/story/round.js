// The year as a round of turns (docs/STORY_DESIGN.md §3.6, Phase V2).
//
// The engine plays a year in a fixed order: the world's turn (land opened,
// events still running, crises, and the borders warming or cooling before
// anyone acts), then each active house in turn, then the close (the Crown's
// founding roll and the standings). A game played with rules 1.0's
// `round_record` says which of those every event was recorded in (the beat's
// `part`: "world", the house whose turn it is, or "close") and keeps the
// playing order in each season record (`order`). This module tells a year
// that way, one turn at a time. A game without the fields keeps the
// year-at-a-time dispatch (dispatch.js), and nothing here is used for it.
//
//   buildRound   one year's round: its parts in playing order, each with its
//                told beats, its weight, its pace and the board after it
//   entryPace    quiet, routine, notable or pause, from what a beat is
//                (weights.json `pace`); a part takes its heaviest beat's
//   stopsAuto    whether a part stops Auto (its pace, or the followed house)
//   autoMs       how long Auto shows a part, at a speed, quiet turns shown or
//                skipped; autoLength sums a game
//   yearCounts, countLine
//                what the year did, in counts, for the close
//   stripOf      the turn-order strip: each chip's state
//   houseCard    what a house's turn says: what it did, what was done to it,
//                where its scheme stands, and its ridings, rank and place
//   holderAt, heirAt, houseSheet
//                a house's sheet at a turn, from the record's people
//   placeLabels  house names on the map: by priority, never overlapping
//
// Pure: no DOM, no engine, no clock, no randomness.

import { compareText } from './beats.js';
import { applyBeats } from './standings.js';
import { verbFirst } from './text.js';

// Four paces (Phase V3), lowest first. Which beat kinds belong to which, how
// long Auto shows each and how long the camera takes to reach it are in
// weights.json (`pace`), not here.
//   quiet    a house kept to its estates, a scheme's middle step, a letter, a
//            response to an ordinary event: no camera move, a pulse at the seat
//   routine  land gained or given up without a contest, a scheme begun,
//            answered or abandoned, an heir named or come of age, a compact or
//            a match: the camera flies there
//   notable  a contest decided, a riding passing between houses, a succession,
//            an elevation, a quarrel or a reconciliation, a partition, a founding
//   pause    a fall or removal, a crisis, a chapter close, the reckoning, and
//            any beat at the pause weight: Auto stops
export const PACES = ['quiet', 'routine', 'notable', 'pause'];

export const ERA_RESPONSES = ['era_response', 'major_response'];

// Next year plays a round's remaining turns at QUICK_MS each.
export const QUICK_MS = 260;

const RANK = { quiet: 0, routine: 1, notable: 2, pause: 3 };

export function paceRank(pace) {
  return RANK[pace];
}

function higher(a, b) {
  return RANK[b] > RANK[a] ? b : a;
}

const KIND_PACES = new WeakMap();

// weights.json's `pace.kinds` as a Map kind -> pace.
function kindTable(pace) {
  let table = KIND_PACES.get(pace);
  if (!table) {
    table = new Map();
    for (const name of ['routine', 'notable', 'pause']) {
      for (const kind of pace.kinds[name] || []) table.set(kind, name);
    }
    KIND_PACES.set(pace, table);
  }
  return table;
}

// The pace of one told beat ({ beat, weight }): pause at or above the pause
// weight, else by what the beat is; a merged act takes its heaviest part's.
export function entryPace(entry, { pace, thresholds }) {
  if (entry.weight >= thresholds.pause) return 'pause';
  const table = kindTable(pace);
  const beat = entry.beat;
  let best = table.get(beat.kind) || 'quiet';
  if (beat.merge) for (const p of beat.parts) best = higher(best, table.get(p.kind) || 'quiet');
  return best;
}

function heavier(a, b) {
  return a === null || b.weight > a.weight || (b.weight === a.weight && b.beat.seq < a.beat.seq) ? b : a;
}

function bySeq(a, b) {
  return a.beat.seq - b.beat.seq;
}

// One year's round. `entries` are the year's told beats ({ beat, weight,
// text, alone }, every merged beat of the turn); `playing` the order the
// house turns were played in; `deck` the events of the year by name, which
// the world's turn announces; `board` the board before the year.
//
// Returns { turn, parts, stray }. Each part is
//   { id, kind: 'world' | 'house' | 'close', house, entries (in record
//     order), weight, pace, boardBefore, board, gone, deck }
// `gone` marks a house removed earlier in the year, before its turn came.
// The world's turn is at least routine when it announces anything. The close
// carries the standings and the year in brief, and is shown as long as the
// year's headline merits (at least routine, at most notable: the turn that made
// the headline has stopped Auto already); one that ends a chapter or the
// game (`closing`) is a pause. `counts` is
// what the year did (yearCounts) and `headlinePace` the pace of the year's
// headline, which the close uses to decide which to lead with.
// `stray` lists entries whose part is not in the round (none, for a record
// written with round_record; the tests hold it to that).
export function buildRound({
  turn, entries, playing, deck = [], board, thresholds, pace, closing = false, headlinePace = 'quiet',
}) {
  const groups = new Map([['world', []], ...playing.map((h) => [h, []]), ['close', []]]);
  const stray = [];
  for (const entry of entries) {
    const part = entry.beat.part;
    if (part !== undefined && groups.has(part)) groups.get(part).push(entry);
    else stray.push(entry);
  }
  const parts = [];
  let current = board;
  const removedSoFar = new Set(board.removed || []);
  for (const [id, list] of groups) {
    const kind = id === 'world' || id === 'close' ? id : 'house';
    const sorted = [...list].sort(bySeq);
    const weight = sorted.reduce((m, e) => Math.max(m, e.weight), 0);
    let partPace = sorted.reduce((m, e) => higher(m, entryPace(e, { pace, thresholds })), 'quiet');
    if (kind === 'world' && (deck.length || sorted.length)) partPace = higher(partPace, 'routine');
    if (kind === 'close') partPace = closing ? 'pause' : higher(higher(partPace, 'routine'), headlinePace === 'pause' ? 'notable' : headlinePace);
    const boardBefore = current;
    current = applyBeats(current, sorted.map((e) => e.beat));
    const gone = kind === 'house' && removedSoFar.has(id) && !sorted.length;
    for (const h of current.removed) removedSoFar.add(h);
    parts.push({
      id, kind, house: kind === 'house' ? id : null, entries: sorted, weight, pace: partPace,
      boardBefore, board: current, gone, deck: kind === 'world' ? deck : [],
    });
  }
  const counts = yearCounts(entries, board.owners);
  return { turn, parts, stray, counts, countLine: countLine(counts), headlinePace };
}

// What the year did, from the round just played: [{ key, n, text }], nothing
// at zero, in the order a reader would weigh them. Ridings are counted by the
// moves the record gives, a founding's own ground aside; a riding that moves
// twice counts twice. `owners` is the board before the year.
export function yearCounts(entries, owners = {}) {
  const held = { ...owners };
  const n = { taken: 0, hands: 0, contests: 0, successions: 0, elevations: 0, founded: 0, fallen: 0 };
  const ordered = [...entries].sort(bySeq);
  for (const { beat } of ordered) {
    for (const leaf of beat.merge ? beat.parts : [beat]) {
      const seating = leaf.kind === 'founding' || leaf.kind === 'partition';
      for (const [fed, to] of Object.entries(leaf.owners || {})) {
        const from = held[fed] || null;
        if (!seating && to) {
          if (!from) n.taken += 1;
          else if (from !== to) n.hands += 1;
        }
        held[fed] = to || null;
      }
      if (['contest_won', 'contest_lost', 'dispute_won'].includes(leaf.kind) && leaf.outcome !== 'rout') n.contests += 1;
      if (leaf.kind === 'succession_clean' || leaf.kind === 'succession_disorderly') n.successions += 1;
      if (leaf.kind === 'elevation') n.elevations += 1;
      if (seating) n.founded += 1;
      if (leaf.kind === 'removed' || leaf.kind === 'fallen') n.fallen += 1;
    }
  }
  const plural = (count, one, many) => `${count} ${count === 1 ? one : many}`;
  return [
    ['taken', plural(n.taken, 'riding taken', 'ridings taken')],
    ['hands', plural(n.hands, 'riding changing hands', 'ridings changing hands')],
    ['contests', plural(n.contests, 'contest decided', 'contests decided')],
    ['successions', plural(n.successions, 'succession', 'successions')],
    ['elevations', plural(n.elevations, 'elevation', 'elevations')],
    ['founded', plural(n.founded, 'house founded', 'houses founded')],
    ['fallen', plural(n.fallen, 'house fallen', 'houses fallen')],
  ].filter(([key]) => n[key] > 0).map(([key, text]) => ({ key, n: n[key], text }));
}

// The counts as one line: "3 ridings taken · 1 contest decided".
export function countLine(counts) {
  return counts.map((c) => c.text).join(' · ');
}

// Whether a part stops Auto: a pause-weight turn, and for a followed house its
// own turns and the turns aimed at it (whose beats name it).
export function stopsAuto(part, { follow = null } = {}) {
  if (part.pace === 'pause') return true;
  if (!follow || part.kind !== 'house') return false;
  if (part.house === follow) return true;
  return part.entries.some((e) => (e.beat.houses || []).includes(follow));
}

// How long Auto shows a part, in ms, at `speed` (1, 2 or 4), from weights.json's
// `pace.hold_ms` (`hold`). A quiet house turn takes no time at all when quiet
// turns are skipped.
export function autoMs(part, { hold, skipQuiet = false, speed = 1 }) {
  if (part.pace === 'quiet' && skipQuiet && part.kind === 'house') return 0;
  return Math.round(hold[part.pace] / speed);
}

// The whole game on Auto: total ms, parts shown, and the stops a reader would
// have to press on through. `rounds` are buildRound results, in order.
export function autoLength(rounds, { hold, skipQuiet = false, speed = 1, follow = null }) {
  let ms = 0;
  let shown = 0;
  let stops = 0;
  const byPace = { quiet: 0, routine: 0, notable: 0, pause: 0 };
  for (const round of rounds) {
    for (const part of round.parts) {
      byPace[part.pace] += 1;
      const t = autoMs(part, { hold, skipQuiet, speed });
      if (t > 0) shown += 1;
      ms += t;
      if (stopsAuto(part, { follow })) stops += 1;
    }
  }
  return { ms, shown, stops, byPace };
}

// The turn-order strip: the world, each house in playing order, and the
// close, with the current one lit, those done dimmed and those to come plain.
export function stripOf(round, current) {
  return round.parts.map((part, i) => ({
    id: part.id,
    kind: part.kind,
    house: part.house,
    pace: part.pace,
    gone: part.gone,
    state: i < current ? 'done' : i === current ? 'current' : 'todo',
  }));
}

// ---------------------------------------------------------------- words ----

const ORDINALS = ['zeroth', 'first', 'second', 'third', 'fourth', 'fifth', 'sixth', 'seventh',
  'eighth', 'ninth', 'tenth', 'eleventh', 'twelfth'];
const WORDS = ['no', 'one', 'two', 'three', 'four', 'five', 'six', 'seven', 'eight', 'nine', 'ten',
  'eleven', 'twelve'];

function ordinalWord(n) {
  if (n < ORDINALS.length) return ORDINALS[n];
  const tail = n % 100 >= 11 && n % 100 <= 13 ? 'th' : ({ 1: 'st', 2: 'nd', 3: 'rd' }[n % 10] || 'th');
  return `${n}${tail}`;
}

function countWord(n) {
  return n < WORDS.length ? WORDS[n] : String(n);
}

export function placeWord(n) {
  const tail = n % 100 >= 11 && n % 100 <= 13 ? 'th' : ({ 1: 'st', 2: 'nd', 3: 'rd' }[n % 10] || 'th');
  return `${n}${tail}`;
}

// A scheme as a noun phrase: "claim on Guelph", "courtship of Bellechasse".
// `placeOf(house)` names a target house by its designation.
export function schemePhrase(plan, placeOf = (h) => h) {
  const riding = plan.riding || null;
  const target = plan.target_house ? placeOf(plan.target_house) : null;
  const on = (noun, what) => (what ? `${noun} ${what}` : noun.replace(/ (on|of|into|to|with)$/, ''));
  switch (plan.scheme) {
    case 'Claim a riding': return on('claim on', riding);
    case 'Counter-claim': return on('counter-claim on', riding);
    case 'Fortify': return on('defence of', riding);
    case 'Open the frontier': return on('push into', riding);
    case 'Buy out a neighbour': return on('bid to buy out', target);
    case 'Break a rival': return on('campaign to break', target);
    case 'Dynastic match': return on('courtship of', target);
    case 'Win elevation': return 'suit for elevation';
    case 'Seek a protector': return target ? `suit to ${target} for protection` : 'search for a protector';
    case 'Secure the line': return 'work to secure its line';
    case 'Make peace': return on('overture to', target);
    case 'Sue for peace': return on('suit for peace with', target);
    default: return String(plan.scheme || 'scheme').toLowerCase();
  }
}

// Where a house's scheme stands at the end of `turn`: "It is in the second of
// four years of its claim on Guelph." A scheme begun at turn b with r turns
// remaining at turn t runs (t - b + 1) + r years in all. One that ended this
// turn (in the plans before, not after) says so; a house with none, so.
export function schemeLine(house, turn, plans, plansBefore, placeOf = (h) => h) {
  const now = (plans || []).find((p) => p.house === house);
  if (now) {
    const year = turn - now.begun + 1;
    const total = year + now.turns_remaining;
    return `It is in the ${ordinalWord(year)} of ${countWord(total)} years of its ${schemePhrase(now, placeOf)}.`;
  }
  const ended = (plansBefore || []).find((p) => p.house === house);
  if (ended) return `Its ${schemePhrase(ended, placeOf)} ended this year.`;
  return 'It has no scheme afoot.';
}

// The heaviest of a list of entries, or null.
function heaviest(list) {
  return list.reduce((best, e) => heavier(best, e), null);
}

function actorOf(beat) {
  const first = beat.merge ? beat.parts[0] : beat;
  return (first.houses || [])[0];
}

// The heaviest of a list of entries by what they are, then by weight, then
// record order; null for none.
function heaviestBy(list, options) {
  let best = null;
  let bestRank = -1;
  for (const e of list) {
    const rank = RANK[entryPace(e, options)];
    if (best === null || rank > bestRank || (rank === bestRank && (e.weight > best.weight
      || (e.weight === best.weight && e.beat.seq < best.beat.seq)))) {
      best = e;
      bestRank = rank;
    }
  }
  return best;
}

// A house's answer to the year's event, as a tag: the event's name and the
// response in one word, with a glyph (weights.json `pace.responses`). Not a
// sentence and not a mark on the map.
function tagOf(entry, responses) {
  const response = entry.beat.outcome ?? 'Neutral';
  const r = responses[response] || { glyph: '○', word: String(response).toLowerCase() };
  const world = entry.beat.world || {};
  return { event: world.event || null, response, word: r.word, glyph: r.glyph };
}

// A crisis's camp for one house, in words (the crisis is an event of the
// world's turn, which names its camps): "Leads in the Great War crisis."
function campLine(crisis, house) {
  const w = crisis.beat.world;
  const name = w.event ? `the ${w.event.replace(/^(The|A|An) /, '')} crisis` : 'the crisis';
  if ((w.lead || []).includes(house)) return `Leads in ${name}.`;
  if ((w.resist || []).includes(house)) return `Resists in ${name}.`;
  return `Stands aside in ${name}.`;
}

// What a house's turn says (the card): what it did this year (its heaviest act
// of its own turn, by what it was), what was done to it (the heaviest beat of
// an earlier turn this year that names it and is not its own), its answers to
// the year's events as tags, its camp in a crisis in words, and where its
// scheme stands. Its other acts of the turn at the routine pace or above
// (`also`, at most two) are told after the first. `before` are the parts played before this one this year.
//
// A card carries the house's peerage in its header, so `did` starts at the verb
// ("Sets out to open Cumberland—Colchester."); other houses in the sentence
// keep their names, and the house itself, where a sentence must name it, is
// "the house" (text.js verbFirst). `didFull` is the whole sentence, for the text Replay, the
// drawer and the house sheet.
export function houseCard(part, before, {
  turn, plans, plansBefore, placeOf = (h) => h, styleOf = () => null, pace, thresholds, responses = {},
} = {}) {
  const house = part.house;
  const options = { pace, thresholds };
  const own = part.entries.filter((e) => !ERA_RESPONSES.includes(e.beat.kind)
    && (e.weight > 0 || RANK[entryPace(e, options)] > 0));
  const mine = own.filter((e) => actorOf(e.beat) === house);
  const did = heaviestBy(mine, options) || heaviestBy(own, options);
  // The turn's other acts at the routine pace or above, which the map draws a
  // mark for, so each is told: at most two, heaviest first.
  const also = own.filter((e) => e !== did && RANK[entryPace(e, options)] > 0)
    .sort((a, b) => RANK[entryPace(b, options)] - RANK[entryPace(a, options)] || b.weight - a.weight || a.beat.seq - b.beat.seq)
    .slice(0, 2);
  const tags = part.entries.filter((e) => ERA_RESPONSES.includes(e.beat.kind)).map((e) => tagOf(e, responses));
  const doneTo = heaviest(before
    .filter((p) => p.kind === 'house')
    .flatMap((p) => p.entries)
    .filter((e) => e.weight > 0 && (e.beat.houses || []).includes(house) && actorOf(e.beat) !== house));
  const camps = part.gone ? [] : before
    .filter((p) => p.kind === 'world')
    .flatMap((p) => p.entries)
    .filter((e) => e.beat.kind === 'crisis' && e.beat.world)
    .map((e) => campLine(e, house));
  let lead;
  let leadFull;
  if (part.gone) lead = leadFull = 'Its turn did not come: the house had fallen earlier in the year.';
  else if (did) {
    leadFull = did.alone || did.text;
    lead = verbFirst(leadFull, house, styleOf);
  } else lead = leadFull = 'It kept to its estates.';
  return {
    house,
    did: lead,
    didFull: leadFull,
    also: part.gone ? [] : also.map((e) => verbFirst(e.alone || e.text, house, styleOf)),
    doneTo: doneTo ? verbFirst(doneTo.alone || doneTo.text, house, styleOf) : null,
    tags,
    camps,
    scheme: part.gone ? null : schemeLine(house, turn, plans, plansBefore, placeOf),
  };
}

// The small line under a house's card: "4 ridings · Earl · 3rd of 24".
export function houseLine({ ridings, rank, place, of }) {
  const bits = [`${ridings} riding${ridings === 1 ? '' : 's'}`];
  if (rank) bits.push(rank);
  if (place) bits.push(`${placeWord(place)} of ${of}`);
  return bits.join(' · ');
}

// ------------------------------------------------------------- the sheet ----

// The record's people of one house (hoc/export/beats.py people_of): rows of
// [name, gender, role, entered, died, age, from]. `last` is the game's last
// turn: a living person's age is their age then.
function ageAt(row, turn, last) {
  const [, , , , died, age] = row;
  return age - ((died === null ? last : died) - turn);
}

// The holder at the end of `turn`: the person who held from a turn at or
// before it and had not died by it.
export function holderAt(people, turn, last) {
  let best = null;
  for (const row of people || []) {
    const [, , , , died, , from] = row;
    if (from === null || from > turn || (died !== null && died <= turn)) continue;
    if (best === null || from > best[6]) best = row;
  }
  if (!best) return null;
  return { name: best[0], gender: best[1], age: ageAt(best, turn, last) };
}

// The heir at the end of `turn`: someone in the record by then, alive, not yet
// holder, and named heir — the one who went on to hold first, then a named
// heir, then a second heir. Null when the record names none.
export function heirAt(people, turn, last) {
  const rank = (row) => (row[6] !== null ? 0 : row[2] === 'heir' ? 1 : 2);
  const candidates = (people || []).filter((row) => {
    const [, , role, entered, died, , from] = row;
    if (entered === null || entered > turn) return false;
    if (died !== null && died <= turn) return false;
    if (from !== null && from <= turn) return false;
    return role === 'heir' || role === 'heir2' || from !== null;
  });
  candidates.sort((a, b) => rank(a) - rank(b) || (a[6] ?? 0) - (b[6] ?? 0) || (a[3] - b[3]));
  const best = candidates[0];
  return best ? { name: best[0], gender: best[1], age: ageAt(best, turn, last) } : null;
}

// A house's sheet at a turn. Everything is handed in: the page knows the board,
// the standings, the plans and the storylines; this only assembles them.
export function houseSheet({
  house, turn, last, people = [], rank = null, ridings = 0, prestige = null, place = null, of = 0,
  plans = null, plansBefore = null, allies = [], rivals = [], history = [], placeOf = (h) => h,
}) {
  const plan = (plans || []).find((p) => p.house === house) || null;
  return {
    house,
    holder: holderAt(people, turn, last),
    heir: heirAt(people, turn, last),
    rank,
    ridings,
    prestige,
    place,
    of,
    scheme: plans === null ? null : schemeLine(house, turn, plans, plansBefore, placeOf),
    // The house a scheme is aimed at, where its sentence does not already
    // name it (a claim names its riding, not the riding's holder).
    target: plan && plan.target_house && !schemePhrase(plan, placeOf).includes(placeOf(plan.target_house))
      ? placeOf(plan.target_house) : null,
    allies: [...allies],
    rivals: [...rivals],
    history: history.slice(-5).reverse(),
  };
}

// ---------------------------------------------------------------- labels ----

// House names on the map. Each candidate is { house, text, x, y, priority }
// (lower priority first: the house whose turn it is, then the houses its turn
// touches, then the top eight by place) at its seat, in screen pixels. Each
// house is named once; a label goes above its seat, else below, right or left
// of it, close or a little further off, and is dropped when each would overlap a label already placed or a
// `blocked` rectangle — so the lower-ranked label is the one that goes. A
// candidate marked `must` (the house whose turn it is) that finds no clear
// place takes the first that overlaps no other name, badges or not. Returns the
// placed labels with their rectangles { x0, y0, x1, y1 } and text anchor.
export function placeLabels(candidates, {
  blocked = [], size = 12, charWidth = 0.58, pad = 4, gap = 9, screen = null,
} = {}) {
  const seen = new Set();
  const placed = [];
  const taken = [...blocked];
  const overlaps = (a, b) => a.x0 < b.x1 && b.x0 < a.x1 && a.y0 < b.y1 && b.y0 < a.y1;
  const order = [...candidates].sort((a, b) => a.priority - b.priority || compareText(a.house, b.house));
  for (const c of order) {
    if (seen.has(c.house)) continue;
    seen.add(c.house);
    const w = c.text.length * size * charWidth + 2 * pad;
    const h = size + 2 * pad;
    // Two rings of places: close to the seat, then clear of a badge on it.
    const options = [];
    for (const g of [gap, gap + 16]) {
      const side = g + 8;
      options.push(
        { x0: c.x - w / 2, y0: c.y - g - h, x1: c.x + w / 2, y1: c.y - g },
        { x0: c.x - w / 2, y0: c.y + g, x1: c.x + w / 2, y1: c.y + g + h },
        { x0: c.x + side, y0: c.y - h / 2, x1: c.x + side + w, y1: c.y + h / 2 },
        { x0: c.x - side - w, y0: c.y - h / 2, x1: c.x - side, y1: c.y + h / 2 },
      );
    }
    const inside = (r) => !screen || (r.x0 >= 0 && r.y0 >= 0 && r.x1 <= screen.w && r.y1 <= screen.h);
    const spot = options.find((r) => inside(r) && !taken.some((t) => overlaps(t, r)))
      || (c.must ? options.find((r) => inside(r) && !placed.some((t) => overlaps(t, r))) : undefined);
    if (!spot) continue;
    taken.push(spot);
    placed.push({ house: c.house, text: c.text, priority: c.priority, ...spot, x: c.x, y: c.y });
  }
  return placed;
}
