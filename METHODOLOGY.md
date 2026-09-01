# METHODOLOGY.md — Krisha "Best Offer" Methodology

This is the top-level index for the deliverable: a documented, working
**methodology** for turning raw scraped krisha.kz listing text into
structured data, engineering ranking features (including a 3km-radius
spatial price/m² smoothing feature), and scoring/ranking listings as
"best deal" per residential complex (ЖК) and per district. It was built
and verified end-to-end on a small real sample, not run as a full-scale
production pipeline (see "Scope" below).

## Dataset scope

- **Primary dataset for this methodology: `AstanaLinksParserJune2026_parsed.csv`**
  (~34,766 rows, columns `source_row, url, status, http_status, advert_info,
  parameters, lat, lon, fetched_at, error`).
- **`2025_data.csv` is explicitly out of scope for this run.** It was not
  read, parsed, or merged into anything here. It is a candidate input for a
  possible future year-over-year trend-comparison extension, not part of
  this deliverable.
- **No script in this methodology was ever run as a processing/modeling
  pipeline against either full CSV.** The one exception, by design, is a
  single read-through of `AstanaLinksParserJune2026_parsed.csv` in the
  `sample_fixture` task to hand-pick a small fixed sample and compute a few
  descriptive coverage counts (e.g. how many rows have `Жилой комплекс`) —
  not to parse, engineer features from, or model the data. Every other task
  ran real code only against that sample.

## The sample fixture

All real execution (parsing, feature engineering, OLS fitting) in this
methodology runs against `methodology/samples/sample_rows.csv`: 16 rows
hand-picked from the full file to cover the known edge cases (typical
listings with a complex name, standalone listings without one, the
pipe-delimited `parameters` fallback format, a `status=error` row, rows
missing kitchen area/condition/building type, and under-construction build
years), documented row-by-row in `methodology/samples/README.md`. It is a
deliberately curated edge-case fixture, not a random/representative sample.

## Reading order for a human

1. **`methodology/PARSING_SPEC.md`** — how `advert_info`/`parameters` text
   becomes structured fields (label-segmentation algorithm, regexes, real
   test cases).
2. **`methodology/scripts/parse_listings.py`** — the implementation,
   runnable via `--selftest` (35 inline literal checks) and `--sample`
   (real run against the fixture, writes `sample_parsed_preview.csv`).
3. **`methodology/FEATURE_SPEC.md`** — the full ranking feature list: core
   hedonic features, the `avg_price_m2_within_3km` spatial-smoothing
   feature, distance-to-center/mall/park dummies, complex/district median
   aggregates, `grid_cell_id`.
4. **`methodology/scripts/feature_engineering.py`** — the implementation,
   runnable via `--sample` (real run against the parsed sample, writes
   `sample_features.csv`).
5. **`methodology/RANKING_METHODOLOGY.md`** — the two ranking approaches
   (naive percentile rank, and OLS-residual) and how they combine into one
   presentation plus a composite `good_deal_score`.
6. **`methodology/scripts/ranking.py`** — the implementation, runnable via
   `--sample` (real, but deliberately trimmed, OLS fit on the sample,
   writes `sample_ranked_preview.csv`).
7. **`methodology/EDA_PLAN.md`** — the exploratory-analysis checklist to
   run *first* once real full-scale parsing eventually happens (plan only,
   not executed against the full dataset here).

## The two-pronged ranking approach (restated briefly)

Two independent signals are computed per listing and shown side by side,
never silently merged into one opaque number:

- **Approach A — percentile rank**: rank of `price_m2` ascending within
  `complex_name` (falling back to `district` when the complex has too few
  comparables, or no `complex_name` at all) and within `district`. Cheaper
  = lower percentile = better deal, **ignoring every feature difference**
  (area, floor, age, etc.) — a naive baseline.
- **Approach B — OLS residual**: fit `ln_price_m2` on hedonic + spatial
  features (full formula in `RANKING_METHODOLOGY.md` §2); the residual
  (actual − predicted) is the "priced below/above what its features
  justify" signal. This is the approach that actually controls for
  feature differences, but it is only as trustworthy as its diagnostics
  and sample size allow (§4-5 of that doc) — **and the full formula is
  only fit-able on the full ~35k-row dataset**, out of scope for this run.

They combine into a per-listing `good_deal_score`: the mean of two
z-scored components, `-percentile_rank` and `-ols_residual_score` (higher
score = better deal). `RANKING_METHODOLOGY.md` §7-8 documents exactly when
each component should be trusted as primary vs. treated as provisional.

## What was actually run and verified (real output, not assumed)

Every implementation task's steps ran the real code against the real
16-row sample and produced real output files under `methodology/samples/`:

- `parse_listings.py --selftest`: 35 inline-literal checks, all passing.
- `parse_listings.py --sample`: writes `sample_parsed_preview.csv`
  (16 rows); price/district/area parsed on 15/16 (the 1 miss is the
  intentional `status=error` row), `complex_name` present on 8/16.
