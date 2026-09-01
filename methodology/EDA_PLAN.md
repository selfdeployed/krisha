# EDA_PLAN.md — Exploratory Analysis Plan (Full-Scale, Future Work)

This document specifies the exploratory data analysis to run **first**, once
real full-scale parsing of `AstanaLinksParserJune2026_parsed.csv` (~34,766
rows) eventually happens. It is a **plan only** — nothing in this document is
executed against the full dataset in this loop. Per the hard constraint that
governs every task in `ralpheasy/plan.md`, the full CSV may only ever be
opened for a single read pass (already done once, in `sample_fixture`, to
hand-pick `methodology/samples/sample_rows.csv`); no parser/feature/EDA
pipeline may run against it here.

Where a method below is illustrated, it is illustrated against
`methodology/samples/sample_features.csv` / `sample_ranked_preview.csv` (the
16-row sample), explicitly labeled **illustrative only, not representative**
— 16 rows cannot support real distributional or outlier conclusions.

## 1. Missingness report (per parsed field)

Run `df.isna().mean()` (or `.isnull().sum()`) over the full parsed output of
`parse_listings.py` for every field in its return dict
(`PARSING_SPEC.md`/`build_parser_script`), and present as a sorted table
(highest missingness first). Known coverage rates from prior exploration,
to sanity-check the full-scale numbers against once computed:

| field | known/expected coverage | source |
|---|---|---|
| `complex_name` | ~76-78% present (~22-24% absent, standalone listings) | full-file scan in `sample_fixture` (27,121/34,766 present) |
| `rooms` | ~0% present (field does not exist in this dataset version) | confirmed zero `комнат` matches across 5,000 scanned rows, `PARSING_SPEC.md` |
| `kitchen_area_m2` | partial; ~45% missing at full scale (15,603/34,766 rows missing) per `sample_fixture` full-file scan; 11/16 missing in the sample fixture | `sample_fixture`, `FEATURE_SPEC.md` |
| `apartment_condition` | partial; 13,961/34,766 missing at full scale per `sample_fixture` full-file scan | `sample_fixture` |
| `building_type` | ~7% missing at full scale (2,525/34,766); 2/16 in sample | `sample_fixture`, `FEATURE_SPEC.md` |
| `status` (fetch outcome) | ok=33,809 / error=957 at full scale | `sample_fixture` full-file scan |

The full run must recompute all of these directly (the table above is a
prior-knowledge cross-check, not a substitute), and must additionally cover
every other `parse_row()` output field not already measured above (e.g.
`ceiling_height_m`, `former_dormitory`, `exchange_possible`, `bathroom`,
`balcony`, `door`, `phone`, `internet`, `parking`, `furnished`, `flooring`,
`security_features`).

## 2. Distribution checks

- **`price_tenge` histogram** — raw price distribution; expect strong right
  skew (a handful of very high-end listings).
- **`area_total_m2` histogram** — expect a main mass in the ~30-120 m² range
  with a long right tail (large houses/penthouses).
- **`price_m2` histogram, log-scale** — the primary target variable's
  underlying distribution; log-scale specifically because `price_m2` is
  expected to be strongly right-skewed (motivates the `ln_price_m2` target
  used throughout `RANKING_METHODOLOGY.md`).
