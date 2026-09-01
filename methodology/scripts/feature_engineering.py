# -*- coding: utf-8 -*-
"""feature_engineering.py -- ranking feature engineering for krisha.kz listings.

Implements the feature list documented in methodology/FEATURE_SPEC.md:
core hedonic features, the user-requested avg_price_m2_within_3km spatial
smoothing feature, additional spatial/comparative features (distance to
city center, mall/park/embankment 1km dummies, complex/district median
price aggregates, kitchen_area_ratio, grid_cell_id for later SE clustering).

Cross-file note (see FEATURE_SPEC.md top): parse_listings.py --sample's
output (sample_parsed_preview.csv) does not carry lat/lon/fetched_at
through. --sample mode here loads both sample_parsed_preview.csv and the
raw sample_rows.csv and joins them on source_row before computing any
spatial feature or building_age.

Usage:
    python feature_engineering.py --sample
    python feature_engineering.py --full
"""

import argparse
import math
import os
import time

import numpy as np
import pandas as pd
from sklearn.neighbors import BallTree

EARTH_RADIUS_KM = 6371.0088

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
FULL_RAW_CSV = os.path.join(REPO_ROOT, "AstanaLinksParserJune2026_parsed.csv")
FULL_RUN_DIR = os.path.join(REPO_ROOT, "methodology", "full_run")

# ---------------------------------------------------------------------------
# Reference-data constants (FEATURE_SPEC.md section 3). All approximate,
# manually sourced from general public knowledge of Astana geography --
# NOT re-derived from the lost run_main_model.py / export_current_models_
# two_tabs.py reference data. Verify before any production/reporting use.
# ---------------------------------------------------------------------------

CITY_CENTER = ("Baiterek Tower", 51.1282, 71.4306)  # TODO: approximate, manually sourced, verify before use

MALLS = {
    # name -> (lat, lon)  # TODO: approximate, manually sourced, verify before use
    "khan_shatyr": (51.1330, 71.4087),  # omitted/reference category, not a dummy
    "mega_silkway": (51.0916, 71.4168),
    "asia_park": (51.1255, 71.4189),
    "keruen": (51.1274, 71.4162),
    "keruen_city": (51.1064, 71.4667),
    "saryarka": (51.1198, 71.3805),
}

PARK_POINT = ("Central Park (approx.)", 51.1300, 71.4460)  # TODO: approximate, manually sourced, verify before use
EMBANKMENT_POINT = ("Ishim embankment (approx.)", 51.1215, 71.4330)  # TODO: approximate, manually sourced, verify before use

# Station/line reference table: the original coordinate source file
# (run_main_model.py / export_current_models_two_tabs.py) is not present
# in this repo (confirmed by search in feature_engineering_spec). A new
# table must be manually curated before distance_to_nearest_station_m /
# distance_to_line_m can be computed. Left as an explicit empty stub.
STATIONS = {}  # TODO: not implemented -- station coordinate source lost, needs manual curation

MIN_N_GROUP = 5  # default minimum group size for complex/district median aggregates
LOW_CONFIDENCE_NEIGHBOR_THRESHOLD = 3  # n_neighbors_3km below this -> low_confidence_spatial

# 500m grid cell size in degrees, approximated for Astana's latitude
# (~51N, where 1 deg longitude ~= 111km * cos(51deg) ~= 70km). Exact
# grid-origin/cell-size match to the original DiD grid is not required
# per FEATURE_SPEC.md (that source is also lost) -- this is a fresh,
# documented grid, only used later for clustering OLS standard errors.
_GRID_LAT_STEP_DEG = 500.0 / 111_000.0
_GRID_LON_STEP_DEG = 500.0 / (111_000.0 * math.cos(math.radians(51.1)))


