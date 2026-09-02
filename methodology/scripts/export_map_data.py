# -*- coding: utf-8 -*-
"""export_map_data.py -- compact map-ready data export for the interactive
"sweet spot" artifact (methodology/map/astana_deals_map.html).

Reads methodology/full_run/ranked_full.csv, drops rows with no coordinates
or coordinates outside a sane Astana bounding box, and writes a compact
JSON payload (array-of-arrays, categoricals as lookup-table indices) sized
to embed directly in the artifact HTML -- no external asset store is
available for this user (confirmed via the artifact-capabilities skill),
so the whole dataset travels inline.

Rerunnable: when the live re-scrape's full pipeline run produces a fresh
ranked_full.csv, rerun this script, then build_map_artifact.py, then
republish the artifact to the same URL. See METHODOLOGY.md-style refresh
notes in the plan.

Usage:
    python export_map_data.py
"""

import json
import math
import os
import time
from datetime import datetime

import pandas as pd

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
FULL_RUN_DIR = os.path.join(REPO_ROOT, "methodology", "full_run")
INPUT_CSV = os.path.join(FULL_RUN_DIR, "ranked_full.csv")
OUTPUT_JSON = os.path.join(FULL_RUN_DIR, "map_data.json")
REPORT_PATH = os.path.join(FULL_RUN_DIR, "map_data_report.txt")

# Astana bounding box (EDA_PLAN.md section 5 / generate_eda_report.py):
# generous enough to cover the city plus near-suburban growth, tight
# enough to exclude clear bad-geocode outliers elsewhere in Kazakhstan.
BBOX_LAT = (50.9, 51.3)
BBOX_LON = (71.0, 71.8)

# Diverging color-scale clamp for spatial_price_pct_vs_avg (measured
# distribution: p1=-41%, p50=-1%, p95=+48%, max=+833% from luxury
# outliers) -- ±35% keeps the meaningful range legible; values beyond are
# clamped and flagged in the UI, not stretched into the scale.
SPATIAL_PCT_CLAMP = 0.35

# Diverging color-scale clamp for the heatmap's price-vs-city-median signal
# (a different, wider-dispersion measure than the per-listing spatial
# signal above -- measured distribution: p1=-46%, p50=0%, p95=+65%,
# p99=+118%). ±50% keeps most of the real spread legible.
HEAT_PCT_CLAMP = 0.5

# residual_pct = exp(hier residual)-1 (% vs. what comparable flats at the
# same address predict) has a similar spread to spatial_price_pct_vs_avg
# (p1=-30%, p5=-20%, p50=0%, p95=+26%, p99=+46%) -- reuse the same clamp
# so both render on one consistent, comparable color scale.
RESIDUAL_PCT_CLAMP = SPATIAL_PCT_CLAMP

# good_deal_score is a composite robust z-score (mean of MAD-scaled
# z(-spatial_pct), z(-residual_pct)), a different unit from the two
# percent signals above; +-2.5 covers the meaningful range (measured
# distribution is printed in the report on every run).
COMPOSITE_CLAMP = 2.5

# residual_z is exported x100 as an int; the map badges "strong deal" at
# z <= -1.5 (relative discrepancy AND significance, given the number of
# comparables behind the estimate).
STRONG_DEAL_Z = -1.5

# Expected category sets -- asserted on every run so a refresh with an
# unexpected new category (e.g. krisha.kz adding a 7th district) fails
# loudly instead of silently mis-indexing.
EXPECTED_DISTRICTS = ["Алматы", "Байконур", "Есильский", "Нура", "Сарайшык", "Сарыарка"]
EXPECTED_BUILDING_TYPES = ["иной", "кирпичный", "монолитный", "панельный"]
EXPECTED_CONDITIONS = ["fresh_renovation", "needs_renovation", "rough", "unknown"]
EXPECTED_ROOMS_BUCKETS = ["1-room", "2-room", "3-room", "4+room", "studio"]


def _lookup_index(value, ordered_values, allow_missing=True):
    if pd.isna(value):
        return -1
    try:
        return ordered_values.index(value)
    except ValueError:
        if allow_missing:
            raise ValueError(f"Unexpected category {value!r} not in {ordered_values} -- "
                              f"update the EXPECTED_* list and re-check the UI lookup tables.")
        raise


def _clean_int(value):
    return None if pd.isna(value) else int(value)


def _clean_float(value, ndigits):
    return None if pd.isna(value) else round(float(value), ndigits)


