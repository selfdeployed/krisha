# sample_rows.csv — fixture documentation

16 rows hand-picked from `AstanaLinksParserJune2026_parsed.csv` (34,766 rows
total) by a single read-through in the `sample_fixture` task. This is the
fixed fixture every later parsing/feature/ranking task in this loop runs
against for real; no later task re-reads or re-scans the full CSV.

Columns are unchanged from the source file: `source_row, url, status,
http_status, advert_info, parameters, lat, lon, fetched_at, error`.

Row order below matches row order in `sample_rows.csv` (0-indexed).

| # | source_row | Edge case(s) covered |
|---|---|---|
| 0 | 2 | Typical case: has `Жилой комплекс` (Turan Tower) + full `advert_info`/`parameters`. Also `Год постройки 2026` → under-construction (future build year) case. |
| 1 | 3 | Typical case: `Жилой комплекс` (View Park Family) + full params, Алматы р-н. |
| 2 | 7 | Typical case: `Жилой комплекс` (Фирдаус), кирпичный, full params, Алматы р-н — a second "normal" row for variety (different building_type, condition phrase `свежий ремонт`). |
| 3 | 15 | Typical case: `Жилой комплекс` (Акерке 2), Сарыарка р-н — only row from this district, adds district variety. |
| 4 | 8 | Has `Жилой комплекс` (ХАБАР) but **missing** `Площадь кухни` (kitchen area) AND **missing** `Состояние квартиры` (apartment condition) — both absent from advert_info and parameters. |
| 5 | 12 | **Pipe-delimited parameters fallback** (`parameters` contains `' | '`-joined segments duplicating advert_info fields, matching the confirmed `Sanara` example in the plan). Also: price prefix variant `от 78 950 600 ₸ Рассрочка` (price has a "from" prefix and an installment-plan word before the district segment — a harder price-regex case than the plain `56 500 000 ₸` prefix). Also `Год постройки 2027` → future/under-construction. |
| 6 | 97 | **Pipe-delimited parameters fallback** (Orleu). **Missing** `Состояние квартиры`. `Год постройки 2026`. |
| 7 | 20 | **No `Жилой комплекс`** (standalone listing). **Missing `Тип дома`** (building type) entirely. Also **pipe-delimited parameters fallback** (same content duplicated with `' | '` separators) — one row intentionally covers three edge cases at once. |
| 8 | 21 | **No `Жилой комплекс`** (standalone). Has `Состояние квартиры` (`свежий ремонт`), `Санузел совмещенный`, and `Балкон остеклён да` (yes/no glazed-balcony field) — exercises that field's да/нет normalization. |
| 9 | 37 | **No `Жилой комплекс`** (standalone), very sparse `parameters` (only `Бывшее общежитие`/`Возможен обмен`) — tests graceful handling of near-empty parameters. Old building (`Год постройки 1992`). |
| 10 | 43 | **No `Жилой комплекс`** (standalone). `Санузел раздельный` (separate bathroom — a different bathroom-value than `совмещенный`/`2 с/у и более` seen elsewhere). |
| 11 | 58 | **No `Жилой комплекс`** (standalone), панельный building type, oldest build year in the sample (`1981`), floor 1 of 5 → exercises `floor_is_first`. Missing Телефон/Интернет/Парковка/Высота потолков entirely. |
| 12 | 133 | **Pipe-delimited parameters fallback**, no `Жилой комплекс`, minimal fields beyond the basics (`Высота потолков 3 м`, `Возможен обмен Нет`). |
| 13 | 161 | **Pipe-delimited parameters fallback**, no `Жилой комплекс`, **`Возможен обмен Да`** — the only "yes" case for this field in the sample (all others are "Нет"), monolitный building type, floor 14 of 16 → exercises `floor_is_last` when total is not equal to floor (not last here, but high floor for variety). |
| 14 | 87 | **status='error', http_status=404**, `advert_info`/`parameters`/`lat`/`lon` all empty/NaN — the failed-fetch case. |
| 15 | 11 | Has `Жилой комплекс` (MOD Frame). **Missing** `Площадь кухни`. `Год постройки 2026` → future/under-construction. Southwesternmost point in the sample, giving the 3km-radius spatial feature a genuine "isolated, few neighbors" case to compute against. |

## Coverage checklist (per sample_fixture task spec)

- (a) rows WITH `Жилой комплекс` + full params: rows 0, 1, 2, 3 (and partially 4, 15).
- (b) rows WITHOUT `Жилой комплекс`: rows 7, 8, 9, 10, 11, 12, 13.
- (c) rows with pipe-delimited `parameters` fallback (`' | '` + `р-н`): rows 5, 6, 7, 12, 13.
- (d) row with status='error' / http_status=404 and empty advert_info/parameters: row 14.
- (e) rows missing `Площадь кухни`, `Состояние квартиры`, or `Тип дома`: rows 4 (both kitchen area and condition), 6 (condition), 7 (building type), 15 (kitchen area).
- (f) rows with build year >= current fetch year (under construction): rows 0 (2026), 5 (2027), 6 (2026), 15 (2026).

## Spatial spread (for the 3km-radius feature in feature_scaffold_code)

Latitudes span 51.078295–51.168629 (~10 km north-south) and longitudes span
71.396319–71.512703 (~8 km east-west at this latitude), giving a mix of
tightly clustered points (rows 7–13, all within the central Алматы/Есиль
area) and more isolated points (rows 3, 5, 15) so that `n_neighbors_3km`
varies meaningfully across the sample instead of being uniform. Row 14
(the error row) has no lat/lon and must be excluded from spatial
calculations, not treated as 0,0.

## Notes

- No processing beyond this single hand-pick read-through was run against
  the full `AstanaLinksParserJune2026_parsed.csv`.
- `source_row` values are preserved from the original file for traceability
  back to the full dataset.
