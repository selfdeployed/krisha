# RANKING_METHODOLOGY.md — "Best Deal" Ranking

How engineered features (`FEATURE_SPEC.md`) become a "this listing is a
good deal" score. Two independent approaches are documented, each with its
own validation story, then combined into one side-by-side presentation —
never silently merged into a single opaque number.

Implemented in `methodology/scripts/ranking.py`
(`ranking_scaffold_code`, next task), exercised for real against
`methodology/samples/sample_features.csv` (the output of
`feature_engineering.py --sample`, see `feature_scaffold_code`).

## 1. Approach A — percentile rank (naive baseline)

- `percentile_rank_in_complex` = rank of `price_m2` ascending within
  `complex_name`, divided by count in that group (0 = cheapest in its
  complex, ~1 = most expensive).
- `percentile_rank_in_district` = same computation, grouped by `district`
  instead.
- Lower percentile = cheaper = better deal, **all else being equal**.
- **This approach ignores every feature difference** — area, floor, age,
  building type, distance to center, everything in `FEATURE_SPEC.md`
  section 1 and 3. Two listings can have very different percentile ranks
  purely because one is a small studio and the other is a large 3-room
  unit in the same complex. It is a naive baseline, not a fair-value
  estimate, and must always be labeled as such wherever it is shown.

## 2. Approach B — OLS residual (real, full-scale model — future work)

**Not run in this loop.** Formula sketch for the eventual full-dataset fit:

```
ln_price_m2 ~ ln_area + building_age + floor_is_first + floor_is_last
            + ceiling_height_m + former_dormitory + exchange_possible
            + C(building_type) + C(district) + distance_to_center_km
            + avg_price_m2_within_3km
            (+ distance_to_nearest_station_m, once that reference table exists)
```

- Fit via `statsmodels.formula.api.ols`, matching the pattern already used
  in `01_near_stations_final.py` (`smf.ols(formula, data=sample,
  missing="raise").fit()`).
- `ols_residual_score` = `actual ln_price_m2 - predicted ln_price_m2`. A
  strongly **negative** residual means the listing is priced well below
  what its own features predict — a good deal. A strongly positive
  residual means it's priced above what its features justify.
- This is the model that actually controls for area/floor/age/location
  differences instead of ignoring them like Approach A does, but it is
  only as trustworthy as its diagnostics (section 4) and its sample size
  (section 3) allow.

## 3. Sample-scale OLS check actually run in this loop

`ranking_scaffold_code` runs a real OLS fit against
`sample_features.csv`, but with only **~15-20 rows** the full formula in
section 2 is **rank-deficient**: it has far more dummy/categorical
parameter columns (`C(building_type)`, `C(district)`, plus every
continuous control) than there are observations to estimate them from.

**Trimmed sample-scale formula, continuous predictors only:**

```
ln_price_m2 ~ ln_area + avg_price_m2_within_3km_median
```

(`avg_price_m2_within_3km_median` is used rather than `_mean`, matching
`FEATURE_SPEC.md`'s stated preference for the median as the more
robust/primary spatial-smoothing signal.)

**Purpose of this fit is narrow and explicit: prove the code path works**
— the formula parses, `statsmodels` fits without error, residuals compute,
percentile ranks compute, and the composite score (section 6) combines
them sensibly on real numbers. **It is NOT a trustworthy coefficient
estimate or price model.** Two continuous predictors on ~15-20 rows (many
with missing `price_m2` or missing spatial neighbors) cannot support
causal or even reliable predictive claims. Every place this fit's output
is shown — script stdout, `sample_ranked_preview.csv`, activity.md — must
say so explicitly. The real model only becomes meaningful once fit on the
full ~35k-row dataset, which is explicitly out of scope for this run.

## 4. Minimum sample size rules (for the real, full-scale model)

- **Per-complex minimum:** a complex needs **n >= 8-10** comparable
  listings before a complex-specific fixed effect (a `C(complex_name)`
  dummy, or any complex-level adjustment) should be trusted as capturing
  a real complex-level price premium/discount rather than noise.
- **Below that threshold:** do not fit a complex fixed effect for that
  complex. Instead, fall back to predicting from the district-level model
  and applying `complex_median_price_m2` (from `FEATURE_SPEC.md`, itself
  only computed when `complex_listing_count >= 5`) as a simple additive/
  multiplicative adjustment on top of the district-level prediction,
  rather than a fitted dummy coefficient. This mirrors the two-tier
  `min_n` structure already present in `FEATURE_SPEC.md`
  (`complex_median_price_m2` / `district_median_price_m2`, `min_n=5` each)
  — the OLS fixed-effect threshold (8-10) is deliberately set higher than
  the aggregate's `min_n` (5), since a fitted dummy coefficient demands
  more data to be reliable than a simple group median does.

## 5. Diagnostics checklist (before trusting the real, full-scale OLS)

Apply all of the following before treating `ols_residual_score` from the
full-dataset model as primary:

1. **Adjusted R-squared** — sanity-check overall explanatory power; not
   sufficient on its own, but a very low value (model barely explains
   variation in `ln_price_m2`) is disqualifying.