def haversine_km(lat1, lon1, lat2, lon2):
    """Great-circle distance in km between two lat/lon points (degrees)."""
    r = 6371.0088  # mean Earth radius, km
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlambda / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _haversine_selfcheck():
    # Baiterek Tower (51.1282, 71.4306) to Khan Shatyr (51.1330, 71.4087):
    # two well-known, close-together Astana landmarks. Straight-line
    # distance is on the order of ~1.6 km (short hop across the river/park
    # area between them) -- a loose bound is enough to catch a broken
    # formula (e.g. degrees-vs-radians mixups, wrong radius) without
    # depending on a precise ground-truth figure.
    d = haversine_km(51.1282, 71.4306, 51.1330, 71.4087)
    assert 0.5 < d < 3.0, f"haversine_km self-check failed: got {d:.3f} km, expected ~1-2 km"
    print(f"ok   haversine_km self-check: Baiterek Tower -> Khan Shatyr = {d:.3f} km")


def compute_avg_price_m2_within_radius(df, radius_km=3.0, label=None, stat="median", lat_col="lat", lon_col="lon", value_col="price_m2"):
    """Add avg_price_m2_within_{label}_mean/median and n_neighbors_{label} columns.

    For each row with valid lat/lon/value_col, averages `value_col` over all
    OTHER rows within `radius_km` haversine distance that also have valid
    lat/lon/value_col. Uses sklearn.neighbors.BallTree (metric='haversine',
    radians in/out) for an O(n log n) radius query -- required at full
    ~35k-row scale, where the previous naive O(n^2) pairwise loop would be
    ~604M haversine calls. Cross-checked to produce identical output to the
    old pairwise implementation on the 16-row sample fixture before this
    replaced it (see full-run activity notes).

    `label` names the output columns (defaults to e.g. "3km" derived from
    radius_km) -- lets this run at multiple radii (3km primary, 1km toggle)
    without column collisions.
    """
    if label is None:
        label = f"{radius_km:g}km"
    n = len(df)
    means = [None] * n
    medians = [None] * n
    counts = [0] * n

    valid = (df[lat_col].notna() & df[lon_col].notna() & df[value_col].notna()).to_numpy()
    valid_positions = np.nonzero(valid)[0]

    if len(valid_positions) > 0:
        coords_deg = df.iloc[valid_positions][[lat_col, lon_col]].to_numpy(dtype=float)
        coords_rad = np.radians(coords_deg)
        values = df.iloc[valid_positions][value_col].to_numpy(dtype=float)

        tree = BallTree(coords_rad, metric="haversine")
        radius_rad = radius_km / EARTH_RADIUS_KM
        neighbor_lists = tree.query_radius(coords_rad, r=radius_rad)

        for k, neighbor_idx in enumerate(neighbor_lists):
            neighbor_idx = neighbor_idx[neighbor_idx != k]  # exclude self
            if len(neighbor_idx) == 0:
                continue
            neighbor_vals = values[neighbor_idx]
            orig_pos = valid_positions[k]
            means[orig_pos] = float(neighbor_vals.mean())
            medians[orig_pos] = float(np.median(neighbor_vals))
            counts[orig_pos] = int(len(neighbor_vals))

    df = df.copy()
    df[f"avg_price_m2_within_{label}_mean"] = means
    df[f"avg_price_m2_within_{label}_median"] = medians
    df[f"n_neighbors_{label}"] = counts
    if label == "3km":
        df["low_confidence_spatial"] = df["n_neighbors_3km"] < LOW_CONFIDENCE_NEIGHBOR_THRESHOLD
    return df


def compute_group_aggregate(df, group_col, value_col, min_n=MIN_N_GROUP):
    """Return a DataFrame indexed by group_col with median/count/insufficient_n."""
    grouped = df.groupby(group_col)[value_col].agg(["median", "count"])
    grouped = grouped.rename(columns={"median": f"{value_col}_median", "count": f"{value_col}_count"})
    grouped["insufficient_n"] = grouped[f"{value_col}_count"] < min_n
    return grouped


def _grid_cell_id(lat, lon):
    if pd.isna(lat) or pd.isna(lon):
        return None
    lat_bin = math.floor(lat / _GRID_LAT_STEP_DEG)
    lon_bin = math.floor(lon / _GRID_LON_STEP_DEG)
    return f"{lat_bin}_{lon_bin}"


