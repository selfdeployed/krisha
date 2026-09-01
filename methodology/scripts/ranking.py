# -*- coding: utf-8 -*-
"""ranking.py -- "best deal" ranking per methodology/RANKING_METHODOLOGY.md.

Implements:
- compute_spatial_relative_price: the PRIMARY signal
  (RANKING_METHODOLOGY.md section 1) -- a listing's price/m2 relative to
  the average price/m2 of every OTHER listing within 3km, regardless of
  complex or district membership. Needs no per-complex or per-district
  sample size at all, only enough nearby listings
  (n_neighbors_3km >= MIN_NEIGHBORS_FOR_SPATIAL).
- percentile_rank_within_group: CONTEXT-ONLY signal (section 2) -- naive
  in-complex / in-district percentile, shown for reference, never fed
  into good_deal_score.
- fit_price_model: SECONDARY signal (section 3) -- OLS via
  statsmodels.formula.api.ols, optional clustered covariance matching
  01_near_stations_final.py's pattern. --sample mode below runs this ONLY
  with the TRIMMED sample-scale formula from RANKING_METHODOLOGY.md
  section 4 (ln_price_m2 ~ ln_area + avg_price_m2_within_3km_median) on
  ~15-20 rows. This is a PIPELINE-CORRECTNESS CHECK ONLY -- it proves the
  fit/residual/ranking code path runs end-to-end, NOT a trustworthy
  coefficient estimate or price model. The real full-formula model
  (section 3) only becomes meaningful once fit on the full ~35k-row
  dataset, which is explicitly out of scope for this run.
- compute_composite_score: z-scored average of
  (-spatial_price_pct_vs_avg) and (-ols_residual_score), per
  RANKING_METHODOLOGY.md section 8. percentile ranks are NOT an input.

Usage:
    python ranking.py --sample
    python ranking.py --full
"""

import argparse
import os

import numpy as np
import pandas as pd
import statsmodels.formula.api as smf
from statsmodels.stats.outliers_influence import variance_inflation_factor
from statsmodels.tools.tools import add_constant

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
FULL_RUN_DIR = os.path.join(REPO_ROOT, "methodology", "full_run")

# Full-formula OLS (RANKING_METHODOLOGY.md section 3), minus the
# distance_to_nearest_station_m term (dropped per user instruction -- no
# LRT-distance feature wanted, and the reference table is a TODO stub
# anyway). This is a DIAGNOSTIC pass only (R2, coefficients, VIF) -- its
# residuals are NOT merged into good_deal_score yet (section 8 / this
# file's --full mode keeps ols_residual_score as NaN in the ranked
# output), pending a decision on which features to keep after seeing
# real VIF numbers.
FULL_FORMULA = (
    "ln_price_m2 ~ ln_area + building_age + floor_is_first + floor_is_last "
    "+ ceiling_height_m + former_dormitory + exchange_possible "
    "+ C(building_type) + C(district) + distance_to_center_km "
    "+ avg_price_m2_within_3km_median"
)

# Continuous predictors from FULL_FORMULA, for the VIF pre-check
# (RANKING_METHODOLOGY.md section 6 / EDA_PLAN.md section 6) -- run
# separately from the dummy-heavy full design matrix, since VIF is only
# meaningful/requested for continuous predictors.
VIF_CONTINUOUS_COLS = [
    "ln_area", "building_age", "ceiling_height_m",
    "distance_to_center_km", "avg_price_m2_within_3km_median",
]

# RANKING_METHODOLOGY.md section 1: a listing's 3km neighborhood average
# is only trustworthy with at least this many other listings nearby.
MIN_NEIGHBORS_FOR_SPATIAL = 3

# Context-only (section 2): reuse FEATURE_SPEC.md's min_n=5 threshold so
# a lone-listing "complex" doesn't silently look like a 0th-percentile
# "cheapest in complex" -- not used by the composite score.
MIN_N_FOR_COMPLEX_PERCENTILE = 5


