# Krisha Best-Offer Methodology — Activity Log

## Current Status

**Last Updated:** 2026-09-01
**Tasks Completed:** 3 / 11
**Current Task:** build_parser_script (next, not started)

## Session Log

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
