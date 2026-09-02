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
- fit_hier_model: SECONDARY signal (map 'residual' mode) -- a hedonic
  model whose location control is a nested set of leave-one-out,
  empirical-Bayes-shrunken intercepts (district > 500m grid cell >
  complex > building) plus a 100m kernel mop-up, on top of a spline-in-
  area attribute model. See the HIER_* constants below for why this
  replaced the plain OLS with C(district): with only 6 districts as the
  location control, the OLS residual was 0.89-0.93 correlated with the
  spatial signal (location leaked into it), so the map's residual mode
  just mirrored the spatial mode. The hierarchical model drops that to
  ~0.46 while raising CV R^2 from 0.42 to 0.78 and coverage from 76% to
  ~100%.
- fit_price_model: plain OLS, kept ONLY for --sample mode's trimmed
  pipeline-correctness check (RANKING_METHODOLOGY.md section 4) on
  ~15-20 rows -- NOT a trustworthy price model.
- compute_composite_score: robust-z average of (-spatial_price_pct_vs_avg)
  and (-residual_pct), each restricted to rows where that signal is
  reliable. percentile ranks are NOT an input.

Usage:
    python ranking.py --sample
    python ranking.py --full
"""

import argparse
import os
import time

import numpy as np
import pandas as pd
import patsy
import scipy.sparse as sp
import statsmodels.api as sm
import statsmodels.formula.api as smf
from sklearn.neighbors import BallTree

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
FULL_RUN_DIR = os.path.join(REPO_ROOT, "methodology", "full_run")

EARTH_RADIUS_KM = 6371.0088

# ---------------------------------------------------------------------------
# Hierarchical hedonic model (map 'residual' mode)
# ---------------------------------------------------------------------------
#
# Attribute side: everything about the flat itself, NOTHING about where it
# is (no district, no distance-to-center, no lat/lon) -- location is
# handled entirely by the nested LOO intercepts below, so "residual" =
# "priced below what comparable flats at this address go for". ln_area
# gets a 5-df B-spline: a linear ln_area term was mis-specified and let
# big 4+ room flats dominate the deal list. Missing continuous inputs are
# median-imputed with a *_miss indicator instead of dropping the row
# (listwise deletion was the reason coverage was only 76%).
HIER_ATTR_FORMULA = (
    "bs(ln_area, df=5) + building_age + ceiling_height_m + ceiling_miss "
    "+ floor_is_first + floor_is_last + former_dormitory + exchange_possible "
    "+ is_under_construction + price_is_installment + floor_rel + floor_miss "
    "+ C(building_type) + C(apartment_condition) + C(rooms_bucket)"
)

# Nested location levels, coarse -> fine, and the empirical-Bayes
# shrinkage constant lambda per level. A group's LOO effect is
# sum(other members' deviations) / (n_others + lambda): a group with 0
# other members contributes 0 (the coarser levels + kernel carry it), 1
# other member gets weight 1/(1+lambda). No hard MIN_N cliff. REML on a
# 6k-row MixedLM subsample gave lambda_complex~1.1, lambda_grid~0.3; the
# values here are deliberately on the more-shrinkage side, which is what
# a deal ranker wants (a single cheap twin should not make a flat look
# fairly priced). `building` = complex + floor_total + build_year (or a
# ~11m lat/lon cell + floor_total + build_year for standalone buildings):
# complex_name alone lumps physically different phases of one complex
# (e.g. a 2014 7-floor block at 600k/m2 with a 2024 tower at 1-2.8M/m2).
HIER_LEVELS = ("district", "grid_cell_id", "complex_name", "building")
HIER_LAMBDA = (2.0, 1.0, 2.0, 2.0)

# Residual-surface mop-up after the named levels: LOO Gaussian kernel,
# h=100m (cutoff 500m), shrunk by sum_w/(sum_w+HIER_KERNEL_LAMBDA). Wider
# bandwidths (>=250m) were measured to hurt fit AND re-couple the
# residual with the spatial signal -- price variation in Astana lives at
# building/complex scale, not neighborhood scale.
HIER_KERNEL_H_KM = 0.1
HIER_KERNEL_CUTOFF_KM = 0.5
HIER_KERNEL_LAMBDA = 3.0
HIER_BACKFIT_ITERS = 6

# Fit-sample filters (rows failing these still get spatial signals and
# stay on the map, but get no residual): obvious data errors that would
# otherwise anchor a building's price level.
FIT_BBOX_LAT = (50.95, 51.30)
FIT_BBOX_LON = (71.15, 71.75)
FIT_AREA_M2 = (15, 400)
FIT_PRICE_M2 = (150_000, 3_000_000)

# residual_reliable: enough comparables at SOME level for the LOO
# location estimate to be trustworthy. Measured OOF residual sd by
# bucket: building n>=2 ~0.12-0.14, complex n>=3 ~0.15, kernel eff_n>=10
# ~0.16-0.18, vs 0.275 (and biased -0.1) for rows with <5 kernel
# comparables and no group -- those must never be shown as deals.
RELIABLE_BUILDING_N = 2
RELIABLE_COMPLEX_N = 3
RELIABLE_KERNEL_EFF_N = 10

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


def apply_fit_filters(df):
    """Flag rows eligible for the hierarchical fit.

    Adds fit_ok (bool) and fit_excl_reason (first failing rule, "" if
    none). Excluded rows keep their spatial signals; they just get no
    residual (and never anchor anyone else's location level).
    """
    df = df.copy()
    reason = pd.Series("", index=df.index)

    def _flag(mask, name):
        m = mask.fillna(False) & (reason == "")
        reason.loc[m] = name

    _flag(df["ln_price_m2"].isna(), "no_price")
    _flag(df["lat"].isna() | df["lon"].isna(), "no_latlon")
    _flag(~df["lat"].between(*FIT_BBOX_LAT) | ~df["lon"].between(*FIT_BBOX_LON), "latlon_outside_astana")
    _flag(df["area_total_m2"] < FIT_AREA_M2[0], "area_lt_15")
    _flag(df["area_total_m2"] > FIT_AREA_M2[1], "area_gt_400")
    _flag(df["price_m2"] < FIT_PRICE_M2[0], "price_m2_lt_150k")
    _flag(df["price_m2"] > FIT_PRICE_M2[1], "price_m2_gt_3M")
    df["fit_excl_reason"] = reason
    df["fit_ok"] = reason == ""
    return df


def build_hedonic_features(df):
    """Attribute-only design inputs for HIER_ATTR_FORMULA (no location).

    Continuous inputs: clipped to a sane range, median-imputed, with a
    *_miss indicator where missingness is common enough to matter.
    Booleans arrive as object columns (True/False/NaN) -> int, NaN=0.
    """
    X = pd.DataFrame(index=df.index)
    # Clipped to the fit-sample area range so the spline's boundary knots
    # come from real flats, and NaN-filled so patsy keeps every row
    # aligned (rows without an area are outside the fit sample anyway).
    ln_area = df["ln_area"].clip(np.log(FIT_AREA_M2[0]), np.log(FIT_AREA_M2[1]))
    X["ln_area"] = ln_area.fillna(ln_area.median())
    age = df["building_age"].clip(upper=80)
    X["building_age"] = age.fillna(age.median())
    ceil = df["ceiling_height_m"].where(df["ceiling_height_m"].between(2.2, 4.5))
    X["ceiling_miss"] = ceil.isna().astype(int)
    X["ceiling_height_m"] = ceil.fillna(ceil.median())
    for col in ["floor_is_first", "floor_is_last", "former_dormitory", "exchange_possible",
                "is_under_construction", "price_is_installment"]:
        X[col] = (df[col].astype(object) == True).astype(int)  # noqa: E712 -- NaN-safe truthiness
    X["floor_miss"] = df["floor"].isna().astype(int)
    floor_rel = (df["floor"] / df["floor_total"]).where(df["floor_total"] > 0)
    X["floor_rel"] = floor_rel.fillna(0.5)
    X["building_type"] = df["building_type"].fillna("unknown")
    X["apartment_condition"] = df["apartment_condition"].fillna("unknown")
    X["rooms_bucket"] = df["rooms_bucket_estimated"].fillna("unknown")
    return X


def building_key(df):
    """Finest location level: one physical building (see HIER_LEVELS note)."""
    floors = df["floor_total"].fillna(-1).astype(int).astype(str)
    year = df["build_year"].fillna(-1).astype(int).astype(str)
    latlon = df["lat"].round(4).astype(str) + "," + df["lon"].round(4).astype(str)
    return pd.Series(np.where(
        df["complex_name"].notna(),
        "cx:" + df["complex_name"].astype(str) + "|" + floors + "|" + year,
        "ll:" + latlon + "|" + floors + "|" + year,
    ), index=df.index)


def eb_loo_group_effect(groups, values, lam):
    """Leave-one-out empirical-Bayes group mean of `values` (NaN = not in fit).

    For row i in group g: sum(values of OTHER fitted members of g) /
    (n_others + lam). Rows with a missing group key, or whose group has no
    other fitted member, get 0. Returns (effect, n_others).
    """
    groups = pd.Series(groups).reset_index(drop=True)
    vals = np.asarray(values, dtype=float)
    fitted = ~np.isnan(vals)
    agg = pd.DataFrame({"g": groups, "v": vals}).dropna().groupby("g")["v"].agg(["sum", "count"])
    total = groups.map(agg["sum"]).fillna(0.0).to_numpy()
    count = groups.map(agg["count"]).fillna(0).to_numpy()
    total_loo = total - np.where(fitted, vals, 0.0)
    n_others = count - fitted.astype(int)
    with np.errstate(divide="ignore", invalid="ignore"):
        effect = np.where(n_others + lam > 0, total_loo / (n_others + lam), 0.0)
    effect = np.where(groups.isna().to_numpy(), 0.0, effect)
    return effect, n_others


def kernel_weight_matrix(coords_rad, h_km, cutoff_km):
    """Sparse n x n Gaussian kernel weights on haversine distance, zero diagonal (LOO)."""
    tree = BallTree(coords_rad, metric="haversine")
    ind, dist = tree.query_radius(coords_rad, r=cutoff_km / EARTH_RADIUS_KM, return_distance=True)
    rows = np.repeat(np.arange(len(coords_rad)), [len(i) for i in ind])
    cols = np.concatenate(ind)
    d_km = np.concatenate(dist) * EARTH_RADIUS_KM
    off_diag = rows != cols
    w = np.exp(-0.5 * (d_km[off_diag] / h_km) ** 2)
    return sp.csr_matrix((w, (rows[off_diag], cols[off_diag])), shape=(len(coords_rad), len(coords_rad)))


def sparse_loo_smooth(W, values):
    """LOO kernel-weighted mean of values (NaN ignored). Returns (smooth, eff_n, sum_w)."""
    ok = ~np.isnan(values)
    v = np.where(ok, values, 0.0)
    W_ok = W.multiply(ok[None, :]).tocsr()
    sum_w = np.asarray(W_ok.sum(axis=1)).ravel()
    sum_w2 = np.asarray(W_ok.multiply(W_ok).sum(axis=1)).ravel()
    num = W_ok @ v
    with np.errstate(invalid="ignore", divide="ignore"):
        smooth = np.where(sum_w > 1e-12, num / sum_w, 0.0)
        eff_n = np.where(sum_w2 > 0, sum_w ** 2 / sum_w2, 0.0)
    return smooth, eff_n, sum_w


def fit_hier_model(df):
    """Hierarchical hedonic model -> per-row residual columns (see module docstring).

    Backfit: alternate an OLS of (y - loc) on the attribute design with a
    re-estimate of loc = sum over HIER_LEVELS of LOO-EB group effects of
    the current attribute residual, plus the shrunk LOO kernel term. Every
    location term is leave-one-out, so a listing's own price never enters
    its own prediction and the in-sample residual is honest (measured
    corr 0.99 with true out-of-fold residuals).

    Adds to a copy of df: fit_ok, fit_excl_reason, predicted_ln_price_m2,
    predicted_price_m2, hier_residual_ln, residual_pct, residual_reliable,
    residual_n_eff, residual_z, building_n_others, complex_n_others,
    kernel_eff_n. Returns (df, info) where info carries the fitted
    coefficients (statsmodels OLS on the final iteration, clustered by
    grid_cell_id) and run diagnostics for the report.
    """
    df = apply_fit_filters(df)
    fit = df["fit_ok"].to_numpy()
    n = len(df)
    n_fit = int(fit.sum())

    X = build_hedonic_features(df)
    # A categorical level that only occurs OUTSIDE the fit sample (e.g.
    # rooms_bucket "unknown" = rows with no area at all) would be an
    # all-zero design column -> rank-deficient OLS. Fold such levels into
    # the fit-sample mode; the affected rows get no residual anyway.
    for col in ["building_type", "apartment_condition", "rooms_bucket"]:
        seen = set(X.loc[fit, col].unique())
        mode = X.loc[fit, col].mode().iloc[0]
        X[col] = X[col].where(X[col].isin(seen), mode)
    # NA_action="raise": every input is imputed above, so a NaN here is a
    # bug -- silently dropping the row would misalign A with df.
    design = patsy.dmatrix(HIER_ATTR_FORMULA, X, return_type="dataframe", NA_action="raise")
    A = design.to_numpy()
    y = df["ln_price_m2"].to_numpy(dtype=float)
    y_fit = np.where(fit, y, np.nan)

    level_keys = {
        "district": df["district"],
        "grid_cell_id": df["grid_cell_id"],
        "complex_name": df["complex_name"],
        "building": building_key(df),
    }
    # Kernel matrix over fit rows only (rows outside the fit have no or
    # bogus coordinates); mapped back to full-length arrays below.
    fit_idx = np.flatnonzero(fit)
    t0 = time.time()
    coords_rad = np.radians(df.loc[fit, ["lat", "lon"]].to_numpy(dtype=float))
    W = kernel_weight_matrix(coords_rad, HIER_KERNEL_H_KM, HIER_KERNEL_CUTOFF_KM)
    kernel_build_s = time.time() - t0

    loc = np.zeros(n)
    beta = None
    level_info = {}
    for _ in range(HIER_BACKFIT_ITERS):
        beta, *_ = np.linalg.lstsq(A[fit], (y - loc)[fit], rcond=None)
        attr = A @ beta
        r = y_fit - attr
        loc = np.zeros(n)
        level_info = {}
        for level, lam in zip(HIER_LEVELS, HIER_LAMBDA):
            effect, n_others = eb_loo_group_effect(level_keys[level], r - loc, lam)
            loc = loc + effect
            level_info[level] = (effect, n_others)
        smooth, eff_n, sum_w = sparse_loo_smooth(W, (r - loc)[fit_idx])
        kernel = np.zeros(n)
        kernel[fit_idx] = smooth * (sum_w / (sum_w + HIER_KERNEL_LAMBDA))
        loc = loc + kernel
        kernel_eff_n = np.zeros(n)
        kernel_eff_n[fit_idx] = eff_n

    predicted_ln = attr + loc
    resid = np.where(fit, y - predicted_ln, np.nan)

    has_complex = df["complex_name"].notna().to_numpy()
    building_n = np.where(fit, level_info["building"][1], 0)
    complex_n = np.where(fit & has_complex, level_info["complex_name"][1], 0)
    reliable = fit & (
        (building_n >= RELIABLE_BUILDING_N)
        | (complex_n >= RELIABLE_COMPLEX_N)
        | (kernel_eff_n >= RELIABLE_KERNEL_EFF_N)
    )
    n_eff = building_n + 0.5 * complex_n + 0.5 * kernel_eff_n
    sigma = float(np.nanstd(resid[reliable]))
    se = sigma * np.sqrt(1 + 1 / np.maximum(n_eff, 1))
    z = resid / se

    df["predicted_ln_price_m2"] = np.where(fit, predicted_ln, np.nan)
    df["predicted_price_m2"] = np.exp(df["predicted_ln_price_m2"])
    df["hier_residual_ln"] = resid
    df["residual_pct"] = np.exp(resid) - 1
    df["residual_reliable"] = reliable
    df["residual_n_eff"] = np.where(fit, n_eff, np.nan)
    df["residual_z"] = z
    df["building_n_others"] = building_n
    df["complex_n_others"] = complex_n
    df["kernel_eff_n"] = np.round(kernel_eff_n, 2)

    # Coefficient table for the report: OLS of (y - loc) on the attribute
    # design at the converged loc, clustered by grid_cell_id (the location
    # terms are LOO shrinkage estimates, not fixed effects, so clustering
    # on the grid cell is not the degenerate FE-and-cluster-on-same-key
    # case). Descriptive only -- nothing downstream uses these SEs.
    ols = sm.OLS((y - loc)[fit], design[fit]).fit(
        cov_type="cluster", cov_kwds={"groups": df.loc[fit, "grid_cell_id"].fillna(-1).astype(int).to_numpy()}
    )
    in_sample_r2 = 1 - np.nansum(resid ** 2) / np.nansum((y_fit - np.nanmean(y_fit)) ** 2)

    info = {
        "n_fit": n_fit,
        "excl_reasons": df.loc[~df["fit_ok"], "fit_excl_reason"].value_counts().to_dict(),
        "coef": ols.params,
        "pvalues": ols.pvalues,
        "in_sample_r2_loo": in_sample_r2,
        "sigma_reliable": sigma,
        "kernel_build_s": kernel_build_s,
        "level_n_others": {lvl: level_info[lvl][1] for lvl in HIER_LEVELS},
    }
    return df, info


def _robust_z(s):
    """(s - median) / (1.4826 * MAD): a z-score the +-30-45% tails can't set the scale of."""
    med = s.median()
    mad = (s - med).abs().median() * 1.4826
    if not mad or pd.isna(mad):
        return pd.Series(0.0, index=s.index)
    return (s - med) / mad


def compute_composite_score(
    df,
    spatial_col="spatial_price_pct_vs_avg",
    spatial_reliable_col="spatial_rank_reliable",
    residual_col="residual_pct",
    residual_reliable_col="residual_reliable",
    out_col="good_deal_score",
):
    """good_deal_score = nanmean(robust_z(-spatial), robust_z(-residual)).

    Higher = better deal: cheaper than its 3km neighborhood AND cheaper
    than comparable flats at its address predict. Each input only counts
    where its own reliability flag is set (an unreliable signal is
    treated as missing, not as zero); a row with neither gets NaN. The
    residual already conditions on location, so this does not
    double-count it. percentile_rank_in_complex/_in_district are NOT
    inputs (context-only).
    """
    df = df.copy()
    spatial = df[spatial_col].where(df[spatial_reliable_col].fillna(False).astype(bool))
    resid = df[residual_col].where(df[residual_reliable_col].fillna(False).astype(bool))
    z_spatial = _robust_z(-spatial)
    z_resid = _robust_z(-resid)
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
    df["residual_pct"] = np.exp(df["ols_residual_score"]) - 1
    df["residual_reliable"] = df["ols_residual_score"].notna()

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

    # SECONDARY: hierarchical hedonic model (map 'residual' mode). Location
    # is absorbed by LOO-shrunk district > grid > complex > building
    # intercepts + a 100m kernel, so residual_pct = "% vs. what comparable
    # flats at this address go for" -- an axis genuinely distinct from the
    # spatial (neighborhood-average) signal.
    t0 = time.time()
    df, hier = fit_hier_model(df)
    hier_elapsed = time.time() - t0
    df["actual_price_m2"] = df["price_m2"]
    n_fit = hier["n_fit"]
    n_reliable_residual = int(df["residual_reliable"].sum())

    df = compute_composite_score(df)
    n_composite = int(df["good_deal_score"].notna().sum())
    df.to_csv(out_path, index=False, encoding="utf-8")

    # Independence check: the whole point of the hierarchical location
    # control is that this stays well below the 0.89-0.93 the plain OLS had.
    both = df["residual_reliable"] & df["spatial_rank_reliable"]
    corr_3km = df.loc[both, "residual_pct"].corr(df.loc[both, "spatial_price_pct_vs_avg"])
    both_1km = df["residual_reliable"] & df["spatial_rank_reliable_1km"]
    corr_1km = df.loc[both_1km, "residual_pct"].corr(df.loc[both_1km, "spatial_price_pct_vs_avg_1km"])
    top_r = set(df.loc[df["residual_reliable"], "residual_pct"].nsmallest(300).index)
    top_s = set(df.loc[df["spatial_rank_reliable"], "spatial_price_pct_vs_avg"].nsmallest(300).index)
    top300_overlap = len(top_r & top_s) / 300
    q = df.loc[df["residual_reliable"], "residual_pct"].quantile([0.01, 0.05, 0.10, 0.50, 0.90, 0.95, 0.99])
    bn, cn, kn = df["building_n_others"], df["complex_n_others"], df["kernel_eff_n"]
    fit_mask = df["fit_ok"]
    bucket_counts = {
        f"building n_others >= {RELIABLE_BUILDING_N}": int((fit_mask & (bn >= RELIABLE_BUILDING_N)).sum()),
        f"else complex n_others >= {RELIABLE_COMPLEX_N}": int((fit_mask & (bn < RELIABLE_BUILDING_N) & (cn >= RELIABLE_COMPLEX_N)).sum()),
        f"else kernel eff_n >= {RELIABLE_KERNEL_EFF_N}": int((fit_mask & (bn < RELIABLE_BUILDING_N) & (cn < RELIABLE_COMPLEX_N) & (kn >= RELIABLE_KERNEL_EFF_N)).sum()),
        "unreliable (thin comparables)": int((fit_mask & ~df["residual_reliable"]).sum()),
    }

    lines = []
    lines.append("ranking.py --full")
    lines.append(f"input: {features_path}")
    lines.append(f"output: {out_path}")
    lines.append(f"total rows: {n_total}")
    lines.append("")
    lines.append("=== SPATIAL: 3km-radius price vs. neighborhood (map 'spatial' mode) ===")
    lines.append(f"rows with a reliable (n_neighbors_3km >= {MIN_NEIGHBORS_FOR_SPATIAL}) neighborhood avg: {n_reliable_spatial}/{n_total} ({n_reliable_spatial/n_total:.1%})")
    lines.append("")
    lines.append("=== UI TOGGLE: 1km-radius spatial relative price (not in composite) ===")
    lines.append(f"rows with a reliable (n_neighbors_1km >= {MIN_NEIGHBORS_FOR_SPATIAL}) neighborhood avg: {n_reliable_spatial_1km}/{n_total} ({n_reliable_spatial_1km/n_total:.1%})")
    lines.append("")
    lines.append("=== CONTEXT ONLY: in-complex / in-district percentile (not in composite) ===")
    lines.append(f"rows with complex_listing_count >= {MIN_N_FOR_COMPLEX_PERCENTILE} (in-complex percentile meaningful): {n_complex_reliable}/{n_total} ({n_complex_reliable/n_total:.1%})")
    lines.append("")
    lines.append("=== RESIDUAL: hierarchical hedonic model (map 'residual' mode) ===")
    lines.append("ln_price_m2 = attributes + LOO-shrunk location intercepts (district > grid > complex > building) + 100m LOO kernel")
    lines.append(f"attribute formula: {HIER_ATTR_FORMULA}")
    lines.append(f"levels / lambda: {dict(zip(HIER_LEVELS, HIER_LAMBDA))}; kernel h={HIER_KERNEL_H_KM*1000:.0f}m cutoff={HIER_KERNEL_CUTOFF_KM*1000:.0f}m lambda={HIER_KERNEL_LAMBDA}; backfit iters={HIER_BACKFIT_ITERS}")
    lines.append(f"fit sample: {n_fit}/{n_total} ({n_fit/n_total:.1%}); excluded by reason: {hier['excl_reasons']}")
    lines.append(f"residual_reliable: {n_reliable_residual}/{n_total} ({n_reliable_residual/n_total:.1%})")
    for k, v in bucket_counts.items():
        lines.append(f"  {k}: {v}")
    lines.append(f"in-sample R-squared (all location terms leave-one-out): {hier['in_sample_r2_loo']:.4f}")
    lines.append(f"sigma (sd of ln residual, reliable rows): {hier['sigma_reliable']:.4f}")
    lines.append("residual_pct quantiles (reliable rows): " + ", ".join(f"p{int(p*100)}={v:+.1%}" for p, v in q.items()))
    lines.append(f"corr(residual_pct, spatial_pct_3km): {corr_3km:.3f}   corr(residual_pct, spatial_pct_1km): {corr_1km:.3f}")
    lines.append(f"top-300 deal overlap residual vs spatial_3km: {top300_overlap:.2f}")
    lines.append(f"elapsed: {hier_elapsed:.1f}s (kernel matrix {hier['kernel_build_s']:.1f}s)")
    lines.append("")
    lines.append("attribute coefficients (OLS at converged location terms, SE clustered by grid_cell_id):")
    coef_table = pd.DataFrame({"coef": hier["coef"], "p": hier["pvalues"]})
    lines.append(coef_table.to_string(float_format=lambda v: f"{v:.4f}"))
    lines.append("")
    lines.append("=== COMPOSITE: good_deal_score = nanmean(robust_z(-spatial_pct | reliable), robust_z(-residual_pct | reliable)) ===")
    lines.append(f"rows with a composite score: {n_composite}/{n_total} ({n_composite/n_total:.1%})")

    report_path = os.path.join(FULL_RUN_DIR, "ranking_full_report.txt")
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    print(f"wrote {n_total} ranked rows to {out_path}")
    print(f"spatial signal reliable: {n_reliable_spatial}/{n_total}")
    print(f"residual signal reliable: {n_reliable_residual}/{n_total}, LOO R2={hier['in_sample_r2_loo']:.4f}, "
          f"corr w/ spatial 3km={corr_3km:.3f}, 1km={corr_1km:.3f}, top300 overlap={top300_overlap:.2f}")
    print(f"composite scored: {n_composite}/{n_total}; hier fit {hier_elapsed:.1f}s")
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