def compute_spatial_relative_price(
    df,
    price_col="price_m2",
    avg_col="avg_price_m2_within_3km_median",
    n_neighbors_col="n_neighbors_3km",
    min_neighbors=MIN_NEIGHBORS_FOR_SPATIAL,
    suffix="",
):
    """PRIMARY ranking signal (RANKING_METHODOLOGY.md section 1).

    Adds (column names get `suffix` appended, e.g. "_1km", so the 1km
    toggle variant can live alongside the unsuffixed 3km primary without
    collisions):
    - spatial_price_ratio{suffix} = price_col / avg_col (1.0 = at the
      neighborhood average; <1 = cheaper than its neighbors).
    - spatial_price_pct_vs_avg{suffix} = spatial_price_ratio - 1 (e.g.
      -0.15 = 15% below its neighborhood's average price/m2). More
      negative = better deal. The unsuffixed (3km) column is the primary
      composite-score input.
    - spatial_rank_reliable{suffix} = n_neighbors_col >= min_neighbors.
      Requires no per-complex or per-district sample size -- only that
      the listing's own radius circle contains enough OTHER listings
      (from any complex) to make the neighborhood average itself
      trustworthy.
    """
    df = df.copy()
    ratio = df[price_col] / df[avg_col]
    df[f"spatial_price_ratio{suffix}"] = ratio
    df[f"spatial_price_pct_vs_avg{suffix}"] = ratio - 1
    df[f"spatial_rank_reliable{suffix}"] = df[n_neighbors_col].fillna(0) >= min_neighbors
    return df


def percentile_rank_within_group(df, group_col, value_col, out_col=None):
    """Ascending percentile rank of value_col within group_col groups.

    0 = cheapest in its group, 1 = most expensive. A lone-member group
    gets 0.0 (no relative position to express -- it is both the cheapest
    and only listing). Rows with a missing group_col or value_col get NaN.
    """
    out_col = out_col or f"percentile_rank_in_{group_col}"
    df = df.copy()

    def _pct(s):
        n = s.notna().sum()
        if n <= 1:
            return pd.Series([0.0 if pd.notna(v) else np.nan for v in s], index=s.index)
        ranks = s.rank(method="min", ascending=True)
        return (ranks - 1) / (n - 1)

    valid_mask = df[group_col].notna() & df[value_col].notna()
    result = pd.Series(np.nan, index=df.index)
    for _, group_df in df[valid_mask].groupby(group_col):
        result.loc[group_df.index] = _pct(group_df[value_col]).values
    df[out_col] = result
    return df


def fit_price_model(df, formula, cluster_col=None):
    """Fit an OLS price model via statsmodels.formula.api.ols.

    Returns (result, df_with_predictions): df_with_predictions is a copy
    of df with `predicted_ln_price_m2` and `ols_residual_score` columns
    added, aligned back by index (NaN for rows the formula's own listwise
    deletion dropped for a missing target/predictor).

    If cluster_col is given, refits the covariance via
    result.get_robustcov_results(cov_type="cluster", groups=...,
    use_correction=True, df_correction=True, use_t=True), matching
    01_near_stations_final.py's exact pattern (RANKING_METHODOLOGY.md
    section 6). Not exercised by --sample mode below -- see that
    section's note on why clustering is meaningless at ~15-20 rows.
    """
    model = smf.ols(formula, data=df)
    result = model.fit()
    fitted_index = model.data.row_labels

    if cluster_col:
        groups = df.loc[fitted_index, cluster_col]
        result = result.get_robustcov_results(
            cov_type="cluster", groups=groups, use_correction=True, df_correction=True, use_t=True
        )

    df = df.copy()
    df.loc[fitted_index, "predicted_ln_price_m2"] = result.fittedvalues
    df.loc[fitted_index, "ols_residual_score"] = result.resid
    return result, df


def compute_composite_score(df, spatial_col="spatial_price_pct_vs_avg", residual_col="ols_residual_score", out_col="good_deal_score"):
    """good_deal_score = mean(zscore(-spatial_col), zscore(-residual_col)).

    Higher good_deal_score = better deal (RANKING_METHODOLOGY.md section
    8): a more negative spatial_price_pct_vs_avg (cheaper than its 3km
    neighborhood) and a more negative OLS residual (priced below what its
    features predict) both push the score up. Row-wise mean skips a
    component that's NaN for that row (e.g. a row the OLS fit dropped
    still gets a spatial-only score); a row with both components missing
    gets NaN. percentile_rank_in_complex/_in_district are NOT inputs here
    -- they are context-only (section 2).
    """
    df = df.copy()

    def _z(s):
        mu, sd = s.mean(), s.std(ddof=0)
        if not sd or pd.isna(sd):
            return pd.Series(0.0, index=s.index)
        return (s - mu) / sd

    z_spatial = _z(-df[spatial_col])
    z_resid = _z(-df[residual_col])
    df[out_col] = pd.concat([z_spatial, z_resid], axis=1).mean(axis=1, skipna=True)
    return df


