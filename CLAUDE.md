# House of Cards — working rules for Claude Code sessions

Read this fully before doing anything. Sessions in this repo do not share memory with the design conversations that produced these rules, so this file is the handoff.

## What the game is
- Alternate 1867 Canadian Confederation. Fictional noble houses hold peerages over real federal ridings (343 ridings, 2023 Representation Order).
- The game director issues one-line directives. Claude writes narrative and executes the mechanics.
- At migration baseline: 33 active houses, 2 historically removed houses, roughly 145 ridings claimed. Societal climate most recently at −1 Significant Conservative (following the Regulation 17 / Ontario Bilingual Schools Crisis event). Narrative era roughly 1867–1918 on house personal clocks.

## Source of truth
- The original workbook no longer exists. See `scenarios/legacy/RECONSTRUCTION.md`.
- `hoc.db` is canonical (Phase 3 complete). Everything in `outputs/` is regenerated from it.
- `hoc.db` is a derived artefact: `python scripts/rebuild.py` reconstructs it from scratch out of the active scenario's `seed/*.csv` plus `data/reference/*.csv` and then replays that scenario's record (`turns/` for the reconstructed game, `seasons/` for an engine-played one). The seed CSVs and the turn/season files are the reproducible record; the database is what they produce. The seed CSVs remain the audited input and the record of provenance — do not edit their values; add reconstructed data only in the manner described in scenarios/legacy/RECONSTRUCTION.md, then rebuild.
- Which game the database holds is `scenarios/current.txt`: `legacy` is the reconstructed playthrough (frozen), `new` is the live autoplay game. Switch with `python -m hoc scenario use <name>`, then rebuild. Everything below about turns applies to the legacy scenario.
- Game state produced by turns lives in the turn files and, once applied, in `hoc.db` (events, turns, narrative). The seed is never regenerated from the database.

## Hard rules (these have all been broken before and corrected by hand)
1. Never fabricate. No house attributes, riding names, relationships, dates or colours that are not in the data. If something is missing, record it as missing (e.g. TBD) and flag it in your final status.
2. Riding names must match the 2023 Representation Order exactly. Names change over time (e.g. West Nova no longer exists; the current riding is Acadie—Annapolis). Validate against the `ridings` table once it exists; before that, flag anything you cannot verify.
3. Expansions require land adjacency to an existing holding. Water-only adjacency is a fallback that must be flagged, never silently accepted. Non-adjacent proposals are rejected before any narrative is written.
4. Primary colour of a house is the colour of its principal seat, which is the first of its ridings in canonical row order. Do not use count-based or rarity rules; they break on ties.
5. No universal calendar. Each house has its own personal clock starting at 1867. Clocks sync only on direct shared events between named houses. Global events never sync clocks. On succession the new holder's clock resets to personal 1867; biological ages are not reset.
6. Founding grants must be evaluated for cohort fit against the current climate state before execution. This is mandatory, not advisory.
7. Rank ladder and remaining mechanics are defined in Mechanics Sections 1–3 of the baseline workbook. Extract them in Phase 1; do not guess them.
8. The game runs more than one era-cohort of Section 10 events in parallel (see scenarios/legacy/RECONSTRUCTION.md). Never collapse the climate ledgers into one number; always state which era-cohort a climate value belongs to.
9. A turn narrative may use house detail only if it is in hoc.db (house_blocks, holders, holdings, relations, events). Detail supplied in a directive that is not yet in the database must be added to scenarios/legacy/seed/house_blocks.csv in a reconstruction commit in the same PR before the turn is applied.

## Autoplay

The live game is the **new** scenario, played by the engine. `scenarios/current.txt` says so and `hoc.db` holds it.

