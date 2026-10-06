// Storylines (docs/STORY_DESIGN.md §3.4), derived from typed beats alone.
//
// A storyline is { id, type, houses, opened, beats, state, outcome, closed }:
// `beats` are [{ turn, beat }] in order, `state` is 'rising', 'climax' or
// 'closed', and `opened`/`closed` are turns. Types, triggers and closes:
//
//   rivalry     opens on a quarrel between two houses, or (rules 1.0) on a
//               claim one lays to the other's riding. Every later beat both
//               take part in escalates it. Closes on a reconciliation, a
//               dispute carried to a settlement, a riding passing between
//               them, a contest decided between them, a cession under a
//               standing claim, or the removal of either.
//   succession  opens on a disorderly succession, or — for a game whose record
//               carries rules 1.0's succession watch — on a holder turning sixty
//               with no heir. Escalated by the house's successions, ridings lost
//               and partition. Closes when an heir is named (or, with the watch,
//               comes of age) or succeeds cleanly, or when the house fails.
//   rise        opens when a house enters the top eight. Escalated by every
//               beat that moves the house's own standing. Closes when it
//               reaches first, or drops out of the top eight.
//   decline     opens when a top-eight house loses a riding or two places.
//               Escalated as a rise is. Closes when its standing recovers to
//               what it was before, or on its removal.
//   union       opens on a marriage or compact between two houses of the
//               cast. Escalated by every beat both take part in. Closes on a
//               partition or absorption of either, or a falling-out between them.
//   frontier    opens on the first riding any house holds in a province.
//               Escalated by every unclaimed riding taken there (a riding
//               passing between houses is not a frontier beat). Closes when the
//               province is half claimed (`storylines.frontier_share`).
//
// Over all of them: a storyline with no beat for `lapse_turns` turns closes as
// "lapsed"; a house's removal closes every storyline it is in, the removal its
// outcome — except a frontier, which the house only leaves; and a cadet house inherits nothing from its parent's storylines —
// the partition beat belongs to the parent's and to any it opens itself.
//
// A storyline is at climax from its `climax_beats`th beat until it closes.
// Only storyline beats count: bookkeeping, letters and era responses never
// open, escalate or close one.
//
// Pure: no DOM, no engine. `step` changes the tracker it is called on, and
// nothing it is handed.

import { compareText } from './beats.js';
import { provinceOf } from './weight.js';

export const STORYLINE_TYPES = ['rivalry', 'union', 'succession', 'rise', 'decline', 'frontier'];

export const PROVINCES = {
  10: 'Newfoundland and Labrador', 11: 'Prince Edward Island', 12: 'Nova Scotia',
  13: 'New Brunswick', 24: 'Quebec', 35: 'Ontario', 46: 'Manitoba', 47: 'Saskatchewan',
  48: 'Alberta', 59: 'British Columbia', 60: 'Yukon', 61: 'Northwest Territories', 62: 'Nunavut',
};

const QUIET_KINDS = new Set([
  'invest', 'cultivate', 'consolidate', 'name_heir', 'correspondence', 'era_response',
  'major_response', 'other', 'bide',
  // Rules 1.0: a scheme's preparation steps and its resolution are ledger-only.
  'scheme_step', 'scheme_resolved',
]);

// A claim begun, or answered with a counter-claim (rules 1.0 `schemes`): the
// pair it sets at odds, which a rivalry storyline then holds.
function claimPair(beat, names) {
  if (beat.kind !== 'scheme_begun' && beat.kind !== 'scheme_answered') return null;
  if (!names.includes(beat.outcome) || (beat.houses || []).length < 2) return null;
  return [beat.houses[0], beat.houses[1]];
}

const CONTESTS = ['contest_won', 'contest_lost', 'fallen'];

function storyBeat(beat) {
  return !QUIET_KINDS.has(beat.kind);
}

// The two houses a beat sets at odds: a quarrel's, or the quarrel folded into
// a merged act (a disorderly succession's falling-out, a contest).
function quarrelPair(beat) {
  const q = beat.kind === 'quarrel' ? beat : (beat.parts || []).find((p) => p.kind === 'quarrel');
  return q && q.houses.length >= 2 ? [q.houses[0], q.houses[1]] : null;
}

