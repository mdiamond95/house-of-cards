// A deterministic dump of every portable primitive, for the parity test.
//
// `tests/test_js_engine_parity.py` runs this under node and compares the JSON
// it prints against the same values computed in Python. That is what keeps the
// two engines' foundations honest between full cross-checks: the cross-check
// tells you *that* the engines diverged, while this tells you *which
// primitive* did, which is the difference between an afternoon and a minute.
//
//     node web/engine/selftest.js [repo-root]
//
// Everything printed must be exactly reproducible in Python. Nothing here may
// depend on the clock, the filesystem layout beyond the repo root, or the
// platform.

import { readFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import { Prng, seasonSeed, fnv1a32, pFound } from './prng.js';
import { parseCsv } from './csv.js';
import {
  hslToHex,
  hexToHsl,
  hslDistanceSq,
  farthestHue,
  assignColours,
} from './palette.js';
import { loadRules, probabilityForAge } from './rules.js';
import { NameGenerator, nameKey, fold, casefold, peerageTitle, frenchParticle } from './names.js';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const ROOT = process.argv[2] ? path.resolve(process.argv[2]) : path.resolve(HERE, '..', '..');
const read = (relative) => readFileSync(path.join(ROOT, relative), 'utf8');

// A minimal logging-free RNG view: the banks and the palette need only these.
class Draws {
  constructor(seed) {
    this.p = new Prng(seed);
  }

  choice(seq) {
    return this.p.choice(seq);
  }

  randint(lo, hi) {
    return this.p.randInt(lo, hi);
  }
}

function prngSection() {
  const seed = seasonSeed(1867, 1);
  const words = new Prng(seed);
  const floats = new Prng(seed);
  const dice = new Prng(seed);
  const weighted = new Prng(seed);
  const ranges = new Prng(4242);

  const out = {
    season_seed: seed,
    state: new Prng(seed).s,
    fnv: ['1867:1', '1867:2', '2:1', '0:0', '999999:300'].map(fnv1a32),
    season_seeds: [
      seasonSeed(1867, 1),
      seasonSeed(1867, 2),
      seasonSeed(1, 1),
      seasonSeed(2, 300),
    ],
    first_ten: [],
    floats: [],
    dice: [],
    weighted: [],
    ranges: [],
    two_d6: [],
    p_found: [pFound(343, 343, 0.5), pFound(300, 343, 0.5), pFound(1, 343, 0.5), pFound(0, 343, 0.5)],
  };
  for (let i = 0; i < 10; i += 1) out.first_ten.push(words.nextU32());
  for (let i = 0; i < 20; i += 1) out.floats.push(floats.randFloat());
  for (let i = 0; i < 40; i += 1) out.dice.push(dice.randInt(1, 6));
  for (let i = 0; i < 40; i += 1) {
    out.weighted.push(weighted.weightedChoice(['a', 'b', 'c', 'd'], [300, 0, 250, 75]));
  }
  // Ranges that do and do not divide 2^32, plus a single-valued one (which
  // must consume no word at all).
  for (const [lo, hi] of [[0, 1], [1, 6], [1, 100], [0, 342], [5, 5], [-3, 3], [1, 65536]]) {
    const drawn = [];
    for (let i = 0; i < 12; i += 1) drawn.push(ranges.randInt(lo, hi));
    out.ranges.push({ lo, hi, drawn });
  }
  const pair = new Prng(77);
  for (let i = 0; i < 10; i += 1) out.two_d6.push(pair.rand2d6());
  return out;
}

function paletteSection() {
  const out = { to_hex: [], to_hsl: [], distance: [], farthest: [], assigned: [] };
  for (let h = 0; h < 360; h += 7) {
    for (let s = 0; s <= 100; s += 5) {
      for (let l = 0; l <= 100; l += 5) out.to_hex.push(hslToHex(h, s, l));
    }
  }
  for (const value of ['#4a6f8a', '#8a4a6f', '#6f8a4a', '#2b2b2b', '#ffffff', '#000000', '#123456', '#fedcba', '#010203']) {
    out.to_hsl.push(hexToHsl(value));
  }
  for (const [a, b] of [
    [[0, 40, 30], [180, 40, 30]],
    [[10, 35, 25], [350, 55, 40]],
    [[0, 0, 0], [0, 0, 0]],
    [[359, 55, 40], [1, 35, 25]],
  ]) {
    out.distance.push(hslDistanceSq(a, b));
  }
  for (const hues of [[], [0, 180], [90, 270], [10, 20, 30, 200], [0], [359]]) {
    out.farthest.push(farthestHue(hues));
  }
  const rng = new Draws(4);
  const primaries = [];
  for (let i = 0; i < 120; i += 1) {
    const [primary, secondary] = assignColours(primaries, rng);
    primaries.push(primary);
    out.assigned.push([primary, secondary]);
  }
  return out;
}

function rulesSection(rules) {
  return {
    csv_row_counts: Object.fromEntries(
      [
        'rules/actions.csv',
        'rules/communities.csv',
        'rules/denylist.csv',
        'rules/events.csv',
        'rules/given_names.csv',
        'rules/mortality.csv',
        'rules/objectives.csv',
        'rules/places.csv',
        'rules/surnames.csv',
        'data/reference/ridings.csv',
        'data/reference/adjacency.csv',
      ].map((name) => [name, parseCsv(read(name)).length]),
    ),
    // Every cell of the two smallest tables, so a parsing difference shows up
    // as data rather than as a count.
    mortality: rules.mortality,
    actions: rules.actions,
    objectives: rules.objectives,
    community_weights: rules.communities.map((c) => [c.community, c.weight, c.region, c.namingTradition]),
    mortality_at: [0, 30, 59, 60, 69, 70, 85, 95, 150].map((age) =>
      probabilityForAge(rules.mortality, age),
    ),
    region_weights: rules.founding.region_weights.initial,
    rank_weights: rules.founding.rank_probabilities,
    coefficient: rules.founding.p_found.coefficient,
    hardens_pct: rules.friction.dispute_outcome.hardens_probability_pct,
    sig_minus_pct: rules.succession.disorderly_succession.sig_minus_probability_pct,
    riding_loss_pct: rules.succession.losing_ridings.disorderly_succession.probability_pct,
  };
}

function namesSection(rules) {
  const strings = [];
  for (const row of rules.surnames) strings.push(row.surname);
  for (const row of rules.givenNames) strings.push(row.name);
  for (const row of rules.places) strings.push(row.place);
  for (const row of rules.communities) strings.push(row.community);
  for (const row of parseCsv(read('data/reference/ridings.csv')).slice(1)) strings.push(row[1]);

  const out = {
    casefold: strings.map(casefold),
    name_key: strings.map(nameKey),
    fold: strings.map(fold),
    particle: [],
    peerage: [],
    persons: [],
    places: [],
    houses: [],
  };
  for (const place of ['Le Rocher', 'La Prairie', 'Les Îles', "L'Assomption", 'the Red River', 'Alberni', 'Îles-de-la-Madeleine', 'Ottawa', 'the Le Mans']) {
    out.particle.push(frenchParticle(place));
  }
  for (const tradition of ['french', 'scots', 'english', 'anishinaabe']) {
    for (const place of ['Le Rocher', 'Alberni', "L'Assomption", 'Les Îles']) {
      out.peerage.push(peerageTitle('Baron', 'Tremblay', place, tradition));
    }
  }
  const generator = new NameGenerator(rules, new Draws(1867));
  for (const community of ['Irish Protestant (Orange)', 'Canadien Catholic', 'Scottish Highland Catholic', 'Cree and Saulteaux']) {
    for (let i = 0; i < 30; i += 1) out.persons.push(generator.drawPerson(community));
  }
  const placeGen = new NameGenerator(rules, new Draws(99));
  for (const province of ['ON', 'QC', 'NS', 'BC', 'MB']) {
    for (let i = 0; i < 12; i += 1) out.places.push(placeGen.drawPlace(province, ['Glengarry', 'Alberni']));
  }
  const houseGen = new NameGenerator(rules, new Draws(5));
  for (const [community, province, rank] of [
    ['Canadien Catholic', 'QC', 'Baron'],
    ['Irish Catholic', 'ON', 'Viscount'],
    ['Scottish Presbyterian', 'NS', 'Earl'],
  ]) {
    for (let i = 0; i < 10; i += 1) out.houses.push(houseGen.drawHouse(community, province, rank, []));
  }
  return out;
}

function main() {
  const rules = loadRules(read);
  process.stdout.write(
    JSON.stringify({
      prng: prngSection(),
      palette: paletteSection(),
      rules: rulesSection(rules),
      names: namesSection(rules),
    }),
  );
}

main();
