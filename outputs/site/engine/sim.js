// The autoplay engine, in JavaScript: a straight port of hoc/sim.py.
//
// Read hoc/sim.py for what the game *is*. This file's only job is to do the
// same thing in the same order, so that both engines write byte-identical
// season files (docs/DETERMINISM.md, CLAUDE.md "Two engines").
//
// Three rules govern every line here:
//
//   * **Draw for draw.** Every call into the RNG must happen in the same order,
//     the same number of times, with the same `purpose` string. The purpose
//     strings are compared by the cross-check, so they are part of the contract
//     rather than decoration. A branch that draws in Python and not here (or
//     vice versa) desynchronises the stream and every later season with it.
//   * **Character for character.** Chronicle lines, event titles and delta keys
//     go into the season file, so they are compared too. The separator in
//     "Season 3 · ..." is U+00B7, and the relation markers are the v1 glyphs.
//   * **Integers only.** No float arithmetic anywhere except pFound, and no
//     float comparison except the founding roll.
//
// Where the Python reads SQLite, this reads `WorldState` (state.js), whose
// methods carry each query's ORDER BY. Where the Python calls `hoc/rules.py`
// helpers (`_next_seat_order`, `_expansion_hex`, `elevate`, `climate_shift`),
// those are inlined here as small private methods, named after their originals.

import { Prng, seasonSeed as prngSeasonSeed, pFound } from './prng.js';
import { WorldState, clamp } from './state.js';
import { compareStrings } from './adjacency.js';
import { NameGenerator, peerageTitle, nameKey } from './names.js';
import { assignColours } from './palette.js';
import { probabilityForAge } from './rules.js';

export const RULES_VERSION = '0.7';
export const WEIGHT_SCALE = 100;
export const TOTAL_RIDINGS = 343;
export const STAT_RANGE = [0, 100];
export const AMBITION_RANGE = [0, 10];

export const MAX_OBJECTIVES = 3;
export const OBJECTIVES_AT_FOUNDING = 2;
export const DEFEND_THE_SEAT_SEASONS = 3;
export const SIEGE_SEASONS = 10;
export const SNAPSHOT_EVERY = 5;
export const NO_SUCCESSOR_PCT = 20;
export const CORRESPONDENCE_RANGE = 2;

// The v1 relation glyphs, spelled exactly as the reconstructed record spells
// them (Sig− carries a real minus sign, U+2212, not a hyphen).
export const ACQUAINTED = '◎';
export const FRIENDLY = '+';
export const COMPACT = '◉+';
export const GRIEVANCE = 'Sig−';
export const HOSTILE = '⊖';
export const CHALLENGED = '⚔';
export const RESOLVED = '~';
export const KIN = 'kin';

export const IMPLEMENTED_ACTIONS = new Set([
  'Expand', 'Invest', 'Cultivate influence', 'Name heir', 'Endow',
  'Petition elevation', 'Consolidate (rest)',
  'Correspond', 'Propose compact', 'Reconcile', 'Dispute', 'Challenge (11b)',
  'Purchase riding', 'Marriage alliance', 'Absorb', 'Cede / swap',
]);

export const ENCLOSURE_DOUBLED = new Set(['Cultivate influence', 'Endow', 'Petition elevation']);

export const RESPONSE_VERB = {
  Lead: 'leads',
  Resist: 'resists',
  Exploit: 'exploits',
  Neutral: 'stands aside',
};

export const PROVINCE_NEIGHBOURS = {
  NL: ['QC'],
  PE: ['NB', 'NS'],
  NS: ['NB', 'PE'],
  NB: ['QC', 'NS', 'PE'],
  QC: ['NL', 'NB', 'ON'],
  ON: ['QC', 'MB'],
  MB: ['ON', 'SK', 'NU'],
  SK: ['MB', 'AB', 'NT'],
  AB: ['SK', 'BC', 'NT'],
  BC: ['AB', 'YT', 'NT'],
  YT: ['BC', 'NT'],
  NT: ['YT', 'BC', 'AB', 'SK', 'NU'],
  NU: ['NT', 'MB'],
};

export const PROVINCE_REGION = {
  NL: 'maritime', PE: 'maritime', NS: 'maritime', NB: 'maritime',
  QC: 'quebec', ON: 'ontario',
  MB: 'prairie', SK: 'prairie', AB: 'prairie',
  BC: 'bc', YT: 'north', NT: 'north', NU: 'north',
};

export const RANK_LADDER = [
  ['Baron', 'Baroness'],
  ['Viscount', 'Viscountess'],
  ['Earl', 'Countess'],
  ['Marquis', 'Marchioness'],
  ['Duke', 'Duchess'],
];

const RANK_LEVEL = new Map();
RANK_LADDER.forEach((forms, level) => forms.forEach((form) => RANK_LEVEL.set(form, level)));

const CLIMATE_TAGS = new Set(['Progressive', 'Conservative', 'Mixed', 'Outside', 'Global', 'regressive']);
const CLIMATE_MAGNITUDES = new Set(['Minor', 'Significant', 'Major']);

// The §6 phases, in order. `--phases` on the Python CLI and `--phases` here
// select a prefix-agnostic subset for phase-by-phase cross-checking; the
// default is all of them and that is the only configuration the game is ever
// played in (see hoc/__main__.py, and tests/test_sim.py).
export const PHASES = [
  'clocks', 'friction', 'events', 'mortality', 'actions', 'objectives',
  'debt', 'founding', 'enclosure',
];

export class SimError extends Error {}

// -------------------------------------------------------------------- rng --

// A seeded RNG that records every draw it is asked for. Mirrors
// hoc/sim.py's LoggingRandom exactly, including the shapes of the logged
// results, which go into the season file.
export class LoggingRandom {
  constructor(prng, log, purpose = 'unattributed') {
    this.rng = prng;
    this.log = log;
    this._purpose = purpose;
  }

  forPurpose(purpose) {
    return new LoggingRandom(this.rng, this.log, purpose);
  }

  _record(purpose, result) {
    this.log.push({ purpose: purpose || this._purpose, result });
    return result;
  }

  draw(purpose, result) {
    return this._record(purpose, result);
  }

  choice(sequence, purpose = null) {
    return this._record(purpose, this.rng.choice(Array.from(sequence)));
  }

  randint(low, high, purpose = null) {
    return this._record(purpose, this.rng.randInt(low, high));
  }

  chance(percent, purpose = null) {
    const pct = Math.trunc(percent);
    const roll = this.rng.randInt(1, 100);
    return this._record(purpose, { roll, pct, hit: roll <= pct }).hit;
  }

  chanceFloat(probability, purpose = null) {
    const roll = this.rng.randFloat();
    return this._record(purpose, {
      roll: new FloatValue(roll),
      p: new FloatValue(probability),
      hit: roll < probability,
    }).hit;
  }

  die(sides = 6, purpose = null) {
    return this._record(purpose, this.rng.randInt(1, sides));
  }

  twoD6(purpose = null) {
    const [a, b] = this.rng.rand2d6();
    return this._record(purpose, { dice: [a, b], total: a + b }).total;
  }

  // Draws from an ordered list of [key, integer weight] pairs — never a map.
  weighted(options, purpose = null) {
    const pairs = Array.from(options);
    const keys = pairs.map((pair) => pair[0]);
    const weights = pairs.map((pair) => Math.trunc(pair[1]));
    return this._record(purpose, this.rng.weightedChoice(keys, weights));
  }
}

export function seasonSeed(worldSeed, seasonNo) {
  return prngSeasonSeed(worldSeed, seasonNo);
}

// A number that must be written the way Python writes a float.
//
// Python distinguishes 1 from 1.0 and json.dumps writes them differently;
// JavaScript has one number type and would write both as "1". The engine puts
// exactly two genuine floats into a season record — §10's founding probability
// and the rand_float() it is compared against — and both are boxed in this so
// `encodeFloat` can render them as Python's repr does. Everything else in the
// record is an integer and must stay one.
export class FloatValue {
  constructor(value) {
    this.value = value;
  }
}

// The one way this repo serialises a season log: sorted keys, no spaces after
// separators, UTF-8 as written, one trailing newline. Mirrors
// hoc/sim.py's canonical_json.
//
// JSON.stringify does not sort keys and has no separator control, so this walks
// the value itself. Python's json.dumps with sort_keys sorts by the raw string
// comparison, which for these ASCII keys is code-point order — the same order
// compareStrings gives.
export function canonicalJson(value) {
  return `${encode(value)}\n`;
}

function encode(value) {
  if (value === null || value === undefined) return 'null';
  if (typeof value === 'boolean') return value ? 'true' : 'false';
  if (value instanceof FloatValue) return encodeFloat(value.value);
  if (typeof value === 'number') return encodeNumber(value);
  if (typeof value === 'string') return JSON.stringify(value);
  if (Array.isArray(value)) return `[${value.map(encode).join(',')}]`;
  const keys = Object.keys(value)
    .filter((key) => value[key] !== undefined)
    .sort(compareStrings);
  return `{${keys.map((key) => `${JSON.stringify(key)}:${encode(value[key])}`).join(',')}}`;
}

// Every unboxed number in a season record is an integer, and is written as one.
function encodeNumber(value) {
  if (!Number.isInteger(value)) {
    throw new Error(
      `refusing to serialise the non-integer ${value}: wrap a genuine float in`
      + ' FloatValue so it is written the way Python writes one',
    );
  }
  return String(value);
}

// Python's repr for a float, reproduced.
//
// Both languages print the shortest decimal that round-trips, so the *digits*
// agree; what differs is the formatting around them. Python always shows a
// decimal point ("0.0", never "0"), and switches to exponential notation when
// the decimal exponent is below -4 or at least 16 — where JavaScript switches
// below -6 and at 21 — and pads the exponent to two digits ("1e-05", not
// "1e-5"). All three differences bite: the engine's floats live in [0, 1), so a
// rand_float() below 1e-4 is written one way here and another way there.
function encodeFloat(value) {
  if (!Number.isFinite(value)) throw new Error(`cannot serialise ${value}`);
  if (value === 0) return Object.is(value, -0) ? '-0.0' : '0.0';

  const negative = value < 0;
  // toExponential() with no argument gives the shortest digits that uniquely
  // identify the number — the same digits Python's repr chooses.
  const [mantissa, exponentText] = Math.abs(value).toExponential().split('e');
  const exponent = parseInt(exponentText, 10);
  const digits = mantissa.replace('.', '');
  const sign = negative ? '-' : '';

  if (exponent < -4 || exponent >= 16) {
    const expSign = exponent < 0 ? '-' : '+';
    const expDigits = String(Math.abs(exponent)).padStart(2, '0');
    return `${sign}${mantissa}e${expSign}${expDigits}`;
  }

  if (exponent >= 0) {
    const whole = digits.slice(0, exponent + 1).padEnd(exponent + 1, '0');
    const fraction = digits.slice(exponent + 1);
    return `${sign}${whole}.${fraction === '' ? '0' : fraction}`;
  }
  return `${sign}0.${'0'.repeat(-exponent - 1)}${digits}`;
}

// ------------------------------------------------------------------ world --

export class World {
  constructor({ state, rules, worldSeed, phases = null }) {
    this.state = state;
    this.rules = rules;
    this.worldSeed = worldSeed;
    this.rulesVersion = RULES_VERSION;
    this.phases = phases === null ? new Set(PHASES) : new Set(phases);

    this.log = [];
    this.chronicle = [];
    this._turnCache = new Map();
    this._expansionClaims = new Map();
    this._provinceDistance = new Map();

    this.eras = rules.eras;
    this.actions = new Map(rules.actions.map((a) => [a.action, a]));
    this.objectives = new Map(rules.objectives.map((o) => [o.objective, o]));

    this.communitiesByRegion = new Map();
    for (const community of rules.communities) {
      if (!this.communitiesByRegion.has(community.region)) {
        this.communitiesByRegion.set(community.region, []);
      }
      this.communitiesByRegion.get(community.region).push(community);
    }

    this.regionWeights = rules.founding.region_weights.initial;
    this.rankIndex = new Map(
      Object.entries(rules.founding.rank_index).filter(([, v]) => Number.isInteger(v)),
    );
  }