function pairKey(a, b) {
  return compareText(a, b) <= 0 ? `${a}\u0000${b}` : `${b}\u0000${a}`;
}

// Did this beat move `house`'s own standing: a riding to or from it, its rank,
// or its removal?
function movesStanding(beat, house, boardBefore) {
  for (const [fed, owner] of Object.entries(beat.owners || {})) {
    if (owner === house || boardBefore.owners[fed] === house) return true;
  }
  if (beat.ranks && Object.prototype.hasOwnProperty.call(beat.ranks, house)) return true;
  return (beat.removed || []).includes(house);
}

function lostRiding(beat, house, boardBefore) {
  return Object.entries(beat.owners || {})
    .some(([fed, owner]) => boardBefore.owners[fed] === house && owner !== house);
}

export class Storylines {
  // `provinceTotals` maps a province code to its number of ridings; `held`
  // lists the provinces in which some house already held a riding before the
  // first turn (they are no frontier).
  constructor({ weights, provinceTotals = {}, held = [], watch = false }) {
    this.weights = weights;
    // Whether the record carries rules 1.0's succession watch (heir_wanted and
    // heir_of_age beats): its questions then close on an heir coming of age.
    this.watch = watch;
    this.provinceTotals = provinceTotals;
    this.held = new Set(held);
    this.all = [];
    this.next = 1;
  }

  get open() {
    return this.all.filter((s) => s.state !== 'closed');
  }

  find(type, key) {
    return this.all.find((s) => s.state !== 'closed' && s.type === type && s.key === key);
  }

  of(id) {
    return this.all.find((s) => s.id === id);
  }

