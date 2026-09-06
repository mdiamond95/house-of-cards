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

## Autoplay

The v2 engine plays the game itself: houses hold stats and objectives, draw actions from the weighted tables in `rules/`, respond to a deck of real Canadian events on their own personal clocks, and age, die, succeed and fail without a director writing turns.

    python -m hoc scenario use new         # switch off the frozen reconstruction
    python -m hoc sim new --seed 42        # season 1: exactly one house is founded
    python -m hoc sim run 50               # play fifty seasons
    python -m hoc sim run 50 --stop-on removal,major
    python -m hoc sim status

Houses correspond, form compacts, marry, quarrel, buy and challenge for ridings, absorb failing neighbours and split into cadet lines when a large house's holder dies leaving two heirs. Every draw comes from a seed derived from the world seed and the season number alone, and each season writes `scenarios/new/seasons/NNNN.json` recording every roll with the purpose it was drawn for — so a world replays identically from its seed, and any outcome can be traced to the roll that caused it. Tuning the game means editing a table in `rules/` and recording it in `rules/CHANGELOG.md`; it never means editing `hoc/sim.py`.

`python -m hoc scenario use legacy` switches back to the reconstructed playthrough, which the turn runner still drives.

See `CLAUDE.md` for game rules and working conventions, `scenarios/legacy/RECONSTRUCTION.md` for what is reconstructed and what is still missing, and `docs/BUILD_PLAN.md` for the migration phases.
