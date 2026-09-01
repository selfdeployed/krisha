# FEATURE_SPEC.md — Ranking Feature Engineering

Feature list for the "best deal" ranking model, to be implemented in
`methodology/scripts/feature_engineering.py` and exercised for real against
`methodology/samples/sample_parsed_preview.csv` (the output of
`parse_listings.py --sample`, see `PARSING_SPEC.md` / `build_parser_script`).

**Important cross-file note (affects `feature_scaffold_code`):**
`parse_listings.py --sample` writes `sample_parsed_preview.csv` from the
`parse_row()` output dict only — it does **not** carry `lat`, `lon`, or
`fetched_at` through, since `parse_row()` never receives or returns them.
Those three columns exist only in the raw
`methodology/samples/sample_rows.csv` fixture. Any feature below that needs
lat/lon (the spatial features) or `fetched_at` (`building_age`) requires
`feature_engineering.py` to load **both** CSVs and join them on
`source_row` before computing features. This is documented here so the next
task doesn't rediscover it by a failed run.

## 1. Core hedonic features

Recovered from the structure of `01_near_stations_final.py` and
`02_between_stations_final.py` (their `CONTROLS` formula string itself
lives in `run_main_model.py`, which is not present in this repo — see
"known data-quality risks" below — so these are reconstructed from the
dummy/column names those two scripts reference, not copied verbatim).

| feature | formula / derivation | depends on (parser field) | hard control? | expected missingness |
|---|---|---|---|---|
| `ln_price_m2` (target) | `log(price_tenge / area_total_m2)` | `price_tenge`, `area_total_m2` | target | same as `price_tenge`/`area_total_m2` (~1/16 in sample: the one error row) |
| `ln_area` | `log(area_total_m2)` | `area_total_m2` | hard | ~1/16 in sample |
| `building_age` | `max(0, fetch_year - build_year)`, where `fetch_year = int(fetched_at[:4])` (join required, see above) | `build_year` (parser) + `fetched_at` (raw sample_rows.csv) | hard | rows missing `build_year` (0/16 non-error rows in sample; error row is missing) |
| `is_under_construction` | pass through from parser (`build_year >= fetch_year`) | `is_under_construction` | hard | same as `building_age` |
| `district` | `C(district)` fixed effect / dummy | `district` | hard | 1/16 in sample (error row only) |
| `floor_is_first` | pass through | `floor_is_first` | hard | rows with no `Этаж` label (e.g. `Sanara`, source_row=12) → `None`, must be excluded or imputed, not treated as `False` |
| `floor_is_last` | pass through | `floor_is_last` | hard | same as `floor_is_first` |
| `ceiling_height_m` | pass through | `ceiling_height_m` | soft (missingness non-trivial) | 4/16 in sample missing (source_row 20, 58, 97, 87 — verified by inspecting `sample_parsed_preview.csv`) |
| `former_dormitory` | pass through (bool) | `former_dormitory` | hard | `None` when neither column has the label; 5/16 in sample (source_row 12, 97, 133, 161, 87 — verified by inspecting `sample_parsed_preview.csv`) |
| `exchange_possible` | pass through (bool) | `exchange_possible` | hard | `None` similarly; 2/16 in sample (source_row 12, 87) |
| `building_type` | `C(building_type)` dummy | `building_type` | hard where present, else `unknown` category | ~2,525/34,766 (~7%) missing at full scale (from `sample_fixture` coverage stats); 2/16 in sample (source_row=20 standalone, source_row=87 error row) |

## 2. Spatial feature — user-requested: `avg_price_m2_within_3km`

For each listing, the (robust) average `price_m2` of **other** listings
within a `radius_km` haversine radius (default 3.0 km), excluding the
listing itself.

- `avg_price_m2_within_3km_mean` — simple mean of neighbor `price_m2`.
- `avg_price_m2_within_3km_median` — median of neighbor `price_m2` (more
  robust to outliers — preferred as the primary spatial-smoothing signal).