  // One turn. `beats` are the turn's merged beats; `cast` the top eight at its
  // start; `before`/`after` the boards and standings tables around it. Returns
  // { roles, changes }: for each beat, the storylines it opens, escalates or
  // closes ({ id, role, earlier }), and every storyline that opened, reached
  // climax or closed this turn ({ id, change }).
  step(turn, beats, { cast, boardBefore, boardAfter, tableBefore, tableAfter }) {
    const cfg = this.weights.storylines;
    const roles = beats.map(() => []);
    const changes = [];
    const touched = new Set();
    let board = boardBefore;

    const open = (type, key, houses, index, extra = {}) => {
      const s = {
        id: `s${this.next}`, type, key, houses: [...houses], opened: turn, beats: [],
        state: 'rising', outcome: null, closed: null, ...extra,
      };
      this.next += 1;
      this.all.push(s);
      changes.push({ id: s.id, change: 'opened' });
      if (index !== null) attach(s, index, 'open');
      return s;
    };
    const attach = (s, index, role) => {
      if (s.beats.some((entry) => entry.index === index && entry.turn === turn)) return;
      const earlier = s.beats.length;
      s.beats.push({ turn, beat: beats[index], index });
      roles[index].push({ id: s.id, role, earlier, type: s.type });
      touched.add(s.id);
      if (s.state === 'rising' && s.beats.length >= cfg.climax_beats && role !== 'close') {
        s.state = 'climax';
        changes.push({ id: s.id, change: 'climax' });
      }
    };
    const close = (s, index, outcome) => {
      if (s.state === 'closed') return;
      if (index !== null) attach(s, index, 'close');
      s.state = 'closed';
      s.outcome = outcome;
      s.closed = turn;
      changes.push({ id: s.id, change: 'closed' });
    };

    beats.forEach((beat, i) => {
      const houses = beat.houses || [];
      const [a, b] = houses;
      const story = storyBeat(beat);

      // Removal closes everything the house is in, after the beat is attached.
      const removed = beat.removed || [];

      if (story) {
        const quarrel = quarrelPair(beat);
        const parted = beat.kind === 'partition' || beat.merge === 'partition'
          || (beat.parts || []).some((p) => p.kind === 'partition');
        // Pair storylines: the beat belongs to every one whose two houses both
        // take part in it; a union also ends on a partition or absorption of
        // either house.
        for (const s of this.open) {
          if (s.type !== 'rivalry' && s.type !== 'union') continue;
          const both = s.houses.every((h) => houses.includes(h));
          if (s.type === 'rivalry') {
            if (!both) continue;
            const settles = beat.kind === 'reconciled' || beat.merge === 'cession'
              || (beat.kind === 'dispute_won' && beat.outcome === '~');
            if (settles) close(s, i, beat.merge === 'cession' ? 'settled by cession' : 'reconciled');
            else if (CONTESTS.includes(beat.kind)) {
              close(s, i, beat.kind === 'contest_lost' ? 'held in a contest' : 'won in a contest');
            } else if (beat.kind === 'riding_passes' && beat.outcome === 'cession under claim') {
              close(s, i, 'ceded under a claim');
            } else if (beat.kind === 'riding_passes') close(s, i, 'a riding changed hands');
            else attach(s, i, 'escalate');
          } else if (quarrel && pairKey(...quarrel) === s.key) {
            close(s, i, 'a falling-out');
          } else if (parted && s.houses.includes(a)) {
            close(s, i, 'partition');
          } else if (beat.kind === 'riding_passes' && beat.outcome === 'absorption'
                     && houses.some((h) => s.houses.includes(h))) {
            close(s, i, 'absorption');
          } else if (both) {
            attach(s, i, 'escalate');
          }
        }

        if (quarrel) {
          const key = pairKey(...quarrel);
          if (!this.find('rivalry', key)) open('rivalry', key, [...quarrel].sort(compareText), i);
        }
        // A claim belongs to the two houses' rivalry, and opens one if none runs.
        const claim = claimPair(beat, this.weights.claim_schemes || []);
        if (claim) {
          const key = pairKey(...claim);
          if (!this.find('rivalry', key)) open('rivalry', key, [...claim].sort(compareText), i);
        }
        if ((beat.kind === 'marriage' || beat.kind === 'compact') && a !== undefined && b !== undefined
            && cast.has(a) && cast.has(b)) {
          const key = pairKey(a, b);
          if (!this.find('union', key)) open('union', key, [a, b].sort(compareText), i);
        }

        // Succession questions.
        const subject = beat.merge ? beat.parts[0].houses[0] : a;
        const running = subject === undefined ? null : this.find('succession', subject);
        if (running) {
          if (beat.kind === 'heir_of_age') {
            close(running, i, 'an heir came of age');
          } else if (beat.kind === 'succession_clean' || beat.merge === 'partition') {
            close(running, i, 'an heir succeeded');
          } else if (['succession_disorderly', 'riding_lost', 'partition', 'removed', 'fallen', 'heir_wanted'].includes(beat.kind)
                     && houses.includes(running.key)) {
            attach(running, i, 'escalate');
          }
        } else if (beat.kind === 'succession_disorderly' || beat.kind === 'heir_wanted'
                   || (beat.merge === 'collapse' && beat.parts[0].kind === 'succession_disorderly')) {
          if (!removed.includes(subject)) open('succession', subject, [subject], i);
        }

        // Rise and decline: beats that move the house's standing.
        for (const s of this.open) {
          if ((s.type === 'rise' || s.type === 'decline') && movesStanding(beat, s.key, board)) {
            attach(s, i, 'escalate');
          }
        }

        // Frontier: the first riding in a province opens one; later ridings
        // there escalate it.
        for (const [fed, owner] of Object.entries(beat.owners || {})) {
          // Only unclaimed land taken counts: a riding passing from one house
          // to another is never a frontier beat.
          if (owner === null || board.owners[fed] !== undefined) continue;
          const province = provinceOf(fed);
          const running = this.find('frontier', province);
          if (running) {
            // A cadet inherits nothing: the partition beat belongs to the
            // frontier, but does not make the cadet one of its houses.
            if (!running.houses.includes(owner) && !parted) running.houses.push(owner);
            attach(running, i, 'escalate');
          } else if (!this.held.has(province)) {
            this.held.add(province);
            open('frontier', province, [owner], i, { province });
          }
        }

        // Decline opened by a lost riding: a top-eight house losing ground.
        for (const house of cast) {
          if (lostRiding(beat, house, board) && !this.find('decline', house) && !removed.includes(house)) {
            const place = tableBefore.find((row) => row.house === house);
            open('decline', house, [house], i, { mark: place ? place.score : 0 });
          }
        }
      } else if (beat.kind === 'name_heir' && a !== undefined) {
        // With the watch, naming an heir is a step; the question closes when
        // the heir comes of age. Without it, naming one is the answer.
        const running = this.find('succession', a);
        if (running && this.watch) attach(running, i, 'escalate');
        else if (running) close(running, i, 'an heir named');
      }

      // A removal ends every storyline the house is a principal of. A frontier
      // is the province's, not any one settler's: the house leaves it, and it
      // ends only if no house is left in it.
      for (const house of removed) {
        for (const s of this.open) {
          if (s.type === 'frontier') {
            if (!s.houses.includes(house)) continue;
            s.houses = s.houses.filter((h) => h !== house);
            if (!s.houses.length) close(s, i, `${house} removed`);
          } else if (s.houses.includes(house) || s.key === house) {
            close(s, i, `${house} removed`);
          }
        }
      }
      board = { ...board, owners: { ...board.owners } };
      for (const [fed, owner] of Object.entries(beat.owners || {})) {
        if (owner === null) delete board.owners[fed];
        else board.owners[fed] = owner;
      }
    });

    // What the standings say once the turn is done.
    const lastMover = (house) => {
      for (let i = beats.length - 1; i >= 0; i -= 1) {
        if (storyBeat(beats[i]) && movesStanding(beats[i], house, boardBefore)) return i;
      }
      return null;
    };
    const placeBefore = new Map(tableBefore.map((row) => [row.house, row]));
    const placeAfter = new Map(tableAfter.map((row) => [row.house, row]));
    const size = this.weights.cast_size;
    for (const row of tableAfter.slice(0, size)) {
      const prior = placeBefore.get(row.house);
      // A house that enters straight at first has nowhere to rise to.
      if ((!prior || prior.place > size) && row.place > 1 && !this.find('rise', row.house)) {
        open('rise', row.house, [row.house], lastMover(row.house));
      }
    }
    for (const s of this.open) {
      const now = placeAfter.get(s.key);
      if (s.type === 'rise' && now) {
        if (now.place === 1) close(s, lastMover(s.key), 'reached first');
        else if (now.place > size) close(s, lastMover(s.key), 'fell back');
      }
      if (s.type === 'decline' && now && s.opened < turn && now.score >= s.mark) {
        close(s, lastMover(s.key), 'recovered');
      }
    }
    for (const row of tableBefore.slice(0, size)) {
      const now = placeAfter.get(row.house);
      if (now && now.place >= row.place + 2 && !this.find('decline', row.house)) {
        open('decline', row.house, [row.house], lastMover(row.house), { mark: row.score });
      }
    }
    for (const s of this.open) {
      if (s.type !== 'frontier') continue;
      const total = this.provinceTotals[s.province] || 0;
      const claimed = Object.keys(boardAfter.owners).filter((fed) => provinceOf(fed) === s.province).length;
      if (total && claimed * cfg.frontier_share[1] >= total * cfg.frontier_share[0]) {
        let last = null;
        for (let i = beats.length - 1; i >= 0 && last === null; i -= 1) {
          if (Object.entries(beats[i].owners || {}).some(([fed, o]) => o !== null && provinceOf(fed) === s.province)) last = i;
        }
        close(s, last, 'half claimed');
      }
    }

    // Lapses: nothing for `lapse_turns` turns.
    for (const s of this.open) {
      const lastTurn = s.beats.length ? s.beats[s.beats.length - 1].turn : s.opened;
      if (!touched.has(s.id) && turn - lastTurn >= cfg.lapse_turns) close(s, null, 'lapsed');
    }
    return { roles, changes };
  }
}

// A storyline's name: "The Bellechasse–Belfast rivalry", "The rise of Perth",
// "The Saskatchewan frontier". `placeOf(house)` gives a house's designation.
export function storylineName(s, placeOf = (h) => h) {
  const [a, b] = s.houses;
  switch (s.type) {
    case 'rivalry': return `The ${placeOf(a)}–${placeOf(b)} rivalry`;
    case 'union': return `The ${placeOf(a)}–${placeOf(b)} union`;
    case 'succession': return `The ${placeOf(s.key)} succession`;
    case 'rise': return `The rise of ${placeOf(s.key)}`;
    case 'decline': return `The decline of ${placeOf(s.key)}`;
    case 'frontier': return `The ${PROVINCES[s.province] || s.province} frontier`;
    default: return s.type;
  }
}
