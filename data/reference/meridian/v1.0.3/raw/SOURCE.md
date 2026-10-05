# Source: Meridian v1.0.3, riding unit table

## What this is

The two files below, downloaded unmodified by `scripts/fetch_meridian.py` from the
Meridian repository (`mdiamond95/meridian`) at release tag `v1.0.3`, and the input to
`scripts/build_world_meridian.py`, which builds the `meridian-v1.0.3` reference-data
version in the directory above this one.

| File | URL | SHA-256 |
|---|---|---|
| `ridings.v1.json.gz` | https://raw.githubusercontent.com/mdiamond95/meridian/v1.0.3/data/build/ridings.v1.json.gz | `60f048f44c4952638ea941162a646cddadbf6fc11478b6838178dacd307e3eb7` |
| `ridings.v1.topojson.gz` | https://raw.githubusercontent.com/mdiamond95/meridian/v1.0.3/data/build/layers/ridings.v1.topojson.gz | `4e0be1c453e5f5cdcaa3216596b21b635ac9115b8c16b2b72958d4fc9beb8d15` |

Tag: `v1.0.3`. Both hashes are checked on every read and the files are refused on any
other; Meridian's versioning rule 7 makes a released file immutable, so a different
hash is a different file, not a newer copy of this one.

## What the table declares

- format `meridian.unitTable`, version `1`, unit `fed_2023` (checked; anything else is refused)
- 343 rows: Federal electoral districts, 2023 Representation Order
- census year 2021; GDP method `allocation_v1`, reference year 2022, `current_dollars_basic_prices`
- jurisdictions from the atlas `v1`, from 1867-07-01

**GDP is an allocation, not a measurement.** The table's own caveat, verbatim:

> GDP is an estimate: provincial GDP by industry shared over ridings by census labour force (allocation_v1), not a measurement of what a riding produces.

## Attribution and licences

As the table's `meta.sources` gives them:

- `elections_fed_2023`: Contains information licensed under the Open Government Licence – Canada. Open Government Licence – Canada, https://www.statcan.gc.ca/en/terms-conditions/open-licence
- `statcan_csd_2021`: Adapted from Statistics Canada, 2021 Census – Boundary files, 2022. This does not constitute an endorsement by Statistics Canada of this product. Statistics Canada Open Licence, https://www.statcan.gc.ca/en/terms-conditions/open-licence
- `statcan_da_2021`: Adapted from Statistics Canada, 2021 Census – Boundary files, 2022. This does not constitute an endorsement by Statistics Canada of this product. Statistics Canada Open Licence, https://www.statcan.gc.ca/en/terms-conditions/open-licence
- `statcan_cma_2021`: Adapted from Statistics Canada, 2021 Census – Boundary files, 2022. This does not constitute an endorsement by Statistics Canada of this product. Statistics Canada Open Licence, https://www.statcan.gc.ca/en/terms-conditions/open-licence
- `statcan_profile_da_2021`: Adapted from Statistics Canada, Census Profile, 2021 Census of Population, 2022. This does not constitute an endorsement by Statistics Canada of this product. Statistics Canada Open Licence, https://www.statcan.gc.ca/en/terms-conditions/open-licence
- `statcan_profile_csd_2021`: Adapted from Statistics Canada, Census Profile, 2021 Census of Population, 2022. This does not constitute an endorsement by Statistics Canada of this product. Statistics Canada Open Licence, https://www.statcan.gc.ca/en/terms-conditions/open-licence
- `statcan_gdp_36100711`: Adapted from Statistics Canada, Table 36-10-0711-01 Gross domestic product (GDP) at basic prices, by industry, provinces and territories, 2022 (current dollars). This does not constitute an endorsement by Statistics Canada of this product. Statistics Canada Open Licence, https://www.statcan.gc.ca/en/terms-conditions/open-licence

## Retrieval

Fetched over HTTPS from `raw.githubusercontent.com`, which serves `.gz` as plain bytes;
the files are stored exactly as served. Nothing is fetched at play time, in CI or in the
browser. To move to a newer Meridian release, add a new reference-data version beside
this one (CLAUDE.md, "World data"); never re-fetch into this directory.