  get seasonNo() {
    let highest = 0;
    for (const row of this.state.seasons) highest = Math.max(highest, row.seasonNo);
    return highest;
  }

  rngFor(seasonNo) {
    return new LoggingRandom(new Prng(seasonSeed(this.worldSeed, seasonNo)), this.log);
  }

  // -- reading the world (thin wrappers so the port reads like its original) --

  activeHouses() { return this.state.activeHouses(); }

  houseRow(house) {
    const row = this.state.houseRow(house);
    if (row === undefined) throw new SimError(`unknown house '${house}'`);
    return row;
  }

  holder(house) { return this.state.holder(house); }
  heirs(house) { return this.state.heirs(house); }
  holdings(house) { return this.state.holdingsOf(house); }
  holdingCount(house) { return this.state.holdingCount(house); }
  personalYear(house) { return this.state.personalYear(house); }
  heldObjectives(house) { return this.state.heldObjectives(house); }

  bandFor(personalYear) {
    for (const era of this.eras) {
      if (era.end_year === null || personalYear <= era.end_year) {
        if (personalYear >= era.start_year) return era.id;
      }
    }
    const last = this.eras[this.eras.length - 1];
    return personalYear >= last.start_year ? last.id : this.eras[0].id;
  }

  setStats(house, deltas) { return this.state.setStats(house, deltas); }

  ridingName(fedId) { return this.state.map.nameEn(fedId); }

  // hoc/rules.py record_event, plus sim.py's record(): the season is stamped
  // into mechanical_delta because the events table has no season column.
  record(kind, title, houses, season, { band = null, line = null, delta = null } = {}) {
    const payload = { season };
    if (delta) Object.assign(payload, delta);
    const eventId = this.state.recordEvent({
      kind,
      title,
      houses,
      eraCohort: band,
      narrative: line,
      mechanicalDelta: payload,
      source: 'engine',
    });
    if (line) this.chronicle.push(line);
    return eventId;
  }

  // hoc/rules.py _next_seat_order.
  nextSeatOrder(house) {
    let highest = 0;
    for (const holding of this.state.holdings) {
      if (holding.house === house && holding.releasedEventId === null) {
        highest = Math.max(highest, holding.seatOrder);
      }
    }
    return highest + 1;
  }

  // hoc/rules.py house_colours, through the v_house_colours view: the seat's
  // own hex wins over the house's recorded colour (hard rule 4).
  houseColours(house) {
    const row = this.state.house(house);
    let primary = row.primaryHex;
    let secondary = row.secondaryHex;
    for (const holding of this.state.holdings) {
      if (holding.house !== house || holding.releasedEventId !== null) continue;
      if (holding.seatOrder === 1) primary = holding.hex ?? primary;
      if (holding.seatOrder === 2) secondary = holding.hex ?? secondary;
    }
    return [primary, secondary];
  }

  // hoc/rules.py _expansion_hex.
  expansionHex(house) {
    const [primary, secondary] = this.houseColours(house);
    return secondary || primary;
  }

  // -- climate (hoc/rules.py current_climate / climate_shift) --

  currentClimate(eraCohort) {
    let latest = null;
    for (const row of this.state.climate) {
      if (row.eraCohort !== eraCohort) continue;
      if (latest === null || row.seq > latest.seq) latest = row;
    }
    if (latest === null) return null; // the caller treats this as RuleError
    return parseInt(latest.cumulativeAfter, 10);
  }

  climateShift(eraCohort, event, magnitude, tag, delta) {
    if (!CLIMATE_MAGNITUDES.has(magnitude)) return;
    if (!CLIMATE_TAGS.has(tag)) return;
    const previous = this.currentClimate(eraCohort);
    if (previous === null) return; // no ledger: Python raises and sim.py swallows it
    const cumulative = previous + delta;
    let nextSeq = 0;
    for (const row of this.state.climate) {
      if (row.eraCohort === eraCohort) nextSeq = Math.max(nextSeq, row.seq);
    }
    this.state.addClimate({
      eraCohort,
      seq: nextSeq + 1,
      event,
      magnitude,
      tag,
      cumulativeAfter: cumulative > 0 ? `+${cumulative}` : String(cumulative),
      source: 'turn',
    });
  }

  initialClimate() {
    for (const era of this.eras) {
      const exists = this.state.climate.some((row) => row.eraCohort === era.id);
      if (!exists) {
        this.state.addClimate({
          eraCohort: era.id,
          seq: 1,
          event: 'Season 0',
          magnitude: null,
          tag: null,
          cumulativeAfter: '0',
          source: 'engine',
        });
      }
    }
  }

  // ------------------------------------------------------------- founding --

  drawRegion(rng) {
    const capacity = new Map();
    for (const [province, count] of this.state.unclaimedCountByProvince()) {
      const region = PROVINCE_REGION[province] ?? 'north';
      capacity.set(region, (capacity.get(region) ?? 0) + count);
    }
    const weights = [];
    for (const region of Object.keys(this.regionWeights).sort(compareStrings)) {
      const room = capacity.get(region) ?? 0;
      if (room === 0) continue;
      weights.push([region, Math.floor((this.regionWeights[region] * (20 + room)) / 20)]);
    }
    if (weights.length === 0) return null;
    return rng.weighted(weights, 'founding.region');
  }

  drawSeat(rng, region) {
    const provinces = Object.keys(PROVINCE_REGION).filter((p) => PROVINCE_REGION[p] === region);
    if (provinces.length === 0) return null;
    const rows = this.state.unclaimedInProvinces(provinces);
    if (rows.length === 0) return null;
    return rng.choice(rows, 'founding.seat');
  }

  drawTag(rng) {
    const weights = { Progressive: 200, Conservative: 200, Mixed: 200, Outside: 100 };
    const climate = this.currentClimate('confederation') ?? 0;
    if (climate > 0) weights.Progressive *= 2;
    else if (climate < 0) weights.Conservative *= 2;
    return rng.weighted(
      ['Progressive', 'Conservative', 'Mixed', 'Outside'].map((tag) => [tag, weights[tag]]),
      'founding.tag',
    );
  }

  foundHouse(season, { seat = null, rng = null, community = null, tag = null, rank = null, surname = null } = {}) {
    const draws = rng || this.rngFor(season);
    this.initialClimate();

    let fedId;
    let province;
    let region;
    if (seat !== null) {
      fedId = this.state.map.resolve(nameKey(seat));
      if (fedId === null) throw new SimError(`unknown riding '${seat}'`);
      if (this.state.holderOfRiding(fedId) !== null) throw new SimError(`riding '${seat}' is already held`);
      province = this.state.map.province(fedId);
      region = PROVINCE_REGION[province] ?? 'north';
    } else {
      region = this.drawRegion(draws);
      if (region === null) return null;
      fedId = this.drawSeat(draws, region);
      if (fedId === null) return null;
      province = this.state.map.province(fedId);
    }

    const pool = this.communitiesByRegion.get(region) || this.communitiesByRegion.get('ontario');
    let communityName = community;
    if (communityName === null) {
      communityName = draws.weighted(pool.map((c) => [c.community, c.weight]), 'founding.community');
    }
    const communityObj =
      pool.find((c) => c.community === communityName) ||
      this.rules.communities.find((c) => c.community === communityName);

    const chosenTag = tag || this.drawTag(draws);
    const chosenRank =
      rank ||
      draws.weighted(
        Object.entries(this.rules.founding.rank_probabilities).sort((a, b) => {
          const ai = this.rankIndex.get(a[0]) ?? 0;
          const bi = this.rankIndex.get(b[0]) ?? 0;
          return ai - bi || compareStrings(a[0], b[0]);
        }),
        'founding.rank',
      );
    const rankIndex = this.rankIndex.get(chosenRank) ?? 0;

    const generator = new NameGenerator(this.rules, draws);
    let drawn;
    try {
      drawn = generator.drawHouse(
        communityObj.community, province, chosenRank,
        this.state.takenPlaces(), null, surname || null,
      );
    } catch (exc) {
      this.log.push({ purpose: 'founding.abandoned', result: String(exc.message) });
      return null;
    }

    const house = this.uniqueHouseName(drawn.surname);
    const primaries = this.state.activePrimaryHexes();
    const [primary, secondary] = assignColours(primaries, draws.forPurpose('founding.colour'));

    this.state.addHouse({
      house,
      peerage: drawn.peerage,
      rank: chosenRank,
      status: 'active',
      primaryHex: primary,
      secondaryHex: secondary,
      notes: `founded season ${season}`,
    });

    const stats = {
      capital: clamp(30 + 5 * rankIndex + draws.randint(1, 20, 'founding.capital'), STAT_RANGE[0], STAT_RANGE[1]),
      influence: clamp(20 + 5 * rankIndex + draws.randint(1, 20, 'founding.influence'), STAT_RANGE[0], STAT_RANGE[1]),
      cohesion: clamp(60 + draws.randint(1, 20, 'founding.cohesion'), STAT_RANGE[0], STAT_RANGE[1]),
      ambition: clamp(draws.randint(1, 10, 'founding.ambition'), AMBITION_RANGE[0], AMBITION_RANGE[1]),
    };
    this.state.houseStats.set(house, {
      house,
      capital: stats.capital,
      influence: stats.influence,
      cohesion: stats.cohesion,
      ambition: stats.ambition,
      enclosed: 0,
      enclosedSince: null,
      community: communityObj.community,
      region,
      tradition: drawn.tradition,
      tag: chosenTag,
      province,
      seatPlace: drawn.place,
      foundedSeason: season,
      removedSeason: null,
      forcedAction: null,
    });

    const holderAge = 40 + draws.randint(1, 30, 'founding.holder_age');
    this.state.addPerson({
      house,
      name: `${drawn.given} ${drawn.surname}`,
      gender: drawn.gender,
      age: holderAge,
      role: 'holder',
      bornSeason: season,
    });
    this.state.setClock(house, 1867, `founded season ${season}`);

    const eventId = this.record(
      'founding',
      `${drawn.peerage} founded`,
      [house],
      season,
      {
        band: 'confederation',
        line: `Season ${season} · ${drawn.peerage} is created, seated at ${this.ridingName(fedId)}.`,
        delta: { stats, community: communityObj.community, tag: chosenTag },
      },
    );
    this.state.addHolding({ house, fedId, seatOrder: 1, hex: primary, acquiredEventId: eventId });

    this.drawFoundingObjectives(house, season, draws);
    return house;
  }

  drawFoundingObjectives(house, season, rng) {
    const row = this.houseRow(house);
    const weights = this.rules.objectives.map((objective) => [
      objective.objective,
      WEIGHT_SCALE + 2 * WEIGHT_SCALE * this.objectiveFavoured(objective.objective, row, house),
    ]);
    for (let i = 0; i < OBJECTIVES_AT_FOUNDING; i += 1) {
      const held = new Set(this.heldObjectives(house));
      const available = weights.filter(([name]) => !held.has(name));
      if (available.length === 0) break;
      const chosen = rng.weighted(available, 'founding.objective');
      this.state.addObjective(house, chosen, season);
    }
  }