- `n_neighbors_3km` — count of comparables found within the radius. Used
  as a reliability weight: listings with very few 3km neighbors (e.g. `< 3`)
  should be flagged `low_confidence_spatial=True` and not trusted as
  strongly in downstream ranking.
- `radius_km` must be a configurable function parameter, not hardcoded, so
  it can be tuned later (e.g. 1km/3km/5km comparison) without code changes.
- Depends on: `lat`, `lon` (raw `sample_rows.csv`, join required — see
  cross-file note above) and computed `price_m2` (`price_tenge /
  area_total_m2`, needs both parser fields present and non-error).
- Expected missingness: any row missing `lat`/`lon` (the error row,
  source_row=87) or `price_m2` gets `avg_price_m2_within_3km_* = NaN`,
  `n_neighbors_3km = 0`.

## 3. Additional spatial/comparative features

| feature | derivation | justification | status |
|---|---|---|---|
| `distance_to_center_km` | haversine to Baiterek Tower, `(51.1282, 71.4306)` | Single, well-known, universally-agreed city-center reference point; cheap proxy for general centrality/desirability. **TODO: verify precision before production use** — the coordinate above is an approximate public landmark location, not surveyed. | ready to implement (approximate coord) |
| `distance_to_nearest_station_m` / `distance_to_line_m` | haversine to nearest LRT station / perpendicular distance to the LRT line, reusing the `station_distance_m` / `line_distance_m` concept from the two DiD scripts | Proximity to transit is a strong, well-established price driver in the original DiD work this project is descended from. | **TODO stub only** — the original station-coordinate reference table lived in `run_main_model.py` / `export_current_models_two_tabs.py`, neither of which exists in this repo (confirmed: searched the full repo tree, not found). A new reference table of station coordinates must be manually curated before this can be computed. Leave as an empty/unimplemented stub with this comment; do not fabricate station coordinates. |
| `near_park_1km`, `near_embankment_1km`, `near_mall_1km`, `mall_mega_silkway_1km`, `mall_asia_park_1km`, `mall_keruen_1km`, `mall_keruen_city_1km`, `mall_saryarka_1km` | boolean: haversine distance to the named landmark point < 1km | Reconstructs the confirmed reference set of amenity dummies from `02_between_stations_final.py`'s `AMENITY_TERMS` list and its `mall_keruen_city_1km` addition to the formula; `Khan Shatyr` is the omitted/reference mall category (asserted by that script: `source.MALL_REFERENCE != "Khan Shatyr"` raises). | Approximate coordinates hardcoded as a small table (below), each flagged `# TODO: approximate, manually sourced, verify before production use`. Park/embankment original geometries (point vs. polyline in the source script) are lost along with `run_main_model.py`; approximated here as single points only. |
| `complex_median_price_m2` / `complex_listing_count` | median `price_m2` / count, grouped by `complex_name`, computed only when `complex_listing_count >= min_n` (default 5) | Fair-value anchor at the finest available grouping; below `min_n` a single complex's median is noisy/unreliable. | ready (uses `compute_group_aggregate`) |
| `district_median_price_m2` / `district_listing_count` | same, grouped by `district`, default `min_n = 5` | Fallback anchor for the ~22-24% of listings with no `complex_name`. | ready |
| `kitchen_area_ratio` | `kitchen_area_m2 / area_total_m2` when both known | Layout-efficiency signal; larger kitchen ratio can indicate an older/Soviet-era layout vs. a modern studio-kitchen open plan. | ready; soft/optional given `kitchen_area_m2`'s high missingness (11/16 rows missing in sample — verified by inspecting `sample_parsed_preview.csv`; ~15,603/34,766 ≈ 45% missing at full scale per `sample_fixture` stats) |
| `grid_cell_id` | 500x500m spatial grid cell id from `(lat, lon)`, reusing the DiD scripts' `grid_groups`/clustering pattern | Not a ranking feature itself — reserved for clustering OLS standard errors in `ranking.py` per the DiD precedent (nearby listings' errors are spatially correlated, not i.i.d.). | ready to implement (simple lat/lon binning; exact grid-origin/cell-size match to the original DiD grid is not required since that source is also lost — a fresh, documented 500m grid is sufficient) |

