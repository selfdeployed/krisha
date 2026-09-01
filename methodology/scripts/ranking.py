# -*- coding: utf-8 -*-
"""ranking.py -- "best deal" ranking per methodology/RANKING_METHODOLOGY.md.

Implements:
- Approach A: percentile_rank_within_group (naive baseline, per complex or
  district; ignores every feature difference -- see RANKING_METHODOLOGY.md
  section 1).
- Approach B: fit_price_model (OLS via statsmodels.formula.api.ols,
  optional clustered covariance matching 01_near_stations_final.py's
  pattern). --sample mode below runs this ONLY with the TRIMMED
  sample-scale formula from RANKING_METHODOLOGY.md section 3
  (ln_price_m2 ~ ln_area + avg_price_m2_within_3km_median) on ~15-20 rows.
  This is a PIPELINE-CORRECTNESS CHECK ONLY -- it proves the fit/residual/
  ranking code path runs end-to-end, NOT a trustworthy coefficient
  estimate or price model. The real full-formula model (section 2) only
  becomes meaningful once fit on the full ~35k-row dataset, which is
  explicitly out of scope for this run.
- compute_composite_score: z-scored average of (-percentile_rank) and
  (-ols_residual_score), per RANKING_METHODOLOGY.md section 7.

Usage:
    python ranking.py --sample
"""

import argparse
import os

import numpy as np
import pandas as pd
import statsmodels.formula.api as smf

# Reuse FEATURE_SPEC.md's min_n=5 group-aggregate threshold: below this,
# an in-complex percentile rank isn't meaningful (RANKING_METHODOLOGY.md
# section 7/8 fallback rule) -- fall back to the district-level percentile.
MIN_N_FOR_COMPLEX_PERCENTILE = 5


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


def compute_composite_score(df, percentile_col="percentile_rank_for_composite", residual_col="ols_residual_score", out_col="good_deal_score"):
    """good_deal_score = mean(zscore(-percentile_col), zscore(-residual_col)).

    Higher good_deal_score = better deal (RANKING_METHODOLOGY.md section 7):
    a lower percentile rank (cheaper in its group) and a more negative OLS
    residual (priced below what its features predict) both push the score
    up. Row-wise mean skips a component that's NaN for that row (e.g. a
    row the OLS fit dropped still gets a percentile-only score); a row
    with both components missing gets NaN.
    """
    df = df.copy()

    def _z(s):
        mu, sd = s.mean(), s.std(ddof=0)
        if not sd or pd.isna(sd):
            return pd.Series(0.0, index=s.index)
        return (s - mu) / sd

    z_pct = _z(-df[percentile_col])
    z_resid = _z(-df[residual_col])
    df[out_col] = pd.concat([z_pct, z_resid], axis=1).mean(axis=1, skipna=True)
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

    df = percentile_rank_within_group(df, "district", "price_m2", out_col="percentile_rank_in_district")
    df = percentile_rank_within_group(df, "complex_name", "price_m2", out_col="percentile_rank_in_complex")

    # Composite-score input per RANKING_METHODOLOGY.md section 7/8: use the
    # in-complex percentile only when complex_name is present AND the
    # complex clears the same min_n=5 threshold FEATURE_SPEC.md uses for
    # complex_median_price_m2; otherwise fall back to the district
    # percentile. Reported explicitly below rather than assumed, since
    # feature_scaffold_code's activity.md entry already noted every sample
    # complex has complex_listing_count=1 (16 rows across 8 complexes).
    complex_ok = df["complex_name"].notna() & (df["complex_listing_count"].fillna(0) >= MIN_N_FOR_COMPLEX_PERCENTILE)
    df["percentile_rank_for_composite"] = df["percentile_rank_in_district"]
    df.loc[complex_ok, "percentile_rank_for_composite"] = df.loc[complex_ok, "percentile_rank_in_complex"]
    n_complex_used = int(complex_ok.sum())

    formula = "ln_price_m2 ~ ln_area + avg_price_m2_within_3km_median"
    result, df = fit_price_model(df, formula)  # no cluster_col: sample-scale check, section 6

    df["predicted_price_m2"] = np.exp(df["predicted_ln_price_m2"])
    df["actual_price_m2"] = df["price_m2"]

    df = compute_composite_score(df)

    df.to_csv(out_path, index=False, encoding="utf-8")

    n_total = len(df)
    n_fitted = df["ols_residual_score"].notna().sum()

    print("=== SAMPLE-SCALE OLS FIT: PIPELINE-CORRECTNESS CHECK ONLY ===")
    print("n is ~15-20 rows and the formula is deliberately trimmed to 2")
    print("continuous predictors (RANKING_METHODOLOGY.md section 3) because")
    print("the full formula (section 2) is rank-deficient at this scale.")
    print("This proves the fit/residual/ranking code path works -- it is")
    print("NOT a trustworthy coefficient estimate or price model. The real")
    print("model only becomes meaningful on the full ~35k-row dataset,")
    print("explicitly out of scope for this run.")
    print(f"formula: {formula}")
    print(f"n used in fit (non-missing ln_price_m2 & avg_price_m2_within_3km_median): {n_fitted}/{n_total}")
    print(f"R-squared: {result.rsquared:.4f}  Adj R-squared: {result.rsquared_adj:.4f}")
    print("coefficients:")
    print(result.params.to_string())
    print(f"in-complex percentile used for composite (complex_listing_count >= {MIN_N_FOR_COMPLEX_PERCENTILE}): {n_complex_used}/{n_total} rows")
    print(f"wrote {n_total} ranked rows to {out_path}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--sample", action="store_true")
    args = parser.parse_args()

    if not args.sample:
        parser.print_help()
        return

    run_sample()


if __name__ == "__main__":
    main()