  objectiveFavoured(objective, row, house) {
    const holder = this.holder(house);
    const holdings = this.holdingCount(house);
    if (objective === 'Consolidate region') return holdings <= 2 ? 1 : 0;
    if (objective === 'Secure succession') {
      return holder !== null && holder.age >= 60 && this.heirs(house).length === 0 ? 1 : 0;
    }
    if (objective === 'Seek elevation') return row.influence >= 60 ? 1 : 0;
    if (objective === 'Endow an institution') return row.capital >= 70 ? 1 : 0;
    if (objective === 'Form a compact') return ['Progressive', 'Mixed'].includes(row.tag) ? 1 : 0;
    return 0;
  }

  uniqueHouseName(surname) {
    const existing = new Set(this.state.houses.keys());
    if (!existing.has(surname)) return surname;
    for (let suffix = 2; suffix < 100; suffix += 1) {
      const candidate = `${surname} ${suffix}`;
      if (!existing.has(candidate)) return candidate;
    }
    throw new SimError(`cannot make a unique house name from '${surname}'`);
  }

  // ------------------------------------------------------------ mortality --

  ageEveryone() { this.state.ageEveryone(); }

  mortality(house, season, rng, extraRoll = false) {
    const holder = this.holder(house);
    if (holder === null) return this.succeed(house, season, rng, 'no holder');

    const percent = probabilityForAge(this.rules.mortality, holder.age);
    const rolls = extraRoll ? 2 : 1;
    // Python's `any(... for _ in range(rolls))` short-circuits, so a house that
    // dies on the first roll never draws the second.
    let died = false;
    for (let i = 0; i < rolls; i += 1) {
      if (rng.chance(percent, `mortality.${house}`)) { died = true; break; }
    }
    if (!died) return false;

    holder.alive = 0;
    holder.diedSeason = season;
    return this.succeed(house, season, rng, 'death');
  }

  succeed(house, season, rng, cause) {
    const row = this.houseRow(house);
    const heirs = this.heirs(house);
    const band = this.bandFor(this.personalYear(house));

    if (heirs.length > 0) {
      const heir = heirs[0];
      heir.role = 'holder';
      let partitioned = null;
      const spec = this.rules.succession.partition;
      if (heirs.length >= spec.min_heirs && this.holdingCount(house) >= spec.min_holdings) {
        partitioned = this.partition(house, heirs[1], season, rng, band);
      }
      for (const spare of heirs.slice(1)) {
        if (partitioned === null || spare.id !== heirs[1].id) spare.role = 'other';
      }
      this.setStats(house, { cohesion: this.rules.succession.clean_succession.cohesion_delta });
      this.state.setClock(house, 1867, `reset at accession, season ${season}`);
      this.record('succession', `${row.peerage}: clean succession`, [house], season, {
        band,
        line: `Season ${season} · ${heir.name} succeeds to ${row.peerage}.`,
        delta: { nature: 'clean', cause },
      });
      return this.checkExtinction(house, season, rng);
    }

    const succession = this.rules.succession.disorderly_succession;
    this.setStats(house, {
      cohesion: succession.cohesion_delta,
      capital: succession.capital_delta,
    });
    if (rng.chance(NO_SUCCESSOR_PCT, `succession.no_successor.${house}`)) {
      this.removeHouse(house, season, 'no successor', rng);
      return true;
    }

    const community = row.community;
    const generator = new NameGenerator(this.rules, rng);
    const [given, surname, gender] = generator.drawPerson(community, null, house.split(' ')[0]);
    const age = 35 + rng.randint(1, 20, 'succession.successor_age');
    this.state.addPerson({
      house, name: `${given} ${surname}`, gender, age, role: 'holder', bornSeason: season,
    });
    this.state.setClock(house, 1867, `reset at disorderly accession, season ${season}`);
    this.record('succession', `${row.peerage}: disorderly succession`, [house], season, {
      band,
      line: `Season ${season} · ${row.peerage} passes in disorder to ${given} ${surname}.`,
      delta: { nature: 'disorderly', cause },
    });

    const neighbours = this.neighbouringHouses(house);
    const percent = succession.sig_minus_probability_pct;
    if (neighbours.length > 0 && rng.chance(percent, `succession.grievance.${house}`)) {
      const other = rng.choice(neighbours, `succession.grievance_with.${house}`);
      const marker = this.relationMarker(house, other);
      if (marker !== KIN && marker !== COMPACT) {
        const grievanceId = this.record(
          'relational',
          `${row.peerage} falls out with ${this.houseRow(other).peerage}`,
          [house, other],
          season,
          { band, delta: { marker: GRIEVANCE, cause: 'disorderly succession' } },
        );
        this.setRelation(house, other, GRIEVANCE, grievanceId, 'disorderly succession');
      }
    }

    const loss = this.rules.succession.losing_ridings.disorderly_succession;
    if (this.holdingCount(house) >= 4 && rng.chance(loss.probability_pct, `succession.riding_loss.${house}`)) {
      this.loseRiding(house, season, 'disorderly succession');
    }

    return this.checkExtinction(house, season, rng);
  }

  partition(house, junior, season, rng, band) {
    const row = this.houseRow(house);
    const holdings = this.holdings(house);
    if (holdings.length < this.rules.succession.partition.min_holdings) return null;

    const outer = this.outerHoldings(house, holdings);
    if (outer.length === 0) return null;

    const cadet = this.uniqueHouseName(house.split(' ')[0]);
    const primaries = this.state.activePrimaryHexes();
    const [primary, secondary] = assignColours(primaries, rng.forPurpose('partition.colour'));

    const province = this.state.map.province(outer[0].fedId);
    const generator = new NameGenerator(this.rules, rng);
    let place;
    try {
      place = generator.drawPlace(province, this.state.takenPlaces());
    } catch (exc) {
      return null;
    }
    const peerage = peerageTitle('Baron', house.split(' ')[0], place, row.tradition);

    this.state.addHouse({
      house: cadet, peerage, rank: 'Baron', status: 'active',
      primaryHex: primary, secondaryHex: secondary,
      notes: `cadet of ${house}, season ${season}`,
    });
    this.state.houseStats.set(cadet, {
      house: cadet,
      capital: Math.max(0, Math.floor(row.capital / 2)),
      influence: Math.max(0, Math.floor(row.influence / 2)),
      cohesion: clamp(60 + rng.randint(1, 20, 'partition.cohesion'), STAT_RANGE[0], STAT_RANGE[1]),
      ambition: row.ambition,
      enclosed: 0,
      enclosedSince: null,
      community: row.community,
      region: row.region,
      tradition: row.tradition,
      tag: row.tag,
      province,
      seatPlace: place,
      foundedSeason: season,
      removedSeason: null,
      forcedAction: null,
    });
    junior.house = cadet;
    junior.role = 'holder';
    this.state.setClock(cadet, 1867, `cadet founding by partition, season ${season}`);

    const eventId = this.record(
      'founding',
      `${peerage} founded by partition from ${row.peerage}`,
      [house, cadet],
      season,
      {
        band,
        line: `Season ${season} · ${peerage} is founded by partition from ${row.peerage}.`,
        delta: { nature: 'partition', parent: house },
      },
    );
    for (const holding of outer) this.state.releaseHolding(holding, eventId);
    outer.forEach((holding, index) => {
      const order = index + 1;
      this.state.addHolding({
        house: cadet, fedId: holding.fedId, seatOrder: order,
        hex: order === 1 ? primary : secondary, acquiredEventId: eventId,
      });
    });
    this.setRelation(house, cadet, KIN, eventId, 'cadet line');
    this.drawFoundingObjectives(cadet, season, rng);
    this.state.renumber(house);
    return cadet;
  }

  // The half of the holdings furthest from the seat, by land steps.
  outerHoldings(house, holdings) {
    const seat = holdings[0];
    const held = new Set(holdings.map((h) => h.fedId));
    const distance = new Map([[seat.fedId, 0]]);
    let frontier = [seat.fedId];
    while (frontier.length > 0) {
      const next = [];
      for (const node of frontier) {
        for (const neighbour of this.state.map.land(node)) {
          if (!held.has(neighbour) || distance.has(neighbour)) continue;
          distance.set(neighbour, distance.get(node) + 1);
          next.push(neighbour);
        }
      }
      frontier = next;
    }
    const ranked = holdings
      .filter((h) => h.fedId !== seat.fedId)
      .sort((a, b) => {
        const da = -(distance.has(a.fedId) ? distance.get(a.fedId) : 10000);
        const db = -(distance.has(b.fedId) ? distance.get(b.fedId) : 10000);
        return da - db || compareStrings(a.fedId, b.fedId);
      });
    return ranked.slice(0, Math.max(1, Math.floor(ranked.length / 2)));
  }

  checkExtinction(house, season, rng) {
    if (this.houseRow(house).cohesion < 15) {
      this.removeHouse(house, season, 'cohesion collapse', rng);
      return true;
    }
    return false;
  }

  removeHouse(house, season, reason, rng = null) {
    const row = this.houseRow(house);
    const band = this.bandFor(this.personalYear(house));

    if (rng !== null) {
      const partners = this.housesRelatedBy(house, new Set([COMPACT, KIN]));
      if (partners.length > 0) {
        const heirHouse = rng.choice(partners, `extinction.absorber.${house}`);
        if (rng.twoD6(`extinction.absorb_roll.${house}`) + 3 >= 8) {
          this.absorbInto(heirHouse, house, season, band, `escheat: ${reason}`);
          return;
        }
      }
    }
    const eventId = this.record('succession', `${row.peerage} extinct`, [house], season, {
      band,
      line: `Season ${season} · ${row.peerage} fails; its ridings return to the Crown.`,
      delta: { nature: 'extinction', reason },
    });
    for (const holding of this.state.holdings) {
      if (holding.house === house && holding.releasedEventId === null) {
        this.state.releaseHolding(holding, eventId);
      }
    }
    this.state.house(house).status = 'removed';
    this.state.stats(house).removedSeason = season;
    for (const person of this.state.persons) {
      if (person.house === house && person.alive === 1) {
        person.alive = 0;
        person.diedSeason = season;
      }
    }
  }

  // Lose the most recently acquired non-seat riding (§7c).
  loseRiding(house, season, reason, toHouse = null) {
    const candidates = this.state.holdings
      .filter((h) => h.house === house && h.releasedEventId === null && h.seatOrder > 1)
      .sort((a, b) => b.id - a.id);
    if (candidates.length === 0) return null;
    const holding = candidates[0];
    const row = this.houseRow(house);
    const band = this.bandFor(this.personalYear(house));
    const name = this.ridingName(holding.fedId);
    const houses = toHouse === null ? [house] : [house, toHouse];
    const eventId = this.record('transfer', `${row.peerage} loses ${name}`, houses, season, {
      band,
      line: `Season ${season} · ${row.peerage} gives up ${name} (${reason}).`,
      delta: { reason, riding: name },
    });
    this.state.releaseHolding(holding, eventId);
    if (toHouse !== null) {
      this.state.addHolding({
        house: toHouse, fedId: holding.fedId,
        seatOrder: this.nextSeatOrder(toHouse), hex: this.expansionHex(toHouse),
        acquiredEventId: eventId,
      });
    }
    return holding.fedId;
  }

  // ----------------------------------------------------------- era events --

  firedEvents(house) {
    const out = new Set();
    for (const event of this.state.events) {
      if (event.kind === 'societal' && event.houses.includes(house)) out.add(event.title);
    }
    return out;
  }

