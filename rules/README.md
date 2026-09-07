# rules/

**Rules are versioned, and a season is always replayed under the rules it was played with.**

    rules/
      current.txt              the version a NEW season is played under
      versions/0.7/            one version's tables, frozen once published
        actions.csv ... features.json
      versions/0.8/
      CHANGELOG.md             one entry per version, with the metric that motivated it
      README.md

Every season file records `rules_version`, and `hoc/sim.py`'s `World.replay`, `web/engine/index.js`'s `replaySeasons`, `scripts/rebuild.py` and `scripts/referee.py` all load *that* version's tables to replay it. Without this, tuning a number would silently rewrite history: the committed record would stop reproducing the committed database, and the referee would start refusing seasons that were correct when they were played.

## The rule for every rules change

1. **Never edit a published version's tables.** A version directory is frozen the moment a season is played under it.
2. Copy the current version's directory to the next version, change the copy, and point `current.txt` at it. `scripts/apply_rules_patch.py` — the console's Rules control — does exactly this, and refuses if the directory already exists.
3. Record it in `CHANGELOG.md` with the metric that motivated it.
4. **A change in *algorithm* rather than in a number goes behind a named boolean in `features.json`**, false in every version that came before it. The old code path stays in both engines, reachable by replay, and the flag decides which one a season takes. `hoc/rules_data.py`'s `FEATURE_DEFAULTS` and `web/engine/rules.js`'s `FEATURE_DEFAULTS` are the two lists of known flags and must agree; both default every flag to false, so a version written before a flag existed keeps the behaviour it was played with.

A flag added with a `true` default would change the past, which is the one thing this arrangement exists to prevent. `tests/test_rules_versions.py` asserts the two default tables match and that every default is false.

## features.json

Named booleans, one per behaviour change. As of 0.8:

- `local_designations` — a house's territorial designation is drawn from places inside its seat riding, then the seat's own name tokens, then places in land-adjacent ridings, before falling back to the province bank. False in 0.7, which drew from the province bank alone.
- `quiet_season_line` — a season with no chronicle at all says so, and a house that has taken no notable action for ten consecutive seasons is noticed once. False in 0.7, which left both silent.

## The tables

Machine-readable transcription of `docs/ENGINE_DESIGN.md`'s numeric tables, loaded by `hoc/rules_data.py` and by `web/engine/rules.js`. Where the design gives a formula instead of a number, it is stored as a string in a `formula` field (or as prose in a JSON value) and implemented in the engines, not evaluated here. Every table below lives in a version directory.

