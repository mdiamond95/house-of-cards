// Loading rules/ — the same tables the Python engine reads, typed the same way.
//
// A mirror of hoc/rules_data.py's loading half. It does not repeat that file's
// validation: `hoc.rules_data` is the gatekeeper for the tables, runs in the
// test suite and in the engine workflow, and a second set of half-matching
// checks here would be two definitions of "valid" to keep in step. What this
// file must get exactly right is the **typing and the row order**, because
// those are what the draws depend on (docs/DETERMINISM.md).
//
// Every numeric field is parsed with parseInt, not Number: rules 0.7 made every
// weight and probability an integer, and a value that is silently a float here
// would diverge from Python without any error to point at it.

import { parseCsvDicts } from './csv.js';
import { loadDenylist } from './names.js';

// Python's int() accepts a leading '+' and surrounding whitespace; the event
// deck uses '+5' for a positive direct effect, so this has to as well.
function toInt(value, label) {
  const text = String(value).trim();
  if (!/^[+-]?\d+$/.test(text)) {
    throw new Error(`${label}: '${value}' is not an integer (rules 0.7 requires integers)`);
  }
  return parseInt(text, 10);
}

// Split a semicolon-separated list the way hoc/rules_data.py does.
function splitList(raw) {
  return (raw || '')
    .split(';')
    .map((part) => part.trim())
    .filter((part) => part.length > 0);
}

// Every behaviour flag the engines know about, and what a version that does not
// name it means. A mirror of hoc/rules_data.py's FEATURE_DEFAULTS, and it must
// stay one: a flag that defaulted differently in the two engines would be a
// divergence the cross-check finds only when that code path is reached.
//
// Every default is false. A version's features.json says what that version
// turns *on*, so a rules directory written before a flag existed keeps the
// behaviour it was played with.
export const FEATURE_DEFAULTS = {
  local_designations: false,
  quiet_season_line: false,
};

// Where a version's tables live. Rules are versioned so that a season always
// replays under the rules it was played with — see hoc/rules_data.py and
// rules/README.md for why that is not optional.
export function rulesPath(version, name) {
  return `rules/versions/${version}/${name}`;
}

/** One version's behaviour flags, defaulted for anything it does not name. */
export function loadFeatures(read, version) {
  const features = { ...FEATURE_DEFAULTS };
  let text;
  try {
    text = read(rulesPath(version, 'features.json'));
  } catch (error) {
    return features;  // a version predating features.json turns nothing on
  }
  const declared = JSON.parse(text);
  for (const [name, value] of Object.entries(declared)) {
    if (!(name in FEATURE_DEFAULTS)) {
      throw new Error(
        `rules ${version} features.json names a feature the engine does not know:`
        + ` ${name}. Add it to FEATURE_DEFAULTS (defaulting to false) first.`,
      );
    }
    if (typeof value !== 'boolean') {
      throw new Error(`rules ${version} features.json: ${name} must be true or false`);
    }
    features[name] = value;
  }
  return features;
}

/** The version a new season is played under, from rules/current.txt. */
export function currentVersion(read) {
  const version = read('rules/current.txt').trim();
  if (!version) throw new Error('rules/current.txt is empty; it must name a rules version');
  return version;
}