- **Only the engine workflow or a Code session may commit game state.** `hoc.db`, `scenarios/`, `rules/` and `outputs/` change through `.github/workflows/engine.yml` (dispatched from the site's console, or by hand) or through a session working to these rules. Nothing else writes to them, and nothing writes to them directly from a browser.
- The workflow takes four commands: `run` (play seasons, halting on any armed stop condition), `intervene` (apply a director's turn file between seasons), `rules` (patch numeric fields, bump the version, append a CHANGELOG entry) and `rebuild` (replay the record and verify it reproduces `hoc.db`). It runs the suite with `-m "not smoke"` and exports before it commits, so a failing run commits nothing. The 300-season smoke run stays here, in Code sessions.
- No model is called by any workflow. The console's Narrate control produces a block of instructions for a person to paste into a Claude Code session; that is the whole of Claude's part in the running game. A narrative written that way lands in `narratives/NNNN-NNNN.md` and may use house detail only from `hoc.db` (hard rule 9).
- Seasons are run only through `python -m hoc sim run N`. Never advance the game by editing the database, and never hand-write a season file — `scenarios/new/seasons/NNNN.json` is written by the engine as its audit trail, and `scripts/rebuild.py` replays the game from the world seed to check it.
- `python -m hoc sim status` says where the game stands. `python -m hoc sim run N --stop-on removal,challenge,major,marquis` stops early on anything worth the director's attention.
- Hand-written turn files remain available for director interventions — a grant, a correction, a scripted event. Apply one **between** seasons with `python -m hoc apply <turnfile>`, never in the middle of a run, and commit it with the database as any turn is. An intervention on the live game is named `NNNN_sSSSS-<slug>.json`, where SSSS is the season it follows: `scripts/rebuild.py` reads that to replay it back into the right place between two seasons.
- The intervention operations are `set_objective`, `veto_objective`, `force_action`, `adjust_stat` (which will not apply without a reason), `grant_house`, `set_clock` and `relation`. Expansion, succession, elevation and the climate ledger are the engine's own business — a director who wants those runs seasons.
- Tuning the game means editing a table in `rules/` and recording it in `rules/CHANGELOG.md` with the metric that motivated it. It never means editing `hoc/sim.py`.
- Never edit `hoc.db` by hand. It is derived: the seed CSVs plus the season logs (and any turn files) are the record, and the database is what they produce.
- The reconstructed 2026 playthrough is frozen in the **legacy** scenario and published at `outputs/site/archive/`, rebuilt on every export. `python -m hoc scenario use legacy` switches back to it; the turn procedure below is about that game.

## Conventions
- Canadian English spelling throughout (colour, honour, centre, defence).
- Narrative for a turn is about 500 words, rich prose, not bullet lists; the runner warns above 550 words and refuses above 600.
- Mechanics Section 5 house-block updates are short-form appends: Holdings always; Economic when operation type changes; Political when named political figures attend or relational events occur; Cultural only for genuinely new nodes. Transaction log entries stay detailed.
- Section 13 watch items: zero or one per turn, only for genuinely unresolved structural questions.

## openpyxl pitfalls (relevant to extract.py and the workbook exporter)
- `insert_rows()` does not update merged cell ranges. Unmerge every range at script start, re-merge at the end.
- After any row insert, previously cached row numbers are invalid; re-find rows by content search.
- Section header searches must confirm the character after the section-number prefix is uppercase, to avoid matching list items.
- Section 5 house blocks are 9 rows (house name row plus 8 labelled rows), starting around row 36; match on the surname before the " — " delimiter in column A. Some column B cells are intentionally None; guard with `current or ""`.
- The house matrix (Section 9) data rows are tightly bounded to actual house rows; do not let loops capture annotation text beneath the matrix.
- The adjacency register (Section 10) is single-column, label-only.

## Repository layout
- `hoc/` — package: schema.sql, db.py, names.py, rules.py, turnfile.py, turn.py, `__main__.py` (CLI), export/
- `scripts/` — build scripts: build_ridings.py, build_adjacency.py, build_geometry.py, load_seed.py, rebuild.py
- `scenarios/` — one directory per game: `legacy/` (the reconstructed playthrough: `seed/`, `turns/NNNN_<slug>.json`, `RECONSTRUCTION.md`) and `new/` (the autoplay game: `seed/` headers only, `seasons/NNNN.json`); `current.txt` names the active one
- `tests/` — pytest; fixtures drawn from real logged cases
- `scenarios/legacy/seed/` — reconstructed canonical data (see scenarios/legacy/RECONSTRUCTION.md); values change only via reconstruction commits
- `data/reference/` — ridings, adjacency, simplified geometry; `raw/` holds Elections Canada source files
- `data/extract/` — JSON produced by extract.py
- `outputs/` — generated workbook, map.svg, and `dump/` CSV+JSON; regenerated every turn
- `docs/` — build plan and design notes

## Working pattern
- One build step or one game turn per session. Work on a branch, commit with a clear message, push, open a PR.
- Make one commit per logical change; keep the diff reviewable on a phone.
- Never modify values in `scenarios/legacy/seed/` except through a reconstruction commit as defined in scenarios/legacy/RECONSTRUCTION.md.
- Do not add dependencies beyond openpyxl, shapely and pytest without noting it in the status block.

## Turn procedure
This is the legacy scenario's procedure, and the procedure for a director intervention in the live game. Run a game turn in exactly these steps. The format of a turn file is in docs/TURN_FILE.md.

1. **Read the state first.** Run `python -m hoc status`, then read `outputs/dump/state.json` for the houses the directive touches — holder, generation, clock, holdings, colours. Write nothing until you have.
2. **Check any expansion before writing it.** Run `python -m hoc check <house> <riding>`. If it fails, pick another riding that the data supports, or stop and report the problem to the director. Never write narrative for a move that has not passed the check. Water-only adjacency passes with a warning — surface that warning in your status block, never bury it.
3. **Write `scenarios/legacy/turns/NNNN_<slug>.json`.** Operations first, then the narrative. The narrative is Canadian spelling, about 500 words, rich prose rather than bullet lists, anchored only in what the data records — no invented settlers, dates, relations or colours. Dates are personal years on the house's own clock; there is no universal calendar, so never write a shared year for houses that did not meet.
4. **Apply it.** `python -m hoc apply scenarios/legacy/turns/NNNN_<slug>.json`. This validates, applies and re-exports in one transaction. If it fails, fix the turn file and run it again. Never edit `hoc.db` by hand, and never hand-edit anything in `outputs/`.
5. **Commit `hoc.db`, the turn file and `outputs/` together**, so the database and its generated views never disagree. Push, open a PR.
6. **Give the director the narrative in full in the message, then close with the STATUS block.** The narrative goes in the body so it can be read in chat without opening the repo; the STATUS block stays last, as the section below requires.

## Required end-of-session status block
The director works from a phone and copies your final message back into a planning conversation. Always end your final message with exactly this block, plainly formatted, nothing after it:

STATUS
Branch: <name>
PR: <url or "not opened: reason">
Files created/changed: <comma-separated list>
Tests: <passed/failed/none>
Flags: <anything that could not be verified, was missing, or needs a decision; or "none">
Next: <the single next step you recommend>
