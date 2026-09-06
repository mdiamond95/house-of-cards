# Turn file format

A turn is one JSON file at `turns/NNNN_<slug>.json`. It holds everything a turn
needs: the director's directive, the event it produces, the narrative, and the
mechanical operations. Applying it is atomic — either the whole turn lands or
none of it does.

    python -m hoc apply turns/0001_whitcombe-nipigon.json

The four-digit prefix is the turn id, so it must be unique and ordered. The slug
is lowercase letters, digits and hyphens.

## Shape

```json
{
  "directive": "<the director's one-line directive, verbatim>",
  "era_cohort": "founding-era",
  "event": {
    "kind": "expansion",
    "title": "The Nipigon Concession",
    "houses": ["Whitcombe"],
    "narrative": "<prose, target 500 words>"
  },
  "operations": [
    {"op": "expand", "house": "Whitcombe", "riding": "Thunder Bay—Superior North"}
  ],
  "watch": {"add": ["Does the Nipigon lease bind the successor?"], "discharge": [3]},
  "threads": ["Whitcombe timber financing"]
}
```

- `directive` — required, the director's words, unedited.
- `era_cohort` — `"founding-era"`, `"later-era"` or `null`. Required if the turn
  contains a `found_house` operation, because founding grants are evaluated for
  cohort fit against that cohort's climate. The two ledgers run in parallel and
  are never collapsed into one number (hard rule 8).
- `event` — required. `kind` must be one of the schema's kinds: founding,
  expansion, relational, incursion, challenge, succession, societal, elevation,
  transfer, other. `houses` lists the houses taking part; every one must already
  exist. `narrative` targets about 500 words; over 550 warns, over 600 is rejected.
- `operations` — applied in order, each mapping to one `hoc/rules.py` call. A turn must have at least one, unless it is a housekeeping turn recorded as `"kind": "other"`, which may have none.
- `watch` — `add` appends open watch items; `discharge` closes existing ones by
  id. Zero or one new item per turn, only for genuinely unresolved structural
  questions.
- `threads` — narrative threads to record.

A house created by `found_house` must **not** appear in `event.houses`: it does
not exist when the event is recorded. `found_house` links it to the event itself
with the role `founder`.

## Operations

| op | fields | notes |
|---|---|---|
| `expand` | `house`, `riding` | Rejected unless the riding is unheld and adjacent to a current holding. Water-only adjacency passes with a warning, never silently (hard rule 3). Takes the house's secondary colour. |
| `transfer` | `from_house`, `to_house`, `riding` | Not adjacency-bound. Releases from one house, appends to the other. |
| `release` | `house`, `riding` | Keeps the row as history with `released_event_id` set. |
| `succeed` | `house`, `successor_name`, `bio_age_at_accession`, `personal_date`, `nature`; optional `heir_apparent` | Generation increments, clock resets to personal 1867, a `successions` row is appended. Biological ages are recorded, never recomputed. |
| `elevate` | `house`, `new_rank` | Up the ladder only (Baron/Baroness < Viscount/Viscountess < Earl/Countess < Marquis/Marchioness < Duke/Duchess). Multi-step allowed. Colours do not change. |
| `set_clock` | `house`, `personal_year`, `basis` | The director setting a clock outright. |
| `advance_clock` | `house`, `years` | Fails if that house has no recorded personal year — set it first. |
| `sync_clocks` | `personal_year` | Syncs every house on this turn's event. Only relational, challenge, incursion and transfer events sync; global events never do (hard rule 5). The year is supplied here because the sync semantics were never recovered. |
| `climate_shift` | `era_cohort`, `event`, `magnitude`, `tag`, `delta` | `delta` is explicit: the Section 10 calculator was not recovered and is not inferred from magnitude or tag. |
| `relation` | `house_a`, `house_b`, `marker`, `text` | Appends to the relational matrix, tied to this turn's event. |
| `found_house` | `house`, `peerage`, `rank`, `riding`, `primary_hex`, `holder_name`, `bio_age`, `tag`; optional `secondary_hex`, `heir_apparent`, `acknowledge_cohort_mismatch` | Creates the house, its principal seat (seat_order 1, primary colour), a G1 current holder and a clock at personal 1867 with basis "founding grant". |

`magnitude` is one of Minor, Significant, Major. `tag` is one of Progressive,
Conservative, Mixed, Outside, Global, regressive. Colours are `#RRGGBB`.

### Cohort fit on a founding grant

`found_house` calls `cohort_fit` against the turn's `era_cohort` before writing
anything (hard rule 6). A `mismatch` blocks the turn unless
`"acknowledge_cohort_mismatch": true` is set, in which case the grant proceeds
and the acknowledgement — house, tag, cohort and the climate at the time — is
recorded in the event's `mechanical_delta`, so the override is visible later.

## Validation and failure

Validation runs before anything is written and reports every problem it finds,
not just the first: unknown ops, unknown fields, missing required fields,
unknown houses, unknown ridings, unknown ranks, bad magnitudes or tags, and an
over-length narrative.

If an operation fails while the turn is being applied, everything the turn wrote
is rolled back — including the `turns` row and the event — and the error names
the index of the operation that failed. Fix the turn file and run it again;
never edit `hoc.db` by hand.
