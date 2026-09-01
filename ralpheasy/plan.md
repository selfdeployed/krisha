# Krisha "Best Offer" Methodology — Plan

## Overview

Goal: produce a written **methodology** (design docs + working utility code,
run end-to-end only on a small real sample) for turning raw scraped
krisha.kz text into structured listing data, engineering ranking features
(including a spatial 3km-radius average price/m² feature), and
scoring/ranking listings as "best deal" per residential complex (ЖК) and
per district.

Primary dataset for this run: `AstanaLinksParserJune2026_parsed.csv` (the
2026 file). `2025_data.csv` is explicitly OUT OF SCOPE for this run.

Hard constraint for every task below: **no script may ever be run against
the full `AstanaLinksParserJune2026_parsed.csv` or `2025_data.csv`
(~35k / ~38k rows).** All real execution happens only against
`methodology/samples/sample_rows.csv`, a fixed hand-picked fixture of
~15-20 rows created in the `sample_fixture` task. Reading the full CSV
once, in that one task, to hand-pick the sample is fine; running a
parser/feature/ranking pipeline across the full file, in any task, is not.
Within that constraint, DO actually run the code (parsing, feature
engineering, OLS fitting) against the real sample and produce real output
— synthetic/fabricated data is a fallback only for isolated pure-math unit
checks (e.g. the haversine formula), never a substitute for exercising the
pipeline on real numbers.

Deliverables live under `methodology/` (specs, scripts, samples) with the
final consolidated `METHODOLOGY.md` at the repo root.

## Agent Instructions

1. Read `activity.md` first to understand current state.
2. Find the next task below whose `passes` field is set to false and whose
   `depends_on` tasks all have their `passes` field set to true.
3. Set that task's `"passes"` to `"in_progress"`.
4. Do only the work described in that task's `steps`. Do not start other
   tasks even if they look quick.
5. Verify using the method specified in the task — run the real code
   against the real sample fixture wherever the task calls for it; only
   fall back to synthetic/fabricated data for isolated pure-math checks.
   Never run anything against the full CSVs.
6. Update `"passes"` to `true` only after verification passes.
7. Append a dated entry to `activity.md` (what changed, how it was
   verified, with real example output pasted in).
8. Make exactly one git commit for this task only.

**Important:** Only modify the `passes` field (and, transiently, set it to
`"in_progress"` while working). Do not remove, renumber, or rewrite tasks
or their `depends_on`.

## Completion Criteria

All tasks below have their `passes` field set to true.

## Task List

