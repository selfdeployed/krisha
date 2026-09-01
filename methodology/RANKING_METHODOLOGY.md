# RANKING_METHODOLOGY.md — "Best Deal" Ranking

How engineered features (`FEATURE_SPEC.md`) become a "this listing is a
good deal" score. **Primary signal is a 3km-radius spatial relative price**
(this section, first) — a listing's price/m² compared against the average
price/m² of every *other* listing within 3km of it, regardless of complex
or district membership. Two secondary/contextual signals are also computed
and shown alongside it, never silently merged into the primary score: an
in-complex/in-district percentile rank (informational only), and an
OLS-residual model (full-scale future work). Every column is shown
side by side — never collapsed into a single opaque number without its
components visible.

Implemented in `methodology/scripts/ranking.py`
(`ranking_scaffold_code`), exercised for real against
`methodology/samples/sample_features.csv` (the output of
`feature_engineering.py --sample`, see `feature_scaffold_code`).

## 1. Primary approach — 3km-radius spatial relative price

- `spatial_price_ratio` = `price_m2 / avg_price_m2_within_3km_median`
  (uses the median, matching `FEATURE_SPEC.md`'s stated preference for
  median over mean as the more outlier-robust neighborhood summary).
  `1.0` = priced exactly at its neighborhood's average; `<1.0` = cheaper
  than its neighbors; `>1.0` = pricier.