  eraEvent(house, season, rng) {
    const year = this.personalYear(house);
    let due = this.rules.events.filter((e) => e.personalYear === year);
    if (due.length === 0) return null;

    const already = this.firedEvents(house);
    due = due.filter((e) => !already.has(e.name));
    if (due.length === 0) return null;

    let event;
    if (due.length === 1) {
      event = due[0];
    } else {
      const name = rng.choice(due.map((e) => e.name), `event.pick.${house}`);
      event = due.find((e) => e.name === name);
    }
    const row = this.houseRow(house);
    const band = this.bandFor(year);

    let modifier = 0;
    if (row.tag === event.tag) modifier = this.rules.responses.tag_modifier.matching_tag;
    else if (World.opposing(row.tag, event.tag)) modifier = this.rules.responses.tag_modifier.opposing_tag;
    const roll = rng.die(6, `event.response.${house}`) + modifier;
    const response = World.responseFor(roll);

    let deltas = null;
    if (response === 'Lead') { deltas = { influence: 5 }; this.shiftClimate(band, event, 1); }
    else if (response === 'Resist') { deltas = { cohesion: 5 }; this.shiftClimate(band, event, -1); }
    else if (response === 'Exploit') { deltas = { capital: 10, influence: -5 }; }
    if (deltas) this.setStats(house, deltas);

    const extraMortality = this.applyDirectEffects(house, event, season);

    this.record('societal', event.name, [house], season, {
      band,
      line: `Season ${season} · ${row.peerage} meets ${event.name} and ${RESPONSE_VERB[response]}.`,
      delta: {
        response, roll, personal_year: year, magnitude: event.magnitude, tag: event.tag,
      },
    });
    return { event, response, extraMortality };
  }

  static opposing(houseTag, eventTag) {
    return (
      (houseTag === 'Progressive' && eventTag === 'Conservative') ||
      (houseTag === 'Conservative' && eventTag === 'Progressive')
    );
  }

  static responseFor(roll) {
    if (roll >= 6) return 'Lead';
    if (roll >= 4) return 'Exploit';
    if (roll >= 2) return 'Resist';
    return 'Neutral';
  }

  shiftClimate(band, event, direction) {
    const signs = { Progressive: 1, Conservative: -1 };
    const sign = signs[event.tag];
    if (sign === undefined) return;
    this.climateShift(
      band, event.name, event.magnitude,
      CLIMATE_TAGS.has(event.tag) ? event.tag : 'Mixed',
      sign * direction,
    );
  }

  inScope(houseRow, scope) {
    if (scope === 'all') return true;
    if (scope === houseRow.region) return true;
    if (scope === 'newfoundland') return houseRow.province === 'NL';
    if (scope === houseRow.tag) return true;
    const groups = {
      asian: ['Chinese', 'Japanese', 'Punjabi Sikh'],
      francophone: ['Canadien Catholic', 'Acadian', 'Franco-Ontarian', 'French-Canadian Prairie', 'Métis'],
      metis: ['Métis'],
    };
    if (Object.prototype.hasOwnProperty.call(groups, scope)) {
      return groups[scope].includes(houseRow.community);
    }
    if (scope === 'female_line') {
      const holder = this.holder(houseRow.house);
      return holder !== null && holder.gender === 'f';
    }
    return false;
  }

  applyDirectEffects(house, event, season) {
    const row = this.houseRow(house);
    let extra = false;
    const deltas = {};
    for (const effect of event.directEffect) {
      if (!this.inScope(row, effect.scope)) continue;
      if (effect.stat === 'mortality') extra = true;
      else deltas[effect.stat] = (deltas[effect.stat] ?? 0) + effect.delta;
    }
    if (Object.keys(deltas).length > 0) this.setStats(house, deltas);

    if (
      event.magnitude === 'Major' &&
      event.tag === 'Conservative' &&
      event.directEffect.some((e) => e.stat === 'capital' && e.delta < 0) &&
      this.houseRow(house).capital < 20
    ) {
      this.sellRiding(house, season, 'contraction sale');
    }
    return extra;
  }

  sellRiding(house, season, reason) {
    // The buyer: an adjacent house with capital >= 50, richest first, then by
    // name — the ORDER BY s.capital DESC, s.house of the original query.
    const neighbours = this.neighbouringHouses(house);
    const buyers = neighbours
      .map((other) => this.houseRow(other))
      .filter((other) => other.capital >= 50)
      .sort((a, b) => b.capital - a.capital || compareStrings(a.house, b.house));
    const toHouse = buyers.length > 0 ? buyers[0].house : null;
    const lost = this.loseRiding(house, season, reason, toHouse);
    if (lost !== null && toHouse !== null) {
      this.setStats(house, { capital: 30 });
      this.setStats(toHouse, { capital: -40 });
    }
    return lost;
  }

  // ------------------------------------------------------------ relations --

  relation(a, b) { return this.state.relation(a, b); }
  relationMarker(a, b) { return this.state.relationMarker(a, b); }

  setRelation(a, b, marker, eventId = null, text = null) {
    this.state.setRelation(a, b, marker, eventId, text);
  }

  housesRelatedBy(house, markers) {
    const key = `related|${house}`;
    if (!this._turnCache.has(key)) {
      const pairs = [];
      for (const r of this.state.relations) {
        let other = null;
        if (r.houseA === house) other = r.houseB;
        else if (r.houseB === house) other = r.houseA;
        if (other === null) continue;
        if (this.state.house(other)?.status !== 'active') continue;
        pairs.push([r.marker, other]);
      }
      this._turnCache.set(key, pairs);
    }
    const out = this._turnCache.get(key)
      .filter(([marker]) => markers.has(marker))
      .map(([, other]) => other);
    return out.sort(compareStrings);
  }

  relationSeason(a, b) {
    const row = this.relation(a, b);
    if (row === null || row.eventId === null) return null;
    const event = this.state.event(row.eventId);
    if (!event || !event.mechanicalDelta) return null;
    const season = event.mechanicalDelta.season;
    return season === undefined ? null : season;
  }

  disputeBlocked(a, b, season) {
    if (this.relationMarker(a, b) !== KIN) return false;
    const made = this.relationSeason(a, b);
    if (made === null) return true;
    const window = this.rules.succession.marriage_alliance.dispute_block_seasons;
    return season - made < window;
  }

  provinceDistance(a, b) {
    if (a === b) return 0;
    const key = `${a}|${b}`;
    if (this._provinceDistance.has(key)) return this._provinceDistance.get(key);
    const seen = new Set([a]);
    let frontier = [a];
    let answer = null;
    for (let step = 1; step <= CORRESPONDENCE_RANGE && answer === null; step += 1) {
      const next = [];
      for (const province of frontier) {
        for (const neighbour of PROVINCE_NEIGHBOURS[province] ?? []) {
          if (seen.has(neighbour)) continue;
          if (neighbour === b) { answer = step; break; }
          seen.add(neighbour);
          next.push(neighbour);
        }
        if (answer !== null) break;
      }
      frontier = next;
    }
    this._provinceDistance.set(key, answer);
    return answer;
  }

  profiles() {
    if (!this._turnCache.has('profiles')) {
      const out = new Map();
      for (const [name, house] of this.state.houses) {
        if (house.status !== 'active') continue;
        const stats = this.state.stats(name);
        out.set(name, [stats.province, stats.tag]);
      }
      this._turnCache.set('profiles', out);
    }
    return this._turnCache.get('profiles');
  }

  housesWithinReach(house) {
    const key = `reach|${house}`;
    if (!this._turnCache.has(key)) {
      const profiles = this.profiles();
      const mine = profiles.get(house);
      const out = [];
      if (mine !== undefined) {
        for (const [other, [province]] of profiles) {
          if (other === house) continue;
          const distance = this.provinceDistance(mine[0], province);
          if (distance !== null && distance <= CORRESPONDENCE_RANGE) out.push(other);
        }
      }
      this._turnCache.set(key, out.sort(compareStrings));
    }
    return this._turnCache.get(key);
  }

  neighbouringHouses(house) {
    const key = `neighbours|${house}`;
    if (!this._turnCache.has(key)) {
      this._turnCache.set(key, this.state.neighbouringHouses(house));
    }
    return this._turnCache.get(key);
  }

  // A riding `other` holds that touches one of `house`'s, seat last.
  adjacentHoldingOf(house, other) {
    const key = `adjacent|${house}|${other}`;
    if (this._turnCache.has(key)) return this._turnCache.get(key);
    const found = new Map();
    for (const mine of this.state.holdings) {
      if (mine.house !== house || mine.releasedEventId !== null) continue;
      for (const neighbour of this.state.map.land(mine.fedId)) {
        for (const theirs of this.state.holdings) {
          if (theirs.releasedEventId !== null) continue;
          if (theirs.house !== other || theirs.fedId !== neighbour) continue;
          found.set(theirs.fedId, theirs.seatOrder);
        }
      }
    }
    const rows = [...found.entries()].sort((a, b) => {
      const sa = a[1] === 1 ? 1 : 0;
      const sb = b[1] === 1 ? 1 : 0;
      return sa - sb || compareStrings(a[0], b[0]);
    });
    const answer = rows.length === 0 ? null : rows[0][0];
    this._turnCache.set(key, answer);
    return answer;
  }

  unmarriedHeir(house) {
    for (const heir of this.heirs(house)) {
      if (!heir.married) return heir;
    }
    return null;
  }

  // ------------------------------------------------------------- friction --

  frictionBetween(a, b) { return this.state.frictionBetween(a, b); }

  setFriction(a, b, value) {
    const bounds = this.rules.friction.range;
    const clamped = clamp(value, bounds[0], bounds[1]);
    this.state.setFriction(a, b, clamped);
    return clamped;
  }

  frictionDelta(rowA, rowB, marker) {
    const spec = this.rules.friction.per_season;
    if (marker === GRIEVANCE || marker === HOSTILE) return spec.open_quarrel.value;

    const tags = new Set([rowA.tag, rowB.tag]);
    let delta = 0;
    let moved = false;
    if (tags.size === 2 && tags.has('Progressive') && tags.has('Conservative')) {
      delta += spec.opposed_tags.value;
      moved = true;
    }
    if (rowA.enclosed || rowB.enclosed) { delta += spec.either_enclosed.value; moved = true; }
    if (rowA.ambition >= 7 || rowB.ambition >= 7) { delta += spec.high_ambition.value; moved = true; }
    if (marker === FRIENDLY || marker === COMPACT || marker === KIN) {
      delta += spec.bound.value;
      moved = true;
    }
    if (!moved) delta += spec.decay.value;
    return delta;
  }

  grievanceTemplate(rowA, rowB, rng) {
    const templates = this.rules.friction.grievances;
    const key = [rowA.tag || 'Mixed', rowB.tag || 'Mixed'].sort(compareStrings).join('|');
    const options = templates[key] || templates.default;
    return rng.choice(options, 'friction.grievance');
  }

  lapseGrievances(season) {
    const window = this.rules.friction.grievance_lapse.seasons;
    for (const row of this.state.relations.filter((r) => r.marker === GRIEVANCE)) {
      const made = this.relationSeason(row.houseA, row.houseB);
      if (made !== null && season - made >= window) {
        row.marker = RESOLVED;
        row.eventText = 'lapsed: no longer pressed';
      }
    }
  }

