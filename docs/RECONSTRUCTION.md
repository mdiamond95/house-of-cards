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