def main():
    t0 = time.time()
    df = pd.read_csv(INPUT_CSV, encoding="utf-8")
    n_total = len(df)

    # Assert category sets match expectations before indexing anything.
    for col, expected, name in [
        ("district", EXPECTED_DISTRICTS, "district"),
        ("building_type", EXPECTED_BUILDING_TYPES, "building_type"),
        ("apartment_condition", EXPECTED_CONDITIONS, "apartment_condition"),
        ("rooms_bucket_estimated", EXPECTED_ROOMS_BUCKETS, "rooms_bucket_estimated"),
    ]:
        actual = sorted(df[col].dropna().unique().tolist())
        if actual != sorted(expected):
            raise SystemExit(
                f"{name} category set changed: expected {sorted(expected)}, got {actual}. "
                f"Update EXPECTED_{name.upper()} above before re-running."
            )

    n_no_coords = df["lat"].isna().sum() + (df["lat"].notna() & df["lon"].isna()).sum()
    has_coords = df["lat"].notna() & df["lon"].notna()
    in_bbox = (
        has_coords
        & df["lat"].between(*BBOX_LAT)
        & df["lon"].between(*BBOX_LON)
    )
    n_out_of_bbox = int((has_coords & ~in_bbox).sum())

    shown = df[in_bbox].copy()
    n_shown = len(shown)

    # --- id from url ---
    shown["_id"] = shown["url"].str.extract(r"/a/show/(\d+)$")[0]
    if shown["_id"].isna().any():
        bad = shown[shown["_id"].isna()]["url"].head(5).tolist()
        raise SystemExit(f"{shown['_id'].isna().sum()} url(s) don't match the expected "
                          f"/a/show/<id> pattern, e.g.: {bad}")
    shown["_id"] = shown["_id"].astype(int)

    # --- complexes lookup: name -> (index, median_price_m2) ---
    complex_names = sorted(shown["complex_name"].dropna().unique().tolist())
    complex_index = {name: i for i, name in enumerate(complex_names)}
    complex_median = shown.dropna(subset=["complex_name"]).groupby("complex_name")["complex_median_price_m2"].first()
    complexes_table = [
        [name, _clean_int(complex_median.get(name)) if pd.notna(complex_median.get(name)) else None]
        for name in complex_names
    ]

    # --- district medians lookup ---
    district_medians = {}
    for i, d in enumerate(EXPECTED_DISTRICTS):
        rows = shown[shown["district"] == d]
        val = rows["district_median_price_m2"].dropna()
        district_medians[i] = _clean_int(val.iloc[0]) if len(val) else None

    city_median_price_m2 = _clean_int(shown["price_m2"].median())

    rows_out = []
    n_pct_null = 0
    n_reliable_false = 0
    n_pct_null_1km = 0
    n_reliable_false_1km = 0
    n_residual_null = 0
    n_residual_unreliable = 0
    n_strong_deal = 0
    n_composite_null = 0
    for _, r in shown.iterrows():
        spatial_pct = r["spatial_price_pct_vs_avg"]
        spatial_pm = None if pd.isna(spatial_pct) else int(round(spatial_pct * 1000))
        if spatial_pm is None:
            n_pct_null += 1
        reliable = 1 if bool(r["spatial_rank_reliable"]) else 0
        if not reliable:
            n_reliable_false += 1

        spatial_pct_1km = r["spatial_price_pct_vs_avg_1km"]
        spatial_pm_1km = None if pd.isna(spatial_pct_1km) else int(round(spatial_pct_1km * 1000))
        if spatial_pm_1km is None:
            n_pct_null_1km += 1
        reliable_1km = 1 if bool(r["spatial_rank_reliable_1km"]) else 0
        if not reliable_1km:
            n_reliable_false_1km += 1

        residual_pct = r["residual_pct"]
        residual_pm = None if pd.isna(residual_pct) else int(round(residual_pct * 1000))
        if residual_pm is None:
            n_residual_null += 1
        residual_reliable = 1 if bool(r["residual_reliable"]) else 0
        if residual_pm is not None and not residual_reliable:
            n_residual_unreliable += 1
        residual_z = r["residual_z"]
        residual_z100 = None if pd.isna(residual_z) else int(round(residual_z * 100))
        if residual_reliable and residual_z100 is not None and residual_z <= STRONG_DEAL_Z:
            n_strong_deal += 1

        composite = r["good_deal_score"]
        composite_pm = None if pd.isna(composite) else int(round(composite * 1000))
        if composite_pm is None:
            n_composite_null += 1

        rows_out.append([
            int(r["_id"]),
            _clean_float(r["lat"], 6),
            _clean_float(r["lon"], 6),
            _clean_int(round(r["price_tenge"] / 1000)) if pd.notna(r["price_tenge"]) else None,
            _clean_float(r["area_total_m2"], 1),
            _clean_int(r["build_year"]),
            _clean_int(r["floor"]),
            _clean_int(r["floor_total"]),
            _lookup_index(r["rooms_bucket_estimated"], EXPECTED_ROOMS_BUCKETS),
            _lookup_index(r["apartment_condition"], EXPECTED_CONDITIONS),
            _lookup_index(r["building_type"], EXPECTED_BUILDING_TYPES),
            _lookup_index(r["district"], EXPECTED_DISTRICTS),
            complex_index.get(r["complex_name"], -1) if pd.notna(r["complex_name"]) else -1,
            spatial_pm,
            reliable,
            _clean_int(r["n_neighbors_3km"]),
            spatial_pm_1km,
            reliable_1km,
            _clean_int(r["n_neighbors_1km"]),
            residual_pm,
            residual_reliable,
            residual_z100,
            _clean_int(round(r["predicted_price_m2"])) if pd.notna(r["predicted_price_m2"]) else None,
            composite_pm,
        ])

    payload = {
        "meta": {
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "source_rows_total": n_total,
            "rows_excluded_no_coords": int(n_no_coords),
            "rows_excluded_bbox": n_out_of_bbox,
            "rows_shown": n_shown,
            "spatial_pct_clamp": SPATIAL_PCT_CLAMP,
            "residual_pct_clamp": RESIDUAL_PCT_CLAMP,
            "composite_clamp": COMPOSITE_CLAMP,
            "strong_deal_z": STRONG_DEAL_Z,
            "heat_pct_clamp": HEAT_PCT_CLAMP,
            "city_median_price_m2": city_median_price_m2,
            "bbox_lat": list(BBOX_LAT),
            "bbox_lon": list(BBOX_LON),
        },
        "districts": EXPECTED_DISTRICTS,
        "building_types": EXPECTED_BUILDING_TYPES,
        "conditions": EXPECTED_CONDITIONS,
        "rooms_buckets": EXPECTED_ROOMS_BUCKETS,
        "district_medians": district_medians,
        "complexes": complexes_table,
        "rows": rows_out,
    }

    os.makedirs(FULL_RUN_DIR, exist_ok=True)
    with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))

    elapsed = time.time() - t0
    size_mb = os.path.getsize(OUTPUT_JSON) / (1024 * 1024)

    report_lines = [
        "export_map_data.py",
        f"input: {INPUT_CSV}",
        f"output: {OUTPUT_JSON}",
        f"generated_at: {payload['meta']['generated_at']}",
        f"source rows total: {n_total}",
        f"rows excluded (no coords): {n_no_coords}",
        f"rows excluded (outside bbox {BBOX_LAT}x{BBOX_LON}): {n_out_of_bbox}",
        f"rows shown on map: {n_shown}",
        f"spatial_price_pct_vs_avg null (shown as gray/hollow): {n_pct_null}",
        f"spatial_rank_reliable=False (shown de-emphasized): {n_reliable_false}",
        f"spatial_price_pct_vs_avg_1km null: {n_pct_null_1km}",
        f"spatial_rank_reliable_1km=False: {n_reliable_false_1km}",
        f"residual_pct null (outside fit sample): {n_residual_null}",
        f"residual_reliable=False (thin comparables, shown de-emphasized): {n_residual_unreliable}",
        f"strong deals (reliable & residual_z <= {STRONG_DEAL_Z}): {n_strong_deal}",
        f"good_deal_score null: {n_composite_null}",
        "good_deal_score quantiles (shown rows): " + ", ".join(
            f"p{int(p*100)}={v:+.2f}" for p, v in shown["good_deal_score"].quantile([0.01, 0.05, 0.5, 0.95, 0.99]).items()),
        f"city median price_m2 (shown rows): {city_median_price_m2}",
        f"distinct complexes: {len(complex_names)}",
        f"output file size: {size_mb:.2f} MB",
        f"elapsed: {elapsed:.2f}s",
    ]
    with open(REPORT_PATH, "w", encoding="utf-8") as f:
        f.write("\n".join(report_lines) + "\n")

    print("\n".join(report_lines))


if __name__ == "__main__":
    main()
