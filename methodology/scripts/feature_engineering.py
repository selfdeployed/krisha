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
"""

import argparse
import math
import os

import pandas as pd

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


def compute_avg_price_m2_within_radius(df, radius_km=3.0, stat="median", lat_col="lat", lon_col="lon", value_col="price_m2"):
    """Add avg_price_m2_within_{radius}_mean/median and n_neighbors columns.

    For each row with valid lat/lon, averages `value_col` over all OTHER
    rows within `radius_km` haversine distance that also have a valid
    lat/lon and valid value_col. Straightforward O(n^2) pairwise loop --
    fine at sample scale.

    TODO: at full ~35k-row scale this must be replaced with a spatial
    index (e.g. sklearn.neighbors.BallTree with metric='haversine') for
    performance -- not implemented or benchmarked here.
    """
    df = df.copy()
    means, medians, counts = [], [], []
    valid = df[lat_col].notna() & df[lon_col].notna()

    for i, row in df.iterrows():
        if not valid.loc[i] or pd.isna(row[value_col]):
            means.append(None)
            medians.append(None)
            counts.append(0)
            continue
        neighbor_values = []
        for j, other in df.iterrows():
            if i == j or not valid.loc[j] or pd.isna(other[value_col]):
                continue
            d = haversine_km(row[lat_col], row[lon_col], other[lat_col], other[lon_col])
            if d <= radius_km:
                neighbor_values.append(other[value_col])
        if neighbor_values:
            s = pd.Series(neighbor_values)
            means.append(s.mean())
            medians.append(s.median())
        else:
            means.append(None)
            medians.append(None)
        counts.append(len(neighbor_values))

    df["avg_price_m2_within_3km_mean"] = means
    df["avg_price_m2_within_3km_median"] = medians
    df["n_neighbors_3km"] = counts
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
    """Join parsed fields with raw lat/lon/fetched_at and compute all features."""
    df = parsed_df.merge(raw_df[["source_row", "lat", "lon", "fetched_at"]], on="source_row", how="left")

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

    df = compute_avg_price_m2_within_radius(df, radius_km=3.0)

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

    features_df = engineer_features(parsed_df, raw_df)
    features_df.to_csv(out_path, index=False, encoding="utf-8")

    n_total = len(features_df)
    n_price_m2 = features_df["price_m2"].notna().sum()
    n_neighbors_summary = features_df["n_neighbors_3km"].describe()
    n_low_conf = features_df["low_confidence_spatial"].sum()
    n_complex_agg = features_df["complex_median_price_m2"].notna().sum()
    n_district_agg = features_df["district_median_price_m2"].notna().sum()

    print(f"wrote {n_total} feature rows to {out_path}")
    print(f"price_m2 computed: {n_price_m2}/{n_total}")
    print(f"n_neighbors_3km stats:\n{n_neighbors_summary}")
    print(f"low_confidence_spatial (n_neighbors_3km < {LOW_CONFIDENCE_NEIGHBOR_THRESHOLD}): {n_low_conf}/{n_total}")
    print(f"complex_median_price_m2 present: {n_complex_agg}/{n_total}")
    print(f"district_median_price_m2 present: {n_district_agg}/{n_total}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--sample", action="store_true")
    args = parser.parse_args()

    if not args.sample:
        parser.print_help()
        return

    _haversine_selfcheck()
    run_sample()


if __name__ == "__main__":
    main()
