# -*- coding: utf-8 -*-
"""parse_listings.py -- field extraction for krisha.kz scraped listings.

Implements the label-segmentation strategy documented in
methodology/PARSING_SPEC.md: an ordered list of known label tokens (more
specific labels before shorter labels they prefix), one alternation regex
found via re.finditer, matches sorted by position, and each label's value
taken as the text between its match end and the next match's start.

Implementation note (a deliberate, documented simplification of the spec's
description in PARSING_SPEC.md section 5): the spec describes the
pipe-delimited `parameters` fallback as "split on ' | ', run the same
logic on each segment". In practice, running label-segmentation directly
on the raw (unsplit) parameters string produces identical results, because
finditer scans the whole string regardless of what separates one label's
value from the next label -- a space or a " | " token both stop at the
next label match. " | " and "|" are simply added to the set of characters
stripped from each extracted value's edges. This file therefore segments
`advert_info` and `parameters` independently with the same combined label
list, then merges field-by-field (advert_info value wins; parameters value
fills the gap only when advert_info's is missing) -- which is exactly the
"fill gaps only, never overwrite" rule from the spec, verified against
every pipe-fallback test case documented there (see --selftest).

Usage:
    python parse_listings.py --selftest
    python parse_listings.py --sample
"""

import argparse
import os
import re
import sys
from datetime import datetime

import pandas as pd

# Combined, ordered label list. advert_info-specific labels come first (in
# the specific-before-general order required by the spec: "Площадь кухни"
# before "Площадь", "Балкон остеклён" before "Балкон"), followed by the
# parameters-only labels. There is no prefix conflict across the two
# groups. Real sample rows show amenity labels (Балкон, Бывшее общежитие,
# Возможен обмен, Высота потолков) appearing directly in advert_info for
# standalone / pipe-fallback listings, so both columns are segmented with
# this single list rather than two separate ones.
LABELS = [
    "Тип дома",
    "Жилой комплекс",
    "Год постройки",
    "Этаж",
    "Площадь кухни",
    "Площадь",
    "Состояние квартиры",
    "Санузел",
    "Балкон остеклён",
    "Балкон",
    "Дверь",
    "Телефон",
    "Интернет",
    "Парковка",
    "Квартира меблирована",
    "Пол",
    "Высота потолков",
    "Безопасность",
    "Бывшее общежитие",
    "Возможен обмен",
]

_LABEL_RE = re.compile("|".join(re.escape(label) for label in LABELS))
_PRICE_RE = re.compile(r"(\d[\d\s]*)\s*₸")  # ₸
_DISTRICT_RE = re.compile(r"Астана,\s*([А-Яа-яёЁ\-\s]+?)\s*р-н показать на карте")
_NUM_RE = re.compile(r"(\d+(?:[.,]\d+)?)")
_FLOOR_RE = re.compile(r"(\d+)\s+из\s+(\d+)")

_STRIP_CHARS = " \t,|—–-"

OUTPUT_FIELDS = [
    "price_tenge", "price_is_installment", "city", "district",
    "building_type", "complex_name", "build_year", "is_under_construction",
    "floor", "floor_total", "floor_is_first", "floor_is_last",
    "area_total_m2", "kitchen_area_m2", "apartment_condition", "bathroom",
    "balcony", "balcony_glazed", "door", "phone", "internet", "parking",
    "furnished", "flooring", "ceiling_height_m", "security_features",
    "former_dormitory", "exchange_possible", "rooms",
    "rooms_bucket_estimated", "rooms_estimate_is_heuristic",
    "parse_warnings",
]


def segment_labels(text):
    """Return {label: raw_value_string} from position-sorted label matches."""
    if not text:
        return {}
    matches = list(_LABEL_RE.finditer(text))
    result = {}
    for i, m in enumerate(matches):
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        value = text[start:end].strip(_STRIP_CHARS).strip()
        label = m.group()
        if label not in result:  # first occurrence wins
            result[label] = value
    return result


def _to_float(s):
    if not s:
        return None
    m = _NUM_RE.search(s)
    if not m:
        return None
    return float(m.group(1).replace(",", "."))