# ---------------------------------------------------------------------------
# --sample: real run against methodology/samples/sample_features.csv
# ---------------------------------------------------------------------------

def run_sample():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    samples_dir = os.path.join(os.path.dirname(script_dir), "samples")
    features_path = os.path.join(samples_dir, "sample_features.csv")
    out_path = os.path.join(samples_dir, "sample_ranked_preview.csv")

    df = pd.read_csv(features_path, encoding="utf-8")

    # price_m2 / ln_price_m2 are already computed by feature_engineering.py
    # --sample; compute defensively only if a future caller feeds a
    # features file that lacks them.
    if "price_m2" not in df.columns:
        df["price_m2"] = df["price_tenge"] / df["area_total_m2"]
    if "ln_price_m2" not in df.columns:
        df["ln_price_m2"] = df["price_m2"].apply(lambda v: np.log(v) if pd.notna(v) and v > 0 else np.nan)

    # PRIMARY signal (RANKING_METHODOLOGY.md section 1): needs no
    # per-complex or per-district sample size, only nearby listings.
    df = compute_spatial_relative_price(df)
    n_reliable_spatial = int(df["spatial_rank_reliable"].sum())

    # CONTEXT-ONLY signals (section 2): shown for reference, never fed
    # into good_deal_score. Reported explicitly below since
    # feature_scaffold_code's activity.md entry already noted every
    # sample complex has complex_listing_count=1 (16 rows across 8
    # complexes) -- percentile_rank_in_complex is uninformative here, but
    # that no longer affects the primary ranking at all.
    df = percentile_rank_within_group(df, "district", "price_m2", out_col="percentile_rank_in_district")
    df = percentile_rank_within_group(df, "complex_name", "price_m2", out_col="percentile_rank_in_complex")
    n_complex_reliable = int((df["complex_name"].notna() & (df["complex_listing_count"].fillna(0) >= MIN_N_FOR_COMPLEX_PERCENTILE)).sum())

    formula = "ln_price_m2 ~ ln_area + avg_price_m2_within_3km_median"
    result, df = fit_price_model(df, formula)  # no cluster_col: sample-scale check, section 6

    df["predicted_price_m2"] = np.exp(df["predicted_ln_price_m2"])
    df["actual_price_m2"] = df["price_m2"]

    df = compute_composite_score(df)

    df.to_csv(out_path, index=False, encoding="utf-8")

    n_total = len(df)
    n_fitted = df["ols_residual_score"].notna().sum()

    print("=== PRIMARY: 3km-radius spatial relative price ===")
    print("spatial_price_pct_vs_avg = price_m2 / avg_price_m2_within_3km_median - 1")
    print(f"rows with a reliable (n_neighbors_3km >= {MIN_NEIGHBORS_FOR_SPATIAL}) neighborhood avg: {n_reliable_spatial}/{n_total}")
    print("this needs no per-complex or per-district sample size -- unaffected")
    print("by every sample complex currently having complex_listing_count=1.")
    print()
    print("=== CONTEXT ONLY: in-complex / in-district percentile (not in composite) ===")
    print(f"rows with a complex_listing_count >= {MIN_N_FOR_COMPLEX_PERCENTILE} (in-complex percentile meaningful): {n_complex_reliable}/{n_total}")
    print()
    print("=== SECONDARY: SAMPLE-SCALE OLS FIT -- PIPELINE-CORRECTNESS CHECK ONLY ===")
    print("n is ~15-20 rows and the formula is deliberately trimmed to 2")
    print("continuous predictors (RANKING_METHODOLOGY.md section 4) because")
    print("the full formula (section 3) is rank-deficient at this scale.")
    print("This proves the fit/residual/ranking code path works -- it is")
    print("NOT a trustworthy coefficient estimate or price model. The real")
    print("model only becomes meaningful on the full ~35k-row dataset,")
    print("explicitly out of scope for this run.")
    print(f"formula: {formula}")
    print(f"n used in fit (non-missing ln_price_m2 & avg_price_m2_within_3km_median): {n_fitted}/{n_total}")
    print(f"R-squared: {result.rsquared:.4f}  Adj R-squared: {result.rsquared_adj:.4f}")
    print("coefficients:")
    print(result.params.to_string())
    print()
    print(f"wrote {n_total} ranked rows to {out_path}")


