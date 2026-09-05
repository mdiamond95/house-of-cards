# Reconstruction record

The original workbook (`Riding_Tracker_v4.xlsx` / `v5.xlsx`) was lost after the 4 May 2026 session. The game state was reconstructed on 5 September 2026 from conversation transcripts. This file records provenance and known gaps so that nothing reconstructed is mistaken for something verified.

## What `data/seed/` contains and where it came from

- `holdings.csv` — 143 ridings across 33 active houses. Source: the director's canonical riding list, which was pasted verbatim into the reconciliation script on 4 May 2026 and confirmed by the director as accurate for owners and colours. Row order within each house is the director's original order; `seat_order` 1 is the principal seat and carries the primary colour. Three riding names were normalised from hyphens to em dashes to match the 2023 Representation Order: Toronto—Danforth, Columbia—Kootenay—Southern Rockies, Similkameen—South Okanagan—West Kootenay.
- `houses.csv` — derived from holdings.csv plus two removed houses (Tupper-Blair, Kilmartin) and one preserved secondary (Wilson, #B07AB0, from the old Mechanics Section 4).

## Not yet recovered

- Per-riding settler name, generation and notes (the workbook's other columns).
- Section 5 house blocks: current holder, heir apparent, economic/political/cultural positions, personal clocks.
- The relational matrix (Section 9), societal events and climate history (Section 10), event and transaction logs, watch list, narrative threads.
- Secondary colours for eight single-riding houses (blank `secondary_hex` in houses.csv). The director has confirmed these exist but they were never recorded in any file.
- The rank ladder and the remaining written mechanics from Sections 1–3.

Known state at the point of loss: climate score −1 Significant Conservative (after Regulation 17 / Ontario Bilingual Schools Crisis); narrative era roughly 1867–1918 on personal clocks; Sinclair-McKay elevated to Countess; Vernon—Lake Country—Monashee had placeholder settler/notes; Sinclair-McKay's elevation had no Structural Firsts entry yet.

## Rule for reconstructed data

Anything added to the seed from transcripts after this date goes in its own commit with the source session named in the commit message and a line added to this file. Anything the director supplies directly is marked as director-supplied. Nothing is inferred to fill a gap.

## Addendum — 5 September 2026, second pass (Tier A structural state)

New files in `data/seed/`:
- `houses_state.csv` — current holder, generation, accession, heir, per house, with a `source` and `confidence` column. Sources are session dates: 2026-04-25 handoff refresh (25 houses), 2026-04-27 thirteen-house succession cascade (holders named, aged and dated), 2026-05-04 founding blocks (Anand, Calabrese, Trondek, Boyer-Lavallée). `confidence: none` rows are not recovered; do not fill them.
- `successions.csv` — the 22 successions logged as of 2026-04-27, in the order the metrics line gave them.
- `climate_ledger.csv` — two ledgers. The game ran two era-cohorts of Section 10 events in parallel: a later era (WWI → Internment) and a founding era (Confederation Extension → Komagata Maru). Cumulative values are recorded exactly as stated in the sources; the per-event delta rule (Section 10 calculator) was not recovered and must not be inferred from these numbers. One later-era event between CCF Founding and Internment is unidentified. The state at loss was the founding-era ledger at −1 Significant Conservative.
- `relations_seed.csv` — only ties explicitly stated in recovered text. This is a fragment of the matrix, not the matrix. Marker vocabulary as used in the workbook: `◎` first formal contact, `◉` commercial tie, `◉+` strong positive / compact, `+` positive, `Sig+`/`Sig−` significant relational events, `⊖` Major negative, `⚔` challenge origin, `~−◉` resolved negative, `·` none.

Known conflicts (recorded, not resolved):
- Whitcombe founder: metrics 2026-04-27 says Cedric → Edwin; a 2026-05-04 founding-era letter names the founder Edward Joshua with Edwin as heir-apparent.
- Tupper-Blair founder: handoff 2026-04-25 says Gordon → Charles Gordon; a 2026-05-04 founding-era letter names Sir Charles with Hartley as heir-apparent.
- Generation tally: 2026-04-27 records 20 of 25 houses at G2; a 2026-05-04 metrics line at 28 houses records 21 G1, 6 G2, 1 G3. The later line appears to have been written from a founding-era perspective. `houses_state.csv` follows the 2026-04-27 cascade because it is the detailed, self-consistent source.
- Rank changes after 2026-04-27 (Richard-Arseneau to Marquis, Fitzroy-Crane to Marchioness, Sinclair-McKay to Countess, Macleod / Stanton-Greville / Garland / MacDonald / Delany to Viscount) are reflected in `houses.csv` from the canonical list; the elevation events themselves are not recovered.

Design consequence for Phase 3: the `events` table needs an `era_cohort` column, and climate must be stored per era-cohort, not as a single scalar. Personal-clock placement of an event is per house and may be blank.

Recovery queue (holder names still missing): Polkinghorne, Ashworth, Akatsiak, Hryhoryshyn, Klassen-Reimer, FitzWilliam-Macklem, Cardinal; confirm Wilson. Secondary colours for eight single-riding houses remain director-supplied only.