- `spatial_price_pct_vs_avg` = `spatial_price_ratio - 1` (e.g. `-0.15` =
  15% below the 3km-neighborhood average price/m² — the primary "good
  deal" signal). More negative = better deal.
- `spatial_rank_reliable` = `n_neighbors_3km >= MIN_NEIGHBORS_FOR_SPATIAL`
  (default 3; reuses `FEATURE_SPEC.md`'s `low_confidence_spatial` concept
  in `feature_engineering.py`). A listing whose 3km circle contains too
  few other listings gets an unreliable neighborhood average — flag it,
  don't silently trust it.
- **Why this is primary, not `percentile_rank_in_complex`:** the
  comparison set here is every listing within 3km, drawn from *any*
  complex or none at all — it does **not** require multiple listings in
  the same ЖК to produce a meaningful score. A complex with exactly 1
  scraped listing still gets a fully valid `spatial_price_pct_vs_avg`, as
  long as it has `>= MIN_NEIGHBORS_FOR_SPATIAL` other listings (from any
  complex) nearby. This directly avoids the coverage problem the naive
  in-complex percentile has: in the current 16-row sample, every complex
  that appears has exactly 1 listing (`complex_listing_count=1` for all
  8 complexes present), so `percentile_rank_in_complex` is uninformative
  for 100% of sample rows — `spatial_price_pct_vs_avg` is not affected by
  this at all, since it never groups by complex.
- **Still feature-light**: like the percentile approaches, this does not
  control for area/floor/age/condition differences between a listing and
  its neighbors — a large new-build next to older smaller units will look
  "expensive" by this metric even if it's fairly priced for its own
  specs. It controls for *location* (the single largest real-estate price
  driver) but nothing else. The OLS approach (section 3) is what
  additionally adjusts for those other features, once it's fit on enough
  data to be trustworthy.

## 2. Context-only signal — percentile rank within complex / district

- `percentile_rank_in_complex` = rank of `price_m2` ascending within
  `complex_name`, divided by count in that group (0 = cheapest in its
  complex, ~1 = most expensive).
- `percentile_rank_in_district` = same computation, grouped by `district`.
- **Shown for reference only — not an input to `good_deal_score`.** If
  you want to know "is this the cheapest unit in this specific building,"
  these columns answer that directly; they are not used to drive the
  primary ranking because they inherit the small-sample-per-complex
  problem described in section 1, and because they, like the spatial
  metric, ignore feature differences entirely (a small studio and a large
  3-room unit in the same complex get compared with no adjustment).
  Always label them "naive, in-group only" wherever shown.

## 3. Secondary signal — OLS residual (real, full-scale model — future work)

**Not run in this loop's primary score.** Formula sketch for the eventual
full-dataset fit:

```
ln_price_m2 ~ ln_area + building_age + floor_is_first + floor_is_last
            + ceiling_height_m + former_dormitory + exchange_possible
            + C(building_type) + C(district) + distance_to_center_km
            + avg_price_m2_within_3km_median
            (+ distance_to_nearest_station_m, once that reference table exists)
```

- Fit via `statsmodels.formula.api.ols`, matching the pattern already used
  in `01_near_stations_final.py` (`smf.ols(formula, data=sample,
  missing="raise").fit()`).
- `ols_residual_score` = `actual ln_price_m2 - predicted ln_price_m2`. A
  strongly **negative** residual means the listing is priced well below
  what its own features predict — a good deal. A strongly positive
  residual means it's priced above what its features justify.
- This is the only approach that actually controls for area/floor/age
  differences instead of ignoring them like sections 1 and 2 do, but it
  is only as trustworthy as its diagnostics (section 5) and its sample
  size (section 4) allow — and unlike section 1, it genuinely does need
  enough data per group to fit reliably.
- Once trustworthy (full dataset, diagnostics pass), this becomes a
  second input to `good_deal_score` alongside the spatial signal — see
  section 7.

## 4. Sample-scale OLS check actually run in this loop

`ranking_scaffold_code` runs a real OLS fit against
`sample_features.csv`, but with only **~15-20 rows** the full formula in
section 3 is **rank-deficient**: it has far more dummy/categorical
parameter columns (`C(building_type)`, `C(district)`, plus every
continuous control) than there are observations to estimate them from.

**Trimmed sample-scale formula, continuous predictors only:**

```
ln_price_m2 ~ ln_area + avg_price_m2_within_3km_median
```

**Purpose of this fit is narrow and explicit: prove the code path works**
— the formula parses, `statsmodels` fits without error, residuals compute,
and (when the fit succeeds) `ols_residual_score` blends into
`good_deal_score` as a secondary refinement on real numbers. **It is NOT a
trustworthy coefficient estimate or price model.** Two continuous
predictors on ~15-20 rows (many with missing `price_m2` or missing
spatial neighbors) cannot support causal or even reliable predictive
claims. Every place this fit's output is shown — script stdout,
`sample_ranked_preview.csv`, activity.md — must say so explicitly. The
real model only becomes meaningful once fit on the full ~35k-row dataset,
which is explicitly out of scope for this run.

## 5. Minimum sample size rules (for the real, full-scale OLS model)

These rules apply to section 3's OLS model, **not** to the primary
spatial-relative-price signal (section 1), which only needs
`n_neighbors_3km >= MIN_NEIGHBORS_FOR_SPATIAL` and is unaffected by
per-complex sample size.

- **Per-complex minimum:** a complex needs **n >= 8-10** comparable
  listings before a complex-specific fixed effect (a `C(complex_name)`
  dummy, or any complex-level adjustment) should be trusted as capturing
  a real complex-level price premium/discount rather than noise.
- **Below that threshold:** do not fit a complex fixed effect for that
  complex. Instead, fall back to predicting from the district-level model
  and applying `complex_median_price_m2` (from `FEATURE_SPEC.md`, itself
  only computed when `complex_listing_count >= 5`) as a simple additive/
  multiplicative adjustment on top of the district-level prediction,
  rather than a fitted dummy coefficient.

## 6. Diagnostics checklist (before trusting the real, full-scale OLS)

Apply all of the following before treating `ols_residual_score` from the
full-dataset model as a composite-score input:

1. **Adjusted R-squared** — sanity-check overall explanatory power; not
   sufficient on its own, but a very low value (model barely explains
   variation in `ln_price_m2`) is disqualifying.
2. **Residual-vs-fitted plot** — check for heteroscedasticity; if
   present, prefer the clustered/robust standard errors from section 8
   over the naive OLS SEs regardless.
3. **QQ plot of residuals** — check approximate normality; heavy tails or
   skew undermine residual-magnitude comparisons across listings.
4. **VIF (variance inflation factor)** for every continuous predictor —
   flag any predictor with **VIF > 10** as a multicollinearity risk.
   Specifically expected to be collinear: `C(district)` dummies,
   `distance_to_center_km`, and (once available)
   `distance_to_nearest_station_m` — all three encode overlapping
   "where in the city" information, and `avg_price_m2_within_3km_median`
   also partially encodes location. **Decision rule:** when two
   predictors both exceed VIF > 10 and encode overlapping location
   information, drop the one with weaker standalone justification first
   (`distance_to_center_km` is the first candidate to drop, since
   `C(district)` and `avg_price_m2_within_3km_median` both carry more
   granular location signal) rather than dropping both blindly.
5. **Out-of-sample validation** — leave-one-complex-out or k-fold
   cross-validation on `ln_price_m2` prediction error.

None of these diagnostics are computed for the sample-scale check in
section 4 — with ~15-20 rows they would not be meaningful, which is
exactly why section 4 is scoped as a code-path check, not a
model-quality check.

## 7. Standard-error treatment (real, full-scale OLS model)

Cluster standard errors by `grid_cell_id` (the 500x500m spatial grid from
`FEATURE_SPEC.md` section 3), matching `01_near_stations_final.py`'s
exact pattern: `ols.get_robustcov_results(cov_type="cluster",
groups=grid_groups, use_correction=True, df_correction=True, use_t=True)`.
The sample-scale check (section 4) does **not** apply clustering — with
only ~15-20 rows spread across up to 15-20 distinct grid cells, cluster
count would be close to or equal to observation count. `ranking.py`'s
`fit_price_model` still accepts an optional `cluster_col` parameter
(unused when called from `--sample` mode) so the same function is ready
for the full-scale run.

## 8. Combining signals into one presentation

Per listing, show **all of the following side by side** — never silently
collapsed into a single number without the components visible:

| column | source | role |
|---|---|---|
| `spatial_price_pct_vs_avg` | section 1 | **primary composite input** |
| `spatial_rank_reliable` | section 1 | reliability flag for the above |
| `percentile_rank_in_complex` | section 2 | context only, not in composite |
| `percentile_rank_in_district` | section 2 | context only, not in composite |
| `predicted_price_m2` (`exp(predicted ln_price_m2)`) | section 3 | secondary composite input |
| `actual_price_m2` | data | reference |
| `ols_residual_score` | section 3 | secondary composite input |
| `good_deal_score` | composite, below | primary ranking output |

**Composite score:**

```
good_deal_score = mean(
    zscore(-spatial_price_pct_vs_avg),   # cheaper vs. 3km neighborhood -> higher (better) z
    zscore(-ols_residual_score)          # more negative residual -> higher (better) z, when available
)
```

Row-wise mean skips a missing component (e.g. a row the OLS fit dropped,
or a row with `spatial_rank_reliable=False`, still contributes whichever
component it has); a row with both missing gets NaN. `ols_residual_score`
is treated as trustworthy input only once the model's diagnostics
(section 6) are healthy and the sample size (section 5) is adequate —
i.e. only meaningful on the real full-dataset fit. Until then (as in this
loop), `good_deal_score` is effectively spatial-signal-dominated, with the
OLS component labeled low-confidence wherever it contributes.
`percentile_rank_in_complex`/`_in_district` are never part of
`good_deal_score` — they remain a separate, explicitly-labeled reference
pair a viewer can check per listing (e.g. "how does this compare to just
this building"), independent of how many other units from that same
complex were scraped.

## 9. What would invalidate this

- **Sparse 3km neighborhoods**: a listing with `n_neighbors_3km` below
  `MIN_NEIGHBORS_FOR_SPATIAL` (default 3) has an unreliable
  `avg_price_m2_within_3km_median` and thus an unreliable
  `spatial_price_pct_vs_avg` — flagged via `spatial_rank_reliable=False`,
  never silently trusted. This is now the primary reliability risk for
  the ranking (replacing the old per-complex sample-size risk, which only
  affects the context-only percentile columns, not the primary score).
- **Overfitting risk from too many dummy variables relative to n** (OLS,
  section 3): the full formula has one parameter per `district` level,
  one per `building_type` level, plus continuous controls — on a dataset
  with many small/rare districts or building types, some dummy levels may
  have very few observations even at full ~35k scale. Check per-level
  observation counts before trusting any single dummy coefficient.
- **`complex_name` coverage gap (~22-24% missing, per `FEATURE_SPEC.md`)**:
  affects only `percentile_rank_in_complex` (undefined for standalone
  listings) — the primary `good_deal_score` is unaffected, since it never
  depends on `complex_name`.
- **Unresolved station/mall reference-data gap**: `distance_to_nearest_
  station_m` remains a TODO stub (`FEATURE_SPEC.md` section 3) until a new
  station-coordinate table is manually curated; until then the full-scale
  OLS formula (section 3) must be fit without that term. Mall/park/
  embankment coordinates used for the 1km dummies are also unverified
  approximations — treat any resulting coefficient as provisional.
