# rules/

Machine-readable transcription of `docs/ENGINE_DESIGN.md`'s numeric tables, loaded by `hoc/rules_data.py`. Nothing here is read by the running game yet — the season engine that consumes it is Phase 9c. Where the design gives a formula instead of a number, it is stored as a string in a `formula` field (or as prose in a JSON value) for 9c to implement, not evaluated here. See `CHANGELOG.md` for the one number this pass had to choose rather than transcribe, and for how table versions map to played seasons once the engine exists.

- **actions.csv** — one row per action from §7 (17 rows, including the five enclosure-era additions: Purchase riding, Marriage alliance, Absorb, Cede / swap, Partition). Columns: `action` (name, exactly as headed in the design table); `preconditions`; `base_weight` (a number, or the literal string `forced` for Partition, which is never drawn from the weighted pool); `modifiers` (free text — bonuses and penalties, some numeric, some formulas); `target` (an integer 2–12 to roll 2d6 against, or `auto` for actions that always resolve without a roll); `success` / `failure` (free text describing the effect); `enclosure_bonus` (the extra modifier §7b grants when the house is enclosed, where the design states a number — blank where §7b names the action but never gives one; see CHANGELOG).
- **objectives.csv** — one row per objective from §5 (7 rows). Columns: `objective`; `favoured_by`; `satisfied_when`; `action_weight_bonus` (semicolon-separated action names, taken only from explicit "+N &lt;Objective&gt;" mentions in §7's modifiers column — an objective with no such mention anywhere in §7, like Defend the seat, is left blank rather than guessed).
- **mortality.csv** — one row per age band from §9. Columns: `age_min`, `age_max` (inclusive; the top band's `age_max` is a sentinel 150 standing in for "no realistic upper bound"), `annual_probability`, `note` (the flu/war extra-roll rule, repeated on every row since it applies regardless of age band).
- **founding.json** — `p_found` (both of the design's two, seemingly conflicting, statements of the founding probability — see CHANGELOG), `region_weights` (§10 starting weights and drift rule), `tag_climate_fit`, `rank_probabilities`, `seat_riding_rule`, `cultural_community`, `cadet_foundings`, and `initial_stats` (the §4 founding-stat formulas).
- **succession.json** — `clean_succession`, `partition`, `disorderly_succession`, `extinction`, `heirs` (all §9); `losing_ridings` (§7c: contraction sale, debt, disorderly succession's riding-loss roll, cession, escheat); `enclosure` (§7b: definition, effects, and what happens once the map is full).
- **eras.json** — the three era bands and their personal-year ranges (§3), with `end_year: null` on the open-ended final band.
- **responses.json** — the four event-response options (Lead / Resist / Exploit / Neutral) and their effects, and the response-roll tag modifier chosen in version 0.1 (§8).
- **events.csv** — the event deck (§8), one row per event from 1867 to 1960. Columns: `personal_year`; `band` (a free-text label for the event's rough period — `confederation`, `dominion`, `late` — not the canonical era-band names in `eras.json`, since a house's actual era context is decided by its own personal clock against `eras.json`'s year ranges, never by this label; see CHANGELOG); `name`; `magnitude` (Minor / Significant / Major); `tag` (Progressive / Conservative / Mixed / Global — Global marking an event with no partisan lean, distinct from `Outside`, which is a scope value below, not an event tag); `direct_effect` (see "Event effect scopes" below); `note`.
- **communities.csv** — the cultural-community table (§10), one row per community. Columns: `region` (`maritime, quebec, ontario, prairie, bc, north` — six of the seven regions used for event scopes; `newfoundland` is not a community region here because before 1949 its communities are recorded under `maritime`, and after 1949 the event deck targets it directly by scope, see CHANGELOG); `community`; `weight` (the founding draw weight within its region); `naming_tradition` (a key into `given_names.csv`); `note`.
- **places.csv** — territorial-designation place names (§10 seat-riding flavour), one row per place. Columns: `province` (2-letter code, matching the codes in `data/reference/ridings.csv`); `place`.
- **given_names.csv** — given names by naming tradition and gender. Columns: `tradition` (matches a `communities.naming_tradition` value); `gender` (`m` or `f`); `name`.
- **surnames.csv** — surnames by community. Columns: `community` (matches a `communities.community` value); `surname`.
- **CHANGELOG.md** — one entry per rules version; every table carries the version it belongs to once seasons exist to be played under it.

## Event effect scopes

`events.direct_effect` is a semicolon-separated list of `stat:delta:scope` triples (or `mortality:extra:scope`, since a mortality effect has no signed magnitude — it marks an extra mortality roll rather than a delta). `stat` is a house-stat name (`capital`, `influence`, `cohesion`) or the literal `mortality`; `delta` is a signed integer, or the literal `extra` for a mortality effect. `scope` must be one of:

- `all` — every house, regardless of region, tag, or community;
- a region: `maritime, quebec, ontario, prairie, bc, north, newfoundland`;
- a tag: `Conservative, Progressive, Mixed, Outside`;
- a community group: `asian, francophone, metis, female_line`.

`hoc/rules_data.py` validates every scope against this vocabulary and raises `RulesDataError` naming the event and the offending scope on any other value.

## Naming policy

A house's name is drawn by pairing a surname from the community bank (`surnames.csv`, filtered to the house's cultural community) with a given name from that community's naming tradition (`given_names.csv`, filtered to `communities.naming_tradition` and the holder's gender). The engine must never combine a bank surname with a given name in a way that reproduces the full name of a well-known real person; Phase 9c adds a small denylist to check generated names against before use. These banks describe real cultural communities present in Canada between 1867 and 1960 and are to be treated with care: extend them only with the same care taken in their initial authoring, never by invention for narrative convenience.
