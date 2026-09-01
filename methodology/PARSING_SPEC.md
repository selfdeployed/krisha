# PARSING_SPEC.md — Field extraction from `advert_info` and `parameters`

Scope: this spec documents how `methodology/scripts/parse_listings.py`
(task `build_parser_script`) turns the two raw scraped text columns —
`advert_info` and `parameters` — from `AstanaLinksParserJune2026_parsed.csv`
into structured fields. Every test case below is a **literal string pulled
from `methodology/samples/sample_rows.csv`**, the 16-row fixture created in
`sample_fixture`. Row numbers below refer to that file's row order (0-15);
`source_row` is the original `source_row` column value for traceability.

## 1. Core strategy: label-segmentation, not per-field lookahead regex

Both `advert_info` and `parameters` are a single space-joined string of
`"<Label> <value>"` pairs with no reliable field delimiter (most of the
time — see §5 for the confirmed pipe-delimited exception). Writing one
regex per field with a lookahead for "the next label or end of string" is
fragile and grows quadratically in complexity as labels are added. Instead:

1. Define an **ordered list of known label tokens** (order matters — a more
   specific label must be listed before a shorter label it starts with,
   otherwise the shorter label's regex will "eat" the specific one's text).
   - `advert_info` labels (checked after price/district prefix — see §2 —
     is stripped from consideration): `Тип дома`, `Жилой комплекс`,
     `Год постройки`, `Этаж`, `Площадь кухни`, `Площадь`,
     `Состояние квартиры`, `Санузел`.
   - `parameters` labels: `Санузел`, `Балкон остеклён`, `Балкон`, `Дверь`,
     `Телефон`, `Интернет`, `Парковка`, `Квартира меблирована`, `Пол`,
     `Высота потолков`, `Безопасность`, `Бывшее общежитие`,
     `Возможен обмен`.
   - Critical ordering pairs, both required for correctness:
     `Площадь кухни` before `Площадь` (`Площадь` is a prefix of
     `Площадь кухни`'s first word), and `Балкон остеклён` before `Балкон`
     (`Балкон` is a prefix of `Балкон остеклён`).
2. Build **one alternation regex** from the ordered label list
   (`re.finditer`), find every label occurrence and its position in the
   string, sort matches by start position.
3. For each matched label, the field **value** is the substring between the
   end of that label's match and the start of the next label's match (or
   end of string for the last label). Strip whitespace and leading
   separators (`,`, `—`, `-`, `–`) from the value.

### Confirmed real test case for label ordering (row 8, `source_row=21`)

```
parameters: "Балкон балкон Балкон остеклён да Дверь металлическая ..."
```

If `Балкон` were listed before `Балкон остеклён` in the alternation, the
segmentation would find only one `Балкон` match (the first one, since regex
alternation is first-match-wins at a given position only if order is
respected — with `Балкон` listed first, `finditer` would still match
`Балкон` a second time at the "Балкон остеклён" position, mis-labeling it),
producing `Балкон = "балкон Балкон остеклён да"` and losing the field
entirely. With `Балкон остеклён` listed first, segmentation correctly
yields `Балкон = "балкон"` and `Балкон остеклён = "да"` as two separate
matches. **This is a real ordering bug the sample fixture caught, not a
hypothetical.**

## 2. Price and district prefix (extracted first, before label-segmentation)

These two fields sit in front of the labeled section and are extracted
with dedicated regexes applied to `advert_info` only, then the matched
span is excluded from the label-segmentation search.

- **Price**: search (not anchor) for `(\d[\d\s]*)\s*₸` — take the **first**
  match, strip internal spaces, cast to `int`. Do not anchor to `^`.
  - Test case (row 0, `source_row=2`): `"56 500 000 ₸ Город Астана, ..."`
    → `price_tenge = 56500000`.
  - Test case (row 5, `source_row=12`), the harder real case: the plan's
    original sketch assumed the digits immediately precede `₸` at the
    start of the string, but the sample fixture surfaced a listing with an
    "installment plan" prefix/suffix: `"от 78 950 600 ₸ Рассрочка Город
    Астана, Есильский р-н показать на карте ..."`. An anchored
    `^([\d\s]+)\s*₸` regex fails here because `"от "` precedes the digits.
    Using `re.search` instead of `^`-anchoring handles this correctly:
    `price_tenge = 78950600`. Record `price_is_installment = True` (word
    `"Рассрочка"` present) as an informational flag; it does not change how
    price is parsed.
- **District prefix**: `Астана,\s*([А-Яа-яёЁ\-\s]+?)\s*р-н показать на карте`,
  `re.search` anywhere in `advert_info` (not positionally tied to right
  after price, since the installment-plan case inserts extra words between
  price and the district segment). Captures the district label **as
  scraped** — do not normalize against an authoritative district list here
  (deferred to `eda_plan`).
  - Test cases confirmed present across the sample: `Нура` (row 0),
    `Алматы` (rows 1, 2, 6-13), `Сарыарка` (row 3), `Есильский` (rows 5,
    15).

## 3. Field-specific post-processing rules (confirmed test cases)

- **`Тип дома\s+(\S+)`** → one of `монолитный` / `кирпичный` / `панельный`
  / other. **OPTIONAL** — absent on some standalone listings.
  - Present: row 0 → `монолитный`; row 3 → `кирпичный`; row 11 →
    `панельный`.
  - Absent: row 7 (`source_row=20`), advert_info has no `Тип дома` label at
    all — `building_type = None`, not an error.
- **`Год постройки\s+(\d{4})`** → `int`. `is_under_construction = year >
  fetch_year` where `fetch_year` is derived from the row's `fetched_at`
  column (all sample rows fetched in 2026).
  - Test cases: row 0 `2026` → under construction; row 3 `2025` → not;
    row 11 `1981` → not (oldest in sample).
- **`Этаж\s+(\d+)\s+из\s+(\d+)`** → `floor`, `floor_total` ints. Derive
  `floor_is_first = floor == 1`, `floor_is_last = floor == floor_total`.
  **OPTIONAL** — absent for at least one pre-construction listing where no
  unit/floor has been assigned yet.
  - Test cases: row 0 `"Этаж 5 из 27"` → `floor=5, floor_total=27`, neither
    first nor last. Row 11 `"Этаж 1 из 5"` → `floor_is_first=True`. Row 7
    `"Этаж 6 из 6"` → `floor_is_last=True`. Row 13 `"Этаж 14 из 16"` →
    neither.
  - Absent: row 5 (`source_row=12`, the `Sanara` pre-construction listing,
    `Год постройки 2027`) — no `Этаж` label anywhere in `advert_info`.
    `floor = floor_total = None`, `floor_is_first = floor_is_last = None`
    (not `False` — unknown, not "not first/last").
- **`Площадь\s+([\d]+(?:[.,]\d+)?)\s*м²`** → `area_total_m2` float (comma
  or dot decimal). Confirmed this does **not** accidentally match
  `Площадь кухни ...` since `"кухни"` is not a digit, so no lookahead is
  needed for disambiguation between the two — the label-segmentation
  algorithm already treats them as distinct labels per §1.
  - Test case (row 0, exact real string): `"Площадь 65.3 м², Площадь
    кухни — 10 м²"` → `area_total_m2 = 65.3` only (not `65.310` or any
    concatenation).
- **`Площадь кухни\s*[—\-–]\s*([\d]+(?:[.,]\d+)?)\s*м²`** →
  `kitchen_area_m2` float. **OPTIONAL** — absent in several samples (rows
  4, 6 has it via pipe-fallback but row 15 lacks it entirely).
  - Present, decimal case: row 2 `"Площадь кухни — 12.1 м²"` →
    `kitchen_area_m2 = 12.1`.
  - Present, integer case: row 0 `"Площадь кухни — 10 м²"` →
    `kitchen_area_m2 = 10.0`.
  - Absent: row 15 (`source_row=11`) — `advert_info` has `Площадь 47 м²`
    with no kitchen-area label anywhere → `kitchen_area_m2 = None`.
- **`Высота потолков\s+([\d]+(?:[.,]\d+)?)\s*м`** → `ceiling_height_m`
  float. Confirmed both decimal (`"3.2 м"` row 0, `"2.85 м"` row 1) and
  bare-integer (`"3 м"` row 5, row 15) forms occur — the optional-decimal
  group handles both without special-casing.
- **`Состояние квартиры`** value from label-segmentation is free text,
  normalized into a small enum: `rough` (черновая отделка),
  `fresh_renovation` (свежий ремонт), `needs_renovation` (any other
  non-empty descriptive phrase, e.g. "not fresh but liveable" wording),
  `unknown` (label absent).
  - Test case row 0: `"черновая отделка"` → `rough`.
  - Test case row 2: `"свежий ремонт"` → `fresh_renovation`.
  - Test case row 11 (`source_row=58`), a phrase not anticipated by the
    original two-bucket sketch and confirmed present in real data:
    `"не новый, но аккуратный ремонт"` (lit. "not new, but tidy
    renovation") → `needs_renovation`. Note the value legitimately
    contains a comma; this is fine because only `Безопасность` is
    comma-split (§4) — `Состояние квартиры`'s value is taken verbatim up
    to the next label (`Санузел` here), commas and all.

## 4. `Жилой комплекс` (complex name) and multi-value / boolean fields

- **`Жилой комплекс`**: value via label-segmentation is whatever text falls
  between the label and the next known label. Present in rows 0-6 and 15
  of the sample (`Turan Tower`, `View Park Family`, `Фирдаус`, `Акерке 2`,
  `ХАБАР`, `Sanara`, `Orleu`, `MOD Frame`); absent in rows 7-13 (standalone
  listings) → `complex_name = None`, not an error. Matches the
  `sample_fixture` task's confirmed ~76-78% present / ~22-24% absent split
  observed on the full file.
- **`Безопасность`**: split value on `,`, trim each piece, produce a list.
  - Test case row 1: `"охрана, домофон, видеонаблюдение, видеодомофон"` →
    `["охрана", "домофон", "видеонаблюдение", "видеодомофон"]`.
  - Test case row 11: `"решетки на окнах, домофон"` → `["решетки на
    окнах", "домофон"]` (confirms multi-word items without internal commas
    survive the split correctly).
- **Yes/no fields** (`Бывшее общежитие`, `Возможен обмен`, `Балкон
  остеклён`): value is literally `"да"` / `"нет"` (case-insensitive) →
  normalize to `bool`.
  - Test case row 0: `"Бывшее общежитие нет"` → `False`; `"Возможен обмен
    Нет"` → `False` (capitalized `Нет`, confirms case-insensitivity is
    needed).
  - Test case row 13 (`source_row=161`): `"Возможен обмен Да"` → `True` —
    the only "yes" case for this field found in the sample.
  - Test case row 8 (`source_row=21`): `"Балкон остеклён да"` → `True`.

## 5. Confirmed pipe-delimited `parameters` fallback

Confirmed present in real data (5 of 16 sample rows: 5, 6, 7, 12, 13):
`parameters` sometimes contains `" | "`-delimited segments duplicating
`advert_info`-style fields (including a repeated district-prefix segment)
instead of amenity data.

- **Detector**: `parameters` contains `" | "` AND matches the district-prefix
  pattern from §2.
- **Handling**: split on `" | "`, run the **same** district-prefix +
  label-segmentation logic (§1-§2) on the joined/each segment, and use any
  extracted values to **fill gaps only** — never overwrite a value already
  reliably extracted from `advert_info`.
- Test case (row 5, `source_row=12`, the confirmed `Sanara`/`Есильский`
  example named in the plan):
  ```
  parameters: "Город Астана, Есильский р-н показать на карте | Тип дома
  монолитный | Жилой комплекс Sanara | Год постройки 2027 | Площадь
  106.69 м² | Санузел 2 с/у и более | Высота потолков 3 м"
  ```
  Every field here duplicates `advert_info` — gap-fill logic is a no-op on
  this row since `advert_info` already has all of them.
- Test case demonstrating gap-fill actually firing (row 7, `source_row=20`,
  standalone + no `Тип дома`):
  ```
  advert_info: "22 400 000 ₸ Город Астана, Алматы р-н показать на карте
  Год постройки 1989 Этаж 6 из 6 Площадь 51 м² Балкон балкон Бывшее
  общежитие нет Возможен обмен Нет"
  parameters: "Город Астана, Алматы р-н показать на карте | Год постройки
  1989 | Этаж 6 из 6 | Площадь 51 м² | Балкон балкон | Бывшее общежитие
  нет | Возможен обмен Нет"
  ```
  Neither column has `Тип дома` here — confirms the fallback duplicates
  rather than adds new information in this case; `building_type` stays
  `None` correctly (fill-gap logic has nothing to fill from either side).
- Test case where a single pipe segment itself contains two labels that
  still need label-segmentation applied *within* the segment (row 6,
  `source_row=97`):
  ```
  parameters: "... | Этаж 2 из 9 | Площадь 39 м², Площадь кухни — 10 м² |
  Возможен обмен Нет"
  ```
  The segment `"Площадь 39 м², Площадь кухни — 10 м²"` is one `" | "`-split
  chunk but contains two labels (`Площадь`, `Площадь кухни`) — confirms
  splitting on `" | "` is only a coarse pre-split; label-segmentation must
  still run on (the concatenation of) the segments, not assume one
  label per segment.

## 6. Confirmed data gap: room count

Confirmed (verified in `sample_fixture`: zero `"комнат"` matches across
5,000 scanned rows of the full file): room count does not appear anywhere
in `advert_info` or `parameters` in this dataset version.

- `rooms` stays `None` always.
- Optionally derive `rooms_bucket_estimated` from `area_total_m2` via a
  documented heuristic: `<=30` → studio, `30-45` → 1-room, `45-65` →
  2-room, `65-90` → 3-room, `>90` → 4+ room. Always set
  `rooms_estimate_is_heuristic = True` alongside it.
  - **Warning**: this heuristic must never be used as a hard OLS control
    without that caveat — area and room count are correlated but not
    equivalent (e.g. a studio with an unusually large kitchen).
- **Future (out-of-scope) scraper enhancement**: capture the page
  `<h1>`/title text in `LinksParser` (which typically encodes
  "N-комнатная квартира" on krisha.kz listing pages) as a new output
  column, so room count can be parsed directly instead of estimated. Not
  implemented in this methodology loop.

## 7. Output field summary

`parse_row(advert_info, parameters, status)` returns: `price_tenge`,
`city`, `district`, `building_type`, `complex_name`, `build_year`,
`is_under_construction`, `floor`, `floor_total`, `floor_is_first`,
`floor_is_last`, `area_total_m2`, `kitchen_area_m2`,
`apartment_condition`, `bathroom`, `balcony`, `balcony_glazed`, `door`,
`phone`, `internet`, `parking`, `furnished`, `flooring`,
`ceiling_height_m`, `security_features` (list), `former_dormitory` (bool),
`exchange_possible` (bool), `rooms` (always `None`),
`rooms_bucket_estimated`, `rooms_estimate_is_heuristic` (bool),
`parse_warnings` (list of strings for any field that failed to parse as
expected, e.g. status='error' rows with empty advert_info/parameters).

For `status='error'` rows (test case row 14, `source_row=87`,
`http_status=404`, `advert_info`/`parameters` both `NaN`): every field is
`None`, `parse_warnings = ["status=error, no advert_info/parameters to
parse"]`, no regex is attempted against `NaN`/empty input.
