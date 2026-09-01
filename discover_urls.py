#!/usr/bin/env python
"""discover_urls.py -- crawl krisha.kz search-result pages to build a fresh
listing-URL list, since the original AstanaLinksParserJune2026.xlsx input
(used by LinksParser) is missing from this machine.

Fetches https://krisha.kz/prodazha/kvartiry/astana/?page=N for N=1.. and
extracts every /a/show/<id> link. Output is a plain CSV (source_row,url)
consumable by LinksParser's new --input-csv flag. Resumable: reruns skip
IDs already present in the output file; page range picks up from
--start-page (default 1) since page fetches are cheap and idempotent.

Usage:
    python discover_urls.py --output krisha_urls.csv
"""

import argparse
import csv
import re
import time
from datetime import datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

SEARCH_URL = "https://krisha.kz/prodazha/kvartiry/astana/"
ID_PATTERN = re.compile(r"/a/show/(\d+)")
FOUND_COUNT_PATTERN = re.compile(r"Найдено\s+([\d\s]+)\s+объявлен")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/125.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
    "Connection": "close",
}


def fetch(url, timeout):
    req = Request(url, headers=HEADERS)
    with urlopen(req, timeout=timeout) as resp:
        charset = resp.headers.get_content_charset() or "utf-8"
        return resp.status, resp.read().decode(charset, "replace")


def load_known_ids(output_path):
    ids = set()
    max_row = 1
    if output_path.exists():
        with output_path.open("r", newline="", encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                url = row.get("url") or ""
                m = ID_PATTERN.search(url)
                if m:
                    ids.add(m.group(1))
                try:
                    max_row = max(max_row, int(row["source_row"]))
                except (KeyError, ValueError):
                    pass
    return ids, max_row


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", default="krisha_urls.csv")
    ap.add_argument("--start-page", type=int, default=1)
    ap.add_argument("--max-pages", type=int, default=1200, help="Hard cap, safety net.")
    ap.add_argument("--stop-after-empty-pages", type=int, default=15,
                     help="Stop once this many consecutive pages yield zero NEW ids.")
    ap.add_argument("--min-delay", type=float, default=0.8)
    ap.add_argument("--max-delay", type=float, default=1.2)
    ap.add_argument("--timeout", type=int, default=30)
    args = ap.parse_args()

    import random

    output_path = Path(args.output)
    known_ids, max_row = load_known_ids(output_path)
    print(f"Resuming with {len(known_ids)} already-known ids (next source_row starts at {max_row + 1}).")

    exists = output_path.exists() and output_path.stat().st_size > 0
    handle = output_path.open("a", newline="", encoding="utf-8-sig")
    writer = csv.DictWriter(handle, fieldnames=["source_row", "url", "discovered_at"])
    if not exists:
        writer.writeheader()

    target_total = None
    empty_streak = 0
    next_row = max_row + 1

    try:
        for page in range(args.start_page, args.max_pages + 1):
            page_url = SEARCH_URL if page == 1 else f"{SEARCH_URL}?page={page}"
            delay = random.uniform(args.min_delay, args.max_delay)
            time.sleep(delay)
            try:
                status, html = fetch(page_url, args.timeout)
            except (HTTPError, URLError, TimeoutError, OSError) as exc:
                print(f"[page {page}] FETCH ERROR: {type(exc).__name__}: {exc}")
                empty_streak += 1
                if empty_streak >= args.stop_after_empty_pages:
                    print("Too many consecutive failures, stopping.")
                    break
                continue

            if target_total is None:
                m = FOUND_COUNT_PATTERN.search(html)
                if m:
                    target_total = int(m.group(1).replace(" ", "").replace("\xa0", ""))
                    print(f"Site reports target total: {target_total} listings.")

            page_ids = set(ID_PATTERN.findall(html))
            new_ids = page_ids - known_ids
            for lid in sorted(new_ids):
                writer.writerow({
                    "source_row": next_row,
                    "url": f"https://krisha.kz/a/show/{lid}",
                    "discovered_at": datetime.now().isoformat(timespec="seconds"),
                })
                next_row += 1
            handle.flush()
            known_ids |= new_ids

            print(f"[page {page}/{args.max_pages}] status={status} page_ids={len(page_ids)} "
                  f"new={len(new_ids)} total_known={len(known_ids)}"
                  + (f"/{target_total}" if target_total else ""))

            if new_ids:
                empty_streak = 0
            else:
                empty_streak += 1
                if empty_streak >= args.stop_after_empty_pages:
                    print(f"{empty_streak} consecutive pages with no new ids -- stopping (exhausted or capped pagination).")
                    break

            if target_total and len(known_ids) >= target_total:
                print("Reached (or exceeded) the site's reported total -- stopping.")
                break
    finally:
        handle.close()

    print(f"Done. {len(known_ids)} unique listing URLs written to {output_path}.")


if __name__ == "__main__":
    main()