def _mall_dummies(lat, lon):
    out = {}
    if pd.isna(lat) or pd.isna(lon):
        for name in MALLS:
            out[f"mall_{name}_1km"] = None
        out["near_mall_1km"] = None
        return out
    any_non_reference = False
    for name, (mlat, mlon) in MALLS.items():
        near = haversine_km(lat, lon, mlat, mlon) < 1.0
        out[f"mall_{name}_1km"] = near
        if name != "khan_shatyr" and near:
            any_non_reference = True
    out["near_mall_1km"] = any_non_reference
    return out


def engineer_features(parsed_df, raw_df):
    """Join parsed fields with raw lat/lon/fetched_at and compute all features.

    raw_df is deduped on source_row (keep first) before the join. The full
    ~35k-row raw CSV has 5 source_row values appearing twice each (10 rows
    total, all status=error, same url both times per pair -- a LinksParser
    resume/retry artifact that re-appended the same failed url on a later
    run rather than a parsing issue). An undeduped merge fans those 5
    source_rows out 2x2=4-wide instead of 1-wide, inflating row count by
    +10 (34766 -> 34776, confirmed on the first --full run before this
    fix). Not present in the 16-row sample fixture.
    """
    raw_dedup = raw_df.drop_duplicates(subset="source_row", keep="first")
    df = parsed_df.merge(raw_dedup[["source_row", "lat", "lon", "fetched_at"]], on="source_row", how="left")

    # --- duplicate / relist dedup (EDA_PLAN.md section 4) ---
    # Rows sharing an identical (lat, lon, area_total_m2, price_tenge)
    # tuple are almost certainly the same physical unit relisted (price
    # cut, bumped visibility) rather than independent comparables --
    # counting them twice would double-weight that one unit in every
    # group median and 3km-neighbor average. Confirmed on the full
    # dataset: 4,165 such rows / ~2,630 duplicate groups
    # (EDA_REPORT.md). User decision: drop outright (keep first by
    # source_row), not merely flag. Rows missing any key field can't be
    # matched and are kept as-is (no false-positive risk from NaN==NaN).
    dedup_key = ["lat", "lon", "area_total_m2", "price_tenge"]
    has_full_key = df[dedup_key].notna().all(axis=1)
    is_dup = pd.Series(False, index=df.index)
    is_dup.loc[has_full_key] = df.loc[has_full_key].duplicated(subset=dedup_key, keep="first")
    df = df.loc[~is_dup].reset_index(drop=True)

    # --- core hedonic features ---
    df["price_m2"] = df["price_tenge"] / df["area_total_m2"]
    df.loc[df["area_total_m2"].isna() | (df["area_total_m2"] == 0), "price_m2"] = None
    df["ln_price_m2"] = df["price_m2"].apply(lambda v: math.log(v) if pd.notna(v) and v > 0 else None)
    df["ln_area"] = df["area_total_m2"].apply(lambda v: math.log(v) if pd.notna(v) and v > 0 else None)

    def _fetch_year(fetched_at):
        if pd.isna(fetched_at):
            return None
        try:
            return int(str(fetched_at)[:4])
        except ValueError:
            return None

    df["fetch_year"] = df["fetched_at"].apply(_fetch_year)
    df["building_age"] = df.apply(
        lambda r: max(0, r["fetch_year"] - int(r["build_year"]))
        if pd.notna(r["fetch_year"]) and pd.notna(r["build_year"])
        else None,
        axis=1,
    )

    df["kitchen_area_ratio"] = df.apply(
        lambda r: r["kitchen_area_m2"] / r["area_total_m2"]
        if pd.notna(r["kitchen_area_m2"]) and pd.notna(r["area_total_m2"]) and r["area_total_m2"] > 0
        else None,
        axis=1,
    )

    # --- spatial features ---
    df["distance_to_center_km"] = df.apply(
        lambda r: haversine_km(r["lat"], r["lon"], CITY_CENTER[1], CITY_CENTER[2])
        if pd.notna(r["lat"]) and pd.notna(r["lon"])
        else None,
        axis=1,
    )
    df["distance_to_park_km"] = df.apply(
        lambda r: haversine_km(r["lat"], r["lon"], PARK_POINT[1], PARK_POINT[2])
        if pd.notna(r["lat"]) and pd.notna(r["lon"])
        else None,
        axis=1,
    )
    df["near_park_1km"] = df["distance_to_park_km"].apply(lambda d: (d < 1.0) if pd.notna(d) else None)
    df["distance_to_embankment_km"] = df.apply(
        lambda r: haversine_km(r["lat"], r["lon"], EMBANKMENT_POINT[1], EMBANKMENT_POINT[2])
        if pd.notna(r["lat"]) and pd.notna(r["lon"])
        else None,
        axis=1,
    )
    df["near_embankment_1km"] = df["distance_to_embankment_km"].apply(lambda d: (d < 1.0) if pd.notna(d) else None)

    mall_rows = df.apply(lambda r: _mall_dummies(r["lat"], r["lon"]), axis=1)
    mall_df = pd.DataFrame(list(mall_rows))
    df = pd.concat([df.reset_index(drop=True), mall_df.reset_index(drop=True)], axis=1)

    df["grid_cell_id"] = df.apply(lambda r: _grid_cell_id(r["lat"], r["lon"]), axis=1)

    df = compute_avg_price_m2_within_radius(df, radius_km=3.0, label="3km")
    df = compute_avg_price_m2_within_radius(df, radius_km=1.0, label="1km")

    # --- group aggregates ---
    complex_agg = compute_group_aggregate(df[df["complex_name"].notna()], "complex_name", "price_m2", min_n=MIN_N_GROUP)
    complex_agg = complex_agg.rename(columns={
        "price_m2_median": "complex_median_price_m2",
        "price_m2_count": "complex_listing_count",
        "insufficient_n": "complex_insufficient_n",
    })
    df = df.merge(complex_agg, left_on="complex_name", right_index=True, how="left")

    district_agg = compute_group_aggregate(df[df["district"].notna()], "district", "price_m2", min_n=MIN_N_GROUP)
    district_agg = district_agg.rename(columns={
        "price_m2_median": "district_median_price_m2",
        "price_m2_count": "district_listing_count",
        "insufficient_n": "district_insufficient_n",
    })
    df = df.merge(district_agg, left_on="district", right_index=True, how="left")

    return df


