# House of Cards

Collaborative alternate-history worldbuilding game set in an alternate 1867 Canadian Confederation. Fictional noble houses hold peerages mapped onto the 343 real federal electoral districts of the 2023 Representation Order.

Source of truth: `hoc.db` (SQLite). The Excel workbook, CSV/JSON dumps and riding map in `outputs/` are generated views, never edited by hand.

Run a turn (after Phase 5 of the build plan):

    python -m hoc turn "directive text"

Run tests:

    python -m pytest

## Viewing the game

The generated site lives in `outputs/site/` and is published to GitHub Pages on every push to `main` by `.github/workflows/pages.yml`:

**https://mdiamond95.github.io/house-of-cards/**

The site has to be switched on once: **Settings → Pages → Build and deployment → Source: GitHub Actions**. Until that is done the workflow will run but the URL will 404. In the meantime `outputs/map.svg` renders directly in GitHub's file view, and `outputs/dump/state.json` is readable as text.

The site is built by `python -m hoc export` along with everything else in `outputs/`, so it is committed with each turn and the workflow only uploads it — deployment never rebuilds the database.

Pages: map with tappable ridings, a page per house (holder, holdings, house block, successions, relations, events), all 343 ridings by province, both climate ledgers, the chronicle of turns, and an about page listing what remains unrecovered.

## Rebuilding the database

    python scripts/rebuild.py

`scripts/rebuild.py` is the reproducible path: it loads the active scenario's seed and then replays that scenario's record — every `turns/*.json` in turn order for the reconstructed game, every `seasons/NNNN.json` in season order for an engine-played one — so the database is reconstructed from files under version control. `hoc.db` is committed as a convenience — the seed CSVs plus the turn files are the record, and the database is what they produce.

To load the seed alone, without replaying any turns:

    python scripts/load_seed.py

`hoc.db` is a derived artefact. The loader deletes and rebuilds it from scratch out of `data/reference/*.csv` (343 ridings and their land adjacency, from the 2023 Representation Order boundaries) and the active scenario's `seed/*.csv` (for `legacy`, the reconstructed houses, holdings, holders, successions, climate ledgers and relations), then prints a row count per table. Run it after any reconstruction commit that changes the seed. The reference CSVs themselves are rebuilt from the raw boundary file by `scripts/build_ridings.py`, `scripts/build_adjacency.py` and `scripts/build_geometry.py` — see `data/reference/raw/SOURCE.md` for provenance.

## Two engines

The game has two implementations of the same engine: `hoc/sim.py` in Python, which plays the committed game and writes the record, and `web/engine/` in JavaScript, which will play it in the browser (Phase 10-2). They are required to produce **byte-identical season files** from the same seed.

That is only possible because nothing in the engine is left to a language's discretion. Every random value comes from one 32-bit generator — xoshiro128\*\*, seeded by splitmix32 from `fnv1a32("seed:season")` — every draw weight is an integer, every probability is an integer per cent, and the only floating-point computation in the game is §10's founding roll, written as a square root because IEEE-754 requires `sqrt` to be correctly rounded where it makes no such promise about `pow`. `docs/DETERMINISM.md` states all of it with worked examples, including the first ten generator values for seed 1867.

    python scripts/crosscheck.py --seed 1867 --seasons 120

runs both engines and diffs their season files byte for byte, ignoring only the field that names which engine wrote them. It prints the first differing season and a unified diff. It exits 2, not 0, when it cannot compare at all — a missing engine never reads as agreement.

`web/engine/` is plain ES modules: no build step, no bundler, no packages, loadable from the static site by `<script type="module">` alone.

Both engines are complete as of Phase 10-1b. `tests/test_crosscheck.py` runs seeds 1867, 2 and 3 for 120 seasons each and asserts zero differences; the same three seeds have been checked to 300 seasons. `tests/test_js_engine_parity.py` holds the primitives underneath to their Python counterparts value for value, so a divergence is named by the primitive that caused it rather than by the season it surfaced in. A 300-season game takes about 6 seconds under node.

## Playing the game

The game plays itself, and the director watches it from the site and pushes it along from the site's **Console**.

The engine holds houses with stats and objectives that draw actions from the weighted tables in `rules/`, respond to a deck of real Canadian events on their own personal clocks, quarrel across their borders, marry, buy and challenge for ridings, absorb failing neighbours, split into cadet lines, and age, die, succeed and fail without anyone writing a turn.

### From the console

The console is a page on the site. It holds no credentials of its own: the director pastes in a fine-grained GitHub token, it is kept in that browser's local storage and sent only to `api.github.com`, and a Disconnect button drops it. Open the console with no token and everything still renders — the controls are simply disabled and say why.

The token needs **Actions: read and write** and **Contents: read** on this repository — Actions read/write is what lets it dispatch `engine.yml` directly, and is what the console prefers. A token granted only **Contents: read and write** still works: the console retries a failed dispatch as a `repository_dispatch` instead, which needs Contents only.

Every control ends as a dispatch of `.github/workflows/engine.yml`, which does the work, runs the suite, exports the site and commits the result. That is the only automated path by which the game changes, and it is the one that checks itself.

- **Run seasons** — 1, 5, 10, 25 or 50, with pause conditions (a house removed, a challenge, a Major event, a house reaching Marquis, a partition, an extinction). The run halts at the first condition met and the summary says which one and which season.
- **Intervene** — set or veto an objective, force a house's next action, grant a house, adjust a stat with a reason, set a clock, record a relation. Each builds a turn file, shows it for review, and applies it between seasons.
- **Rules** — the numeric fields of the rules tables, with the last CHANGELOG note beside them. A proposed change shows its diff, needs a note, and lands as a version bump with an entry. The console cannot add, remove or rename a rule; that is a design decision and belongs in a Code session.
- **Narrate** — builds a block of instructions for a Claude Code session to write prose for a range of seasons from the season logs and the chronicle. The console calls nothing: the director copies the block and pastes it. What comes back lands in `narratives/` and shows up as expandable prose in the chronicle.
- **Rebuild** — replays the whole game from the seed and the season logs and checks it reproduces the committed database exactly.

### From a Code session

The same things, without the browser:

    python -m hoc sim status                      # where the game stands
    python -m hoc sim run 50 --stop-on removal,major
    python -m hoc apply scenarios/new/turns/NNNN_sSSSS-intervention.json
    python -m hoc narrate 40 60 --tone intimate   # the block, printed
    python scripts/rebuild.py                     # replay from the record

Every draw comes from a seed derived from the world seed and the season number alone, and each season writes `scenarios/new/seasons/NNNN.json` recording every roll with the purpose it was drawn for — so a world replays identically from its seed, and any outcome can be traced to the roll that caused it. Tuning the game means editing a table in `rules/` and recording it in `rules/CHANGELOG.md`; it never means editing `hoc/sim.py`.

`python -m hoc scenario use legacy` switches back to the reconstructed 2026 playthrough, which the turn runner still drives and which is published, frozen, at the site's Archive.

See `CLAUDE.md` for game rules and working conventions, `scenarios/legacy/RECONSTRUCTION.md` for what is reconstructed and what is still missing, and `docs/BUILD_PLAN.md` for the migration phases.