- `feature_engineering.py --sample`: writes `sample_features.csv`;
  `haversine_km` self-check (Baiterek Tower → Khan Shatyr ≈ 1.6 km);
  `n_neighbors_3km` ranges 0-9 across the sample's deliberately-spread
  lat/lon, matching the geographic layout chosen in `sample_fixture`.
- `ranking.py --sample`: writes `sample_ranked_preview.csv`; a real
  `statsmodels` OLS fit (`ln_price_m2 ~ ln_area +
  avg_price_m2_within_3km_median`, n=13/16 after listwise deletion,
  R²=0.4503) plus percentile ranks and the composite `good_deal_score`,
  eyeballed row-by-row for sign correctness (the cheapest-in-district,
  most-underpriced-vs-features listing scored highest; the reverse scored
  lowest).

**The sample-scale OLS fit above is a pipeline-correctness check only —
proving the fit/residual/ranking code path runs end-to-end on real
numbers — not a trustworthy price model.** With only 13-16 usable rows and
a formula trimmed to 2 continuous predictors (the full formula in
`RANKING_METHODOLOGY.md` §2 is rank-deficient at this scale), neither the
coefficients nor R² should be read as a real estimate of how price relates
to area or location. `RANKING_METHODOLOGY.md` §3 states this explicitly,
as does every place the fit's output is printed or logged
(`ranking.py`'s own stdout banner, and `ralpheasy/activity.md`'s
`ranking_scaffold_code` entry). The real model only becomes meaningful
once fit on the full ~35k-row dataset.

Full command list to reproduce (from the repo root):

```
python methodology/scripts/parse_listings.py --selftest
python methodology/scripts/parse_listings.py --sample
python methodology/scripts/feature_engineering.py --sample
python methodology/scripts/ranking.py --sample
```

## Known data-quality gaps (consolidated)

- **Room count is not available in this dataset version** (confirmed zero
  `"комнат"` matches across a 5,000-row scan of the full file).
  `rooms_bucket_estimated` is an area-based heuristic
  (`rooms_estimate_is_heuristic=True`) and must never be used as a hard
  OLS control without that caveat. A future scraper enhancement could
  capture the page `<h1>`/title text (which typically encodes
  "N-комнатная квартира") — not implemented here.
- **Station/mall/park/city-center reference coordinates need manual
  verification.** The original coordinate source files
  (`run_main_model.py`, `export_current_models_two_tabs.py`) are not
  present in this repo. Mall/park/embankment/city-center points used here
  are approximate, manually sourced from general knowledge of Astana
  geography, and flagged `# TODO: verify before use` at every definition
  site. The station/line reference table (`distance_to_nearest_station_m` /
  `distance_to_line_m`) is an unimplemented empty stub — a new table must
  be manually curated before it can be computed.
- **`parameters` sometimes duplicates `advert_info` in a pipe-delimited
  (`" | "`) format instead of carrying amenity data** — confirmed present
  in ~4.8% of the full file (1,659/34,766 rows). The parser detects and
  gap-fills from it (never overwrites a value already extracted from
  `advert_info`).
- **District label strings are used as scraped, not yet normalized**
  against an authoritative list (e.g. potential `Есильский` vs. `Есиль`
  variants). This audit is deferred to `EDA_PLAN.md` §7, to be run once
  full-scale parsing happens.
- **`complex_name` is present on only ~76-78% of listings** (27,121/34,766
  on the full file); the remaining ~22-24% are standalone listings with no
  complex, for which `percentile_rank_in_complex` and
  `complex_median_price_m2` are undefined and ranking falls back to the
  district level.

## Next steps to run at scale (out of scope for this loop)

- Run `parse_listings.py` across the full `AstanaLinksParserJune2026_parsed.csv`
  (not just the 16-row sample) to produce a full structured dataset.
- Run the `EDA_PLAN.md` checklist against that full parsed output:
  missingness, distributions, per-district outlier bounds, duplicate/relist
  detection, geographic sanity check, correlation/VIF pre-check, and the
  district/building_type distinct-value audits.
- Fit the real full-formula OLS (`RANKING_METHODOLOGY.md` §2) per
  district (and per complex where `n>=8-10`), with the full diagnostics
  checklist (§5: adjusted R², residual-vs-fitted, QQ plot, VIF>10 rule,
  leave-one-complex-out/k-fold CV) and `grid_cell_id`-clustered standard
  errors (§6).
- Manually curate and verify the station/mall/park reference-coordinate
  tables before trusting any resulting proximity feature or coefficient.
- Generate final ranked-listing output tables (percentile ranks, OLS
  residuals, composite `good_deal_score`) for real apartment-hunting use.

None of the above was executed in this loop; they are documented here as
the concrete path from this methodology to a real, trustworthy ranking of
the full ~35k-listing dataset.