  runFriction(season, rng) {
    this.lapseGrievances(season);
    const spec = this.rules.friction.flashpoint;
    const profiles = new Map();

    for (const [houseA, houseB] of this.state.borderingPairs()) {
      for (const house of [houseA, houseB]) {
        if (!profiles.has(house)) profiles.set(house, this.houseRow(house));
      }
      const rowA = profiles.get(houseA);
      const rowB = profiles.get(houseB);
      const marker = this.relationMarker(houseA, houseB);

      let value = this.frictionBetween(houseA, houseB);
      value = this.setFriction(houseA, houseB, value + this.frictionDelta(rowA, rowB, marker));

      if (value < spec.threshold) continue;
      if (rng.die(6, `friction.flashpoint.${houseA}|${houseB}`) >= spec.succeeds_on) {
        if (marker !== KIN && marker !== COMPACT) {
          const grievance = this.grievanceTemplate(rowA, rowB, rng);
          const band = this.bandFor(this.personalYear(houseA));
          const eventId = this.record(
            'relational',
            `${rowA.peerage} and ${rowB.peerage} fall out`,
            [houseA, houseB],
            season,
            {
              band,
              line: `Season ${season} · ${rowA.peerage} and ${rowB.peerage} fall out over ${grievance}.`,
              delta: { marker: GRIEVANCE, cause: 'friction', grievance },
            },
          );
          this.setRelation(houseA, houseB, GRIEVANCE, eventId, grievance);
        }
      }
      this.setFriction(houseA, houseB, spec.resets_to);
    }
  }

  // ---------------------------------------------------------- action loop --

  legalActions(house) {
    const row = this.houseRow(house);
    const holder = this.holder(house);
    const holdings = this.holdingCount(house);
    const legal = new Set(['Invest', 'Consolidate (rest)']);

    if (row.capital >= 40 && !row.enclosed && this.hasExpansionTarget(house)) legal.add('Expand');
    if (row.capital >= 20) legal.add('Cultivate influence');
    if (holder !== null && holder.age >= 45) {
      const existing = this.heirs(house);
      const second = this.rules.succession.heirs;
      if (existing.length === 0) legal.add('Name heir');
      else if (
        existing.length === 1 &&
        existing[0].age >= second.second_heir_min_age &&
        holdings >= second.second_heir_min_holdings
      ) legal.add('Name heir');
    }
    if (row.capital >= 60) legal.add('Endow');
    if (
      row.influence >= 60 && holdings >= 3 &&
      (this.rankIndex.get(row.rank) ?? 0) < this.rankIndex.get('Marquis')
    ) legal.add('Petition elevation');

    if (this.housesWithinReach(house).length > 0) legal.add('Correspond');

    const friendly = this.housesRelatedBy(house, new Set([FRIENDLY, COMPACT]));
    if (friendly.length > 0 && ['Progressive', 'Mixed', 'Outside', 'Conservative'].includes(row.tag)) {
      if (friendly.some((other) => {
        const tag = this.houseRow(other).tag;
        return tag === row.tag || row.tag === 'Mixed' || tag === 'Mixed';
      })) legal.add('Propose compact');
    }
    if (friendly.length > 0 && this.unmarriedHeir(house)) {
      if (friendly.some((other) => this.unmarriedHeir(other))) legal.add('Marriage alliance');
    }

    const aggrieved = this.housesRelatedBy(house, new Set([GRIEVANCE]));
    if (aggrieved.length > 0) {
      legal.add('Reconcile');
      if (aggrieved.some((other) =>
        this.adjacentHoldingOf(house, other) && !this.disputeBlocked(house, other, this.seasonNo)
      )) legal.add('Dispute');
      if (aggrieved.some((other) => this.adjacentHoldingOf(house, other))) legal.add('Cede / swap');
    }

    const hostile = this.housesRelatedBy(house, new Set([HOSTILE]));
    if (hostile.length > 0 && hostile.some((other) => this.adjacentHoldingOf(house, other))) {
      legal.add('Challenge (11b)');
    }

    if (row.capital >= 70 && this.purchaseTargets(house).length > 0) legal.add('Purchase riding');
    if (this.absorbTargets(house).length > 0) legal.add('Absorb');

    return new Set([...legal].filter((name) => IMPLEMENTED_ACTIONS.has(name)));
  }

  hasExpansionTarget(house) {
    const key = `can_expand|${house}`;
    if (!this._turnCache.has(key)) {
      this._turnCache.set(key, this.state.hasExpansionTarget(house));
    }
    return this._turnCache.get(key);
  }

  purchaseTargets(house) {
    const out = [];
    for (const other of this.neighbouringHouses(house)) {
      const row = this.houseRow(other);
      if ((row.capital < 30 || row.cohesion < 35) && this.adjacentHoldingOf(house, other)) {
        out.push(other);
      }
    }
    return out;
  }

  absorbTargets(house) {
    const bound = new Set(this.housesRelatedBy(house, new Set([COMPACT, KIN])));
    return this.neighbouringHouses(house).filter(
      (other) => bound.has(other) && this.houseRow(other).cohesion < 15,
    );
  }

  actionWeights(house, legal) {
    const row = this.houseRow(house);
    const holder = this.holder(house);
    const held = this.heldObjectives(house);

    const bonusFor = new Map();
    for (const objective of held) {
      const spec = this.objectives.get(objective);
      if (spec === undefined) continue;
      for (const action of spec.actionWeightBonus) {
        bonusFor.set(action, (bonusFor.get(action) ?? 0) + 2 * WEIGHT_SCALE);
      }
    }

    const weights = [];
    for (const name of [...legal].sort(compareStrings)) {
      const action = this.actions.get(name);
      const base = action.baseWeight;
      if (!/^-?\d+$/.test(String(base).trim())) continue; // 'forced' is never drawn
      let weight = parseInt(base, 10) * WEIGHT_SCALE;

      if (name === 'Expand') {
        weight += row.ambition * WEIGHT_SCALE;
        if (row.cohesion < 40) weight -= 2 * WEIGHT_SCALE;
      } else if (name === 'Invest' && row.capital < 40) {
        weight += 2 * WEIGHT_SCALE;
      } else if (name === 'Consolidate (rest)' && row.cohesion < 40) {
        weight += 3 * WEIGHT_SCALE;
      } else if (name === 'Name heir' && holder !== null && holder.age > 60) {
        weight += Math.floor((holder.age - 60) / 5) * WEIGHT_SCALE;
      } else if (name === 'Dispute') {
        weight += row.ambition * Math.floor(WEIGHT_SCALE / 2);
        if (row.cohesion < 50) weight -= 3 * WEIGHT_SCALE;
      } else if (name === 'Reconcile' && row.cohesion < 40) {
        weight += 2 * WEIGHT_SCALE;
      } else if (name === 'Correspond') {
        const sameTag = this.housesWithinReach(house).filter(
          (other) => this.houseRow(other).tag === row.tag,
        );
        if (sameTag.length > 0) weight += 2 * WEIGHT_SCALE;
        if (this.housesRelatedBy(house, new Set([GRIEVANCE])).length > 0) weight -= 2 * WEIGHT_SCALE;
      }

      weight += bonusFor.get(name) ?? 0;
      if (row.enclosed && ENCLOSURE_DOUBLED.has(name)) weight *= 2;
      weights.push([name, Math.max(0, weight)]);
    }
    return weights;
  }

  takeAction(house, season, rng) {
    const forced = this.houseRow(house).forcedAction;
    if (forced) {
      this.state.stats(house).forcedAction = null;
      if (this.legalActions(house).has(forced)) {
        rng.draw(`action.${house}`, { forced_by: 'director', action: forced });
        const outcome = this.resolveAction(house, forced, season, rng);
        if (outcome !== null) outcome.forced = true;
        return outcome;
      }
      rng.draw(`action.${house}`, {
        forced_by: 'director', action: forced, refused: 'not legal this season',
      });
    }

    const legal = this.legalActions(house);
    const weights = this.actionWeights(house, legal);
    const name = rng.weighted(weights, `action.${house}`);
    if (name === null) return null;
    return this.resolveAction(house, name, season, rng);
  }

  resolveAction(house, name, season, rng) {
    const action = this.actions.get(name);
    const row = this.houseRow(house);
    const band = this.bandFor(this.personalYear(house));

    let success;
    let roll = null;
    if (action.target === 'auto') {
      success = true;
    } else {
      roll = rng.twoD6(`resolve.${name}.${house}`);
      const bonus = action.enclosureBonus ? action.enclosureBonus.replace(/^\+/, '') : '';
      const modifier = row.enclosed && action.enclosureBonus ? parseInt(bonus || '0', 10) : 0;
      success = roll + modifier >= action.target;
    }

    return this.handlerFor(name).call(this, house, season, rng, success, band, roll);
  }

  handlerFor(name) {
    const handlers = {
      Expand: this.doExpand,
      Invest: this.doInvest,
      'Cultivate influence': this.doCultivateInfluence,
      'Consolidate (rest)': this.doConsolidateRest,
      'Name heir': this.doNameHeir,
      Endow: this.doEndow,
      'Petition elevation': this.doPetitionElevation,
      Correspond: this.doCorrespond,
      'Propose compact': this.doProposeCompact,
      Reconcile: this.doReconcile,
      Dispute: this.doDispute,
      'Challenge (11b)': this.doChallenge11b,
      'Purchase riding': this.doPurchaseRiding,
      'Marriage alliance': this.doMarriageAlliance,
      Absorb: this.doAbsorb,
      'Cede / swap': this.doCedeSwap,
    };
    const handler = handlers[name];
    if (handler === undefined) throw new SimError(`no handler for action '${name}'`);
    return handler;
  }

  pick(rng, options, purpose) {
    if (options.length === 0) return null;
    return rng.choice([...options].sort(compareStrings), purpose);
  }

  // -- the PART A actions --

  doExpand(house, season, rng, success, band, roll) {
    const row = this.houseRow(house);
    if (!success) {
      this.setStats(house, { capital: -5 });
      return { action: 'Expand', success: false };
    }

    const targets = this.state.expansionTargets(house);
    if (targets.length === 0) return { action: 'Expand', success: false, note: 'no target' };
    const fedId = rng.choice(targets, `expand.target.${house}`);
    const name = this.ridingName(fedId);

    const rival = this._expansionClaims.get(fedId);
    if (rival !== undefined && rival.house !== house) {
      const mine = rng.twoD6(`contest.${house}.${fedId}`);
      if (mine <= rival.roll) {
        this.grievanceFromContest(house, rival.house, name, season, band);
        this.setStats(house, { capital: -5 });
        return { action: 'Expand', success: false, note: 'lost the contest', riding: name, to: rival.house };
      }
      this.grievanceFromContest(rival.house, house, name, season, band);
      for (const holding of this.state.holdings) {
        if (holding.house === rival.house && holding.fedId === fedId && holding.releasedEventId === null) {
          this.state.releaseHolding(holding, holding.acquiredEventId);
        }
      }
      this.state.renumber(rival.house);
      this._expansionClaims.set(fedId, { house, roll: mine });
    } else {
      this._expansionClaims.set(fedId, {
        house, roll: rng.twoD6(`contest.${house}.${fedId}`),
      });
    }

    const eventId = this.record('expansion', `${row.peerage} takes ${name}`, [house], season, {
      band,
      line: `Season ${season} · ${row.peerage} takes ${name}.`,
      delta: { riding: name, roll },
    });
    this.state.addHolding({
      house, fedId, seatOrder: this.nextSeatOrder(house),
      hex: this.expansionHex(house), acquiredEventId: eventId,
    });
    this.setStats(house, { capital: -15 });
    return { action: 'Expand', success: true, riding: name };
  }

  grievanceFromContest(loser, winner, riding, season, band) {
    const marker = this.relationMarker(loser, winner);
    if (marker === KIN || marker === COMPACT) return;
    const eventId = this.record(
      'relational',
      `${this.houseRow(loser).peerage} loses ${riding} to ${this.houseRow(winner).peerage}`,
      [loser, winner],
      season,
      { band, delta: { marker: GRIEVANCE, cause: 'contested expansion', riding } },
    );
    this.setRelation(loser, winner, GRIEVANCE, eventId, `contested claim to ${riding}`);
  }

