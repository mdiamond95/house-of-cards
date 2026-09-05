# House of Cards — working rules for Claude Code sessions

Read this fully before doing anything. Sessions in this repo do not share memory with the design conversations that produced these rules, so this file is the handoff.

## What the game is
- Alternate 1867 Canadian Confederation. Fictional noble houses hold peerages over real federal ridings (343 ridings, 2023 Representation Order).
- The game director (Mark, Edmonton AB) issues one-line directives. Claude writes narrative and executes the mechanics.
- At migration baseline: 33 active houses, 2 historically removed houses, roughly 145 ridings claimed. Societal climate most recently at −1 Significant Conservative (following the Regulation 17 / Ontario Bilingual Schools Crisis event). Narrative era roughly 1867–1918 on house personal clocks.

## Source of truth
- Until Phase 3 is complete: `data/baseline/Riding_Tracker_v4.xlsx` (sheets: Riding Tracker, Mechanics). The Riding Tracker rows are canonical for house colours and riding data. Mechanics Section 4 (colour registry) is derived and known to drift; reconcile from the Riding Tracker, never the other way round.
- After Phase 3: `hoc.db`. Everything in `outputs/` is regenerated from it.

## Hard rules (these have all been broken before and corrected by hand)
1. Never fabricate. No house attributes, riding names, relationships, dates or colours that are not in the data. If something is missing, record it as missing (e.g. TBD) and flag it in your final status.
2. Riding names must match the 2023 Representation Order exactly. Names change over time (e.g. West Nova no longer exists; the current riding is Acadie—Annapolis). Validate against the `ridings` table once it exists; before that, flag anything you cannot verify.
3. Expansions require land adjacency to an existing holding. Water-only adjacency is a fallback that must be flagged, never silently accepted. Non-adjacent proposals are rejected before any narrative is written.
4. Primary colour of a house is the colour of its principal seat, which is the first of its ridings in canonical row order. Do not use count-based or rarity rules; they break on ties.
5. No universal calendar. Each house has its own personal clock starting at 1867. Clocks sync only on direct shared events between named houses. Global events never sync clocks. On succession the new holder's clock resets to personal 1867; biological ages are not reset.
6. Founding grants must be evaluated for cohort fit against the current climate state before execution. This is mandatory, not advisory.
7. Rank ladder and remaining mechanics are defined in Mechanics Sections 1–3 of the baseline workbook. Extract them in Phase 1; do not guess them.

## Conventions
- Canadian English spelling throughout (colour, honour, centre, defence).
- Narrative for a turn is capped at about 500 words, rich prose, not bullet lists.
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
- `hoc/` — package: schema.sql, db.py, rules.py, turn.py, export/
- `scripts/` — one-off migration scripts (extract.py, load.py)
- `tests/` — pytest; fixtures drawn from real logged cases
- `data/baseline/` — frozen migration baseline workbook (do not modify)
- `data/reference/` — ridings, adjacency, simplified geometry; `raw/` holds Elections Canada source files
- `data/extract/` — JSON produced by extract.py
- `outputs/` — generated workbook, map.svg, and `dump/` CSV+JSON; regenerated every turn
- `docs/` — build plan and design notes

## Working pattern
- One build step or one game turn per session. Work on a branch, commit with a clear message, push, open a PR.
- Make one commit per logical change; keep the diff reviewable on a phone.
- Never modify `data/baseline/`.
- Do not add dependencies beyond openpyxl, shapely and pytest without noting it in the status block.

## Required end-of-session status block
The director works from a phone and copies your final message back into a planning conversation. Always end your final message with exactly this block, plainly formatted, nothing after it:

STATUS
Branch: <name>
PR: <url or "not opened: reason">
Files created/changed: <comma-separated list>
Tests: <passed/failed/none>
Flags: <anything that could not be verified, was missing, or needs a decision; or "none">
Next: <the single next step you recommend>