- **actions.csv** — one row per action from §7 (17 rows, including the five enclosure-era additions: Purchase riding, Marriage alliance, Absorb, Cede / swap, Partition). Columns: `action` (name, exactly as headed in the design table); `preconditions`; `base_weight` (a number, or the literal string `forced` for Partition, which is never drawn from the weighted pool); `modifiers` (free text — bonuses and penalties, some numeric, some formulas); `target` (an integer 2–12 to roll 2d6 against, or `auto` for actions that always resolve without a roll); `success` / `failure` (free text describing the effect); `enclosure_bonus` (the extra modifier §7b grants when the house is enclosed, where the design states a number — blank where §7b names the action but never gives one; see CHANGELOG).
- **objectives.csv** — one row per objective from §5 (7 rows). Columns: `objective`; `favoured_by`; `satisfied_when`; `action_weight_bonus` (semicolon-separated action names, taken only from explicit "+N &lt;Objective&gt;" mentions in §7's modifiers column — an objective with no such mention anywhere in §7, like Defend the seat, is left blank rather than guessed).
- **mortality.csv** — one row per age band from §9. Columns: `age_min`, `age_max` (inclusive; the top band's `age_max` is a sentinel 150 standing in for "no realistic upper bound"), `annual_probability`, `note` (the flu/war extra-roll rule, repeated on every row since it applies regardless of age band).
- **founding.json** — `p_found` (the §10 formula, the only founding probability as of 0.3), `region_weights` (§10 starting weights, keyed by lowercase region id, and the drift rule), `tag_climate_fit`, `rank_probabilities`, `rank_index` (the ladder position each rank name maps to), `seat_riding_rule`, `cultural_community`, `cadet_foundings`, and `initial_stats` (the §4 founding-stat formulas).
- **succession.json** — `clean_succession`, `partition`, `disorderly_succession`, `extinction`, `heirs` (all §9); `losing_ridings` (§7c: contraction sale, debt, disorderly succession's riding-loss roll, cession, escheat); `enclosure` (§7b: definition, effects, and what happens once the map is full).
- **eras.json** — the three era bands and their personal-year ranges (§3), each with a lowercase `id` (the key used in data and code) and a display `name`, and `end_year: null` on the open-ended final band.
- **responses.json** — the four event-response options (Lead / Resist / Exploit / Neutral) and their effects, and the response-roll tag modifier chosen in version 0.1 (§8).
- **events.csv** — the event deck (§8), one row per event from 1867 to 1960. Columns: `personal_year`; `band` (the era band id from `eras.json` — `confederation`, `dominion`, `late`; a house's actual era context is still decided by its own personal clock against `eras.json`'s year ranges, since two houses in the same season are rarely in the same band); `name`; `magnitude` (Minor / Significant / Major); `tag` (Progressive / Conservative / Mixed / Global — Global marking an event with no partisan lean, distinct from `Outside`, which is a scope value below, not an event tag); `direct_effect` (see "Event effect scopes" below); `note`.
- **communities.csv** — the cultural-community table (§10), one row per community. Columns: `region` (`maritime, quebec, ontario, prairie, bc, north` — the same lowercase ids as `founding.json`'s `region_weights.initial` keys; six of the seven regions used for event scopes, since `newfoundland` is not a community region: before 1949 its communities are recorded under `maritime`, and after 1949 the event deck targets it directly by scope); `community`; `weight` (the founding draw weight within its region); `naming_tradition` (a key into `given_names.csv`); `note`.
- **places.csv** — territorial-designation place names (§10 seat-riding flavour), one row per place. Columns: `province` (2-letter code, matching the codes in `data/reference/ridings.csv`); `place`.
- **given_names.csv** — given names by naming tradition and gender. Columns: `tradition` (matches a `communities.naming_tradition` value); `gender` (`m` or `f`); `name`.
- **surnames.csv** — surnames by community. Columns: `community` (matches a `communities.community` value); `surname`.
- **features.json** — the named behaviour booleans described above.
- **CHANGELOG.md** — one entry per rules version, with the metric that motivated it. Not inside a version directory: it is the history of all of them.

## Event effect scopes

`events.direct_effect` is a semicolon-separated list of `stat:delta:scope` triples (or `mortality:extra:scope`, since a mortality effect has no signed magnitude — it marks an extra mortality roll rather than a delta). `stat` is a house-stat name (`capital`, `influence`, `cohesion`) or the literal `mortality`; `delta` is a signed integer, or the literal `extra` for a mortality effect. `scope` must be one of:

- `all` — every house, regardless of region, tag, or community;
- a region: `maritime, quebec, ontario, prairie, bc, north, newfoundland`;
- a tag: `Conservative, Progressive, Mixed, Outside`;
- a community group: `asian, francophone, metis, female_line`.

`hoc/rules_data.py` validates every scope against this vocabulary and raises `RulesDataError` naming the event and the offending scope on any other value.

## Naming policy

A house's name is drawn by pairing a surname from the community bank (`surnames.csv`, filtered to the house's cultural community) with a given name from that community's naming tradition (`given_names.csv`, filtered to `communities.naming_tradition` and the holder's gender). The engine must never combine a bank surname with a given name in a way that reproduces the full name of a well-known real person; Phase 9c adds a small denylist to check generated names against before use. These banks describe real cultural communities present in Canada between 1867 and 1960 and are to be treated with care: extend them only with the same care taken in their initial authoring, never by invention for narrative convenience.
