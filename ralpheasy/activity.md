# Krisha Best-Offer Methodology — Activity Log

## Current Status

**Last Updated:** 2026-09-01
**Tasks Completed:** 7 / 11
**Current Task:** ranking_scaffold_code (next; depends_on ranking_methodology_spec + feature_scaffold_code, both now true). eda_plan is also unblocked (depends only on feature_engineering_spec) but plan ordering lists ranking_scaffold_code first.

## Session Log

### 2026-09-01 — ranking_methodology_spec completed

Wrote `methodology/RANKING_METHODOLOGY.md`: Approach A (naive percentile
rank within complex/district, explicitly labeled as ignoring all feature
differences), Approach B (the real full-scale OLS-residual model, formula
sketch `ln_price_m2 ~ ln_area + building_age + floor_is_first +
floor_is_last + ceiling_height_m + former_dormitory + exchange_possible +
C(building_type) + C(district) + distance_to_center_km +
avg_price_m2_within_3km`, explicitly future work not run in this loop),
the trimmed sample-scale formula that `ranking_scaffold_code` (next task)
will actually run (`ln_price_m2 ~ ln_area + avg_price_m2_within_3km_median`,
explicitly labeled as a code-path check only, not a trustworthy
coefficient estimate), per-complex minimum-n rule (n>=8-10 for a fitted
fixed effect, falling back to district-model + `complex_median_price_m2`
adjustment below that), the full diagnostics checklist (adjusted R²,
residual-vs-fitted, QQ plot, VIF>10 rule with a concrete decision rule for
the expected `district`/`distance_to_center_km`/`avg_price_m2_within_3km`
collinearity, leave-one-complex-out or k-fold CV), the 500x500m
`grid_cell_id`-clustered standard-error treatment (matching
`01_near_stations_final.py`'s exact `get_robustcov_results(cov_type=
"cluster", groups=..., use_correction=True, df_correction=True,
use_t=True)` call pattern, confirmed by reading that script directly), how
the two approaches combine into one side-by-side presentation plus a
z-scored composite `good_deal_score`, and a "what would invalidate this"
section (dummy-overfitting risk, the ~22-24% `complex_name` coverage gap
requiring a district-only fallback, the unresolved station/mall
reference-data gap).

**Documentation-only task — no code was written or run** (that is
`ranking_scaffold_code`, next). Verification consisted of cross-checking
claims against real files rather than assumption:

- Read `01_near_stations_final.py` directly (lines 40-80) to confirm the
  exact OLS-fit and clustered-covariance call pattern
  (`smf.ols(formula, data=sample, missing="raise").fit()` then
  `ols.get_robustcov_results(cov_type="cluster", groups=groups,
  use_correction=True, df_correction=True, use_t=True)` via
  `helpers.grid_groups(used)`) before writing it into section 6, rather
  than reconstructing it from memory/guessing.
- Read the real header row of `methodology/samples/sample_features.csv`
  (output of `feature_scaffold_code`) and confirmed every field name used
  in the spec — `ln_price_m2`, `ln_area`, `avg_price_m2_within_3km_mean`/
  `_median`, `district`, `complex_name`, `complex_median_price_m2`,
  `district_median_price_m2`, `grid_cell_id`, `distance_to_center_km` —
  matches exactly:
  ```
  source_row,url,price_tenge,...,price_m2,ln_price_m2,ln_area,fetch_year,
  building_age,kitchen_area_ratio,distance_to_center_km,...,grid_cell_id,
  avg_price_m2_within_3km_mean,avg_price_m2_within_3km_median,
  n_neighbors_3km,low_confidence_spatial,complex_median_price_m2,
  complex_listing_count,complex_insufficient_n,district_median_price_m2,
  district_listing_count,district_insufficient_n
  ```
- Cross-checked the `min_n=5` threshold already used for
  `complex_median_price_m2`/`district_median_price_m2` in `FEATURE_SPEC.md`
  and deliberately set the new per-complex OLS fixed-effect threshold
  higher (n>=8-10), with an explicit note explaining why a fitted dummy
  coefficient needs more data than a simple group median.
- Chose `avg_price_m2_within_3km_median` (not `_mean`) for the trimmed
  sample-scale formula, consistent with `FEATURE_SPEC.md`'s stated
  preference for the median as the more robust primary spatial-smoothing
  signal — checked that field name exists in the real CSV header above
  before writing it into the formula.

Next: ranking_scaffold_code (depends_on ranking_methodology_spec AND
feature_scaffold_code, both now true).

### 2026-09-01 — feature_scaffold_code completed

Implemented `methodology/scripts/feature_engineering.py` per `FEATURE_SPEC.md`:
`haversine_km` with an inline-literal self-check (Baiterek Tower → Khan
Shatyr, asserted in the 0.5-3.0 km range — both well-known close-together
landmarks, loose bound only to catch a broken formula, not to pin an exact
figure); `compute_avg_price_m2_within_radius` (O(n²) pairwise haversine,
adds `avg_price_m2_within_3km_mean/median`, `n_neighbors_3km`, and a
`low_confidence_spatial` flag when `n_neighbors_3km < 3`, docstring TODO
for a BallTree spatial index at full scale, not implemented here);
`compute_group_aggregate` (median/count/`insufficient_n` flag, `min_n=5`
default) used for both `complex_median_price_m2` and
`district_median_price_m2`; module-level `CITY_CENTER`, `MALLS`,
`PARK_POINT`, `EMBANKMENT_POINT` constants (each commented
`# TODO: approximate, manually sourced, verify before use`) and an empty
`STATIONS = {}` stub with a comment explaining the original source file is
lost; `near_mall_1km` computed as OR across all non-`khan_shatyr` mall
dummies per the spec (khan_shatyr itself is still given its own
`mall_khan_shatyr_1km` distance column, just excluded from the OR, since
it is the omitted reference category); a fresh 500m lat/lon grid for
`grid_cell_id` (approximated at Astana's ~51.1°N latitude for the
longitude step, not matched to the lost original DiD grid, per spec's
explicit allowance).

