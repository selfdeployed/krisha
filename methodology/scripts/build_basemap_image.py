# -*- coding: utf-8 -*-
"""build_basemap_image.py -- fetch OSM raster tiles for the Astana bbox ONCE
at build time and stitch them into a single PNG, so the map artifact can
embed a real basemap as a data: URI (via L.imageOverlay) instead of a live
tile layer.

Why: the Artifact sandbox's CSP blocks image/fetch requests to every host
except a short CDN allowlist (cdnjs/jsdelivr/tailwind/googleapis) -- this is
why the live CARTO tile layer rendered blank; it is not specific to CARTO or
to needing an API key. NO live raster tile provider (OSM, CARTO, Esri,
Google Maps) can ever load inside the artifact at view time. A static image
baked in at build time and embedded as a data: URI sidesteps this entirely,
since the browser never makes an external request for it.

Tile source: standard OSM raster tiles (tile.openstreetmap.org), fetched
politely (small serial delay, identifying User-Agent) for a one-time,
modest (~90 tile) personal-use build -- not a live/bulk scrape. Output
carries the required "(c) OpenStreetMap contributors" attribution, which the
map UI must display per ODbL.

Usage:
    python build_basemap_image.py
"""

import io
import math
import os
import time
import urllib.request

from PIL import Image

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
MAP_DIR = os.path.join(REPO_ROOT, "methodology", "map")
OUT_PNG = os.path.join(MAP_DIR, "basemap_astana.jpg")
OUT_META = os.path.join(MAP_DIR, "basemap_astana_meta.txt")

# Same bbox as export_map_data.py's BBOX_LAT/BBOX_LON.
BBOX_LAT = (50.9, 51.3)
BBOX_LON = (71.0, 71.8)
ZOOM = 11
TILE_PX = 256
JPEG_QUALITY = 82

TILE_URL = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"
USER_AGENT = "krisha-sweet-spot-map/1.0 (personal apartment-hunting tool; one-time build-time basemap fetch)"
DELAY_S = 0.25


def deg2num(lat, lon, z):
    lat_rad = math.radians(lat)
    n = 2 ** z
    x = int((lon + 180.0) / 360.0 * n)
    y = int((1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * n)
    return x, y


def num2deg(x, y, z):
    n = 2 ** z
    lon = x / n * 360.0 - 180.0
    lat = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * y / n))))
    return lat, lon


def main():
    lat0, lat1 = BBOX_LAT
    lon0, lon1 = BBOX_LON

    x0, y1 = deg2num(lat0, lon0, ZOOM)  # low lat -> larger y (south edge)
    x1, y0 = deg2num(lat1, lon1, ZOOM)  # high lat -> smaller y (north edge)
    xs = list(range(min(x0, x1), max(x0, x1) + 1))
    ys = list(range(min(y0, y1), max(y0, y1) + 1))

    n_tiles = len(xs) * len(ys)
    print(f"zoom={ZOOM} tiles_x={len(xs)} tiles_y={len(ys)} total={n_tiles}")

    canvas = Image.new("RGB", (len(xs) * TILE_PX, len(ys) * TILE_PX), (240, 239, 236))

    n_ok, n_fail = 0, 0
    for yi, y in enumerate(ys):
        for xi, x in enumerate(xs):
            url = TILE_URL.format(z=ZOOM, x=x, y=y)
            try:
                req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
                with urllib.request.urlopen(req, timeout=10) as resp:
                    tile_bytes = resp.read()
                tile_img = Image.open(io.BytesIO(tile_bytes)).convert("RGB")
                canvas.paste(tile_img, (xi * TILE_PX, yi * TILE_PX))
                n_ok += 1
            except Exception as e:
                print(f"  fail {x},{y}: {e}")
                n_fail += 1
            time.sleep(DELAY_S)

    # Exact geographic bounds of the stitched canvas (tile edges, which
    # extend slightly beyond the requested bbox since tiles don't align to
    # arbitrary lat/lon) -- these are what Leaflet's imageOverlay needs for
    # correct georeferencing, NOT the requested bbox.
    north, west = num2deg(min(xs), min(ys), ZOOM)
    south, east = num2deg(max(xs) + 1, max(ys) + 1, ZOOM)

    os.makedirs(MAP_DIR, exist_ok=True)
    canvas.save(OUT_PNG, "JPEG", quality=JPEG_QUALITY, optimize=True)
    size_mb = os.path.getsize(OUT_PNG) / (1024 * 1024)

    meta_lines = [
        f"zoom: {ZOOM}",
        f"tiles: {n_tiles} ok={n_ok} fail={n_fail}",
        f"canvas_px: {canvas.width}x{canvas.height}",
        f"bounds_north: {north:.6f}",
        f"bounds_south: {south:.6f}",
        f"bounds_west: {west:.6f}",
        f"bounds_east: {east:.6f}",
        f"png_size_mb: {size_mb:.2f}",
        "attribution: (c) OpenStreetMap contributors",
    ]
    with open(OUT_META, "w", encoding="utf-8") as f:
        f.write("\n".join(meta_lines) + "\n")
    print("\n".join(meta_lines))

    if n_fail:
        raise SystemExit(f"{n_fail} tile(s) failed to download -- inspect before using this basemap")


if __name__ == "__main__":
    main()
