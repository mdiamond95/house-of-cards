# rules/

**Rules are versioned, and a season is always replayed under the rules it was played with.**

    rules/
      current.txt              the version a NEW season is played under
      versions/0.7/            one version's tables, frozen once published
        actions.csv ... features.json
      versions/0.8/
      versions/0.9/
      CHANGELOG.md             one entry per version, with the metric that motivated it
      README.md

Every season file records `rules_version`, and `hoc/sim.py`'s `World.replay`, `web/engine/index.js`'s `replaySeasons`, `scripts/rebuild.py` and `scripts/referee.py` all load *that* version's tables to replay it. Without this, tuning a number would silently rewrite history: the committed record would stop reproducing the committed database, and the referee would start refusing seasons that were correct when they were played.

## The rule for every rules change

1. **Never edit a published version's tables.** A version directory is frozen the moment a season is played under it.
2. Copy the current version's directory to the next version, change the copy, and point `current.txt` at it. `scripts/apply_rules_patch.py` — the console's Rules control — does exactly this, and refuses if the directory already exists.
3. Record it in `CHANGELOG.md` with the metric that motivated it.
4. **A change in *algorithm* rather than in a number goes behind a named boolean in `features.json`**, false in every version that came before it. The old code path stays in both engines, reachable by replay, and the flag decides which one a season takes. `hoc/rules_data.py`'s `FEATURE_DEFAULTS` and `web/engine/rules.js`'s `FEATURE_DEFAULTS` are the two lists of known flags and must agree; both default every flag to false, so a version written before a flag existed keeps the behaviour it was played with.

A flag added with a `true` default would change the past, which is the one thing this arrangement exists to prevent. `tests/test_rules_versions.py` asserts the two default tables match and that every default is false.

## A draft version

**Rules 1.0 is a draft.** `versions/1.0/` exists so both engines, the cross-check and `scripts/story_trial.py` can play it, but `current.txt` stays at 0.9 and no season of any committed game — live or frozen — has been played under it. Until one is, its tables are not published and may still be edited, which is what tuning a draft means. The rule above ("never edit a published version's tables") applies from the moment the first season under 1.0 is committed; from then on it is frozen like every other version. Only one draft version may exist at a time: `tests/test_rules_versions.py` allows exactly one directory newer than `current.txt`.

## features.json

Named booleans, one per behaviour change. As of 0.9:

- `local_designations` — a house's territorial designation is drawn from places inside its seat riding, then the seat's own name tokens, then places in land-adjacent ridings, before falling back to the province bank. False in 0.7, which drew from the province bank alone.
- `quiet_season_line` — a season with no chronicle at all says so, and a house that has taken no notable action for ten consecutive seasons is noticed once. False in 0.7, which left both silent.
- `atlas_jurisdiction` — a house reads the map at its own personal year. A riding whose `opens_year` (the reference set's `riding_stats.csv`) is later than the house's personal year is closed to it: the Crown seats no new house there (a new house's clock reads 1867, so only `opens_year` 1867 is foundable), the region weights and `p_found` count only unclaimed *foundable* ridings, and Expand never offers it, filtered before any draw. Cadet foundings by partition, transfers and shared events are not gated. `grant_house` and a forced Expand are refused on a closed riding by name. Founding and expansion records name the riding's jurisdiction at that year (`riding_jurisdictions.csv`), for display only. False in 0.7 and 0.8, which opened every riding.
- `riding_endowments` — founding capital adds `2*(wealth_tier − 3)` of the seat, and a successful Expand costs `15 + (wealth_tier − 3)` of the target instead of 15. False in 0.7 and 0.8, where every riding was worth the same.

Both 0.9 flags read `riding_stats.csv`; on a reference set without it (`ne-2026`) every riding is open at 1867 and every `wealth_tier` reads 3, so turning them on changes nothing there.

Rules 1.0 (draft; `docs/STORY_DESIGN.md` §4) adds six, false in 0.7–0.9 and on in 1.0:

- `upkeep_phase` — at the start of a house's turn, before events, capital, influence and cohesion move by an automatic integer upkeep (`upkeep.json`: from holdings, the seat's wealth tier and the holder's traits). Invest, Cultivate influence, Consolidate (rest) and Correspond leave the action pool; each house gets one automatic letter a turn at `correspondence_pct`, resolved exactly as Correspond was, offence included (its events carry `letter: true`). A house with nothing legal to do bides (`Bide` in `house_actions`).
- `holder_traits` — a holder draws two traits from `traits.csv` at founding or accession; an heir's are drawn when the heir is named. Each shifts named action weights by 2 × WEIGHT_SCALE or an upkeep by 1; Zealot never responds Neutral to an era event and adds 1 friction a turn on each opposed-tag border. Grasping/Cautious and Litigious/Conciliator never occur together. Traits are recorded on `persons.traits` and in the founding, succession and naming events.
- `marriage_pairing` — a Marriage alliance pairs one man and one woman, by recorded gender, from the two houses' unmarried heirs and children, and is legal only when such a pair exists.
- `prestige` — every season each active house's prestige (10 per holding, 20 per rank index, influence // 5, 5 per compact or kin tie, 15 per dispute or challenge won, −15 per riding lost to another house) is written to `house_stats.prestige`, `prestige_history` and the season record. Nothing reads it yet.
- `founding_curve` — Crown foundings follow `founding.json`'s `founding_curve` schedule of integer per cents in place of `p_found`, and after `late_after` never fall within `late_gap` seasons of the last. Partition is unaffected.
- `succession_watch` — an event when a holder turns 60 with no heir named, and one when an heir comes of age (`succession.json` `watch`).

Phase C2 (§4.2, §4.4, §4.5, §4.9) adds four more, false in 0.7–0.9 and on in 1.0:

- `schemes` — the weighted action draw is not used. A house holds at most one public scheme (`schemes.csv`). On its turn it takes that scheme's next step, each step committing capital or influence. A house without a scheme begins one, chosen by an integer utility from its situation, objectives, holder traits, the target riding's wealth tier and (with `prestige_politics`) prestige, by a seeded draw among the three highest. A house with nothing to choose bides.
  - A house that is the target of a claim may, on its next turn, set its scheme aside and answer it: Fortify, Seek a protector, Sue for peace or Counter-claim. It answers only when an answer beats `choice.answer_stand`. A house already pressing a claim against its claimant keeps to that claim.
  - A grievance cannot be reconciled in its first `peace.wait` turns.
  - A scheme is abandoned when its target is gone, its funds run out, or a new holder scores it below `choice.abandon_below`; an abandoned scheme returns `abandon_refund_pct` of its stake.
  - Every begin, step, answer, abandonment and resolution is an event with its turns remaining, and each season record carries `plans`, the public schemes as the season left them.
  - The existing action handlers stay the resolution primitives. Break a rival hardens on success, and Make peace may also end open hostility.
- `contested_claims` — a Claim resolves as a contest:
  - The attacker rolls 2d6 + committed // `committed_per_point` + rank index + 2 per ally + the holder's claim trait. The defender rolls 2d6 + fortified // `fortified_per_point` + cohesion // 25 + 2 per ally + 2 for a seat (`schemes.json` `contest`). Ties go to the defender.
  - The loser loses its stake and `loss_cohesion` cohesion, and begins no claim for `loser_bar` turns (Phase D1).
  - A seat can be taken, and a house left with no riding falls, naming the house that took its seat.
  - A win by 5 against cohesion below 40 takes a second riding.
  - The pair is then hostile and may not contest again for `cooldown` turns.
  - Allies (compact or kin) are each asked on a per-cent utility test, and a refusal is recorded.
  - Without this flag no claim is offered.
- `prestige_politics` — houses read prestige:
  - the leader is a poorer ally and, for the top eight, a richer target;
  - a house that lost a contest in the last 10 turns, or has cohesion below 40, draws claims;
  - a protector is sought above, the gap adding utility.
- `cohesion_strain` — each turn −1 cohesion per holding beyond `upkeep.json` `strain` (3 + 2 × rank index), and −1 while the holder is over 70. Recovery comes only from upkeep. Under it, each holding past that reach makes another riding worth `utility.overreach` less to the house, and a house at or past it values Win elevation by `utility.elevation_at_reach` more (Phase D1).

Phase D1 (§4.10, §5, §5.1) adds three more, false in 0.7–0.9 and on in 1.0, and its pacing terms ride on the flags above: `upkeep.json` `capital.holdings_per_cost` (one capital a turn for so many holdings), `schemes.json` `contest.loser_bar`, `utility.elevation_at_reach` and `utility.elevation_influence_min`.

- `distinct_surnames` — a Crown founding never draws a surname an active house bears (its name less any numeral) while its community's bank has an unused one. A director's chosen surname, and a cadet's, are kept.
- `world_calendar` — one turn is one year, from `game.json` (start year, turns, chapters). Season records carry `year`.
  - Every event of the world year fires for every house, in deck order; an event with a `through_year` repeats its direct effect each year to it, recorded once a year as a world event (`world: continues`). A §7c contraction sale lands in an event's first year only.
  - One climate ledger (`game.json` `climate_ledger`); the chapters are the era bands.
  - The atlas is read at the world year from `riding_jurisdictions.csv`, unchanged: a riding is in play while its sovereign is Canada, the Crown founds only on a riding in a province, and land outside Canada is not taken or claimed that year. Each accession (land coming under Canada) or extension (land becoming a province) is a world event naming its ridings.
  - After the last turn the engine writes the reckoning (`world: reckoning`, and the season record's `reckoning`): the final standings and, for every house ever of the top eight, its ridings, rank, peak prestige and year, contests won and lost and successions, from `house_stats`' `peak_prestige`, `peak_season`, `top_eight` and `successions`. A run refuses the turn after the last.
  - Personal clocks still advance, reset and sync, as reign years; nothing reads them.
- `crises` — under `world_calendar`, a Major event is a crisis. Every house takes a side by the response roll (tag modifier and the steadfast trait); Lead and Resist are the camps, Exploit takes its capital and Neutral stands aside. The camp with more total influence carries it: the climate moves its way, its members gain `game.json` `crises.win_influence` and the other camp's lose `lose_influence`. Land neighbours in the same camp move `friction_same` on their border, in opposed camps `friction_opposed`, and a compact with a house that stood in the same camp within `goodwill_turns` is worth `goodwill` more. One societal event records both camps and the outcome; the crisis's direct effect lands on each house in its turn.
  - A house's side is its d6 + tag modifier read against `game.json` `crises.response`, not the event response roll (Phase D1 follow-up): Lead at or above `lead_from`, Resist at or below `resist_to`, Exploit at or above `exploit_from`, otherwise Neutral, which a steadfast holder turns to Resist. Lead and Resist are symmetric before the modifier and the trait. A version without `response` takes the event response roll's thresholds (Lead only on a 6).

Phase V2 (docs/STORY_DESIGN.md §3.6) adds one more, false in 0.7–0.9 and on in 1.0. It records and decides nothing:

- `round_record` — every engine event's mechanical delta carries `part`, the part of the round it was recorded in: `"world"` before the house turns, the house's key during its turn, `"close"` from the founding roll on (turn 1, the first founding alone, is `"close"`). Every season record carries `order`, the houses whose turns the season played, in the order fixed when the house turns began, a house removed before its turn included. With the flag on, every draw and every outcome is what it is with it off (`tests/test_round_record.py`); docs/DETERMINISM.md, "The round record", says where each field is set.

`traits.csv` and `upkeep.json` are new in 1.0, and so are `schemes.csv`, `schemes.json` and `game.json`. `founding.json` gains `founding_curve`, `succession.json` gains `watch`, `upkeep.json` gains `strain`, and `events.csv` gains `through_year`. Every loader reads a version without them as having none.

## The tables

Machine-readable transcription of `docs/ENGINE_DESIGN.md`'s numeric tables, loaded by `hoc/rules_data.py` and by `web/engine/rules.js`. Where the design gives a formula instead of a number, it is stored as a string in a `formula` field (or as prose in a JSON value) and implemented in the engines, not evaluated here. Every table below lives in a version directory.

- **actions.csv** — one row per action from §7 (17 rows, including the five enclosure-era additions: Purchase riding, Marriage alliance, Absorb, Cede / swap, Partition). Columns: `action` (name, exactly as headed in the design table); `preconditions`; `base_weight` (a number, or the literal string `forced` for Partition, which is never drawn from the weighted pool); `modifiers` (free text — bonuses and penalties, some numeric, some formulas); `target` (an integer 2–12 to roll 2d6 against, or `auto` for actions that always resolve without a roll); `success` / `failure` (free text describing the effect); `enclosure_bonus` (the extra modifier §7b grants when the house is enclosed, where the design states a number — blank where §7b names the action but never gives one; see CHANGELOG).
- **objectives.csv** — one row per objective from §5 (7 rows). Columns: `objective`; `favoured_by`; `satisfied_when`; `action_weight_bonus` (semicolon-separated action names, taken only from explicit "+N &lt;Objective&gt;" mentions in §7's modifiers column — an objective with no such mention anywhere in §7, like Defend the seat, is left blank rather than guessed).
- **mortality.csv** — one row per age band from §9. Columns: `age_min`, `age_max` (inclusive; the top band's `age_max` is a sentinel 150 standing in for "no realistic upper bound"), `annual_probability`, `note` (the flu/war extra-roll rule, repeated on every row since it applies regardless of age band).
- **founding.json** — `p_found` (the §10 formula, the only founding probability as of 0.3), `region_weights` (§10 starting weights, keyed by lowercase region id, and the drift rule), `tag_climate_fit`, `rank_probabilities`, `rank_index` (the ladder position each rank name maps to), `seat_riding_rule`, `cultural_community`, `cadet_foundings`, and `initial_stats` (the §4 founding-stat formulas).
- **succession.json** — `clean_succession`, `partition`, `disorderly_succession`, `extinction`, `heirs` (all §9); `losing_ridings` (§7c: contraction sale, debt, disorderly succession's riding-loss roll, cession, escheat); `enclosure` (§7b: definition, effects, and what happens once the map is full).
- **eras.json** — the three era bands and their personal-year ranges (§3), each with a lowercase `id` (the key used in data and code) and a display `name`, and `end_year: null` on the open-ended final band.
- **responses.json** — the four event-response options (Lead / Resist / Exploit / Neutral) and their effects, and the response-roll tag modifier chosen in version 0.1 (§8).
- **events.csv** — the event deck (§8), one row per event from 1867 to 1960 (to 1966 in 1.0). Columns: `personal_year`; `band` (the era band id from `eras.json` — `confederation`, `dominion`, `late`; a house's actual era context is still decided by its own personal clock against `eras.json`'s year ranges, since two houses in the same season are rarely in the same band); `name`; `magnitude` (Minor / Significant / Major); `tag` (Progressive / Conservative / Mixed / Global — Global marking an event with no partisan lean, distinct from `Outside`, which is a scope value below, not an event tag); `direct_effect` (see "Event effect scopes" below); `note`; and in 1.0 `through_year`, the last world year an event's direct effect repeats in under `world_calendar` (blank for a one-year event).
- **communities.csv** — the cultural-community table (§10), one row per community. Columns: `region` (`maritime, quebec, ontario, prairie, bc, north` — the same lowercase ids as `founding.json`'s `region_weights.initial` keys; six of the seven regions used for event scopes, since `newfoundland` is not a community region: before 1949 its communities are recorded under `maritime`, and after 1949 the event deck targets it directly by scope); `community`; `weight` (the founding draw weight within its region); `naming_tradition` (a key into `given_names.csv`); `note`.
- **places.csv** — territorial-designation place names (§10 seat-riding flavour), one row per place. Columns: `province` (2-letter code, matching the codes in `data/reference/ridings.csv`); `place`.
- **given_names.csv** — given names by naming tradition and gender. Columns: `tradition` (matches a `communities.naming_tradition` value); `gender` (`m` or `f`); `name`.
- **surnames.csv** — surnames by community. Columns: `community` (matches a `communities.community` value); `surname`.
- **traits.csv** (1.0) — one row per holder trait. Columns: `trait`; `actions` (`Action:+2;Action:-2`, weight shifts in units of WEIGHT_SCALE); `upkeep` (`influence:+1`); `excludes` (traits it never occurs with, named both ways); `effect` (`steadfast`, `friction:+1`); `note`.
- **upkeep.json** (1.0) — the automatic upkeep's integers, the automatic letter's chance (`upkeep_phase`), and `strain` (`cohesion_strain`).
- **schemes.csv** (1.0, Phase C2) — one row per scheme, in the order utility ties are broken. Columns:
  - `scheme`;
  - `answer`: `no` for a scheme a house chooses, `only` for an answer to a claim, `also` for both;
  - `target`: `house`, `riding`, `both` or `none`;
  - `steps_min`, `steps_max`;
  - `step_capital`, `step_influence`: what each step commits;
  - `resolves_as`: an action handler, or one of the primitives `contest`, `frontier`, `fortify`, `sue`;
  - `reads`: the actions whose trait and objective shifts the utility takes;
  - `utility`: the base;
  - `begins`, `abandons`: the chronicle's templates, naming only `{house}`, `{target}` and `{riding}`;
  - `note`.
- **schemes.json** (1.0, Phase C2) — `choice` (top, abandon_below, abandon_refund_pct, answer_stand), `utility` (every term of the integer utility), `peace` (wait, indemnity_capital), `contest` (§4.4's numbers and the ally test), `frontier` (double_on), and, from the Phase D1 follow-up, `elevation`: the highest rank a Win elevation scheme reaches (`highest`), the holdings it needs (`holdings_from` + `holdings_per_rank` × rank index), and one point on its roll per `bonus_per_holdings` holdings beyond that. A version without `elevation` petitions up to Marquis on three holdings with no bonus, as before.
- **game.json** (1.0, Phase D1) — `world_calendar`'s `start_year`, `turns`, `climate_ledger` and `chapters` (`id`, `name`, `numeral`, `start_year`, `end_year`, contiguous over the game), and `crises`' terms.
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
