"""Final near-stations model: 500m spatial clusters and model-specific distance bands."""
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
OUTPUT = os.path.join(HERE, "01_near_stations_final.xlsx")

CONTROL_MIN_M = 1500
CONTROL_MAX_M = 2000
BANDS = [
    ("band_lt300", 0, 300, "<300 м"),
    ("band_300_700", 300, 700, "300–700 м"),
    ("band_700_1000", 700, 1000, "700–1000 м"),
    ("band_1000_1500", 1000, 1500, "1000–1500 м"),
]


def load_module(name: str, path: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    if spec.loader is None:
        raise RuntimeError(f"Cannot load {path}")
    spec.loader.exec_module(module)
    return module


def main():
    helpers = load_module("near_final_helpers", HELPER_PATH)
    source = load_module("near_final_source", SOURCE_MODEL_PATH)
    data = source.prepare_complete_data()
    distance = data["station_distance_m"]
    eligible = (distance < CONTROL_MIN_M) | distance.between(
        CONTROL_MIN_M, CONTROL_MAX_M, inclusive="both"
    )
    sample = data.loc[eligible].copy()
    d = sample["station_distance_m"]
    for dummy, low, high, _ in BANDS:
        sample[dummy] = ((d >= low) & (d < high)).astype(int)
    dummies = [band[0] for band in BANDS]
    if not sample.loc[d < CONTROL_MIN_M, dummies].sum(axis=1).eq(1).all():
        raise AssertionError("Treatment bands do not cover the near-stations sample exactly once")
    if not sample.loc[d >= CONTROL_MIN_M, dummies].sum(axis=1).eq(0).all():
        raise AssertionError("A control observation entered a treatment band")

    formula = (
        "ln_price_m2 ~ year2026 + "
        + " + ".join(dummies)
        + " + "
        + " + ".join(f"year2026:{dummy}" for dummy in dummies)
        + " + "
        + source.CONTROLS
    )
    ols = smf.ols(formula, data=sample, missing="raise").fit()
    used = sample.loc[ols.model.data.row_labels].copy()
    if len(used) != len(sample) or len(used) != 24_176:
        raise AssertionError(f"Expected 24,176 observations, received {len(used):,}")
    if np.linalg.matrix_rank(ols.model.exog) != ols.model.exog.shape[1]:
        raise AssertionError("Near-stations design matrix is not full rank")
    groups, clusters = helpers.grid_groups(used)
    result = ols.get_robustcov_results(
        cov_type="cluster",
        groups=groups,
        use_correction=True,
        df_correction=True,
        use_t=True,
    )

    specification = SimpleNamespace(DUMMIES=dummies, FORMULA=formula)
    helpers.ZONE_LABELS = {dummy: label for dummy, _, _, label in BANDS}
    metrics, did_rows, coefficients = helpers.build_tables(
        specification,
        used,
        result,
        f"Кластеризация 500×500 м ({clusters} кластеров)",
        "нет",
    )
    workbook = Workbook()
    workbook.remove(workbook.active)
    helpers.write_sheet(
        workbook,
        "Main_near_stations",
        "Model 1: effects near LRT stations",
        formula,
        metrics,
        did_rows,
        coefficients,
    )
    workbook.save(OUTPUT)

    print("Output:", OUTPUT)
    print("Observations:", len(used), "Clusters:", clusters)
    print(
        pd.DataFrame(did_rows[:-1])[
            ["distance_zone", "observations_total", "coef", "std_error", "p_value", "effect_percent"]
        ].to_string(index=False, formatters={"p_value": lambda value: f"{value:.3f}"})
    )
    return OUTPUT


if __name__ == "__main__":
    main()