  doInvest(house) {
    this.setStats(house, { capital: 8 });
    return { action: 'Invest', success: true };
  }

  doCultivateInfluence(house, season, rng, success) {
    if (success) this.setStats(house, { influence: 6, capital: -5 });
    else this.setStats(house, { capital: -5 });
    return { action: 'Cultivate influence', success };
  }

  doConsolidateRest(house) {
    this.setStats(house, { cohesion: 8 });
    return { action: 'Consolidate (rest)', success: true };
  }

  doNameHeir(house, season, rng, success, band) {
    const row = this.houseRow(house);
    const holder = this.holder(house);
    if (holder === null) return { action: 'Name heir', success: false };
    const existing = this.heirs(house);
    const role = existing.length > 0 ? 'heir2' : 'heir';
    const heirAge = Math.max(0, holder.age - (25 + rng.randint(1, 15, 'heir.age_gap')));
    const generator = new NameGenerator(this.rules, rng);
    const [given, surname, gender] = generator.drawPerson(row.community, null, house.split(' ')[0]);
    this.state.addPerson({
      house, name: `${given} ${surname}`, gender, age: heirAge, role, bornSeason: season,
    });
    if (role === 'heir2') this.setStats(house, { cohesion: 3 });
    this.record('other', `${row.peerage} names an heir`, [house], season, {
      band,
      line: `Season ${season} · ${row.peerage} names ${given} ${surname}${role === 'heir2' ? ' second heir' : ' heir'}.`,
      delta: { heir_age: heirAge, role },
    });
    return { action: 'Name heir', success: true, role };
  }

  doEndow(house, season, rng, success, band) {
    const row = this.houseRow(house);
    this.setStats(house, { influence: 10, cohesion: 5, capital: -25 });
    this.record('other', `${row.peerage} endows an institution`, [house], season, {
      band,
      line: `Season ${season} · ${row.peerage} endows an institution.`,
    });
    this.satisfyObjective(house, 'Endow an institution', season);
    return { action: 'Endow', success: true };
  }

  doPetitionElevation(house, season, rng, success, band) {
    const row = this.houseRow(house);
    if (!success) {
      this.setStats(house, { influence: -5 });
      return { action: 'Petition elevation', success: false };
    }
    const ladder = RANK_LADDER.map(([r]) => r);
    const current = this.rankIndex.get(row.rank) ?? 0;
    const newRank = ladder[Math.min(current + 1, ladder.length - 1)];

    // hoc/rules.py elevate: refuses a sideways or downward move, and rewrites
    // the peerage's leading rank word.
    if (!RANK_LEVEL.has(newRank) || !RANK_LEVEL.has(row.rank)) {
      return { action: 'Petition elevation', success: false };
    }
    if (RANK_LEVEL.get(newRank) <= RANK_LEVEL.get(row.rank)) {
      return { action: 'Petition elevation', success: false };
    }
    if (!row.peerage) return { action: 'Petition elevation', success: false };
    const spaceAt = row.peerage.indexOf(' ');
    const head = spaceAt === -1 ? row.peerage : row.peerage.slice(0, spaceAt);
    const rest = spaceAt === -1 ? '' : row.peerage.slice(spaceAt + 1);
    if (!RANK_LEVEL.has(head)) return { action: 'Petition elevation', success: false };
    const peerage = `${newRank} ${rest}`;
    const houseRecord = this.state.house(house);
    houseRecord.rank = newRank;
    houseRecord.peerage = peerage;

    this.setStats(house, { influence: -10 });
    this.record('elevation', `${peerage} elevated`, [house], season, {
      band,
      line: `Season ${season} · ${row.peerage} is raised to ${newRank}.`,
      delta: { from: row.rank, to: newRank },
    });
    this.satisfyObjective(house, 'Seek elevation', season);
    return { action: 'Petition elevation', success: true, rank: newRank };
  }

  // -- the PART B actions --

  doCorrespond(house, season, rng, success, band, roll) {
    const row = this.houseRow(house);
    const reachable = this.housesWithinReach(house);
    if (reachable.length === 0) {
      return { action: 'Correspond', success: false, note: 'no one in reach' };
    }
    const known = reachable.filter((o) => this.relationMarker(house, o) === ACQUAINTED);
    const other = this.pick(rng, known.length > 0 ? known : reachable, `correspond.target.${house}`);
    if (other === null) return { action: 'Correspond', success: false };

    const fumble = this.rules.friction.correspond_fumble;
    const currentMarker = this.relationMarker(house, other);
    if (roll === fumble.natural && currentMarker !== KIN && currentMarker !== COMPACT) {
      const otherRow = this.houseRow(other);
      const eventId = this.record(
        'relational',
        `${row.peerage} gives offence to ${otherRow.peerage}`,
        [house, other],
        season,
        {
          band,
          line: `Season ${season} · a letter from ${row.peerage} gives offence to ${otherRow.peerage}.`,
          delta: { marker: GRIEVANCE, cause: 'correspondence' },
        },
      );
      this.setRelation(house, other, GRIEVANCE, eventId, 'a letter that gave offence');
      return { action: 'Correspond', success: false, with: other, fumble: true };
    }

    if (!success) return { action: 'Correspond', success: false };

    const current = this.relationMarker(house, other);
    let marker = current === ACQUAINTED ? FRIENDLY : (current || ACQUAINTED);
    if ([COMPACT, KIN, GRIEVANCE, HOSTILE, CHALLENGED].includes(current)) marker = current;

    const otherRow = this.houseRow(other);
    const eventId = this.record(
      'relational',
      `${row.peerage} corresponds with ${otherRow.peerage}`,
      [house, other],
      season,
      {
        band,
        line: `Season ${season} · ${row.peerage} opens a correspondence with ${otherRow.peerage}.`,
        delta: { marker },
      },
    );
    this.setRelation(house, other, marker, eventId, 'correspondence');
    return { action: 'Correspond', success: true, with: other, marker };
  }

  doProposeCompact(house, season, rng, success, band) {
    const row = this.houseRow(house);
    const candidates = this.housesRelatedBy(house, new Set([FRIENDLY])).filter((other) => {
      const tag = this.houseRow(other).tag;
      return tag === row.tag || row.tag === 'Mixed' || tag === 'Mixed';
    });
    const other = this.pick(rng, candidates, `compact.target.${house}`);
    if (other === null || !success) return { action: 'Propose compact', success: false };

    const otherRow = this.houseRow(other);
    const eventId = this.record(
      'relational',
      `${row.peerage} and ${otherRow.peerage} form a compact`,
      [house, other],
      season,
      {
        band,
        line: `Season ${season} · ${row.peerage} and ${otherRow.peerage} enter into a compact.`,
        delta: { marker: COMPACT },
      },
    );
    this.setRelation(house, other, COMPACT, eventId, 'compact');
    this.setStats(house, { cohesion: 5 });
    this.setStats(other, { cohesion: 5 });
    this.satisfyObjective(house, 'Form a compact', season);
    this.satisfyObjective(other, 'Form a compact', season);
    this.satisfyObjective(house, 'Siege', season);
    return { action: 'Propose compact', success: true, with: other };
  }

  doReconcile(house, season, rng, success, band) {
    const row = this.houseRow(house);
    const other = this.pick(
      rng, this.housesRelatedBy(house, new Set([GRIEVANCE])), `reconcile.target.${house}`,
    );
    if (other === null || !success) return { action: 'Reconcile', success: false };

    const otherRow = this.houseRow(other);
    const eventId = this.record(
      'relational',
      `${row.peerage} reconciles with ${otherRow.peerage}`,
      [house, other],
      season,
      {
        band,
        line: `Season ${season} · ${row.peerage} makes peace with ${otherRow.peerage}.`,
        delta: { marker: RESOLVED },
      },
    );
    this.setRelation(house, other, RESOLVED, eventId, 'reconciliation');
    this.satisfyObjective(house, 'Answer a grievance', season);
    return { action: 'Reconcile', success: true, with: other };
  }

  doDispute(house, season, rng, success, band) {
    const row = this.houseRow(house);
    const candidates = this.housesRelatedBy(house, new Set([GRIEVANCE])).filter(
      (other) => this.adjacentHoldingOf(house, other) && !this.disputeBlocked(house, other, season),
    );
    const other = this.pick(rng, candidates, `dispute.target.${house}`);
    if (other === null) return { action: 'Dispute', success: false };

    const otherRow = this.houseRow(other);
    if (!success) {
      this.setStats(house, { cohesion: -10 });
      this.record(
        'relational',
        `${row.peerage} loses a dispute with ${otherRow.peerage}`,
        [house, other],
        season,
        {
          band,
          line: `Season ${season} · ${row.peerage} presses a claim against ${otherRow.peerage} and is rebuffed.`,
          delta: { outcome: 'lost' },
        },
      );
      return { action: 'Dispute', success: false, with: other };
    }

    this.setStats(other, { cohesion: -10 });
    const hardens = this.rules.friction.dispute_outcome.hardens_probability_pct;
    const marker = rng.chance(hardens, `dispute.hardens.${house}`) ? HOSTILE : RESOLVED;
    const eventId = this.record(
      'relational',
      `${row.peerage} wins a dispute with ${otherRow.peerage}`,
      [house, other],
      season,
      {
        band,
        line: `Season ${season} · ${row.peerage} carries a dispute against ${otherRow.peerage}.`,
        delta: { outcome: 'won', marker },
      },
    );
    this.setRelation(house, other, marker, eventId, 'dispute won');
    this.sync(house, other, eventId, season);
    this.satisfyObjective(house, 'Answer a grievance', season);
    return { action: 'Dispute', success: true, with: other, marker };
  }

  sync(houseA, houseB, eventId, season) {
    const year = Math.max(this.personalYear(houseA), this.personalYear(houseB));
    for (const house of [houseA, houseB]) {
      this.state.setClock(house, year, `synced at season ${season}, event ${eventId}`);
    }
  }

  doChallenge11b(house, season, rng, success, band, roll) {
    const row = this.houseRow(house);
    const candidates = this.housesRelatedBy(house, new Set([HOSTILE])).filter(
      (other) => this.adjacentHoldingOf(house, other),
    );
    const other = this.pick(rng, candidates, `challenge.target.${house}`);
    if (other === null) return { action: 'Challenge (11b)', success: false };

    const otherRow = this.houseRow(other);
    const climate = this.currentClimate(band) ?? 0;
    let modifier = { Progressive: 3, Conservative: -3, Outside: 6 }[row.tag] ?? 0;
    modifier = climate >= 0 ? modifier : -modifier;
    modifier += Math.max(
      0, (this.rankIndex.get(row.rank) ?? 0) - (this.rankIndex.get(otherRow.rank) ?? 0),
    );
    if (row.enclosed) modifier += 2;

    const total = (roll !== null ? roll : rng.twoD6(`challenge.roll.${house}`)) + modifier;
    if (total < this.actions.get('Challenge (11b)').target) {
      this.setStats(house, { ambition: -2, influence: -5 });
      const eventId = this.record(
        'challenge',
        `${row.peerage} fails against ${otherRow.peerage}`,
        [house, other],
        season,
        {
          band,
          line: `Season ${season} · ${row.peerage} challenges ${otherRow.peerage} and fails.`,
          delta: { outcome: 'failed', total },
        },
      );
      this.setRelation(
        house, other, this.rules.friction.challenge_outcome.failure_marker,
        eventId, 'a challenge that failed',
      );
      return { action: 'Challenge (11b)', success: false, with: other };
    }

    const fedId = this.adjacentHoldingOf(house, other);
    const name = this.ridingName(fedId);
    const eventId = this.record(
      'challenge',
      `${row.peerage} takes ${name} from ${otherRow.peerage}`,
      [house, other],
      season,
      {
        band,
        line: `Season ${season} · ${row.peerage} takes ${name} from ${otherRow.peerage} by challenge.`,
        delta: { outcome: 'won', riding: name, total, marker: CHALLENGED },
      },
    );
    for (const holding of this.state.holdings) {
      if (holding.house === other && holding.fedId === fedId && holding.releasedEventId === null) {
        this.state.releaseHolding(holding, eventId);
      }
    }
    this.state.addHolding({
      house, fedId, seatOrder: this.nextSeatOrder(house),
      hex: this.expansionHex(house), acquiredEventId: eventId,
    });
    this.setRelation(house, other, CHALLENGED, eventId, `challenge over ${name}`);
    this.sync(house, other, eventId, season);
    return { action: 'Challenge (11b)', success: true, with: other, riding: name };
  }

