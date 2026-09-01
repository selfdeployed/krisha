# -*- coding: utf-8 -*-
"""build_map_artifact.py -- merge astana_deals_map.template.html with
map_data.json into the final, publish-ready artifact HTML.

Usage:
    python build_map_artifact.py
"""

import base64
import json
import os

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
MAP_DIR = os.path.join(REPO_ROOT, "methodology", "map")
FULL_RUN_DIR = os.path.join(REPO_ROOT, "methodology", "full_run")

TEMPLATE_PATH = os.path.join(MAP_DIR, "astana_deals_map.template.html")
DATA_PATH = os.path.join(FULL_RUN_DIR, "map_data.json")
BASEMAP_PNG_PATH = os.path.join(MAP_DIR, "basemap_astana.jpg")
BASEMAP_META_PATH = os.path.join(MAP_DIR, "basemap_astana_meta.txt")
OUTPUT_PATH = os.path.join(MAP_DIR, "astana_deals_map.html")

PLACEHOLDER = "__MAP_DATA_JSON__"
BASEMAP_URI_PLACEHOLDER = "__BASEMAP_IMAGE_DATA_URI__"
BASEMAP_BOUNDS_PLACEHOLDER = "__BASEMAP_BOUNDS_JSON__"


def _read_basemap_meta():
    meta = {}
    with open(BASEMAP_META_PATH, "r", encoding="utf-8") as f:
        for line in f:
            if ":" not in line:
                continue
            k, v = line.split(":", 1)
            meta[k.strip()] = v.strip()
    return {
        "north": float(meta["bounds_north"]),
        "south": float(meta["bounds_south"]),
        "west": float(meta["bounds_west"]),
        "east": float(meta["bounds_east"]),
    }


def main():
    with open(TEMPLATE_PATH, "r", encoding="utf-8") as f:
        template = f.read()
    with open(DATA_PATH, "r", encoding="utf-8") as f:
        data_json = f.read()
    with open(BASEMAP_PNG_PATH, "rb") as f:
        basemap_b64 = base64.b64encode(f.read()).decode("ascii")
    basemap_bounds = _read_basemap_meta()

    if PLACEHOLDER not in template:
        raise SystemExit(f"Placeholder {PLACEHOLDER!r} not found in template -- did the template change?")
    if BASEMAP_URI_PLACEHOLDER not in template:
        raise SystemExit(f"Placeholder {BASEMAP_URI_PLACEHOLDER!r} not found in template -- did the template change?")
    if BASEMAP_BOUNDS_PLACEHOLDER not in template:
        raise SystemExit(f"Placeholder {BASEMAP_BOUNDS_PLACEHOLDER!r} not found in template -- did the template change?")

    # Defensive JSON-in-HTML escaping: a scraped complex_name could in
    # principle contain a literal "</" sequence, which -- unescaped --
    # would prematurely close the <script> tag it's embedded in. This is
    # the standard mitigation (safe because the payload is parsed via
    # JSON.parse, not evaluated as JS, so escaping "/" doesn't change any
    # decoded value).
    n_escaped = data_json.count("</")
    data_json_safe = data_json.replace("</", "<\\/")

    output = template.replace(PLACEHOLDER, data_json_safe)
    output = output.replace(BASEMAP_URI_PLACEHOLDER, "data:image/jpeg;base64," + basemap_b64)
    output = output.replace(BASEMAP_BOUNDS_PLACEHOLDER, json.dumps(basemap_bounds))

    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        f.write(output)

    size_mb = os.path.getsize(OUTPUT_PATH) / (1024 * 1024)
    print(f"wrote {OUTPUT_PATH}")
    print(f"final artifact size: {size_mb:.2f} MB")
    print(f"escaped {n_escaped} occurrence(s) of '</' inside the embedded data")


if __name__ == "__main__":
    main()