`--sample` mode joins `sample_parsed_preview.csv` (parser output, no
lat/lon/fetched_at) with the raw `sample_rows.csv` on `source_row` — the
cross-file join FEATURE_SPEC.md flagged as required — computes
`price_m2`/`ln_price_m2`/`ln_area`/`building_age`/`kitchen_area_ratio`,
all spatial features, and both group aggregates for every row, and writes
`methodology/samples/sample_features.csv`.

**Verification — `python methodology/scripts/feature_engineering.py --sample`**
(real run against the real 16-row sample, joined with the raw fixture):
```
ok   haversine_km self-check: Baiterek Tower -> Khan Shatyr = 1.619 km
wrote 16 feature rows to .../methodology/samples/sample_features.csv
price_m2 computed: 15/16
n_neighbors_3km stats:
count    16.000000
mean      4.875000
std       3.556684
min       0.000000
25%       1.000000
50%       6.500000
75%       8.000000
max       9.000000
low_confidence_spatial (n_neighbors_3km < 3): 5/16
complex_median_price_m2 present: 8/16
district_median_price_m2 present: 15/16
```

**Eyeballed `sample_features.csv` for plausibility (real values, not
assumed):**
- The 11 Алматы-district rows sit in a tight geographic cluster
  (lat ~51.11-51.16, lon ~71.47-71.51) and correctly get `n_neighbors_3km`
  of 3-9 with mutually similar `avg_price_m2_within_3km_median` values
  (~520,000-524,000 ₸/m² for most of them — makes sense, they're each
  other's neighbors). `district_listing_count=11`,
  `district_insufficient_n=False` (11 ≥ `min_n=5`).
- Deliberately isolated rows get `n_neighbors_3km=0` or `1` as expected
  from the sample's intentional geographic spread (per `sample_fixture`):
  `source_row=2` (Turan Tower, Нура district, lon 71.4027 — ~7.5km west of
  the Алматы cluster) → `n_neighbors_3km=0`. `source_row=12` (Sanara) and
  `source_row=11` (MOD Frame), both Есильский district and only ~1.3km
  apart from each other but far from everything else, each get
  `n_neighbors_3km=1` — they are each other's only neighbor, a real
  pairwise sanity check that the radius logic is symmetric and correct.
  `source_row=15` (Акерке 2, Сарыарка, lat 51.1686 — northernmost point)
  → `n_neighbors_3km=0`.
- The error row (`source_row=87`) correctly has `price_m2`, all engineered
  numeric features, and `n_neighbors_3km=0` / `low_confidence_spatial=True`
  (no lat/lon to compute distances from) — matches the spec's documented
  missingness expectation exactly, not an outlier or bug.
- `complex_median_price_m2` present on exactly 8/16 rows (same 8 rows with
  `complex_name`), and `complex_listing_count=1` with
  `complex_insufficient_n=True` for every one of them — expected and
  called out by the task steps ("most sample rows may lack enough
  same-complex peers"), since 16 total rows across 8 distinct complexes
  can't reach `min_n=5` in any single complex at this sample size.
- `kitchen_area_ratio` for `source_row=2`: `10.0 / 65.3 = 0.15314...`,
  matches the script's printed float exactly.
- `mall_khan_shatyr_1km=True` and `mall_keruen_1km=True` both hold for
  `source_row=2` (it happens to be close to central Astana even though
  it's geographically isolated from the Алматы-district cluster of other
  sample rows) — `near_mall_1km=True` correctly derives from
  `mall_keruen_1km` (non-reference) alone, per the spec's OR-except-
  khan_shatyr rule, confirmed by inspecting the raw boolean columns in
  the CSV rather than trusting the derived column blindly.

No function in this file was run against `AstanaLinksParserJune2026_parsed.csv`
or `2025_data.csv`.

Next: ranking_methodology_spec and eda_plan are both now unblocked
(`depends_on: ["feature_engineering_spec"]`, which is `true`); the plan's
ordering lists `ranking_methodology_spec` first.

### 2026-09-01 — feature_engineering_spec completed

Wrote `methodology/FEATURE_SPEC.md`: core hedonic features reconstructed
from the structure of `01_near_stations_final.py` and
`02_between_stations_final.py`; the user-requested `avg_price_m2_within_3km`
spatial feature (mean + median + `n_neighbors_3km` reliability count,
configurable radius); additional spatial/comparative features
(`distance_to_center_km`, the station/line distance TODO stub,
mall/park/embankment 1km dummies reconstructed from `AMENITY_TERMS` in
`02_between_stations_final.py`, `complex_median_price_m2` /
`district_median_price_m2` with `min_n` thresholds, `kitchen_area_ratio`,
`grid_cell_id`); a field-dependency table cross-checked against real
column names; and a known-data-quality-risks section.

**Documentation-only task — no code was written or run** (that is
`feature_scaffold_code`, next). Verification consisted of cross-checking
every claim against real files rather than assumption:

- Searched the full repo tree for `run_main_model.py` and
  `export_current_models_two_tabs.py` (the source of the exact `CONTROLS`
  formula, the real station/line reference table, and the real mall/park
  coordinates) — confirmed **not present anywhere in this repo**
  (`find ... -iname "run_main_model.py" -o -iname "export_current_models*"`
  returned nothing). This is why `distance_to_nearest_station_m` /
  `distance_to_line_m` is documented as an explicit empty TODO stub rather
  than implemented with fabricated coordinates, and why the mall/park/
  city-center coordinates in FEATURE_SPEC.md are labeled approximate and
  flagged for manual verification rather than presented as sourced from
  the original scripts.
- Read `01_near_stations_final.py` and `02_between_stations_final.py`
  directly to confirm the real `AMENITY_TERMS` list (`near_park_1km,
  near_embankment_1km, near_mall_1km, mall_mega_silkway_1km,
  mall_asia_park_1km, mall_keruen_1km, mall_keruen_city_1km,
  mall_saryarka_1km`) and the `Khan Shatyr` omitted-reference-category
  assertion (`source.MALL_REFERENCE != "Khan Shatyr"` raises) copied
  verbatim into FEATURE_SPEC.md's table.
- Read `methodology/samples/sample_parsed_preview.csv` (the real output of
  `build_parser_script`) directly and counted missingness per field by
  hand against its real 16 rows rather than guessing, catching and fixing
  three numbers that were wrong in an earlier draft of this doc:
  `kitchen_area_m2` missing is 11/16 (not 10/16 as first estimated —
  present only on source_row 2, 3, 7, 15, 97); `building_type` missing is
  2/16 (not 1/16 — source_row 20 AND the error row source_row=87, not just
  20); `former_dormitory` missing is 5/16 (source_row 12, 97, 133, 161,
  87), `exchange_possible` missing is 2/16 (source_row 12, 87);
  `ceiling_height_m` missing is 4/16 (source_row 20, 58, 97, 87). All
  counts in the final doc are these hand-verified real numbers.
- Discovered and documented a real, non-obvious cross-file gap while
  writing this: `parse_listings.py --sample`'s output
  (`sample_parsed_preview.csv`) does **not** carry `lat`, `lon`, or
  `fetched_at` through (confirmed by inspecting its real header row —
  those three columns are absent), because `parse_row()` never receives or
  returns them. Those fields exist only in the raw `sample_rows.csv`.
  Documented this explicitly at the top of FEATURE_SPEC.md and in the
  field-dependency section so `feature_scaffold_code` (next task) knows up
  front that it must load and join both CSVs on `source_row` for
  `building_age` (needs `fetched_at`) and the spatial features (need
  `lat`/`lon`), instead of discovering it via a runtime error.

Next: feature_scaffold_code (depends_on feature_engineering_spec, now
satisfied).

### 2026-09-01 — build_parser_script completed

Implemented `methodology/scripts/parse_listings.py` per `PARSING_SPEC.md`:
the ordered-label alternation regex + `re.finditer`-position-sort +
slice-between-labels core (`segment_labels`), dedicated price/district
prefix regexes, and a `field()` merge helper (advert_info value wins,
parameters value fills the gap only when advert_info's is missing/empty).

**Deliberate simplification vs. the spec's literal wording, verified to
produce identical results on every documented test case:** PARSING_SPEC.md
describes the pipe-delimited fallback as "split `parameters` on `' | '`,
re-run the label logic per segment." In the actual implementation,
`segment_labels()` is run directly on the raw (unsplit) `parameters`
string — `finditer` finds label positions regardless of what separates
them, and `|`/`" | "` were simply added to the value-strip character set.
This produces the same output as segment-by-segment splitting for every
pipe-fallback row in the sample (verified below) with much less code, so
no separate pipe-splitting code path was written. Documented as a comment
in the script.

**Bug found and fixed during verification (a real, not hypothetical,
mismatch with the spec's literal formula text):** the spec's formula for
`is_under_construction` is written as `year > fetch_year`, but its own
worked test case (row 0, `build_year=2026`, `fetched_at=2026-07-13`)
labels that row "under construction" — which requires `>=`, not `>`
(`2026 > 2026` is `False`). Implemented `>=` (a listing built in the same
calendar year it was fetched is still being sold pre-construction on
krisha.kz) and added a code comment explaining the discrepancy. Flagging
here for the `methodology_consolidation` task's doc/code reconciliation
pass — PARSING_SPEC.md's prose should be corrected to `>=` to match its
own test case and this implementation.

**Verification — `python methodology/scripts/parse_listings.py --selftest`**
(35 inline-literal checks pulled from PARSING_SPEC.md's real test-case
strings, no CSV access, runs in a fraction of a second):
```
ok   price (plain)
ok   district prefix regex captures label text
ok   complex_name
ok   build_year
ok   is_under_construction
ok   area not concatenated with kitchen
ok   kitchen_area_m2 (integer form)
ok   apartment_condition rough
ok   ceiling_height_m (decimal)
ok   former_dormitory False
ok   exchange_possible False (capitalized value, case-insensitive)
ok   floor/floor_total
ok   floor_is_first/last (neither)
ok   installment price (not ^-anchored)
ok   price_is_installment flag
ok   district despite installment words
ok   floor absent -> None, not False
ok   ceiling_height_m bare integer
ok   balcony free text not swallowed
ok   balcony_glazed separately True
ok   bathroom from advert_info
ok   condition needs_renovation bucket
ok   security multi-word item preserved
ok   floor_is_first True
ok   exchange_possible True
ok   pipe-fallback gap-fill no-op (advert_info already complete)
ok   building_type None when absent from both columns
ok   complex_name None (standalone)
ok   floor_is_last True (6 of 6)
ok   area from pipe segment with two labels
ok   kitchen_area from same pipe segment
ok   condition unknown (absent from both columns)
ok   error row price None
ok   error row warning
ok   error row rooms_bucket None

selftest: 35 checks passed
```

**Verification — `python methodology/scripts/parse_listings.py --sample`**
(reads `methodology/samples/sample_rows.csv`, encoding='utf-8', writes
`methodology/samples/sample_parsed_preview.csv`):
```
wrote 16 parsed rows to .../methodology/samples/sample_parsed_preview.csv
error rows (status=error): 1
pipe-delimited fallback detected: 5
price parsed: 15/16
district parsed: 15/16
area_total_m2 parsed: 15/16
complex_name present: 8/16
```
These match the fixture exactly: 1 error row (source_row=87), 5
pipe-fallback rows (source_row 12, 97, 20, 133, 161), 15/16 non-error rows
have price/district/area, and complex_name present on exactly the 8 rows
documented in `sample_rows README.md` (source_row 2, 3, 7, 15, 8, 12, 97,
11).

**Real before/after examples (eyeballed every one of the 16 output rows
against the original `sample_rows.csv` text, read back via the Read tool
— never printed raw Cyrillic to the Windows console):**

1. `source_row=2` (Turan Tower, typical case): `advert_info` "56 500 000 ₸
   ... Нура р-н ... Тип дома монолитный Жилой комплекс Turan Tower Год
   постройки 2026 Этаж 5 из 27 Площадь 65.3 м², Площадь кухни — 10 м²
   Состояние квартиры черновая отделка" → `price_tenge=56500000,
   district=Нура, complex_name="Turan Tower", build_year=2026,
   is_under_construction=True, floor=5, floor_total=27, area_total_m2=65.3,
   kitchen_area_m2=10.0, apartment_condition=rough`. Area correctly not
   concatenated with kitchen area.

2. `source_row=12` (Sanara, hardest real case — installment price prefix +
   pipe-delimited fallback + missing floor): `advert_info` "от 78 950 600 ₸
   Рассрочка Город Астана, Есильский р-н ... Тип дома монолитный Жилой
   комплекс Sanara Год постройки 2027 Площадь 106.69 м² ..." (no `Этаж`
   label anywhere) → `price_tenge=78950600, price_is_installment=True,
   district=Есильский, complex_name="Sanara", build_year=2027,
   is_under_construction=True, floor=<empty/None>,
   floor_is_first=<empty/None>, area_total_m2=106.69,
   parse_warnings=['pipe-delimited parameters fallback detected']`. Floor
   correctly `None` (unknown), not `False`.

3. `source_row=20` (standalone, missing building type, pipe fallback):
   `advert_info` "22 400 000 ₸ ... Алматы р-н ... Год постройки 1989 Этаж
   6 из 6 Площадь 51 м² Балкон балкон Бывшее общежитие нет Возможен обмен
   Нет" (no `Тип дома` or `Жилой комплекс` anywhere in either column) →
   `building_type=<empty/None>, complex_name=<empty/None>, floor=6,
   floor_total=6, floor_is_last=True, former_dormitory=False,
   exchange_possible=False`. Confirms gap-fill correctly leaves a field
   `None` when neither column has it, rather than inventing a value.

Deleted the scratch dump script (`ralpheasy/tmp_dump.txt`, used only to
read raw sample text via the Read tool during development) after use — not
part of the deliverable.

Next: feature_engineering_spec (depends_on build_parser_script, now
satisfied).

### 2026-09-01 — field_extraction_spec completed

Wrote `methodology/PARSING_SPEC.md`: the label-segmentation parsing
strategy (ordered label list + `re.finditer` position-sort + slice-between-
labels, with the critical ordering rule that `Площадь кухни` must precede
`Площадь` and `Балкон остеклён` must precede `Балкон`), price/district
prefix extraction, field-specific post-processing rules, the confirmed
pipe-delimited `parameters` fallback, and the confirmed room-count data
gap — per the task's required sections.

Every regex/rule is backed by a literal test-case string pulled directly
from `methodology/samples/sample_rows.csv` (read via
`pandas.read_csv(encoding='utf-8')`, dumped to a scratch UTF-8 file, read
back with the Read tool, then deleted — never printed raw to the Windows
console).

**Real edge cases the sample fixture surfaced that sharpened the spec
beyond the plan's original sketch (documented verification, not assumed):**
- Price regex must not anchor to `^`: row `source_row=12` has
  `"от 78 950 600 ₸ Рассрочка Город Астана, ..."` — an installment-plan
  listing with `"от "` before the digits and `"Рассрочка"` after `₸`,
  before the district segment. Spec now uses `re.search` for
  `(\d[\d\s]*)\s*₸` (first match) instead of a `^`-anchored regex, and
  documents that district-prefix extraction must not assume it
  immediately follows the price match.
- `Этаж` (floor) is not always present: row `source_row=12` (the `Sanara`
  pre-construction listing, build year 2027) has no `Этаж` label anywhere
  in `advert_info` — floor/floor_total/floor_is_first/floor_is_last must
  all be `None` (unknown), not `False`.
- `Состояние квартиры` free-text values go beyond the two obvious buckets:
  row `source_row=58` has `"не новый, но аккуратный ремонт"` (comma
  inside the value itself, correctly preserved since only `Безопасность`
  is comma-split) — added a third `needs_renovation` enum bucket.
- Real label-ordering bug confirmed via row `source_row=21`:
  `"Балкон балкон Балкон остеклён да ..."` — if `Балкон` were ordered
  before `Балкон остеклён` in the alternation regex, segmentation would
  mis-split and lose the `Балкон остеклён` field. Spec documents this as a
  concrete (not hypothetical) real-data test case.
- Pipe-delimited fallback (row `source_row=97`) has a single `" | "`
  segment containing two labels together
  (`"Площадь 39 м², Площадь кухни — 10 м²"`), confirming label-
  segmentation must still run within/across pipe segments, not assume
  one label per segment.

**Verification:** re-read every literal string quoted in
`PARSING_SPEC.md` against the actual `sample_rows.csv` contents (dumped
via pandas, read back with the Read tool) row by row to confirm no
transcription errors; all matched exactly. This was a documentation-only
task — no code was written or run (that is `build_parser_script`, next).

Next: build_parser_script (depends_on field_extraction_spec, now
satisfied).

### 2026-09-01 — sample_fixture completed

Installed `pandas` and `statsmodels` into the system Python (none were
present before; needed for this and every later task). Opened
`AstanaLinksParserJune2026_parsed.csv` with `pandas.read_csv(encoding='utf-8')`
in a single read pass (34,766 rows, columns: `source_row, url, status,
http_status, advert_info, parameters, lat, lon, fetched_at, error`) to
compute coverage stats and hand-pick candidate rows for each required edge
case. No parsing/feature/ranking logic was run against the full file —
only exploratory `.str.contains()` counts and row selection.

Coverage stats observed on the full file (for context only, not written
anywhere as a pipeline result): `status` ok=33809/error=957;
`Жилой комплекс` present in 27,121 rows (~78%) vs absent in 7,645 (~22%);
pipe-delimited `parameters` fallback (`' | '` + `р-н`) in 1,659 rows;
missing kitchen area in 15,603 rows; missing apartment condition in 13,961
rows; missing building type in 2,525 rows; build_year >= 2026 in 4,389
rows. These match the ranges asserted in plan.md.

Hand-picked 16 rows (by dataframe positional index, since `source_row=87`
turned out to be duplicated across two positional rows in the raw file —
selecting by `source_row` alone would have been ambiguous) covering: (a)
typical rows with `Жилой комплекс` + full params, (b) standalone rows
without `Жилой комплекс`, (c) the pipe-delimited `parameters` fallback
format (confirmed present, including the exact `Sanara`/`Есильский`
example named in the plan), (d) one `status='error'`/`http_status=404` row
with empty advert_info/parameters/lat/lon, (e) rows missing kitchen area,
apartment condition, or building type, (f) rows with build_year >= 2026
(under construction). Saved to `methodology/samples/sample_rows.csv`
(utf-8, original columns preserved) and documented per-row edge-case
coverage in `methodology/samples/README.md`.

**Verification (real command output):**
```
wrote 16 rows
[2, 3, 7, 15, 8, 12, 97, 20, 21, 37, 43, 58, 133, 161, 87, 11]
```
Re-read the written file back with pandas (utf-8) to confirm it round-trips:
```
(16, 10)
```
Spot-checked lat/lon spread: latitudes 51.078295-51.168629 (~10km N-S),
longitudes 71.396319-71.512703 (~8km E-W), with a mix of tightly clustered
points and isolated ones (e.g. row source_row=11 at 51.078295/71.435875 is
the southwesternmost point) so `n_neighbors_3km` will vary meaningfully in
the later feature_scaffold_code task. Row source_row=87 (the error row)
has NaN lat/lon as expected, confirmed excluded from any distance
calculation consideration.

Deleted the scratch exploration scripts (`ralpheasy/tmp_explore.py`,
`ralpheasy/tmp_candidates.py`, `ralpheasy/tmp_build_sample.py`, and their
`_output.txt` files) after use — they are not part of the deliverable.

Next: field_extraction_spec (depends_on sample_fixture, now satisfied).

### 2026-09-01 — bootstrap_git completed

Repo had no `.git` directory at all (confirmed via `test -d .git` -> "NO GIT"
before starting). Ran `git init` at the repo root
(`C:\Users\DIT_Admin\Documents\Work\Krisha`). Created `.gitignore` at the
repo root excluding `__pycache__/`, `*.pyc`, `.venv/`, `*.tmp`,
`/tmp/ralph_*`, and the large raw/output files: `2025_data.csv`,
`AstanaLinksParserJune2026_parsed.csv`, `01_near_stations_final.xlsx`,
`02_between_stations_final.xlsx`, `02_between_stations_final_latest.xlsx`,
`Heatmap_price_m2_Astana_2025.png`, `Heatmap_price_m2_Astana_2026.png`.

`git commit` failed initially due to missing identity (empty
`git config user.name`/`user.email`). Set LOCAL-only config for this repo:
`git config --local user.name "Ralph Loop Agent"` and
`git config --local user.email "ansar.seidakhmet@gmail.com"` (global git
config was never touched).

Staged everything with `git add -A` and committed with message
"Initial commit: ralph loop bootstrap, raw data excluded via .gitignore"
(commit `765bab0`).

**Verification (real command output):**
```
=== git log ===
765bab0 Initial commit: ralph loop bootstrap, raw data excluded via .gitignore
=== git status ===
On branch master
nothing to commit, working tree clean
=== git ls-files (checking for large files) ===
NONE FOUND (correct)
```
Confirmed exactly 1 commit exists, working tree is clean, and none of the
7 excluded large files show up in `git ls-files`. Files that WERE tracked:
`.gitignore`, `01_near_stations_final.py`, `02_between_stations_final.py`,
`LinksParser`, and the `ralpheasy/` directory contents (plan, activity,
prompt, guide, helper scripts).

Next: sample_fixture (depends_on bootstrap_git, now satisfied).

### 2026-09-01 — Loop initialized

Plan created: ralpheasy/plan.md with 11 tasks covering git bootstrap,
sample fixture creation, field-extraction spec + parser implementation
(run on the real sample), feature-engineering spec + real feature
computation on the sample, ranking-methodology spec + a real (trimmed,
sample-scale) OLS fit on the sample, EDA plan, and final METHODOLOGY.md
consolidation. No processing has occurred against the full dataset, and
none should at any point in this loop.

Dataset scope: AstanaLinksParserJune2026_parsed.csv is primary; 2025_data.csv
is out of scope for this run. All real execution in this loop is confined
to a ~15-20 row sample fixture created in the sample_fixture task.

No tasks completed yet. Next: bootstrap_git.