def _yes_no(s):
    if not s:
        return None
    v = s.strip().lower()
    if v.startswith("да"):
        return True
    if v.startswith("нет"):
        return False
    return None


def _condition_enum(s):
    if not s:
        return "unknown"
    v = s.strip().lower()
    if not v:
        return "unknown"
    if v == "черновая отделка":
        return "rough"
    if v == "свежий ремонт":
        return "fresh_renovation"
    return "needs_renovation"


def _rooms_bucket(area):
    if area is None:
        return None
    if area <= 30:
        return "studio"
    if area <= 45:
        return "1-room"
    if area <= 65:
        return "2-room"
    if area <= 90:
        return "3-room"
    return "4+room"


def has_pipe_fallback(parameters):
    """True if `parameters` looks like the confirmed pipe-delimited fallback
    format (duplicates advert_info-style fields instead of amenities)."""
    if not parameters:
        return False
    return " | " in parameters and bool(_DISTRICT_RE.search(parameters))


def _is_empty(v):
    return v is None or (isinstance(v, float) and pd.isna(v)) or v == ""


def parse_row(advert_info, parameters, status, fetched_at=None):
    """Parse one scraped listing's advert_info/parameters into structured fields."""
    warnings = []
    out = {
        "price_tenge": None, "price_is_installment": False,
        "city": None, "district": None,
        "building_type": None, "complex_name": None,
        "build_year": None, "is_under_construction": None,
        "floor": None, "floor_total": None, "floor_is_first": None, "floor_is_last": None,
        "area_total_m2": None, "kitchen_area_m2": None,
        "apartment_condition": "unknown", "bathroom": None,
        "balcony": None, "balcony_glazed": None, "door": None, "phone": None,
        "internet": None, "parking": None, "furnished": None, "flooring": None,
        "ceiling_height_m": None, "security_features": [],
        "former_dormitory": None, "exchange_possible": None,
        "rooms": None, "rooms_bucket_estimated": None,
        "rooms_estimate_is_heuristic": False,
        "parse_warnings": warnings,
    }

    if status == "error" or _is_empty(advert_info):
        warnings.append("status=error, no advert_info/parameters to parse")
        return out

    advert_info = str(advert_info)
    parameters = "" if _is_empty(parameters) else str(parameters)

    if has_pipe_fallback(parameters):
        warnings.append("pipe-delimited parameters fallback detected")

    price_m = _PRICE_RE.search(advert_info)
    if price_m:
        out["price_tenge"] = int(price_m.group(1).replace(" ", ""))
        out["price_is_installment"] = "Рассрочка" in advert_info
    else:
        warnings.append("price not found in advert_info")

    district_m = _DISTRICT_RE.search(advert_info)
    if district_m:
        out["city"] = "Астана"
        out["district"] = district_m.group(1).strip()
    else:
        warnings.append("district prefix not found in advert_info")

    advert_fields = segment_labels(advert_info)
    param_fields = segment_labels(parameters)

    def field(label):
        v = advert_fields.get(label)
        if not v:
            v = param_fields.get(label)
        return v if v else None

    bt = field("Тип дома")
    out["building_type"] = bt.split()[0] if bt else None

    cn = field("Жилой комплекс")
    out["complex_name"] = cn if cn else None

    year_raw = field("Год постройки")
    if year_raw:
        year_m = re.match(r"\d{4}", year_raw)
        if year_m:
            out["build_year"] = int(year_m.group())

    fetch_year = datetime.now().year
    if fetched_at and not _is_empty(fetched_at):
        try:
            fetch_year = int(str(fetched_at)[:4])
        except ValueError:
            pass
    if out["build_year"] is not None:
        # >= (not strict >): a listing built in the same calendar year it
        # was fetched is still sold as pre-construction/"under
        # construction" on krisha.kz. Confirmed against PARSING_SPEC.md's
        # test case: row 0, build_year=2026, fetched 2026-07-13 -> under
        # construction.
        out["is_under_construction"] = out["build_year"] >= fetch_year

    floor_raw = field("Этаж")
    if floor_raw:
        fm = _FLOOR_RE.search(floor_raw)
        if fm:
            out["floor"] = int(fm.group(1))
            out["floor_total"] = int(fm.group(2))
            out["floor_is_first"] = out["floor"] == 1
            out["floor_is_last"] = out["floor"] == out["floor_total"]

    out["area_total_m2"] = _to_float(field("Площадь"))
    out["kitchen_area_m2"] = _to_float(field("Площадь кухни"))

    out["apartment_condition"] = _condition_enum(field("Состояние квартиры"))
    out["bathroom"] = field("Санузел")

    out["balcony_glazed"] = _yes_no(field("Балкон остеклён"))
    out["balcony"] = field("Балкон")
    out["door"] = field("Дверь")
    out["phone"] = field("Телефон")
    out["internet"] = field("Интернет")
    out["parking"] = field("Парковка")
    out["furnished"] = field("Квартира меблирована")
    out["flooring"] = field("Пол")
    out["ceiling_height_m"] = _to_float(field("Высота потолков"))

    sec_raw = field("Безопасность")
    out["security_features"] = [s.strip() for s in sec_raw.split(",")] if sec_raw else []

    out["former_dormitory"] = _yes_no(field("Бывшее общежитие"))
    out["exchange_possible"] = _yes_no(field("Возможен обмен"))

    out["rooms"] = None
    out["rooms_bucket_estimated"] = _rooms_bucket(out["area_total_m2"])
    out["rooms_estimate_is_heuristic"] = out["rooms_bucket_estimated"] is not None

    return out