// `read(relativePath)` returns the file's text. The caller supplies it, so this
// module works unchanged under node (readFileSync) and in a browser (fetch),
// which is what web/engine has to do without a build step.
//
// `version` names which version's tables to load; it defaults to whatever
// rules/current.txt says, which is right for a new season and wrong for a
// replay — a replay passes the version its season file recorded.
export function loadRules(read, version = null) {
  const rulesVersion = version || currentVersion(read);
  const table = (name) => read(rulesPath(rulesVersion, name));
  const actions = parseCsvDicts(table('actions.csv')).map((row) => ({
    action: row.action,
    preconditions: row.preconditions,
    // Left a string on purpose: 'forced' is a legal value, and the engine tries
    // an integer conversion and skips the row when it fails (hoc/sim.py).
    baseWeight: row.base_weight,
    modifiers: row.modifiers,
    target: row.target === 'auto' ? 'auto' : toInt(row.target, `actions.${row.action}.target`),
    success: row.success,
    failure: row.failure,
    enclosureBonus: row.enclosure_bonus,
  }));

  const objectives = parseCsvDicts(table('objectives.csv')).map((row) => ({
    objective: row.objective,
    favouredBy: row.favoured_by,
    satisfiedWhen: row.satisfied_when,
    actionWeightBonus: splitList(row.action_weight_bonus),
  }));

  const mortality = parseCsvDicts(table('mortality.csv'))
    .map((row) => ({
      ageMin: toInt(row.age_min, 'mortality.age_min'),
      ageMax: toInt(row.age_max, 'mortality.age_max'),
      annualProbabilityPct: toInt(row.annual_probability_pct, 'mortality.annual_probability_pct'),
      note: row.note,
    }))
    .sort((a, b) => a.ageMin - b.ageMin);

  const communities = parseCsvDicts(table('communities.csv')).map((row) => ({
    region: row.region,
    community: row.community,
    weight: toInt(row.weight, `communities.${row.community}.weight`),
    namingTradition: row.naming_tradition,
    note: row.note,
  }));

  const surnames = parseCsvDicts(table('surnames.csv')).map((row) => ({
    community: row.community,
    surname: row.surname,
  }));

  const givenNames = parseCsvDicts(table('given_names.csv')).map((row) => ({
    tradition: row.tradition,
    gender: row.gender,
    name: row.name,
  }));

  const places = parseCsvDicts(table('places.csv')).map((row) => ({
    province: row.province,
    place: row.place,
  }));

  // The event deck. `direct_effect` is a semicolon-separated list of
  // stat:delta:scope triples; mortality's delta is the literal "extra" and
  // every other delta is an integer. Parsed the same way hoc/rules_data.py
  // parses it, and left unvalidated for the same reason as everything else
  // here — that file is the gatekeeper.
  const events = parseCsvDicts(table('events.csv')).map((row) => ({
    personalYear: toInt(row.personal_year, `events.${row.name}.personal_year`),
    band: row.band,
    name: row.name,
    magnitude: row.magnitude,
    tag: row.tag,
    directEffect: (row.direct_effect || '')
      .trim()
      .split(';')
      .map((part) => part.trim())
      .filter((part) => part.length > 0)
      .map((triple) => {
        const [stat, delta, scope] = triple.split(':');
        return {
          stat,
          delta: stat === 'mortality' ? delta : toInt(delta, `events.${row.name}.direct_effect`),
          scope,
        };
      }),
    note: row.note,
  }));

  return {
    actions,
    objectives,
    mortality,
    communities,
    surnames,
    givenNames,
    places,
    events,
    denylist: loadDenylist(table('denylist.csv')),
    // Era bands, sorted by start year — hoc/sim.py sorts them the same way in
    // its constructor, and band_for walks them in that order.
    eras: JSON.parse(table('eras.json')).bands
      .slice()
      .sort((a, b) => a.start_year - b.start_year),
    founding: JSON.parse(table('founding.json')),
    succession: JSON.parse(table('succession.json')),
    responses: JSON.parse(table('responses.json')),
    friction: JSON.parse(table('friction.json')),
    // Which version's tables these are, and what that version turns on. Carried
    // on the bundle so nothing downstream has to ask a second time and risk
    // asking about a different version than the one it is holding.
    version: rulesVersion,
    features: loadFeatures(read, rulesVersion),
  };
}

/** Whether a loaded bundle's version turns on a named behaviour. */
export function feature(rules, name) {
  if (!(name in FEATURE_DEFAULTS)) throw new Error(`no such rules feature ${name}`);
  const features = rules.features || {};
  return Boolean(name in features ? features[name] : FEATURE_DEFAULTS[name]);
}

// The annual death chance for a holder of the given age, as an integer per cent.
export function probabilityForAge(mortality, age) {
  for (const band of mortality) {
    if (band.ageMin <= age && age <= band.ageMax) return band.annualProbabilityPct;
  }
  throw new Error(`no mortality band covers age ${age}`);
}
