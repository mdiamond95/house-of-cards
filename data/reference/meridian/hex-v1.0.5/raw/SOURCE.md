# Source: Meridian v1.0.5, the hex board

## What this is

The five files below, downloaded unmodified by `scripts/fetch_meridian.py --board` from
the Meridian repository (`mdiamond95/meridian`) at release tag `v1.0.5`, and the input to
`scripts/build_world_hexboard.py`, which builds the `meridian-hex-v1.0.5` reference-data
version (the hex board) in the directory above this one.

| File | URL | SHA-256 |
|---|---|---|
| `hexes.r4.v1.2.json.gz` | https://raw.githubusercontent.com/mdiamond95/meridian/v1.0.5/data/build/hexes.r4.v1.2.json.gz | `163019e1cbf8bd97b4df568e58d006f2caf8b7503df40ce13e414ea74ee052d7` |
| `hexes.r4.v1.2.topojson.gz` | https://raw.githubusercontent.com/mdiamond95/meridian/v1.0.5/data/build/layers/hexes.r4.v1.2.topojson.gz | `817ccf7d03c18e6bee8cd093ce98bd2f0473b979412c9e9547ca0c114942c279` |
| `hexes.r5.v1.json.gz` | https://raw.githubusercontent.com/mdiamond95/meridian/v1.0.5/data/build/hexes.r5.v1.json.gz | `2b0e76bf0c8cba89df845f5d42fe7403a2001661a44230e4b9b762288cf75d1e` |
| `hexes.r5.v1.topojson.gz` | https://raw.githubusercontent.com/mdiamond95/meridian/v1.0.5/data/build/layers/hexes.r5.v1.topojson.gz | `95f864b1623ecbf445a22f6e54dcec4a17190982def486db34c148d43bb791e7` |
| `mesh.v1.json.gz` | https://raw.githubusercontent.com/mdiamond95/meridian/v1.0.5/data/build/mesh.v1.json.gz | `f29ac1afe20ff33caa0cf6928f7979101617a71455210ba564a8a7bc86725677` |

Tag: `v1.0.5`. Every hash is checked on every read and a file is refused on any
other; Meridian's versioning rule 7 makes a released file immutable.

## What the tables declare

- format `meridian.unitTable`, version `1`, unit `h3_r4` (checked; anything else is refused): 5986 rows, H3 resolution-4 hexagons with land, the large lakes being water; H3 resolution 4, mesh `v1`, layer `data/build/layers/hexes.r4.v1.2.topojson.gz`, neighbour rule `principalLand`
- format `meridian.unitTable`, version `1`, unit `h3_r5` (checked; anything else is refused): 407 rows, H3 resolution-5 mesh cells of the resolution-4 hexagons of 100,000 people or more; H3 resolution 5, mesh `v1`, layer `data/build/layers/hexes.r5.v1.topojson.gz`, neighbour rule `principalLand`
- `mesh.v1.json.gz`: format `meridian.mesh`, version `v1`, H3 resolution 5 (checked; anything else is refused), 38432 cells, census subdivisions from `statcan_csd_2021`. Its hash was recorded on the first fetch at this tag; the other four were given by the director.
- `hexes.r5.v1.json.gz`'s parent table: `data/build/hexes.r4.v1.2.json.gz`
- census year 2021; GDP method `allocation_v1`, reference year 2022, `current_dollars_basic_prices`
- jurisdictions from the atlas `v1`, from 1867-07-01
- settlement dates withheld from 1950; city years on rows of 100,000 people or more

**GDP is an allocation, not a measurement.** The table's own caveat, verbatim:

> GDP is an estimate: provincial GDP by industry shared over mesh cells by census labour force (allocation_v1), not a measurement of what a hexagon produces.

## Attribution and licences

As the resolution-4 table's `meta.sources` gives them:

- `statcan_csd_2021`: Adapted from Statistics Canada, 2021 Census – Boundary files, 2022. This does not constitute an endorsement by Statistics Canada of this product. Statistics Canada Open Licence, https://www.statcan.gc.ca/en/terms-conditions/open-licence
- `statcan_da_2021`: Adapted from Statistics Canada, 2021 Census – Boundary files, 2022. This does not constitute an endorsement by Statistics Canada of this product. Statistics Canada Open Licence, https://www.statcan.gc.ca/en/terms-conditions/open-licence
- `statcan_cma_2021`: Adapted from Statistics Canada, 2021 Census – Boundary files, 2022. This does not constitute an endorsement by Statistics Canada of this product. Statistics Canada Open Licence, https://www.statcan.gc.ca/en/terms-conditions/open-licence
- `statcan_profile_da_2021`: Adapted from Statistics Canada, Census Profile, 2021 Census of Population, 2022. This does not constitute an endorsement by Statistics Canada of this product. Statistics Canada Open Licence, https://www.statcan.gc.ca/en/terms-conditions/open-licence
- `statcan_profile_csd_2021`: Adapted from Statistics Canada, Census Profile, 2021 Census of Population, 2022. This does not constitute an endorsement by Statistics Canada of this product. Statistics Canada Open Licence, https://www.statcan.gc.ca/en/terms-conditions/open-licence
- `statcan_gdp_36100711`: Adapted from Statistics Canada, Table 36-10-0711-01 Gross domestic product (GDP) at basic prices, by industry, provinces and territories, 2022 (current dollars). This does not constitute an endorsement by Statistics Canada of this product. Statistics Canada Open Licence, https://www.statcan.gc.ca/en/terms-conditions/open-licence
- `aafc_ecozones`: Contains information licensed under the Open Government Licence – Canada. Open Government Licence – Canada, https://www.statcan.gc.ca/en/terms-conditions/open-licence
- `nrcan_atlas_waterbodies_1m`: Contains information licensed under the Open Government Licence – Canada. Open Government Licence – Canada, https://open.canada.ca/en/open-government-licence-canada
- `nrcan_atlas_islands_1m`: Contains information licensed under the Open Government Licence – Canada. Open Government Licence – Canada, https://open.canada.ca/en/open-government-licence-canada
- `wikidata_csd_dates`: Founding, incorporation and city dates from Wikidata (CC0). Creative Commons CC0 1.0 (public domain dedication), https://creativecommons.org/publicdomain/zero/1.0/

## Retrieval

Fetched over HTTPS from `raw.githubusercontent.com`, which serves `.gz` as plain bytes;
the files are stored exactly as served. Nothing is fetched at play time, in CI or in the
browser.