- **`build_year` distribution with sanity bounds** — flag any row with
  `build_year < 1950` (implausibly old for Astana's housing stock) or
  `build_year > current_year + 5` (implausibly far in the future — beyond a
  normal pre-sale/under-construction horizon) as suspect and worth a manual
  spot-check rather than silently trusting.
- **Listings per `district` (bar chart)** — full distinct-value counts; see
  also section 7's district-string audit.
- **Listings per `complex_name` (top 20 bar chart + long-tail histogram)** —
  expect a small number of large, well-known complexes plus a long tail of
  complexes with only 1-2 listings (relevant to the `min_n` thresholds in
  `FEATURE_SPEC.md`/`RANKING_METHODOLOGY.md`).

## 3. Outlier-detection rules

- **`price_m2` bounds computed per district, not globally**: flag rows
  outside `[district_median_price_m2 * 0.2, district_median_price_m2 * 5]`,
  or equivalently an IQR rule (`Q1 - 1.5*IQR`, `Q3 + 1.5*IQR`) computed
  **within each district group**. Per-district (not global) bounds are
  required because districts differ structurally in price level — a global
  rule would flag an entire cheap district as "outliers" or miss real
  outliers within an expensive one.
- **Malformed prices**: `price_tenge` that parsed as 0, negative, or
  implausibly small (e.g. below a floor such as 1,000,000 ₸ for an entire
  Astana apartment) should be flagged and excluded from modeling pending
  manual review, not silently kept.

## 4. Duplicate / relist detection

Flag rows sharing the same `(lat, lon, area_total_m2, price_tenge)` tuple
appearing more than once. This combination repeating exactly is a strong
signal of the same physical unit being relisted (e.g. after a price cut, or
simply re-posted to bump visibility) rather than an independent comparable —
counting it twice in `complex_median_price_m2` / `district_median_price_m2`
or in the 3km-radius spatial average would double-weight that one unit.
Report the count of such duplicate groups and decide (at full-scale-analysis
time) whether to deduplicate before feature computation or merely flag with
a `is_probable_relist` column.

## 5. Geographic sanity check

Plot all `(lat, lon)` pairs and flag any point falling outside a reasonable
Astana bounding box (approximately `lat ∈ [51.0, 51.25]`, `lon ∈ [71.30,
71.55]`, generous enough to cover the full city plus near-suburban growth
areas without being so wide it would pass through obviously wrong
geocodes). Rows with missing `lat`/`lon` (e.g. `status='error'` rows) are
excluded from this check, not flagged as out-of-bounds.

## 6. Correlation matrix / VIF pre-check

Before any engineered numeric feature from `FEATURE_SPEC.md` reaches the OLS
step in `RANKING_METHODOLOGY.md`, compute a correlation matrix and VIF
(variance inflation factor) across the full numeric feature set: `ln_area`,
`building_age`, `ceiling_height_m`, `distance_to_center_km`,
`avg_price_m2_within_3km_mean`/`_median`, `complex_median_price_m2`,
`district_median_price_m2`, `kitchen_area_ratio`. This is the same VIF > 10
decision rule specified in `RANKING_METHODOLOGY.md` section 5, run here as a
pre-check ahead of model fitting so multicollinear features (expected
candidates: `district` dummies, `distance_to_center_km`, and
`avg_price_m2_within_3km_*` — all three encode overlapping "location"
information) are caught and a drop/combine decision made before wasting a
model-fitting cycle.

## 7. Full-scale audits that fell out of the parsing-spec work

- **Complete distinct-value list of `district` strings** — confirm no
  unexpected variants slipped through (e.g. `Есильский` vs `Есиль`,
  trailing whitespace, alternate transliterations). The sample fixture's
  16 rows only surfaced 4 distinct districts (`Нура`, `Есильский`,
  `Алматы`, `Сарыарка`); Astana has more official districts than that, so
  the full-scale distinct-value list is expected to reveal others (e.g.
  `Байконур`) not exercised in the sample. This is also where the
  `FEATURE_SPEC.md`-deferred "district label normalization against an
  authoritative list" audit belongs.
- **Complete distinct-value list of `building_type` strings** — confirm
  only the expected small set (`монолитный`/`кирпичный`/`панельный`/other)
  appears, with no unparsed leftovers.
- **Frequency of the pipe-delimited `parameters` fallback format** — full
  count of rows where `parameters` contains `' | '` + a district-prefix
  match (`PARSING_SPEC.md`). Known from the `sample_fixture` full-file scan:
  1,659/34,766 rows (~4.8%). Re-derive at full-parse time to confirm the
  parser's fallback-detector actually fires at that same rate.
  `sample_rows.csv` itself has 5/16 (~31%) pipe-fallback rows — deliberately
  over-sampled relative to the full-file rate, since the sample was
  hand-picked to exercise this edge case, not to be representative.
- **Frequency of future/under-construction build years** (`build_year >=
  fetch_year`) — known from `sample_fixture`'s full-file scan:
  4,389/34,766 rows (~12.6%) have `build_year >= 2026`. Re-derive per-row
  `is_under_construction` at full-parse time (using each row's own
  `fetched_at` year, not a hardcoded 2026) to get the precise rate.

## 8. Illustrative-only method demo (not representative)

The methods above may be illustrated on the 16-row
`methodology/samples/sample_features.csv` / `sample_ranked_preview.csv`
outputs already produced by `feature_scaffold_code` / `ranking_scaffold_code`
— for example, eyeballing the `price_m2` values or the per-district
`n_neighbors_3km` spread already documented in `activity.md`. Any such
illustration must be labeled **"illustrative only, not representative"**
in any write-up, since 16 hand-picked (not randomly sampled) rows cannot
support a real distributional, outlier, or correlation conclusion at
population scale.

## Closing note

Executing this plan against the full `AstanaLinksParserJune2026_parsed.csv`
dataset is explicitly **deferred to a future run outside this loop**. No
task in `ralpheasy/plan.md` runs any part of this checklist against the full
file; this document is the plan for that future work, not a report of
results.
