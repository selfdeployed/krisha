"""Final between-stations DiD with separate 50 m bands through 200 m.

This final specification deliberately does not add nearest-segment,
segment-by-year, or spatial-grid fixed effects. Standard errors are clustered
by common 500 x 500 m spatial cells. The specification also controls for
proximity to parks, the embankment and shopping malls.
"""
from __future__ import annotations

import importlib.util
import os
from types import SimpleNamespace

import numpy as np
import pandas as pd
import statsmodels.formula.api as smf
from openpyxl import Workbook


HERE = os.path.dirname(os.path.abspath(__file__))
MAIN_DIR = os.path.dirname(HERE)
HELPER_PATH = os.path.join(MAIN_DIR, "export_current_models_two_tabs.py")
SOURCE_MODEL_PATH = os.path.join(MAIN_DIR, "run_main_model.py")
OUTPUT = os.path.join(HERE, "02_between_stations_final.xlsx")

CONTROL_MIN_M = 1500
CONTROL_MAX_M = 2000
STATION_EXCLUSION_M = 500
EXPECTED_OBSERVATIONS = 19_925
EXPECTED_CLUSTERS = 184

BANDS = [
    ("band_0_50", 0, 50, "0–50 m"),
    ("band_50_100", 50, 100, "50–100 m"),
    ("band_100_150", 100, 150, "100–150 m"),
    ("band_150_200", 150, 200, "150–200 m"),
    ("band_200_300", 200, 300, "200–300 m"),
    ("band_300_400", 300, 400, "300–400 m"),
    ("band_400_500", 400, 500, "400–500 m"),
    ("band_500_600", 500, 600, "500–600 m"),
    ("band_600_1000", 600, 1000, "600–1000 m"),
    ("band_1000_1500", 1000, 1500, "1000–1500 m"),
]

AMENITY_TERMS = [
    "near_park_1km",
    "near_embankment_1km",
    "near_mall_1km",
    "mall_mega_silkway_1km",
    "mall_asia_park_1km",
    "mall_keruen_1km",
    "mall_keruen_city_1km",
    "mall_saryarka_1km",
]


def load_module(name: str, path: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    if spec.loader is None:
        raise RuntimeError(f"Cannot load {path}")
    spec.loader.exec_module(module)
    return module


def main():
    helpers = load_module("between_final_helpers", HELPER_PATH)
    source = load_module("between_final_source", SOURCE_MODEL_PATH)

    data = source.prepare_complete_data()
    line_distance = data["line_distance_m"]
    treatment = line_distance < CONTROL_MIN_M
    control = line_distance.between(CONTROL_MIN_M, CONTROL_MAX_M, inclusive="both")
    eligible = (
        (treatment | control)
        & (data["station_distance_m"] > STATION_EXCLUSION_M)
    )
    sample = data.loc[eligible].copy()
    if source.MALL_REFERENCE != "Khan Shatyr":
        raise AssertionError("The shopping-mall reference must be Khan Shatyr")
    missing_amenities = [name for name in AMENITY_TERMS if name not in sample.columns]
    constant_amenities = [name for name in AMENITY_TERMS if name in sample and sample[name].nunique() < 2]
    if missing_amenities or constant_amenities:
        raise AssertionError(
            f"Invalid amenity controls: missing={missing_amenities}, constant={constant_amenities}"
        )

    distance = sample["line_distance_m"]
    for dummy, low, high, _ in BANDS:
        sample[dummy] = ((distance >= low) & (distance < high)).astype(int)
    dummies = [band[0] for band in BANDS]

    treatment_rows = distance < CONTROL_MIN_M
    control_rows = distance >= CONTROL_MIN_M
    if not sample.loc[treatment_rows, dummies].sum(axis=1).eq(1).all():
        raise AssertionError("Treatment bands must cover each treatment row exactly once")
    if not sample.loc[control_rows, dummies].sum(axis=1).eq(0).all():
        raise AssertionError("A control observation entered a treatment band")
    if not sample["station_distance_m"].gt(STATION_EXCLUSION_M).all():
        raise AssertionError("An apartment within 500 m of a station entered the sample")

    formula = (
        "ln_price_m2 ~ year2026 + "
        + " + ".join(dummies)
        + " + "
        + " + ".join(f"year2026:{dummy}" for dummy in dummies)
        + " + "
        + source.CONTROLS
        + " + mall_keruen_city_1km"
    )
    forbidden_controls = ("nearest_segment", "segment", "grid_cell", "cell_id")
    if any(term in formula for term in forbidden_controls):
        raise AssertionError("A segment or spatial-grid fixed effect entered the formula")

    ols = smf.ols(formula, data=sample, missing="raise").fit()
    used = sample.loc[ols.model.data.row_labels].copy()
    if len(used) != len(sample):
        raise AssertionError("The formula silently removed observations")
    if len(used) != EXPECTED_OBSERVATIONS:
        raise AssertionError(
            f"Expected {EXPECTED_OBSERVATIONS:,} observations, received {len(used):,}"
        )
    rank = int(np.linalg.matrix_rank(ols.model.exog))
    columns = int(ols.model.exog.shape[1])
    if rank != columns:
        raise AssertionError(f"Design matrix is not full rank ({rank} < {columns})")

    groups, clusters = helpers.grid_groups(used)
    if clusters != EXPECTED_CLUSTERS:
        raise AssertionError(
            f"Expected {EXPECTED_CLUSTERS} spatial clusters, received {clusters}"
        )
    result = ols.get_robustcov_results(
        cov_type="cluster",
        groups=groups,
        use_correction=True,
        df_correction=True,
        use_t=True,
    )

    specification = SimpleNamespace(DUMMIES=dummies, FORMULA=formula)
    helpers.ZONE_LABELS = {dummy: label for dummy, _, _, label in BANDS}
    helpers.CONTROL_LABEL = "Control 1500–2000 m"
    metrics, did_rows, coefficients = helpers.build_tables(
        specification,
        used,
        result,
        f"500 x 500 m spatial clustering ({clusters} clusters)",
        "apartments <=500 m from a station excluded",
    )
    metrics.extend(
        [
            ("model_scope", "between stations only"),
            ("spatial_fixed_effects", "none (no segment or grid FE)"),
            ("park_control", "within 1 km of a supplied park point"),
            ("embankment_control", "within 1 km of the supplied embankment polyline"),
            ("mall_control", "nearest mall within 1 km; Khan Shatyr is the reference mall"),
        ]
    )

    workbook = Workbook()
    workbook.remove(workbook.active)
    helpers.write_sheet(
        workbook,
        "Between_50m_bands",
        "Between-stations model: detailed distance bands",
        formula,
        metrics,
        did_rows,
        coefficients,
    )
    workbook.save(OUTPUT)

    results = pd.DataFrame(did_rows[:-1])
    print("Output:", OUTPUT)
    print(
        "Observations:", len(used),
        "Clusters:", clusters,
        "Rank:", f"{rank}/{columns}",
    )
    print("Sheets: Between_50m_bands")
    print("Formula:", formula)
    print(
        results[
            [
                "distance_zone",
                "observations_2025",
                "observations_2026",
                "observations_total",
                "coef",
                "std_error",
                "p_value",
                "effect_percent",
                "ci_low_percent",
                "ci_high_percent",
            ]
        ].to_string(
            index=False,
            formatters={"p_value": lambda value: f"{value:.6f}"},
        )
    )
    return OUTPUT, results


if __name__ == "__main__":
    main()