```json
[
  {
    "id": "bootstrap_git",
    "category": "setup",
    "description": "One-time repo initialization. This directory has no git history at all. Initialize git once, add a .gitignore that excludes the large raw data files, and make an initial commit before any methodology work begins. This is a deliberate one-time bootstrap, not a violation of the general 'don't git init' rule (that rule is about not re-initializing an already-set-up repo).",
    "steps": [
      "Check for a .git directory at the repo root (parent of ralpheasy/). If it already exists, skip straight to the verification step below and mark this task true.",
      "Run 'git init' at the repo root.",
      "Create a .gitignore at the repo root containing at least: __pycache__/, *.pyc, .venv/, *.tmp, /tmp/ralph_*, and the large raw/output files that are not generated or modified by this loop: 2025_data.csv, AstanaLinksParserJune2026_parsed.csv, 01_near_stations_final.xlsx, 02_between_stations_final.xlsx, 02_between_stations_final_latest.xlsx, Heatmap_price_m2_Astana_2025.png, Heatmap_price_m2_Astana_2026.png.",
      "If 'git commit' fails due to missing identity, set LOCAL (not global) config only for this repo: 'git config user.name' and 'git config user.email'. Never touch global git config.",
      "Stage everything with 'git add -A' and commit with message 'Initial commit: ralph loop bootstrap, raw data excluded via .gitignore'.",
      "Verify with 'git log --oneline' (at least 1 commit) and 'git status' (clean working tree), and confirm the large files above do NOT show up as tracked ('git ls-files' should not list them).",
      "Do not run 'git init' again in any later task."
    ],
    "passes": true,
    "depends_on": []
  },
  {
    "id": "sample_fixture",
    "category": "data-sampling",
    "description": "Create a small, fixed, hand-picked sample of rows from AstanaLinksParserJune2026_parsed.csv covering the range of formats found in the data. This is the shared test fixture every later parsing/feature/ranking task runs against for real. A single read-through of the file to select rows is fine; no later task may build a pipeline against the full file.",
    "steps": [
      "Open AstanaLinksParserJune2026_parsed.csv with Python using explicit encoding='utf-8' (pandas.read_csv(..., encoding='utf-8') or the csv module). Note: default Windows console tools (raw 'type', non-UTF8 pipes) can mis-decode the Cyrillic text as mojibake -- that is a display/tool artifact, not file corruption. Always open and write with encoding='utf-8' explicitly, including when printing to the console (write results to a UTF-8 file instead of printing raw Cyrillic to the Windows console, which uses cp1251 and will crash on some characters like the tenge sign).",
      "Hand-pick ~15-20 rows covering: (a) rows WITH 'Жилой комплекс' and a full parameters string (typical case), (b) rows WITHOUT 'Жилой комплекс' (standalone listings, e.g. rows whose advert_info has only Тип дома/Год постройки/Этаж/Площадь), (c) at least 1 row where parameters contains ' | ' pipe-delimited content that duplicates advert_info-style fields (search for parameters containing ' | ' and 'р-н' -- this fallback format is confirmed present in the data, e.g. 'Город Астана, Есильский р-н показать на карте | Тип дома монолитный | Жилой комплекс Sanara | Год постройки 2027 | Площадь 106.69 м² | Санузел 2 с/у и более | Высота потолков 3 м'), (d) at least 1 row with status='error' / http_status=404 and empty advert_info/parameters, (e) rows missing 'Площадь кухни', missing 'Состояние квартиры', or missing 'Тип дома', (f) if findable, one row with build year >= current year (under construction). Ensure the picked rows span a reasonable spread of lat/lon (not all in one spot) so the 3km-radius spatial feature has something to compute in task feature_scaffold_code.",
      "Save the picks with the original columns to methodology/samples/sample_rows.csv.",
      "Write methodology/samples/README.md documenting, per row, which edge case it was chosen to cover.",
      "Do not scan or process the file for any purpose beyond selecting this fixed sample."
    ],
    "passes": true,
    "depends_on": ["bootstrap_git"]
  },
  {
    "id": "field_extraction_spec",
    "category": "documentation",
    "description": "Write methodology/PARSING_SPEC.md: the field-extraction design for advert_info and parameters, with concrete regexes and real test cases from the sample fixture.",
    "steps": [
      "Document the core parsing strategy: a label-segmentation algorithm, not one-off per-field regex-with-lookahead. Define an ORDERED list of known label tokens (order matters -- more specific labels must be listed before shorter labels they contain as a prefix, e.g. 'Площадь кухни' before 'Площадь', 'Балкон остеклён' before 'Балкон'). advert_info labels (after price/district prefix is stripped): Тип дома, Жилой комплекс, Год постройки, Этаж, Площадь кухни, Площадь, Состояние квартиры, Санузел. parameters labels: Санузел, Балкон остеклён, Балкон, Дверь, Телефон, Интернет, Парковка, Квартира меблирована, Пол, Высота потолков, Безопасность, Бывшее общежитие, Возможен обмен. Algorithm: find all label occurrences by position via a single alternation regex (re.finditer), sort by position, and take each label's value as the text between its end and the next label's start (or end of string for the last label).",
      "Document that price and the city/district prefix are extracted first with dedicated regexes, before label-segmentation: price ^([\\d\\s]+)\\s*\\u20b8 (strip internal spaces, cast to int); district prefix Астана,\\s*([А-Яа-яёЁ\\-\\s]+?)\\s*р-н показать на карте (captures the district label text as scraped, e.g. 'Есильский', 'Нура' -- do NOT silently normalize to an authoritative district list here; that audit is deferred to the eda_plan task).",
      "Document field-specific post-processing rules with these confirmed real test cases (verified directly against the data): Тип дома\\s+(\\S+) -> монолитный/кирпичный/панельный/иной, OPTIONAL (absent on some standalone listings). Год постройки\\s+(\\d{4}) -> int, flag is_under_construction = year > current fetch year. Этаж\\s+(\\d+)\\s+из\\s+(\\d+) -> floor, floor_total ints; derive floor_is_first = floor==1, floor_is_last = floor==floor_total. Площадь\\s+([\\d]+(?:[.,]\\d+)?)\\s*м\\u00b2 -> area_total_m2 float (comma or dot decimal; verified this naturally does not match 'Площадь кухни ...' since 'кухни' is not a digit, so no lookahead is needed -- test case: 'Площадь 65.3 м², Площадь кухни — 10 м²' must yield area_total_m2=65.3 only). Площадь кухни\\s*[—\\-–]\\s*([\\d]+(?:[.,]\\d+)?)\\s*м\\u00b2 -> kitchen_area_m2 float, OPTIONAL (absent in several samples). Высота потолков\\s+([\\d]+(?:[.,]\\d+)?)\\s*м -> ceiling_height_m float. Состояние квартиры value from label-segmentation is a free-text phrase (e.g. 'черновая отделка', 'свежий ремонт') -- normalize into a small enum (rough/none, fresh_renovation, needs_renovation, unknown) rather than regexing every phrasing.",
      "Document the Жилой комплекс (complex_name) extraction via the label-segmentation approach (value is whatever text falls between 'Жилой комплекс' and the next known label), noting ~76-78% of rows have this label and ~22-24% do not (standalone listings) -- complex_name = None for those, not an error.",
      "Document Безопасность and comma-separated multi-value fields: split the label's value on ',' and trim, producing a list. Document Бывшее общежитие and Возможен обмен and Балкон остеклён as yes/no fields where the label-segmentation value is literally 'да'/'нет' (case-insensitive) -- normalize to bool.",
      "Document the confirmed pipe-delimited parameters fallback (verified directly against the real data): parameters sometimes contains ' | '-delimited content duplicating advert_info-style fields instead of amenities. Detector: parameters contains ' | ' AND matches the district-prefix pattern. Handling: split on ' | ', run the SAME district-prefix + label-segmentation logic per segment, and use extracted values to FILL GAPS ONLY (never overwrite a value already reliably extracted from advert_info).",
      "Document the confirmed data gap (verified: zero 'комнат' matches across 5,000 scanned rows in this dataset version): room count does not appear anywhere in advert_info or parameters. Specify handling: rooms field stays None; optionally derive rooms_bucket_estimated from area_total_m2 via a documented heuristic (e.g. <=30 studio, 30-45 1-room, 45-65 2-room, 65-90 3-room, >90 4+ room) with rooms_estimate_is_heuristic=True, with an explicit warning this heuristic must never be used as a hard OLS control without that caveat. Note as a FUTURE (out-of-scope) scraper enhancement: capturing the page <h1>/title text in LinksParser (which typically encodes 'N-комнатная квартира') as a new output column.",
      "For every regex/rule above, include the literal real sample string it was derived from (pulled directly from methodology/samples/sample_rows.csv) as a documented test case."
    ],
    "passes": true,
    "depends_on": ["sample_fixture"]
  },
  {
    "id": "build_parser_script",
    "category": "implementation",
    "description": "Implement methodology/scripts/parse_listings.py per PARSING_SPEC.md. Run it for real against the sample fixture (never the full CSVs).",
    "steps": [
      "Implement parse_row(advert_info: str, parameters: str, status: str) -> dict returning at least: price_tenge, city, district, building_type, complex_name, build_year, is_under_construction, floor, floor_total, floor_is_first, floor_is_last, area_total_m2, kitchen_area_m2, apartment_condition, bathroom, balcony, balcony_glazed, door, phone, internet, parking, furnished, flooring, ceiling_height_m, security_features (list), former_dormitory (bool), exchange_possible (bool), rooms (always None here), rooms_bucket_estimated, rooms_estimate_is_heuristic (bool), parse_warnings (list of strings for any field that failed to parse as expected).",
      "Implement the label-segmentation core (ordered label list + re.finditer position-sort + slice-between-labels) and the price/district prefix extraction, per the spec.",
      "Implement the parameters pipe-delimited-fallback detector and gap-fill logic per the spec.",
      "Add a `python parse_listings.py --selftest` mode that asserts expected parsed values against the literal test-case strings documented in PARSING_SPEC.md (inline string literals in the script, not file reads) -- this must run in well under a second with no CSV access. Run it now and confirm it passes.",
      "Add a `python parse_listings.py --sample` mode that reads ONLY methodology/samples/sample_rows.csv (encoding='utf-8'), applies parse_row to every row, and writes methodology/samples/sample_parsed_preview.csv (utf-8) plus a short stdout summary. Run it now.",
      "Eyeball sample_parsed_preview.csv row by row against the original sample_rows.csv and confirm each field matches the source text; fix the script if not, and re-run until it does.",
      "Paste 2-3 real before/after example rows into this task's activity.md log entry as evidence of verification.",
      "Do NOT run this script against AstanaLinksParserJune2026_parsed.csv or 2025_data.csv in this or any task."
    ],
    "passes": true,
    "depends_on": ["field_extraction_spec"]
  },
  {
    "id": "feature_engineering_spec",
    "category": "documentation",
    "description": "Write methodology/FEATURE_SPEC.md: the full feature list for the ranking model, combining the recovered DiD feature checklist, the user's requested 3km-radius spatial-smoothing feature, and other proposed spatial/comparative features.",
    "steps": [
      "List core hedonic features recovered from 01_near_stations_final.py / 02_between_stations_final.py's structure: ln_price_m2 (target), ln_area, building_age (= fetch_year - build_year, floored at 0, with is_under_construction flag for negative raw values), district (fixed effect / dummy), floor_is_first, floor_is_last, ceiling_height_m, former_dormitory, exchange_possible, building_type (dummy).",
      "Specify the user's requested spatial feature explicitly: avg_price_m2_within_3km -- for each listing, the (robust) average price/m2 of OTHER listings within a 3km haversine radius using lat/lon, excluding the listing itself. Report BOTH mean and median (median more robust to outliers) plus n_neighbors_3km (count of comparables found) as a reliability weight -- listings with very few 3km neighbors should be flagged low-confidence. The radius should be a configurable parameter, not hardcoded.",
      "Propose additional spatial/comparative features, each with a one-line justification: distance_to_center_km (haversine to a city-center landmark point, e.g. Baiterek Tower ~51.1282N 71.4306E -- flag 'verify precision before production use'), distance_to_nearest_station_m / distance_to_line_m (reusing the station_distance_m / line_distance_m concept from the DiD scripts -- explicitly note the original station-coordinate source file is lost, so this requires a NEW manually-curated reference table before it can actually be computed -- leave as a TODO stub), mall/park/embankment 1km dummies (reconstruct the confirmed reference set from 02_between_stations_final.py: near_park_1km, near_embankment_1km, near_mall_1km, mall_mega_silkway_1km, mall_asia_park_1km, mall_keruen_1km, mall_keruen_city_1km, mall_saryarka_1km, with Khan Shatyr as the omitted reference category -- reconstruct approximate coordinates for these named landmarks as a small hardcoded table, explicitly flagged 'approximate, manually sourced, verify before use'), complex_median_price_m2 and complex_listing_count (only computed when complex_listing_count >= a minimum n, e.g. 5), district_median_price_m2 and district_listing_count, kitchen_area_ratio (kitchen_area_m2 / area_total_m2, when known), grid_cell_id (500x500m spatial grid, reused from the DiD scripts' clustering pattern -- useful later for clustering OLS standard errors).",
      "For every feature, specify: exact formula/derivation, which parse_listings.py output field(s) it depends on (must match field names exactly), whether it is a hard control or an optional/flagged-low-confidence one, and its expected missingness rate given known data gaps (e.g. complex_median_price_m2 unavailable for the ~22-24% of listings with no complex_name).",
      "Add a short 'known data-quality risks' subsection: mall/station reference coordinates are unverified reconstructions (need manual sourcing before production use); district label strings are used as scraped and not yet normalized against an authoritative list (deferred to eda_plan); rooms is not available in this dataset version."
    ],
    "passes": false,
    "depends_on": ["build_parser_script"]
  },
  {
    "id": "feature_scaffold_code",
    "category": "implementation",
    "description": "Implement methodology/scripts/feature_engineering.py per FEATURE_SPEC.md. Run the real feature functions against the actual parsed sample (sample_parsed_preview.csv from build_parser_script) to produce real feature values -- never against the full dataset.",
    "steps": [
      "Implement haversine_km(lat1, lon1, lat2, lon2) -> float. Add a quick inline-literal check: a hand-picked pair of well-known Astana coordinates with a documented approximate expected distance. This is the one place a pure-math inline check (not the sample fixture) is appropriate.",
      "Implement compute_avg_price_m2_within_radius(df, radius_km=3.0, stat='median') -> adds avg_price_m2_within_3km, n_neighbors_3km columns via straightforward pairwise haversine (fine at sample scale). Docstring TODO: at full 35k-row scale this must be replaced with a spatial index (e.g. sklearn BallTree with haversine metric) for performance -- do not implement or benchmark that here.",
      "Implement compute_group_aggregate(df, group_col, value_col, min_n) -> per-group median/count with an 'insufficient_n' flag when count < min_n, used for complex_median_price_m2 / district_median_price_m2.",
      "Add module-level reference-data constants for city center and named malls (from FEATURE_SPEC.md), each clearly commented '# TODO: approximate, verify coordinates before production use'; leave the station/line reference table as an explicit TODO stub (empty dict) with a comment explaining the original source file is lost and a new one must be manually curated.",
      "Add a `python feature_engineering.py --sample` mode that reads methodology/samples/sample_parsed_preview.csv (utf-8), computes price_m2 = price_tenge / area_total_m2, runs haversine radius aggregation, group aggregates, and distance_to_center_km for every row, and writes methodology/samples/sample_features.csv (utf-8) with all engineered columns filled in for the ~15-20 real sample listings.",
      "Run it now. Open sample_features.csv and eyeball the values for plausibility (e.g. do listings that are geographically close to each other get similar avg_price_m2_within_3km values; does n_neighbors_3km look sane given how the sample rows were spread out in sample_fixture). Fix and re-run if not.",
      "Paste a few real rows of sample_features.csv into this task's activity.md log entry as evidence.",
      "Do not run any function in this file against AstanaLinksParserJune2026_parsed.csv or 2025_data.csv in this or any task."
    ],
    "passes": false,
    "depends_on": ["feature_engineering_spec"]
  },
  {
    "id": "ranking_methodology_spec",
    "category": "documentation",
    "description": "Write methodology/RANKING_METHODOLOGY.md: the percentile-rank approach AND the OLS-residual approach, how each is validated, and how they combine into a single 'best deal' presentation.",
    "steps": [
      "Document the percentile-rank approach: percentile_rank_in_complex = rank of price_m2 ascending within complex_name / count, and percentile_rank_in_district = same within district; lower percentile = cheaper = better deal (all else equal). Note this ignores feature differences (area, floor, age, etc.) entirely -- it is a naive baseline, not a fair-value estimate.",
      "Document the OLS approach for the REAL, full-scale model (future work, not run in this loop): a formula sketch such as ln_price_m2 ~ ln_area + building_age + floor_is_first + floor_is_last + ceiling_height_m + former_dormitory + exchange_possible + C(building_type) + C(district) + distance_to_center_km + avg_price_m2_within_3km (+ distance_to_nearest_station_m once that reference table exists). Define the 'good deal' score as the OLS residual (actual ln_price_m2 - predicted): a strongly negative residual = priced well below what its features predict = good deal.",
      "Separately document the SAMPLE-SCALE OLS check that ranking_scaffold_code actually runs in this loop: with only ~15-20 rows, the full formula above is rank-deficient (too many dummy/categorical levels relative to n). Specify a trimmed formula for that check (2-3 continuous predictors only, e.g. ln_price_m2 ~ ln_area + avg_price_m2_within_3km) and state explicitly that its purpose is to prove the code path (fit runs, residuals compute, ranking logic behaves) -- NOT to produce a trustworthy coefficient estimate. The real model, with the full formula, only becomes meaningful once fit on the full dataset (explicitly out of scope for this run).",
      "Specify minimum sample size rules for the real future model: define a per-complex minimum (e.g. n>=8-10 comparable listings) below which a complex-specific effect/dummy should not be trusted; for complexes below that threshold, fall back to predicting from the district-level model plus the complex_median_price_m2 aggregate as a simple adjustment rather than a fitted complex fixed effect.",
      "Specify the diagnostics checklist to apply before trusting the real (full-scale) OLS: adjusted R-squared, residual-vs-fitted plot (heteroscedasticity check), QQ plot of residuals, VIF for multicollinearity (flag that district dummies, distance_to_center_km, and distance_to_nearest_station_m are likely collinear with each other and with avg_price_m2_within_3km -- document a decision rule, e.g. drop or combine features with VIF > 10), and out-of-sample validation via leave-one-complex-out or k-fold cross-validation.",
      "Specify standard-error treatment for the real model: reuse the DiD scripts' pattern of clustering standard errors by 500x500m spatial grid cell (grid_cell_id from FEATURE_SPEC.md) rather than assuming i.i.d. errors, since nearby listings are spatially correlated.",
      "Specify how the two approaches combine into one presentation per listing: show percentile_rank_in_complex, percentile_rank_in_district, predicted_price_m2, actual_price_m2, and ols_residual_score side by side (not silently merged into a single number) plus a composite good_deal_score defined as the average of z-scored versions of (negative percentile rank) and (negative OLS residual), with predicted_price_m2/ols_residual_score treated as primary only when the model's diagnostics are healthy and sample size is adequate (i.e. on the full dataset, not the sample-scale check).",
      "Add a short 'what would invalidate this' section: overfitting risk from too many dummy variables relative to n, complex_name coverage gap (~22-24% missing) meaning percentile_rank_in_complex is undefined for those rows (fall back to district-only ranking), and the unresolved station/mall reference-data gap limiting which spatial features are actually usable until that data is curated."
    ],
    "passes": false,
    "depends_on": ["feature_engineering_spec"]
  },
  {
    "id": "ranking_scaffold_code",
    "category": "implementation",
    "description": "Implement methodology/scripts/ranking.py per RANKING_METHODOLOGY.md. Run it for real against the sample-scale features (sample_features.csv from feature_scaffold_code) using the trimmed sample-scale formula -- never against the full dataset.",
    "steps": [
      "Implement percentile_rank_within_group(df, group_col, value_col) -> adds a percentile-rank column, ascending (0 = cheapest in group).",
      "Implement fit_price_model(df, formula, cluster_col=None) -> fits an OLS via statsmodels.formula.api.ols, optionally with clustered covariance via get_robustcov_results(cov_type='cluster', groups=...) matching the pattern in 01_near_stations_final.py, and returns the fitted result plus predicted values and residuals.",
      "Implement compute_composite_score(df, ...) combining z-scored percentile rank and OLS residual per RANKING_METHODOLOGY.md's formula.",
      "Add a `python ranking.py --sample` mode that reads methodology/samples/sample_features.csv (utf-8), computes price_m2 and ln_price_m2 if not already present, computes percentile_rank_in_district (and percentile_rank_in_complex where complex_name is present -- most sample rows may lack enough same-complex peers, that's expected and should be reported as such, not treated as a bug), fits the OLS using the TRIMMED sample-scale formula documented in RANKING_METHODOLOGY.md (e.g. ln_price_m2 ~ ln_area + avg_price_m2_within_3km), computes residuals and the composite score, and writes methodology/samples/sample_ranked_preview.csv with all of these columns per real sample listing.",
      "Run it now. Print/log the fitted coefficients, R-squared, and n to stdout/activity.md. Confirm the sign of the composite score makes sense (a listing priced notably below similar/nearby listings in the sample should score as a better deal). Note explicitly in the script's output and in activity.md that this fit is a pipeline-correctness check only (n=~15-20, trimmed formula) and not a trustworthy price model -- that requires the full dataset, out of scope for this run.",
      "Paste the real fitted coefficients/R-squared and a few rows of sample_ranked_preview.csv into this task's activity.md log entry as evidence.",
      "Do not run any function in this file against AstanaLinksParserJune2026_parsed.csv or 2025_data.csv in this or any task."
    ],
    "passes": false,
    "depends_on": ["ranking_methodology_spec", "feature_scaffold_code"]
  },
  {
    "id": "eda_plan",
    "category": "documentation",
    "description": "Write methodology/EDA_PLAN.md: the exploratory analysis to run FIRST once real full-scale parsing eventually happens. This task only produces the plan; do not execute it against the full dataset.",
    "steps": [
      "List a missingness report per parsed field, called out by name, with the coverage rates already known from prior exploration where applicable (complex_name ~76-78% present; rooms ~0% present in this data version; kitchen_area_m2 and apartment_condition partial/variable).",
      "List distribution checks: price, area_total_m2, and price_m2 histograms (log-scale for price_m2 given its typical right skew), build_year distribution with sanity bounds (flag build_year before ~1950 or more than ~5 years in the future as suspect), counts of listings per district (bar chart) and per complex_name (top 20 + long-tail histogram).",
      "List outlier-detection rules: price_m2 outside e.g. [district_median*0.2, district_median*5] or an IQR rule computed per district (not globally, since districts differ structurally); obviously malformed prices.",
      "List a duplicate/relist detection check: same lat/lon + same area_total_m2 + same price_tenge appearing more than once, which may indicate the same unit relisted rather than an independent comparable.",
      "List a geographic sanity check: plot lat/lon and flag points falling outside a reasonable Astana bounding box.",
      "List a correlation matrix / VIF pre-check across the engineered numeric features (from FEATURE_SPEC.md) to catch multicollinearity before it reaches the OLS step in RANKING_METHODOLOGY.md.",
      "List the specific edge-case audits that fell out of the parsing spec work and should be run at full scale: complete distinct-value list of district and building_type strings (to confirm no unexpected variants slipped through), frequency of the pipe-delimited parameters-fallback format, frequency of future/under-construction build years.",
      "State explicitly, in a closing note, that executing this plan against the full dataset is deferred to a future run outside this loop; you may illustrate the method (labeled 'illustrative only, not representative') using sample_features.csv / sample_ranked_preview.csv."
    ],
    "passes": false,
    "depends_on": ["feature_engineering_spec"]
  },
  {
    "id": "methodology_consolidation",
    "category": "documentation",
    "description": "Write the top-level METHODOLOGY.md at the repo root, tying together every spec/script produced so far into one deliverable, and reconcile any naming drift between docs and code.",
    "steps": [
      "Write METHODOLOGY.md at the repo root (same level as 2025_data.csv, LinksParser, ralpheasy/) summarizing: dataset scope decision (AstanaLinksParserJune2026_parsed.csv is primary for this methodology; 2025_data.csv is explicitly out of scope for this run, noted as a candidate for a future trend-comparison extension); a short summary of and link to each of methodology/PARSING_SPEC.md, methodology/FEATURE_SPEC.md, methodology/RANKING_METHODOLOGY.md, methodology/EDA_PLAN.md; the two-pronged ranking approach and how it combines, restated briefly; the fact that parsing/feature/ranking code was run end-to-end and verified against a real ~15-20 row sample (with real example output referenced), and that the sample-scale OLS fit is a pipeline check only, not a real model; a consolidated 'known data-quality gaps' section (room count unavailable, station/mall reference coordinates need manual verification, parameters pipe-fallback format, district label normalization deferred); and a 'reading order for a human' list.",
      "Add an explicit 'Next steps to run at scale (out of scope for this loop)' section: run parse_listings.py across the full CSV, run the EDA_PLAN.md checklist, fit the real full-formula OLS per complex/district with the full diagnostics checklist, generate final ranked-listing output tables -- clearly marked as future work.",
      "Cross-check field and feature names: open parse_listings.py, feature_engineering.py, and ranking.py and confirm every field name referenced in FEATURE_SPEC.md and RANKING_METHODOLOGY.md actually matches a real column produced by the pipeline (check against the real sample_features.csv / sample_ranked_preview.csv headers, not just the docs). Fix any drift found in either the docs or the scripts (prefer fixing the docs unless the script clearly has a bug).",
      "Do not execute any script against the full dataset in this task; new execution here is limited to re-running the existing --sample/--selftest modes if needed to verify a fix."
    ],
    "passes": false,
    "depends_on": ["field_extraction_spec", "build_parser_script", "feature_engineering_spec", "feature_scaffold_code", "ranking_methodology_spec", "ranking_scaffold_code", "eda_plan"]
  },
  {
    "id": "final_review",
    "category": "qa",
    "description": "Final consistency pass and closing activity.md summary. Last task in the plan.",
    "steps": [
      "Re-read PARSING_SPEC.md, FEATURE_SPEC.md, RANKING_METHODOLOGY.md, EDA_PLAN.md, and METHODOLOGY.md together; confirm terminology and field names are used consistently across all of them.",
      "Re-run: python methodology/scripts/parse_listings.py --selftest, python methodology/scripts/parse_listings.py --sample, python methodology/scripts/feature_engineering.py --sample, and python methodology/scripts/ranking.py --sample. Confirm all still pass and produce sane real output after any edits made in methodology_consolidation.",
      "Fix anything broken; if fixes are needed, make them and note them in the activity.md entry for this task.",
      "Write a closing summary entry in activity.md describing the full deliverable set (docs + scripts + real sample outputs) and confirming no task step ever executed a script against the full AstanaLinksParserJune2026_parsed.csv or 2025_data.csv.",
      "This is the last task -- after it is marked true, zero tasks should remain false or in_progress."
    ],
    "passes": false,
    "depends_on": ["methodology_consolidation"]
  }
]
```

### Critical Files for Implementation
- ralpheasy/plan.md
- ralpheasy/PROMPT.md
- ralpheasy/activity.md
- AstanaLinksParserJune2026_parsed.csv
- LinksParser
- 01_near_stations_final.py
- 02_between_stations_final.py
