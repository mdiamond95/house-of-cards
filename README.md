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

The game has two implementations of the same engine: `hoc/sim.py` in Python, which plays the committed game and writes the record, and `web/engine/` in JavaScript, which plays it in the browser. They are required to produce **byte-identical season files** from the same seed.

That is only possible because nothing in the engine is left to a language's discretion. Every random value comes from one 32-bit generator — xoshiro128\*\*, seeded by splitmix32 from `fnv1a32("seed:season")` — every draw weight is an integer, every probability is an integer per cent, and the only floating-point computation in the game is §10's founding roll, written as a square root because IEEE-754 requires `sqrt` to be correctly rounded where it makes no such promise about `pow`. `docs/DETERMINISM.md` states all of it with worked examples, including the first ten generator values for seed 1867.

    python scripts/crosscheck.py --seed 1867 --seasons 120

runs both engines and diffs their season files byte for byte, ignoring only the field that names which engine wrote them. It prints the first differing season and a unified diff. It exits 2, not 0, when it cannot compare at all — a missing engine never reads as agreement.

`web/engine/` is plain ES modules: no build step, no bundler, no packages, loadable from the static site by `<script type="module">` alone.

Both engines are complete as of Phase 10-1b. `tests/test_crosscheck.py` runs seeds 1867, 2 and 3 for 120 seasons each and asserts zero differences; the same three seeds have been checked to 300 seasons. `tests/test_js_engine_parity.py` holds the primitives underneath to their Python counterparts value for value, so a divergence is named by the primitive that caused it rather than by the season it surfaced in. A 300-season game takes about 6 seconds under node.

## Playing in the browser

**https://mdiamond95.github.io/house-of-cards/play.html**

The primary way to play. The page loads the JavaScript engine, the rules tables and the world as it stands in the repository, and then plays seasons **on the device** — no network round-trip per season, and no server. Play, Pause, 1/4/12 seasons a second, Step, Run 5/25/50/100 with the six stop conditions, a scrubber back through the seasons this browser has played, and Undo to any of them. The map recolours only the ridings that changed hands and flashes them; tapping one opens the house with its live stats and objectives; the chronicle appends as it goes and filters to a single house. The director's §12 interventions are there too, applied to the local game at once.

Play in the page stays in that browser until you save it. A banner counts the seasons played and not yet in the repository, and the page autosaves to IndexedDB so that closing a tab does not lose an afternoon, offering to resume or discard that local game next time.

The page and everything it fetches weigh about 630 KB (184 KB over the wire, gzipped), of which two thirds is the map's coastline — the same inline SVG the index page draws, built once and shared.

### Saving your game

**Save** commits the seasons this browser played, and only those: `scenarios/new/seasons/NNNN.json` exactly as the engine wrote them, plus `scenarios/new/interventions/NNNN.json` for any intervention taken during them. It does not write `hoc.db`, `outputs/` or the world snapshot — those belong to the referee, which writes them from its own replay.

It needs the same token the console uses, pasted once on the [Console](https://mdiamond95.github.io/house-of-cards/console.html) and kept in that browser's local storage. For saving, the token needs **Contents: read and write** (to commit the season files through the Git Data API) and **Actions: read** (to watch the referee run afterwards and report its verdict). Nothing else. The play page holds no credential of its own and sends the token only to `api.github.com`.

What happens then:

1. The page re-reads `main`'s head. If the repository has moved past the base this game was played from, the save is refused — the seasons in the browser no longer follow the record, and there is no safe merge. It offers **Reload** (resume from the repository) or **Discard local play**, and never a force-push.
2. One commit: blobs, a tree on the current one, a commit, an unforced fast-forward of `main`. The message is `Play: seasons A–B (browser engine)`, with an optional note, authored as the token's own user.
3. `.github/workflows/referee.yml` picks it up. It replays every newly committed season with the **Python** engine and compares what it produced with what was committed, byte for byte, ignoring only the field that names which engine wrote the file. On the first mismatch it stops, names the season and the first differing draw in the run summary, and commits nothing: `hoc.db`, `outputs/` and the published site keep the last verified state. On full agreement it runs the suite, exports, commits, and Pages deploys.
4. The page watches that run and shows its result. On success the banner clears and the local base moves to the new head; on a refusal the local game is untouched and the page links to the run.

So a browser can propose a game but cannot publish one. The public state is always the Python engine's own work — a bug in the JavaScript engine, a hand-edited season file or anything else that disagrees with `hoc/sim.py` is caught before it reaches the site.

The referee shares its concurrency group with the engine workflow, so the two never run at once, and only pushes by the director or the engine reach it at all.

Undo will not rewind past a season that has been saved. Rewriting saved history would need a force-push, and the referee would refuse the result; the page says so rather than trying.

    node web/engine/savecheck.js --seasons 5

builds the payload a save would send, headlessly and with the network mocked, and checks that every blob is the file the engine wrote. `tests/test_referee.py` runs the other half: seasons the JavaScript engine played are verified end to end, a season altered by one draw is rejected with that season named, and seasons the Python engine played are recognised as already applied.

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