  doPurchaseRiding(house, season, rng, success, band) {
    const row = this.houseRow(house);
    const other = this.pick(rng, this.purchaseTargets(house), `purchase.target.${house}`);
    if (other === null) return { action: 'Purchase riding', success: false };
    if (!success) {
      this.setStats(house, { capital: -5 });
      return { action: 'Purchase riding', success: false, with: other };
    }

    const fedId = this.adjacentHoldingOf(house, other);
    const seat = this.state.holdings.find(
      (h) => h.house === other && h.fedId === fedId && h.releasedEventId === null,
    );
    if (fedId === null || seat === undefined || seat.seatOrder === 1) {
      return { action: 'Purchase riding', success: false, note: 'only the seat on offer' };
    }

    const otherRow = this.houseRow(other);
    const name = this.ridingName(fedId);
    const eventId = this.record(
      'transfer',
      `${row.peerage} buys ${name} from ${otherRow.peerage}`,
      [house, other],
      season,
      {
        band,
        line: `Season ${season} · ${row.peerage} buys ${name} from ${otherRow.peerage}.`,
        delta: { riding: name, price: 40 },
      },
    );
    this.state.releaseHolding(seat, eventId);
    this.state.addHolding({
      house, fedId, seatOrder: this.nextSeatOrder(house),
      hex: this.expansionHex(house), acquiredEventId: eventId,
    });
    this.setStats(house, { capital: -40 });
    this.setStats(other, { capital: 30 });
    this.sync(house, other, eventId, season);
    return { action: 'Purchase riding', success: true, with: other, riding: name };
  }

  doMarriageAlliance(house, season, rng, success, band) {
    const row = this.houseRow(house);
    const candidates = this.housesRelatedBy(house, new Set([FRIENDLY, COMPACT])).filter(
      (other) => this.unmarriedHeir(other),
    );
    const other = this.pick(rng, candidates, `marriage.target.${house}`);
    if (other === null || !this.unmarriedHeir(house) || !success) {
      return { action: 'Marriage alliance', success: false };
    }

    const otherRow = this.houseRow(other);
    const mine = this.unmarriedHeir(house);
    const theirs = this.unmarriedHeir(other);
    const eventId = this.record(
      'relational',
      `${row.peerage} and ${otherRow.peerage} are joined by marriage`,
      [house, other],
      season,
      {
        band,
        line: `Season ${season} · ${mine.name} marries ${theirs.name}, binding ${row.peerage} to ${otherRow.peerage}.`,
        delta: { marker: KIN },
      },
    );
    mine.married = 1;
    theirs.married = 1;
    this.setRelation(house, other, KIN, eventId, 'marriage alliance');
    this.setStats(house, { cohesion: 5 });
    this.setStats(other, { cohesion: 5 });
    this.sync(house, other, eventId, season);
    this.satisfyObjective(house, 'Form a compact', season);
    this.satisfyObjective(other, 'Form a compact', season);
    this.satisfyObjective(house, 'Siege', season);
    return { action: 'Marriage alliance', success: true, with: other };
  }

  doAbsorb(house, season, rng, success, band) {
    const row = this.houseRow(house);
    const other = this.pick(rng, this.absorbTargets(house), `absorb.target.${house}`);
    if (other === null) return { action: 'Absorb', success: false };
    if (!success) {
      const eventId = this.record(
        'relational',
        `${row.peerage} fails to absorb ${this.houseRow(other).peerage}`,
        [house, other],
        season,
        { band, delta: { marker: GRIEVANCE } },
      );
      this.setRelation(house, other, GRIEVANCE, eventId, 'failed absorption');
      return { action: 'Absorb', success: false, with: other };
    }
    this.absorbInto(house, other, season, band, 'absorption');
    return { action: 'Absorb', success: true, with: other };
  }

  absorbInto(house, other, season, band, reason) {
    const row = this.houseRow(house);
    const otherRow = this.houseRow(other);
    const eventId = this.record(
      'transfer',
      `${row.peerage} absorbs ${otherRow.peerage}`,
      [house, other],
      season,
      {
        band,
        line: `Season ${season} · ${row.peerage} absorbs ${otherRow.peerage}.`,
        delta: { nature: 'absorption', reason },
      },
    );
    const holdings = this.state.holdingsOf(other);
    for (const holding of holdings) {
      this.state.releaseHolding(holding, eventId);
      this.state.addHolding({
        house, fedId: holding.fedId, seatOrder: this.nextSeatOrder(house),
        hex: this.expansionHex(house), acquiredEventId: eventId,
      });
    }
    this.setStats(house, { cohesion: -10 });
    this.state.house(other).status = 'removed';
    this.state.stats(other).removedSeason = season;
    for (const person of this.state.persons) {
      if (person.house === other && person.alive === 1) {
        person.alive = 0;
        person.diedSeason = season;
      }
    }
    return eventId;
  }

  doCedeSwap(house, season, rng, success, band) {
    const row = this.houseRow(house);
    const candidates = this.housesRelatedBy(house, new Set([GRIEVANCE])).filter(
      (other) => this.adjacentHoldingOf(house, other),
    );
    const other = this.pick(rng, candidates, `cede.target.${house}`);
    if (other === null || !success) return { action: 'Cede / swap', success: false };

    const otherRow = this.houseRow(other);
    const ceded = this.loseRiding(house, season, 'cession', other);
    const eventId = this.record(
      'relational',
      `${row.peerage} settles with ${otherRow.peerage}`,
      [house, other],
      season,
      {
        band,
        line: `Season ${season} · ${row.peerage} settles its grievance with ${otherRow.peerage} by cession.`,
        delta: { marker: RESOLVED, ceded },
      },
    );
    this.setRelation(house, other, RESOLVED, eventId, 'cession');
    this.sync(house, other, eventId, season);
    this.satisfyObjective(house, 'Answer a grievance', season);
    return { action: 'Cede / swap', success: true, with: other };
  }

  // ------------------------------------------------------------ objectives --

  satisfyObjective(house, objective, season) {
    this.state.satisfyObjective(house, objective, season);
  }

  contiguousHoldings(house) {
    const fedIds = this.state.holdings
      .filter((h) => h.house === house && h.releasedEventId === null)
      .map((h) => h.fedId);
    if (fedIds.length < 2) return fedIds.length;
    const held = new Set(fedIds);
    const seen = new Set();
    let best = 0;
    for (const start of fedIds) {
      if (seen.has(start)) continue;
      const stack = [start];
      let size = 0;
      while (stack.length > 0) {
        const node = stack.pop();
        if (seen.has(node)) continue;
        seen.add(node);
        size += 1;
        for (const neighbour of this.state.map.land(node)) {
          if (held.has(neighbour) && !seen.has(neighbour)) stack.push(neighbour);
        }
      }
      best = Math.max(best, size);
    }
    return best;
  }

  checkObjectives(house, season, rng) {
    const row = this.houseRow(house);
    for (const objective of this.heldObjectives(house)) {
      let satisfied = false;
      if (objective === 'Consolidate region') {
        satisfied = this.contiguousHoldings(house) >= 4;
      } else if (objective === 'Secure succession') {
        const heirs = this.heirs(house);
        satisfied = heirs.length > 0 && heirs[0].age >= 25;
      } else if (objective === 'Defend the seat') {
        const since = this.seasonsSinceLoss(house);
        satisfied = since !== null && since >= DEFEND_THE_SEAT_SEASONS;
      } else if (objective === 'Siege') {
        const since = this.seasonsSinceLoss(house);
        satisfied = since !== null && since >= SIEGE_SEASONS;
      }
      if (satisfied) this.satisfyObjective(house, objective, season);
    }

    const held = this.heldObjectives(house);
    if (held.length < OBJECTIVES_AT_FOUNDING) {
      const heldSet = new Set(held);
      const weights = this.rules.objectives
        .filter((o) => !heldSet.has(o.objective))
        .map((o) => [
          o.objective,
          WEIGHT_SCALE + 2 * WEIGHT_SCALE * this.objectiveFavoured(o.objective, row, house),
        ]);
      const chosen = rng.weighted(weights, `objective.replace.${house}`);
      if (chosen !== null && held.length < MAX_OBJECTIVES) {
        this.state.addObjective(house, chosen, season);
      }
    }
  }

  // Seasons since this house last lost a riding. Note that `seasonNo` is the
  // *previous* season during a run: the current season's row is not written
  // until the end, exactly as in Python.
  seasonsSinceLoss(house) {
    let latest = null;
    for (const event of this.state.events) {
      if (event.kind !== 'transfer' || !event.houses.includes(house)) continue;
      if (latest === null || event.id > latest.id) latest = event;
    }
    const stats = this.houseRow(house);
    if (latest === null) {
      const founded = stats.foundedSeason;
      return founded === null || founded === undefined ? null : this.seasonNo - founded;
    }
    const last = latest.mechanicalDelta ? latest.mechanicalDelta.season : undefined;
    if (last === undefined) return null;
    return this.seasonNo - last;
  }

  // ------------------------------------------------------------- enclosure --

  recomputeEnclosure(season) {
    const unenclosed = this.state.unenclosedHouses();
    for (const row of this.activeHouses()) {
      const house = row.house;
      const enclosed = unenclosed.has(house) ? 0 : 1;
      const was = row.enclosed;
      let since = row.enclosedSince;

      if (enclosed && !was) since = season;
      else if (!enclosed) since = null;

      const stats = this.state.stats(house);
      stats.enclosed = enclosed;
      stats.enclosedSince = since;

      if (enclosed && since !== null && season - since > 0 && (season - since) % 10 === 0) {
        this.setStats(house, { ambition: row.tag === 'Progressive' ? -1 : 1 });
      }

      if (enclosed && row.cohesion < 40) {
        const held = this.heldObjectives(house);
        if (!held.includes('Siege') && held.length < MAX_OBJECTIVES) {
          this.state.addObjective(house, 'Siege', season);
        }
      }
    }
  }

  // ---------------------------------------------------------------- debt --

  debtCheck(house, season) {
    const row = this.houseRow(house);
    if (row.capital > 0) return;
    const recent = this.state.events.some(
      (e) => e.kind === 'transfer' && e.houses.includes(house) && e.title.includes('debt'),
    );
    if (recent) return;
    if (this.holdingCount(house) > 1) this.sellRiding(house, season, 'debt');
  }

  // ------------------------------------------------ director interventions --
  //
  // The §12 operations, ported from hoc/turn.py. A turn file applies them
  // *between* seasons through the Python turn runner; here they are applied to
  // the live world directly, and they must leave the same marks — the same
  // state change, and the same entry in the next season's `interventions`
  // field, or a browser-played game would not replay in Python.
  //
  // Each operation merges a note under its own key in one event's delta, the
  // way _merge_mechanical_delta does, and stamps `after_season` so
  // `interventionsSince` can find it exactly once.

  currentSeason() {
    return this.seasonNo;
  }