2. **Residual-vs-fitted plot** — check for heteroscedasticity (residual
   spread should not systematically widen/narrow with fitted value); if
   present, prefer the clustered/robust standard errors from section 6
   over the naive OLS SEs regardless.
3. **QQ plot of residuals** — check approximate normality; heavy tails or
   skew undermine residual-magnitude comparisons across listings.
4. **VIF (variance inflation factor)** for every continuous predictor —
   flag any predictor with **VIF > 10** as a multicollinearity risk.
   Specifically expected to be collinear with each other: `C(district)`
   dummies, `distance_to_center_km`, and (once available)
   `distance_to_nearest_station_m` — all three encode overlapping
   "where in the city" information, and `avg_price_m2_within_3km` also
   partially encodes location. **Decision rule:** when two predictors
   both exceed VIF > 10 and encode overlapping location information,
   drop the one with weaker standalone justification first
   (`distance_to_center_km` is the first candidate to drop, since
   `C(district)` and `avg_price_m2_within_3km` both carry more granular
   location signal) rather than dropping both blindly.
5. **Out-of-sample validation** — leave-one-complex-out or k-fold
   cross-validation on `ln_price_m2` prediction error, to check the model
   isn't just overfitting to in-sample complex/district combinations.

None of these diagnostics are computed for the sample-scale check in
section 3 — with ~15-20 rows they would not be meaningful (e.g. a VIF or
QQ plot on 15 points is not informative), which is exactly why section 3
is scoped as a code-path check, not a model-quality check.

## 6. Standard-error treatment (real, full-scale model)

Reuse the DiD scripts' clustering pattern rather than assuming i.i.d.
errors: nearby listings share unobserved neighborhood-level shocks (e.g. a
new metro announcement, a local development), so residuals are spatially
correlated.

- Cluster standard errors by `grid_cell_id` (the 500x500m spatial grid
  from `FEATURE_SPEC.md` section 3), matching
  `01_near_stations_final.py`'s exact pattern:
  `ols.get_robustcov_results(cov_type="cluster", groups=grid_groups,
  use_correction=True, df_correction=True, use_t=True)`.
- The sample-scale check (section 3) does **not** apply clustering — with
  only ~15-20 rows spread across up to 15-20 distinct grid cells, cluster
  count would be close to or equal to observation count, making clustered
  SEs meaningless at that scale. `ranking.py`'s `fit_price_model` still
  accepts an optional `cluster_col` parameter (unused when called from
  `--sample` mode) so the same function is ready for the full-scale run.

## 7. Combining the two approaches into one presentation

Per listing, show **all of the following side by side** — never silently
collapsed into a single number without the components visible:

| column | source |
|---|---|
| `percentile_rank_in_complex` | Approach A |
| `percentile_rank_in_district` | Approach A |
| `predicted_price_m2` (`exp(predicted ln_price_m2)`) | Approach B |
| `actual_price_m2` | data |
| `ols_residual_score` | Approach B |
| `good_deal_score` | composite, below |

**Composite score:** `good_deal_score` = average of two z-scored
components:

```
good_deal_score = mean(
    zscore(-percentile_rank_in_district),   # lower percentile -> higher (better) z
    zscore(-ols_residual_score)             # more negative residual -> higher (better) z
)
```

using `percentile_rank_in_complex` in place of `percentile_rank_in_district`
when `complex_name` is present and the complex has enough listings to make
the in-complex percentile meaningful (see section 8 fallback rule).
Higher `good_deal_score` = better deal.

`predicted_price_m2` / `ols_residual_score` are treated as the **primary**
signal only when the model's diagnostics (section 5) are healthy and the
sample size is adequate — i.e. only meaningful on the real full-dataset
fit, never on the section 3 sample-scale check. When the OLS model is not
yet trustworthy (as in this loop, and as will be true before the
full-dataset run happens), `good_deal_score` should be presented as
provisional / percentile-rank-dominated, with the OLS component labeled
low-confidence.

## 8. What would invalidate this

- **Overfitting risk from too many dummy variables relative to n**: the
  full formula in section 2 has one parameter per `district` level, one
  per `building_type` level, plus continuous controls — on a dataset with
  many small/rare districts or building types, some dummy levels may have
  very few observations even at full ~35k scale, producing unstable
  coefficients for those levels specifically (not just at sample scale).
  Check per-level observation counts before trusting any single dummy
  coefficient, not just the model's overall diagnostics.
- **`complex_name` coverage gap (~22-24% missing, per `FEATURE_SPEC.md`)**:
  `percentile_rank_in_complex` is undefined for standalone listings with
  no `complex_name`. For those rows, `good_deal_score` must fall back to
  `percentile_rank_in_district` only — never silently impute a
  complex-level rank, and never drop those rows from the output (they
  still get a valid district-based score).
- **Unresolved station/mall reference-data gap**: `distance_to_nearest_
  station_m` remains a TODO stub (`FEATURE_SPEC.md` section 3) until a new
  station-coordinate table is manually curated; until then the full-scale
  formula in section 2 must be fit without that term. Mall/park/embankment
  coordinates used for the 1km dummies are also unverified approximations
  — treat any resulting mall/park coefficient in the fitted model as
  provisional until those coordinates are checked against a maps service.
