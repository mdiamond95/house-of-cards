# Source: 2023 Representation Order federal electoral district boundaries

## What this is

`FED_CA_2023_EN.{shp,shx,dbf,prj,CPG}` — the Elections Canada digital boundary file for the 343 federal electoral districts of the 2023 Representation Order, English attribute set. 343 polygon features. Projection: EPSG:3347 (Statistics Canada Lambert Conformal Conic, NAD83), confirmed from the `.prj` file's parameters (false easting 6,200,000 m; false northing 3,000,000 m; central meridian −91.8666667°; standard parallels 49°/77°; latitude of origin 63.390675°).

## Chain of custody

Fallback path (c) was used per the retrieval order in the working instructions, because direct network access to Elections Canada and Government of Canada domains (`elections.ca`, `open.canada.ca`, `ftp.maps.canada.ca`, `statcan.gc.ca`) is blocked by this environment's egress policy — confirmed by repeated `CONNECT tunnel failed, response 403` results on 2026-09-06.

1. **Original authority**: Her Majesty the Queen in Right of Canada / Elections Canada, under the Open Government Licence – Canada (https://open.canada.ca/en/open-government-licence-canada).
2. **Original publication**: Open Government Portal dataset "Federal Electoral Districts - Canada 2023" (https://open.canada.ca/data/en/dataset/18bf3ea7-1940-46ec-af52-9ba3f77ed708), direct file at `https://ftp.maps.canada.ca/pub/elections_elections/Electoral-districts_Circonscription-electorale/federal_electoral_districts_boundaries_2023/FED_CA_2023_EN-SHP.zip`. Both hosts were unreachable from this session.
3. **Mirror used**: GitHub repository `opennorth/represent-canada-data` (Open North's Represent Canada project), path `boundaries/ocd-division/country:ca/2023/FED_CA_2023_EN.*`. Open North states in that repository's root `LICENSE.txt`/per-directory `LICENSE.txt` that it has permission to redistribute this shapefile; the file-level `LICENSE.txt` alongside these files repeats the Open Government Licence – Canada terms. The repository's `definition.py` for this directory records `last_updated: 2024-12-17` and cites the same `data_url` and `source_url` given above, confirming this is an unmodified copy of the Elections Canada file, not a derivative.
4. **Retrieved**: 2026-09-06, via `git clone` (commit `e1c0f4b457b13f01d56bf35df9095e1cab300252` of `opennorth/represent-canada-data`).

## Fields (from the `.dbf`)

| Field | Meaning |
|---|---|
| `FED_NUM` | 5-digit federal electoral district number; first two digits are the province/territory numeric code (10 NL, 11 PE, 12 NS, 13 NB, 24 QC, 35 ON, 46 MB, 47 SK, 48 AB, 59 BC, 60 YT, 61 NT, 62 NU), confirmed by counting features per prefix against the published 2023 seat counts (ON 122, QC 78, BC 43, AB 37, MB 14, SK 14, NS 11, NB 10, NL 7, PE 4, YT 1, NT 1, NU 1 = 343). |
| `ED_NAMEE` | Riding name, English. |
| `ED_NAMEF` | Riding name, French. |
| `REP_ORDER` | Representation order year; `"2023"` for every record, confirming this is the correct vintage. |

## Reproducibility

The `.shp`/`.shx`/`.dbf`/`.prj`/`.CPG` files are committed here (total ≈18 MB, under the 20 MB threshold). If they ever need to be re-fetched: prefer the direct Elections Canada URLs in step 2 above; if those are unreachable, `git clone https://github.com/opennorth/represent-canada-data` and take `boundaries/ocd-division/country:ca/2023/FED_CA_2023_EN.*`.