# ---------------------------------------------------------------------------
# --selftest: literal test-case strings pulled from PARSING_SPEC.md.
# No CSV access; must run in well under a second.
# ---------------------------------------------------------------------------

def _check(label, actual, expected):
    assert actual == expected, f"FAIL {label}: expected {expected!r}, got {actual!r}"
    print(f"ok   {label}")


def run_selftest():
    n = 0

    # Row 0 (source_row=2): typical case, area must not swallow kitchen area.
    r = parse_row(
        "56 500 000 ₸ Город Астана, Нура р-н показать на карте Тип дома "
        "монолитный Жилой комплекс Turan Tower Год постройки 2026 Этаж 5 из 27 "
        "Площадь 65.3 м², Площадь кухни — 10 м² Состояние квартиры черновая отделка",
        "Санузел 2 с/у и более Парковка паркинг Высота потолков 3.2 м "
        "Бывшее общежитие нет Возможен обмен Нет",
        "ok", fetched_at="2026-07-13T15:47:25",
    )
    _check("price (plain)", r["price_tenge"], 56500000); n += 1
    _check("district prefix regex captures label text", r["district"], "Нура"); n += 1
    _check("complex_name", r["complex_name"], "Turan Tower"); n += 1
    _check("build_year", r["build_year"], 2026); n += 1
    _check("is_under_construction", r["is_under_construction"], True); n += 1
    _check("area not concatenated with kitchen", r["area_total_m2"], 65.3); n += 1
    _check("kitchen_area_m2 (integer form)", r["kitchen_area_m2"], 10.0); n += 1
    _check("apartment_condition rough", r["apartment_condition"], "rough"); n += 1
    _check("ceiling_height_m (decimal)", r["ceiling_height_m"], 3.2); n += 1
    _check("former_dormitory False", r["former_dormitory"], False); n += 1
    _check("exchange_possible False (capitalized value, case-insensitive)", r["exchange_possible"], False); n += 1
    _check("floor/floor_total", (r["floor"], r["floor_total"]), (5, 27)); n += 1
    _check("floor_is_first/last (neither)", (r["floor_is_first"], r["floor_is_last"]), (False, False)); n += 1

    # Row 5 (source_row=12): installment price prefix, no ^-anchor; missing Этаж.
    r = parse_row(
        "от 78 950 600 ₸ Рассрочка Город Астана, Есильский р-н показать на "
        "карте Тип дома монолитный Жилой комплекс Sanara Год постройки 2027 "
        "Площадь 106.69 м² Санузел 2 с/у и более Высота потолков 3 м",
        "Город Астана, Есильский р-н показать на карте | Тип дома монолитный | "
        "Жилой комплекс Sanara | Год постройки 2027 | Площадь 106.69 м² | "
        "Санузел 2 с/у и более | Высота потолков 3 м",
        "ok", fetched_at="2026-07-13T15:48:15",
    )
    _check("installment price (not ^-anchored)", r["price_tenge"], 78950600); n += 1
    _check("price_is_installment flag", r["price_is_installment"], True); n += 1
    _check("district despite installment words", r["district"], "Есильский"); n += 1
    _check("floor absent -> None, not False", (r["floor"], r["floor_is_first"]), (None, None)); n += 1
    _check("ceiling_height_m bare integer", r["ceiling_height_m"], 3.0); n += 1

    # Row 8 (source_row=21): label-ordering bug -- Балкон vs Балкон остеклён.
    r = parse_row(
        "22 500 000 ₸ Город Астана, Алматы р-н показать на карте Тип дома "
        "кирпичный Год постройки 2006 Этаж 3 из 5 Площадь 43 м² Состояние "
        "квартиры свежий ремонт Санузел совмещенный",
        "Балкон балкон Балкон остеклён да Дверь металлическая Телефон есть "
        "возможность подключения Интернет ADSL Парковка рядом охраняемая "
        "стоянка Квартира меблирована частично Пол ламинат Высота потолков "
        "2.7 м Безопасность домофон, видеонаблюдение Бывшее общежитие нет "
        "Возможен обмен Нет",
        "ok", fetched_at="2026-07-13T15:49:04",
    )
    _check("balcony free text not swallowed", r["balcony"], "балкон"); n += 1
    _check("balcony_glazed separately True", r["balcony_glazed"], True); n += 1
    _check("bathroom from advert_info", r["bathroom"], "совмещенный"); n += 1

    # Row 11 (source_row=58): three-bucket apartment_condition + multi-word security items.
    r = parse_row(
        "15 700 000 ₸ Город Астана, Алматы р-н показать на карте Тип дома "
        "панельный Год постройки 1981 Этаж 1 из 5 Площадь 30.2 м² Состояние "
        "квартиры не новый, но аккуратный ремонт Санузел совмещенный",
        "Дверь металлическая Квартира меблирована частично Пол ламинат "
        "Безопасность решетки на окнах, домофон Бывшее общежитие нет "
        "Возможен обмен Нет",
        "ok", fetched_at="2026-07-13T15:52:21",
    )
    _check("condition needs_renovation bucket", r["apartment_condition"], "needs_renovation"); n += 1
    _check("security multi-word item preserved", r["security_features"],
           ["решетки на окнах", "домофон"]); n += 1
    _check("floor_is_first True", r["floor_is_first"], True); n += 1

    # Row 13 (source_row=161): the only "yes" case for Возможен обмен, values live in advert_info.
    r = parse_row(
        "32 000 000 ₸ Город Астана, Алматы р-н показать на карте Тип дома "
        "монолитный Год постройки 2014 Этаж 14 из 16 Площадь 66 м² Высота "
        "потолков 2.7 м Возможен обмен Да",
        "Город Астана, Алматы р-н показать на карте | Тип дома монолитный | "
        "Год постройки 2014 | Этаж 14 из 16 | Площадь 66 м² | Высота "
        "потолков 2.7 м | Возможен обмен Да",
        "ok", fetched_at="2026-07-13T16:01:31",
    )
    _check("exchange_possible True", r["exchange_possible"], True); n += 1
    _check("pipe-fallback gap-fill no-op (advert_info already complete)",
           r["parse_warnings"], ["pipe-delimited parameters fallback detected"]); n += 1

    # Row 7 (source_row=20): standalone, no Тип дома in either column -- confirms gap-fill
    # can't invent a value neither column has.
    r = parse_row(
        "22 400 000 ₸ Город Астана, Алматы р-н показать на карте Год "
        "постройки 1989 Этаж 6 из 6 Площадь 51 м² Балкон балкон Бывшее "
        "общежитие нет Возможен обмен Нет",
        "Город Астана, Алматы р-н показать на карте | Год постройки 1989 | "
        "Этаж 6 из 6 | Площадь 51 м² | Балкон балкон | Бывшее общежитие "
        "нет | Возможен обмен Нет",
        "ok", fetched_at="2026-07-13T15:48:59",
    )
    _check("building_type None when absent from both columns", r["building_type"], None); n += 1
    _check("complex_name None (standalone)", r["complex_name"], None); n += 1
    _check("floor_is_last True (6 of 6)", r["floor_is_last"], True); n += 1

    # Row 6 (source_row=97): pipe segment containing two labels together.
    r = parse_row(
        "27 500 000 ₸ Город Астана, Алматы р-н показать на карте Тип дома "
        "кирпичный Жилой комплекс Orleu Год постройки 2026 Этаж 2 из 9 Площадь "
        "39 м², Площадь кухни — 10 м² Возможен обмен Нет",
        "Город Астана, Алматы р-н показать на карте | Тип дома кирпичный | "
        "Жилой комплекс Orleu | Год постройки 2026 | Этаж 2 из 9 | Площадь 39 "
        "м², Площадь кухни — 10 м² | Возможен обмен Нет",
        "ok", fetched_at="2026-07-13T15:55:43",
    )
    _check("area from pipe segment with two labels", r["area_total_m2"], 39.0); n += 1
    _check("kitchen_area from same pipe segment", r["kitchen_area_m2"], 10.0); n += 1
    _check("condition unknown (absent from both columns)", r["apartment_condition"], "unknown"); n += 1

    # Row 14 (source_row=87): status=error, empty advert_info/parameters.
    r = parse_row(float("nan"), float("nan"), "error", fetched_at="2026-07-13T15:54:49")
    _check("error row price None", r["price_tenge"], None); n += 1
    _check("error row warning", r["parse_warnings"],
           ["status=error, no advert_info/parameters to parse"]); n += 1
    _check("error row rooms_bucket None", r["rooms_bucket_estimated"], None); n += 1

    print(f"\nselftest: {n} checks passed")