# ---------------------------------------------------------------------------
# --sample: real run against methodology/samples/sample_parsed_preview.csv
# joined with methodology/samples/sample_rows.csv
# ---------------------------------------------------------------------------

def run_sample():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    samples_dir = os.path.join(os.path.dirname(script_dir), "samples")
    parsed_path = os.path.join(samples_dir, "sample_parsed_preview.csv")
    raw_path = os.path.join(samples_dir, "sample_rows.csv")
    out_path = os.path.join(samples_dir, "sample_features.csv")

    parsed_df = pd.read_csv(parsed_path, encoding="utf-8")
    raw_df = pd.read_csv(raw_path, encoding="utf-8")

    n_before_dedup = len(parsed_df)
    features_df = engineer_features(parsed_df, raw_df)
    features_df.to_csv(out_path, index=False, encoding="utf-8")

    n_total = len(features_df)
    n_price_m2 = features_df["price_m2"].notna().sum()
    n_neighbors_summary = features_df["n_neighbors_3km"].describe()
    n_low_conf = features_df["low_confidence_spatial"].sum()
    n_complex_agg = features_df["complex_median_price_m2"].notna().sum()
    n_district_agg = features_df["district_median_price_m2"].notna().sum()

    print(f"duplicate/relist rows dropped: {n_before_dedup - n_total}/{n_before_dedup}")
    print(f"wrote {n_total} feature rows to {out_path}")
    print(f"price_m2 computed: {n_price_m2}/{n_total}")
    print(f"n_neighbors_3km stats:\n{n_neighbors_summary}")
    print(f"low_confidence_spatial (n_neighbors_3km < {LOW_CONFIDENCE_NEIGHBOR_THRESHOLD}): {n_low_conf}/{n_total}")
    print(f"complex_median_price_m2 present: {n_complex_agg}/{n_total}")
    print(f"district_median_price_m2 present: {n_district_agg}/{n_total}")


