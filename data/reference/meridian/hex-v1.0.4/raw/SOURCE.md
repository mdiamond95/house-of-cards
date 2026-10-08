# Source: Meridian v1.0.4, H3 resolution-4 hexagon unit table

## What this is

The two files below, downloaded unmodified by `scripts/fetch_meridian.py --hexes` from
the Meridian repository (`mdiamond95/meridian`) at release tag `v1.0.4`, and the input to
`scripts/build_world_hex.py`, which builds the `meridian-hex-v1.0.4` reference-data
version (the hex trial) in the directory above this one.

| File | URL | SHA-256 |
|---|---|---|
| `hexes.r4.v1.json.gz` | https://raw.githubusercontent.com/mdiamond95/meridian/v1.0.4/data/build/hexes.r4.v1.json.gz | `94c2f806ed3ed6315647858b63cc777209c3a97280da7caa98a65734eb455a8a` |
| `hexes.r4.v1.topojson.gz` | https://raw.githubusercontent.com/mdiamond95/meridian/v1.0.4/data/build/layers/hexes.r4.v1.topojson.gz | `336cb743b1da8184af2cf515ef75a34312126c09243d15a735c108c855330325` |

Tag: `v1.0.4`. Both hashes are checked on every read and the files are refused on any
other; Meridian's versioning rule 7 makes a released file immutable.

## What the table declares

- format `meridian.unitTable`, version `1`, unit `h3_r4` (checked; anything else is refused)
- 6011 rows: H3 resolution-4 hexagons with at least one mesh cell
- H3 resolution 4, mesh `v1`, layer `data/build/layers/hexes.r4.v1.topojson.gz`
- census year 2021; GDP method `allocation_v1`, reference year 2022, `current_dollars_basic_prices`
- jurisdictions from the atlas `v1`, from 1867-07-01

**GDP is an allocation, not a measurement.** The table's own caveat, verbatim:

> GDP is an estimate: provincial GDP by industry shared over mesh cells by census labour force (allocation_v1), not a measurement of what a hexagon produces.

## Attribution and licences

As the table's `meta.sources` gives them:

- `statcan_csd_2021`: Adapted from Statistics Canada, 2021 Census – Boundary files, 2022. This does not constitute an endorsement by Statistics Canada of this product. Statistics Canada Open Licence, https://www.statcan.gc.ca/en/terms-conditions/open-licence
- `statcan_da_2021`: Adapted from Statistics Canada, 2021 Census – Boundary files, 2022. This does not constitute an endorsement by Statistics Canada of this product. Statistics Canada Open Licence, https://www.statcan.gc.ca/en/terms-conditions/open-licence
- `statcan_cma_2021`: Adapted from Statistics Canada, 2021 Census – Boundary files, 2022. This does not constitute an endorsement by Statistics Canada of this product. Statistics Canada Open Licence, https://www.statcan.gc.ca/en/terms-conditions/open-licence
- `statcan_profile_da_2021`: Adapted from Statistics Canada, Census Profile, 2021 Census of Population, 2022. This does not constitute an endorsement by Statistics Canada of this product. Statistics Canada Open Licence, https://www.statcan.gc.ca/en/terms-conditions/open-licence
- `statcan_profile_csd_2021`: Adapted from Statistics Canada, Census Profile, 2021 Census of Population, 2022. This does not constitute an endorsement by Statistics Canada of this product. Statistics Canada Open Licence, https://www.statcan.gc.ca/en/terms-conditions/open-licence
- `statcan_gdp_36100711`: Adapted from Statistics Canada, Table 36-10-0711-01 Gross domestic product (GDP) at basic prices, by industry, provinces and territories, 2022 (current dollars). This does not constitute an endorsement by Statistics Canada of this product. Statistics Canada Open Licence, https://www.statcan.gc.ca/en/terms-conditions/open-licence
- `aafc_ecozones`: Contains information licensed under the Open Government Licence – Canada. Open Government Licence – Canada, https://www.statcan.gc.ca/en/terms-conditions/open-licence

## Retrieval

Fetched over HTTPS from `raw.githubusercontent.com`, which serves `.gz` as plain bytes;
the files are stored exactly as served. Nothing is fetched at play time, in CI or in the
browser.