# ---------------------------------------------------------------------------
# --sample: real run against methodology/samples/sample_rows.csv
# ---------------------------------------------------------------------------

def run_sample():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    samples_dir = os.path.join(os.path.dirname(script_dir), "samples")
    in_path = os.path.join(samples_dir, "sample_rows.csv")
    out_path = os.path.join(samples_dir, "sample_parsed_preview.csv")

    df = pd.read_csv(in_path, encoding="utf-8")

    rows = []
    for _, row in df.iterrows():
        parsed = parse_row(
            row.get("advert_info"), row.get("parameters"), row.get("status"),
            fetched_at=row.get("fetched_at"),
        )
        parsed["source_row"] = row.get("source_row")
        parsed["url"] = row.get("url")
        rows.append(parsed)

    out_df = pd.DataFrame(rows)
    out_df = out_df[["source_row", "url"] + OUTPUT_FIELDS]
    out_df.to_csv(out_path, index=False, encoding="utf-8")

    n_total = len(out_df)
    n_error = (out_df["parse_warnings"].apply(
        lambda w: any("status=error" in s for s in w))).sum()
    n_complex = out_df["complex_name"].notna().sum()
    n_price = out_df["price_tenge"].notna().sum()
    n_area = out_df["area_total_m2"].notna().sum()
    n_district = out_df["district"].notna().sum()
    n_pipe_fallback = out_df["parse_warnings"].apply(
        lambda w: any("pipe-delimited" in s for s in w)).sum()

    print(f"wrote {n_total} parsed rows to {out_path}")
    print(f"error rows (status=error): {n_error}")
    print(f"pipe-delimited fallback detected: {n_pipe_fallback}")
    print(f"price parsed: {n_price}/{n_total}")
    print(f"district parsed: {n_district}/{n_total}")
    print(f"area_total_m2 parsed: {n_area}/{n_total}")
    print(f"complex_name present: {n_complex}/{n_total}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--selftest", action="store_true")
    parser.add_argument("--sample", action="store_true")
    args = parser.parse_args()

    if not args.selftest and not args.sample:
        parser.print_help()
        sys.exit(1)

    if args.selftest:
        run_selftest()
    if args.sample:
        run_sample()


if __name__ == "__main__":
    main()