def compute_vif(df, cols):
    """VIF per continuous predictor (RANKING_METHODOLOGY.md section 6).

    Complete-case on `cols` (VIF is undefined with missing data), constant
    added (matches variance_inflation_factor's expectation that column 0
    is the intercept -- excluded from the returned per-predictor VIFs).
    """
    sub = df[cols].dropna()
    X = add_constant(sub, has_constant="add")
    vifs = {}
    for i, col in enumerate(cols, start=1):  # skip index 0 = const
        vifs[col] = variance_inflation_factor(X.values, i)
    return vifs, len(sub)


# ---------------------------------------------------------------------------
# --full: real run against methodology/full_run/features_full.csv
# ---------------------------------------------------------------------------

def run_full():
    features_path = os.path.join(FULL_RUN_DIR, "features_full.csv")
    out_path = os.path.join(FULL_RUN_DIR, "ranked_full.csv")

    df = pd.read_csv(features_path, encoding="utf-8")
    n_total = len(df)

    if "price_m2" not in df.columns:
        df["price_m2"] = df["price_tenge"] / df["area_total_m2"]
    if "ln_price_m2" not in df.columns:
        df["ln_price_m2"] = df["price_m2"].apply(lambda v: np.log(v) if pd.notna(v) and v > 0 else np.nan)

    # PRIMARY signal -- always computed, unconditionally, regardless of
    # OLS diagnostics below (RANKING_METHODOLOGY.md section 1).
    df = compute_spatial_relative_price(df)
    n_reliable_spatial = int(df["spatial_rank_reliable"].sum())

    # UI TOGGLE variant: same signal computed against the 1km neighborhood
    # instead of 3km (map lets the user flip between the two radii). Not
    # used in good_deal_score -- the 3km version stays primary per
    # RANKING_METHODOLOGY.md section 1.
    df = compute_spatial_relative_price(
        df,
        avg_col="avg_price_m2_within_1km_median",
        n_neighbors_col="n_neighbors_1km",
        suffix="_1km",
    )
    n_reliable_spatial_1km = int(df["spatial_rank_reliable_1km"].sum())

    # CONTEXT-ONLY signals (section 2) -- shown for reference, never fed
    # into good_deal_score.
    df = percentile_rank_within_group(df, "district", "price_m2", out_col="percentile_rank_in_district")
    df = percentile_rank_within_group(df, "complex_name", "price_m2", out_col="percentile_rank_in_complex")
    n_complex_reliable = int((df["complex_name"].notna() & (df["complex_listing_count"].fillna(0) >= MIN_N_FOR_COMPLEX_PERCENTILE)).sum())

    # SECONDARY: diagnostic-only full-formula OLS, clustered SEs by
    # grid_cell_id (section 7) -- used here for the first time. Fit on a
    # SEPARATE copy; its residuals are deliberately NOT merged back into
    # the main `df`, so good_deal_score below is computed from the
    # spatial signal alone (per user instruction: decide what to do with
    # the OLS as a separate next step, after seeing these diagnostics).
    result, _diag_df = fit_price_model(df.copy(), FULL_FORMULA, cluster_col="grid_cell_id")
    n_fitted = int(result.nobs)
    fitted_mask = _diag_df["ols_residual_score"].notna()
    n_clusters = int(df.loc[fitted_mask, "grid_cell_id"].nunique())
    vif_values, n_vif = compute_vif(df, VIF_CONTINUOUS_COLS)

    # get_robustcov_results(cov_type="cluster") returns .params/.pvalues as
    # plain numpy arrays (unlike the un-clustered Series from --sample) --
    # re-wrap with the exog names so the report is readable.
    param_names = result.model.exog_names
    params_s = pd.Series(np.asarray(result.params), index=param_names)
    pvalues_s = pd.Series(np.asarray(result.pvalues), index=param_names)

    # good_deal_score from the spatial signal ALONE for now -- put NaN in
    # ols_residual_score so compute_composite_score's skipna mean falls
    # back to the spatial-only score for every row (matches --sample's
    # column contract so downstream consumers see the same columns).
    df["ols_residual_score"] = np.nan
    df["predicted_ln_price_m2"] = np.nan
    df["predicted_price_m2"] = np.nan
    df["actual_price_m2"] = df["price_m2"]

    df = compute_composite_score(df)
    df.to_csv(out_path, index=False, encoding="utf-8")

    lines = []
    lines.append("ranking.py --full")
    lines.append(f"input: {features_path}")
    lines.append(f"output: {out_path}")
    lines.append(f"total rows: {n_total}")
    lines.append("")
    lines.append("=== PRIMARY: 3km-radius spatial relative price (drives good_deal_score) ===")
    lines.append(f"rows with a reliable (n_neighbors_3km >= {MIN_NEIGHBORS_FOR_SPATIAL}) neighborhood avg: {n_reliable_spatial}/{n_total} ({n_reliable_spatial/n_total:.1%})")
    lines.append("")
    lines.append("=== UI TOGGLE: 1km-radius spatial relative price (not in composite) ===")
    lines.append(f"rows with a reliable (n_neighbors_1km >= {MIN_NEIGHBORS_FOR_SPATIAL}) neighborhood avg: {n_reliable_spatial_1km}/{n_total} ({n_reliable_spatial_1km/n_total:.1%})")
    lines.append("")
    lines.append("=== CONTEXT ONLY: in-complex / in-district percentile (not in composite) ===")
    lines.append(f"rows with complex_listing_count >= {MIN_N_FOR_COMPLEX_PERCENTILE} (in-complex percentile meaningful): {n_complex_reliable}/{n_total} ({n_complex_reliable/n_total:.1%})")
    lines.append("")
    lines.append("=== SECONDARY: DIAGNOSTIC full-formula OLS (clustered SE by grid_cell_id) ===")
    lines.append("NOT merged into good_deal_score yet -- diagnostic pass only, pending a")
    lines.append("decision on which features to keep after seeing VIF below.")
    lines.append(f"formula: {FULL_FORMULA}")
    lines.append(f"n used in fit (complete-case across formula vars): {n_fitted}/{n_total} ({n_fitted/n_total:.1%})")
    lines.append(f"n clusters (grid_cell_id): {n_clusters}")
    lines.append(f"R-squared: {result.rsquared:.4f}  Adj R-squared: {result.rsquared_adj:.4f}")
    lines.append("coefficients (clustered SE):")
    lines.append(params_s.to_string())
    lines.append("")
    lines.append("p-values (clustered SE):")
    lines.append(pvalues_s.to_string())
    lines.append("")
    lines.append(f"VIF, continuous predictors only (complete-case n={n_vif}):")
    for col, v in vif_values.items():
        flag = "  <-- VIF > 10, multicollinearity risk (section 6 decision rule)" if v > 10 else ""
        lines.append(f"  {col}: {v:.2f}{flag}")

    report_path = os.path.join(FULL_RUN_DIR, "ranking_full_report.txt")
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    print(f"wrote {n_total} ranked rows to {out_path}")
    print(f"spatial signal reliable: {n_reliable_spatial}/{n_total}")
    print(f"OLS diagnostic n={n_fitted}/{n_total}, R2={result.rsquared:.4f}")
    print("VIF (continuous predictors):", {k: round(v, 2) for k, v in vif_values.items()})
    print(f"full report: {report_path}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--sample", action="store_true")
    parser.add_argument("--full", action="store_true")
    args = parser.parse_args()

    if not args.sample and not args.full:
        parser.print_help()
        return

    if args.sample:
        run_sample()
    if args.full:
        run_full()


if __name__ == "__main__":
    main()