  // Apply one turn's worth of operations. Returns the event id.
  intervene(operations, title = "Director's intervention", kind = 'other') {
    const season = this.currentSeason();
    const delta = {};
    const houses = [];
    const note = (key, value) => {
      if (!Object.prototype.hasOwnProperty.call(delta, key)) delta[key] = [];
      delta[key].push(value);
    };
    const subject = (house) => {
      if (!houses.includes(house)) houses.push(house);
    };

    for (const op of operations) {
      switch (op.op) {
        case 'set_objective': this.opSetObjective(op, season, note, subject); break;
        case 'veto_objective': this.opVetoObjective(op, season, note, subject); break;
        case 'force_action': this.opForceAction(op, season, note, subject); break;
        case 'adjust_stat': this.opAdjustStat(op, season, note, subject); break;
        case 'grant_house': this.opGrantHouse(op, season, note, subject); break;
        case 'set_clock': this.opSetClock(op); break;
        case 'relation': this.opRelation(op); break;
        default: throw new SimError(`unknown intervention operation '${op.op}'`);
      }
    }

    // The event carries the whole turn, as the turn runner's does. Relations
    // recorded by the `relation` operation point at it, so it is created after
    // the operations have run and then back-filled — the same order the Python
    // runner ends up in, since it creates the event first and merges into it.
    const eventId = this.state.recordEvent({
      kind,
      title,
      houses,
      eraCohort: null,
      narrative: null,
      mechanicalDelta: delta,
      source: 'turn',
    });
    for (const relation of this._pendingRelations || []) {
      relation.eventId = eventId;
    }
    this._pendingRelations = [];
    return eventId;
  }

  requireEngineHouse(house) {
    const row = this.state.stats(house);
    if (row === undefined) {
      throw new SimError(
        `${house} has no engine state; director interventions apply to the`
        + ' autoplay game, not to the reconstructed one',
      );
    }
    return row;
  }

  opSetObjective(op, season, note, subject) {
    this.requireEngineHouse(op.house);
    const held = this.state.heldObjectives(op.house);
    if (held.includes(op.objective)) {
      throw new SimError(`${op.house} already holds the objective '${op.objective}'`);
    }
    this.state.addObjective(op.house, op.objective, season);
    subject(op.house);
    note('set_objective', {
      house: op.house, objective: op.objective, reason: op.reason ?? null, after_season: season,
    });
  }

  opVetoObjective(op, season, note, subject) {
    this.requireEngineHouse(op.house);
    const held = this.state.heldObjectives(op.house);
    if (!held.includes(op.objective)) {
      throw new SimError(
        `${op.house} does not currently hold the objective '${op.objective}'`,
      );
    }
    this.state.satisfyObjective(op.house, op.objective, season);
    subject(op.house);
    note('veto_objective', {
      house: op.house, objective: op.objective, reason: op.reason ?? null, after_season: season,
    });
  }

  opForceAction(op, season, note, subject) {
    this.requireEngineHouse(op.house);
    if (!this.actions.has(op.action)) {
      const known = [...this.actions.keys()].sort(compareStrings).join(', ');
      throw new SimError(`unknown action '${op.action}'; valid actions are ${known}`);
    }
    this.state.stats(op.house).forcedAction = op.action;
    subject(op.house);
    note('force_action', {
      house: op.house, action: op.action, reason: op.reason ?? null, after_season: season,
    });
  }

  opAdjustStat(op, season, note, subject) {
    const row = this.requireEngineHouse(op.house);
    const bounds = {
      capital: [0, 100], influence: [0, 100], cohesion: [0, 100], ambition: [0, 10],
    };
    if (!Object.prototype.hasOwnProperty.call(bounds, op.stat)) {
      throw new SimError(
        `unknown stat '${op.stat}'; adjustable stats are ${Object.keys(bounds).sort(compareStrings).join(', ')}`,
      );
    }
    // hoc/turn.py requires a reason and says why: an unexplained adjustment is
    // indistinguishable from a bug when someone reads the log later.
    if (!op.reason || !String(op.reason).trim()) {
      throw new SimError('adjust_stat needs a reason');
    }
    const [low, high] = bounds[op.stat];
    const before = row[op.stat];
    const after = clamp(before + Math.trunc(op.delta), low, high);
    row[op.stat] = after;
    subject(op.house);
    note('adjust_stat', {
      house: op.house, stat: op.stat, delta: Math.trunc(op.delta),
      before, after, reason: op.reason, after_season: season,
    });
  }

  opGrantHouse(op, season, note, subject) {
    const house = this.foundHouse(season, {
      seat: op.riding,
      rng: this.rngFor(season),
      community: op.community ?? null,
      tag: op.tag ?? null,
      rank: op.rank ?? null,
      surname: (op.surname || '').trim() || null,
    });
    if (house === null) {
      throw new SimError(
        `could not grant a house at '${op.riding}';`
        + " the riding may be held, or its province's place bank exhausted",
      );
    }
    subject(house);
    note('grant_house', {
      house, riding: op.riding, community: op.community ?? null, rank: op.rank ?? null,
      tag: op.tag ?? null, reason: op.reason ?? null, after_season: season,
    });
  }

  opSetClock(op) {
    if (!this.state.clocks.has(op.house)) throw new SimError(`unknown house '${op.house}'`);
    this.state.setClock(op.house, op.personal_year, op.basis);
  }

  opRelation(op) {
    // The turn runner inserts a relations row pointing at the turn's event,
    // which does not exist yet here; intervene() back-fills the id.
    const row = this.state.setRelation(
      op.house_a, op.house_b, op.marker, null, op.text, 'turn',
    );
    this._pendingRelations = this._pendingRelations || [];
    this._pendingRelations.push(row);
  }

  // Director interventions applied between the previous season and this one.
  //
  // A mirror of hoc/sim.py's _interventions_since: the same window (after the
  // previous season, before this one), the same shape, the same order.
  interventionsSince(season) {
    let previous = null;
    for (const row of this.state.seasons) {
      if (row.seasonNo < season && (previous === null || row.seasonNo > previous)) {
        previous = row.seasonNo;
      }
    }
    const out = [];
    for (const event of this.state.events) {
      const delta = event.mechanicalDelta;
      if (!delta || typeof delta !== 'object') continue;
      for (const operation of Object.keys(delta)) {
        const entries = delta[operation];
        const list = Array.isArray(entries) ? entries : [entries];
        for (const entry of list) {
          if (entry === null || typeof entry !== 'object' || Array.isArray(entry)) continue;
          const after = entry.after_season;
          if (after === undefined || after === null || after >= season) continue;
          if (previous !== null && after < previous) continue;
          out.push({ operation, title: event.title, ...entry });
        }
      }
    }
    return out;
  }

  // ------------------------------------------------------------ the season --

  initialise(worldSeed, seat = null) {
    this.worldSeed = worldSeed;
    this.log = [];
    this.chronicle = [];
    const rng = this.rngFor(1);

    const house = this.foundHouse(1, { seat, rng });
    if (house === null) {
      throw new SimError('season 1 founded no house: the map has no unclaimed riding');
    }

    const record = this.writeSeason(1, [], house);
    record.kind = 'initial';
    record.seat = seat;
    return record;
  }

  runSeason(seasonNo = null) {
    const season = seasonNo !== null ? seasonNo : this.seasonNo + 1;
    this.log = [];
    this.chronicle = [];
    const rng = this.rngFor(season);

    if (this.phases.has('clocks')) this.ageEveryone();

    this._turnCache = new Map();
    if (this.phases.has('friction')) this.runFriction(season, rng);

    const outcomes = [];
    this._expansionClaims = new Map();
    for (const row of this.activeHouses()) {
      const house = row.house;
      this._turnCache = new Map();
      if (this.houseRow(house).removedSeason !== null) continue;

      let fired = null;
      if (this.phases.has('events')) fired = this.eraEvent(house, season, rng);
      const extraMortality = Boolean(fired && fired.extraMortality);

      if (this.phases.has('mortality')) {
        if (this.mortality(house, season, rng, extraMortality)) continue;
      }

      if (this.phases.has('actions')) {
        const outcome = this.takeAction(house, season, rng);
        if (outcome) {
          outcomes.push(outcome);
          this.state.houseActions.push({
            id: this.state._takeId('houseActions'),
            seasonNo: season,
            house,
            action: outcome.action ?? '—',
            success: outcome.success ? 1 : 0,
            detail: outcome.riding ?? outcome.with ?? outcome.note ?? null,
          });
        }
      }

      if (this.phases.has('objectives')) this.checkObjectives(house, season, rng);
      if (this.phases.has('debt')) this.debtCheck(house, season);
    }

    let founded = null;
    if (this.phases.has('founding')) founded = this.foundingRoll(season, rng);
    if (this.phases.has('enclosure')) this.recomputeEnclosure(season);

    return this.writeSeason(season, outcomes, founded);
  }

  foundingRoll(season, rng) {
    const spec = this.rules.founding.p_found;
    const room = this.state.unclaimedLandAdjacentCount();
    const probability = pFound(room, TOTAL_RIDINGS, spec.coefficient);
    rng.draw('founding.p_found', { room, p: new FloatValue(probability) });
    if (probability <= 0) return null;
    if (!rng.chanceFloat(probability, 'founding.roll')) return null;
    return this.foundHouse(season, { rng });
  }

  snapshot(season) {
    if (season !== 1 && season % SNAPSHOT_EVERY !== 0) return;
    for (const [name, house] of this.state.houses) {
      if (house.status !== 'active') continue;
      const stats = this.state.stats(name);
      this.state.statSnapshots.push({
        seasonNo: season,
        house: name,
        capital: stats.capital,
        influence: stats.influence,
        cohesion: stats.cohesion,
        ambition: stats.ambition,
        holdings: this.holdingCount(name),
      });
    }
  }

  writeSeason(season, outcomes, founded) {
    this.snapshot(season);
    let housesAfter = 0;
    for (const house of this.state.houses.values()) {
      if (house.status === 'active') housesAfter += 1;
    }
    const ridingsAfter = this.state.totalCurrentHoldings();

    const record = {
      season,
      seed: this.worldSeed,
      rules_version: RULES_VERSION,
      engine: { impl: 'javascript', rules_version: RULES_VERSION },
      interventions: this.interventionsSince(season),
      draws: this.log,
      actions: outcomes,
      founded,
      chronicle: this.chronicle,
      houses_after: housesAfter,
      ridings_after: ridingsAfter,
    };

    this.state.seasons.push({
      seasonNo: season,
      seed: this.worldSeed,
      housesAfter,
      ridingsAfter,
      rulesVersion: RULES_VERSION,
    });
    return record;
  }

  // Which of §12's pause conditions a season met. A mirror of hoc/sim.py's
  // _stop_conditions, reading the same event deltas: `removal` is any house
  // leaving play, extinction or absorption alike, while `extinction` and
  // `partition` are the narrower conditions.
  stopConditions(season) {
    const hit = new Set();
    for (const event of this.state.events) {
      const delta = event.mechanicalDelta;
      if (!delta || delta.season !== season) continue;
      if (delta.nature === 'extinction' || delta.nature === 'absorption') hit.add('removal');
      if (delta.nature === 'extinction') hit.add('extinction');
      if (delta.nature === 'partition') hit.add('partition');
      if (event.kind === 'challenge') hit.add('challenge');
      if (delta.magnitude === 'Major') hit.add('major');
      if (delta.to === 'Marquis' || delta.to === 'Marchioness') hit.add('marquis');
    }
    return hit;
  }

  run(count) {
    const records = [];
    for (let i = 0; i < count; i += 1) records.push(this.runSeason());
    return records;
  }
}