# ---------------------------------------------------------------------------
# --full: real run against methodology/full_run/parsed_full.csv joined with
# the raw AstanaLinksParserJune2026_parsed.csv (for lat/lon/fetched_at).
# FIRST time the BallTree spatial join has run at full ~35k-row scale.
# ---------------------------------------------------------------------------

def run_full():
    parsed_path = os.path.join(FULL_RUN_DIR, "parsed_full.csv")
    out_path = os.path.join(FULL_RUN_DIR, "features_full.csv")

    parsed_df = pd.read_csv(parsed_path, encoding="utf-8")
    raw_df = pd.read_csv(FULL_RAW_CSV, encoding="utf-8")

    n_before_dedup = len(parsed_df)
    t0 = time.time()
    features_df = engineer_features(parsed_df, raw_df)
    elapsed_engineer = time.time() - t0
    n_dropped_dup = n_before_dedup - len(features_df)

    t1 = time.time()
    features_df.to_csv(out_path, index=False, encoding="utf-8")
    elapsed_write = time.time() - t1

    n_total = len(features_df)
    n_price_m2 = features_df["price_m2"].notna().sum()
    n_neighbors_summary = features_df["n_neighbors_3km"].describe()
    n_low_conf = features_df["low_confidence_spatial"].sum()
    n_complex_agg = features_df["complex_median_price_m2"].notna().sum()
    n_district_agg = features_df["district_median_price_m2"].notna().sum()
    n_zero_neighbors = (features_df["n_neighbors_3km"] == 0).sum()
    n_has_latlon = (features_df["lat"].notna() & features_df["lon"].notna()).sum()

    lines = []
    lines.append("feature_engineering.py --full")
    lines.append(f"input: {parsed_path}")
    lines.append(f"output: {out_path}")
    lines.append(f"rows before dedup: {n_before_dedup}")
    lines.append(f"duplicate/relist rows dropped (identical lat/lon/area/price): {n_dropped_dup}")
    lines.append(f"total rows: {n_total}")
    lines.append(f"rows with lat/lon: {n_has_latlon}/{n_total}")
    lines.append(f"engineer_features() elapsed (incl. BallTree 3km spatial join): {elapsed_engineer:.2f}s")
    lines.append(f"csv write elapsed: {elapsed_write:.2f}s")
    lines.append("")
    lines.append(f"price_m2 computed: {n_price_m2}/{n_total}")
    lines.append(f"n_neighbors_3km stats:\n{n_neighbors_summary.to_string()}")
    lines.append(f"rows with 0 neighbors within 3km (isolated): {n_zero_neighbors}/{n_total}")
    lines.append(f"low_confidence_spatial (n_neighbors_3km < {LOW_CONFIDENCE_NEIGHBOR_THRESHOLD}): {n_low_conf}/{n_total}")
    lines.append(f"complex_median_price_m2 present (complex_listing_count >= {MIN_N_GROUP}): {n_complex_agg}/{n_total}")
    lines.append(f"district_median_price_m2 present (district_listing_count >= {MIN_N_GROUP}): {n_district_agg}/{n_total}")

    report_path = os.path.join(FULL_RUN_DIR, "feature_full_report.txt")
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    print(f"duplicate/relist rows dropped: {n_dropped_dup}/{n_before_dedup}")
    print(f"wrote {n_total} feature rows to {out_path}")
    print(f"engineer_features() elapsed: {elapsed_engineer:.2f}s (BallTree spatial join included)")
    print(f"price_m2 computed: {n_price_m2}/{n_total}")
    print(f"rows with 0 neighbors within 3km: {n_zero_neighbors}/{n_total}")
    print(f"low_confidence_spatial: {n_low_conf}/{n_total}")
    print(f"full report: {report_path}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--sample", action="store_true")
    parser.add_argument("--full", action="store_true")
    args = parser.parse_args()

    if not args.sample and not args.full:
        parser.print_help()
        return

    _haversine_selfcheck()
    if args.sample:
        run_sample()
    if args.full:
        run_full()


if __name__ == "__main__":
    main()
