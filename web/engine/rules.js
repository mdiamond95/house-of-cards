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

// `read(relativePath)` returns the file's text. The caller supplies it, so this
// module works unchanged under node (readFileSync) and in a browser (fetch),
// which is what web/engine has to do without a build step.
export function loadRules(read) {
  const actions = parseCsvDicts(read('rules/actions.csv')).map((row) => ({
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

  const objectives = parseCsvDicts(read('rules/objectives.csv')).map((row) => ({
    objective: row.objective,
    favouredBy: row.favoured_by,
    satisfiedWhen: row.satisfied_when,
    actionWeightBonus: splitList(row.action_weight_bonus),
  }));

  const mortality = parseCsvDicts(read('rules/mortality.csv'))
    .map((row) => ({
      ageMin: toInt(row.age_min, 'mortality.age_min'),
      ageMax: toInt(row.age_max, 'mortality.age_max'),
      annualProbabilityPct: toInt(row.annual_probability_pct, 'mortality.annual_probability_pct'),
      note: row.note,
    }))
    .sort((a, b) => a.ageMin - b.ageMin);

  const communities = parseCsvDicts(read('rules/communities.csv')).map((row) => ({
    region: row.region,
    community: row.community,
    weight: toInt(row.weight, `communities.${row.community}.weight`),
    namingTradition: row.naming_tradition,
    note: row.note,
  }));

  const surnames = parseCsvDicts(read('rules/surnames.csv')).map((row) => ({
    community: row.community,
    surname: row.surname,
  }));

  const givenNames = parseCsvDicts(read('rules/given_names.csv')).map((row) => ({
    tradition: row.tradition,
    gender: row.gender,
    name: row.name,
  }));

  const places = parseCsvDicts(read('rules/places.csv')).map((row) => ({
    province: row.province,
    place: row.place,
  }));

  // The event deck. `direct_effect` is a semicolon-separated list of
  // stat:delta:scope triples; mortality's delta is the literal "extra" and
  // every other delta is an integer. Parsed the same way hoc/rules_data.py
  // parses it, and left unvalidated for the same reason as everything else
  // here — that file is the gatekeeper.
  const events = parseCsvDicts(read('rules/events.csv')).map((row) => ({
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
    denylist: loadDenylist(read('rules/denylist.csv')),
    // Era bands, sorted by start year — hoc/sim.py sorts them the same way in
    // its constructor, and band_for walks them in that order.
    eras: JSON.parse(read('rules/eras.json')).bands
      .slice()
      .sort((a, b) => a.start_year - b.start_year),
    founding: JSON.parse(read('rules/founding.json')),
    succession: JSON.parse(read('rules/succession.json')),
    responses: JSON.parse(read('rules/responses.json')),
    friction: JSON.parse(read('rules/friction.json')),
  };
}

// The annual death chance for a holder of the given age, as an integer per cent.
export function probabilityForAge(mortality, age) {
  for (const band of mortality) {
    if (band.ageMin <= age && age <= band.ageMax) return band.annualProbabilityPct;
  }
  throw new Error(`no mortality band covers age ${age}`);
}