### Approximate landmark reference table (flagged, not verified)

All coordinates below are **approximate, manually sourced from general
public knowledge of Astana geography, and explicitly flagged for
verification before any production use** — none were re-derived from the
(lost) original `run_main_model.py` reference data.

```python
CITY_CENTER = ("Baiterek Tower", 51.1282, 71.4306)  # TODO: verify precision before production use

MALLS = {
    # name -> (lat, lon)  # TODO: approximate, manually sourced, verify before use
    "khan_shatyr": (51.1330, 71.4087),      # omitted/reference category
    "mega_silkway": (51.0916, 71.4168),
    "asia_park": (51.1255, 71.4189),
    "keruen": (51.1274, 71.4162),
    "keruen_city": (51.1064, 71.4667),
    "saryarka": (51.1198, 71.3805),
}

PARK_POINT = ("Central Park (approx.)", 51.1300, 71.4460)     # TODO: approximate, verify
EMBANKMENT_POINT = ("Ishim embankment (approx.)", 51.1215, 71.4330)  # TODO: approximate, verify
```

`near_mall_1km` = OR across all `mall_*_1km` dummies except the
`khan_shatyr` reference. `near_park_1km` / `near_embankment_1km` use the
single approximated point each (original polyline geometry for the
embankment is lost).

## 4. Field-dependency summary (must match `parse_listings.py` output exactly)

Every parser-derived field name used above (`price_tenge`, `area_total_m2`,
`build_year`, `is_under_construction`, `district`, `floor_is_first`,
`floor_is_last`, `ceiling_height_m`, `former_dormitory`,
`exchange_possible`, `building_type`, `complex_name`, `kitchen_area_m2`)
was cross-checked against the real header row of
`methodology/samples/sample_parsed_preview.csv`:

```
source_row,url,price_tenge,price_is_installment,city,district,building_type,
complex_name,build_year,is_under_construction,floor,floor_total,
floor_is_first,floor_is_last,area_total_m2,kitchen_area_m2,
apartment_condition,bathroom,balcony,balcony_glazed,door,phone,internet,
parking,furnished,flooring,ceiling_height_m,security_features,
former_dormitory,exchange_possible,rooms,rooms_bucket_estimated,
rooms_estimate_is_heuristic,parse_warnings
```

`lat`, `lon`, `fetched_at` are **not** in this header (see the cross-file
note at the top) — `feature_engineering.py` must join `source_row` back to
`methodology/samples/sample_rows.csv` for those three.

## 5. Known data-quality risks

- **Mall/park/embankment/city-center reference coordinates are unverified,
  manually-approximated reconstructions**, not sourced from the original
  (lost) `run_main_model.py` / `export_current_models_two_tabs.py` files.
  Must be manually re-verified (e.g. against a maps service) before any
  production/reporting use.
- **Station/line reference table is a TODO stub with no data** — the
  original station-coordinate source file could not be located in this
  repo. `distance_to_nearest_station_m` / `distance_to_line_m` cannot be
  computed until a new table is manually curated.
- **District label strings are used as scraped**, not yet normalized
  against an authoritative district list (e.g. `Есильский` vs `Есиль`
  variants) — that audit is deferred to `eda_plan`.
- **`rooms` is not available in this dataset version** (confirmed: zero
  `комнат` matches across 5,000 scanned rows, per `PARSING_SPEC.md`).
  `rooms_bucket_estimated` is an area-based heuristic
  (`rooms_estimate_is_heuristic=True`) and must never be used as a hard
  OLS control without that caveat.
- **`complex_median_price_m2` is undefined for the ~22-24% of listings
  with no `complex_name`** (standalone listings) — those rows fall back to
  `district_median_price_m2` only.
