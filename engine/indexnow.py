#!/usr/bin/env python3
"""
IndexNow Search Engine Instant Submission Tool
Submits all storefront URLs to IndexNow (Bing, Yandex, Seznam, Naver) for instant crawl.
"""

import json
import urllib.request
import urllib.error
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
PRODUCTS_FILE = BASE_DIR / "products.json"
BASE_URL = "https://juexing1225.github.io/automate-stack"
HOST = "juexing1225.github.io"
KEY = "38a7c2e841f9450a8b4f1289cf3017de"

def generate_key_file():
    key_filename = f"{KEY}.txt"
    with open(BASE_DIR / key_filename, "w", encoding="utf-8") as f:
        f.write(KEY)
    dist_dir = BASE_DIR / "dist"
    if dist_dir.exists():
        with open(dist_dir / key_filename, "w", encoding="utf-8") as f:
            f.write(KEY)
    print(f"✓ Generated IndexNow verification file {key_filename}")

def submit_urls(dry_run=False):
    with open(PRODUCTS_FILE, "r", encoding="utf-8") as f:
        catalog = json.load(f)

    url_list = [f"{BASE_URL}/"]
    for p in catalog.get("products", []):
        slug = p.get("slug")
        url_list.append(f"{BASE_URL}/p/{slug}.html")

    payload = {
        "host": HOST,
        "key": KEY,
        "keyLocation": f"{BASE_URL}/{KEY}.txt",
        "urlList": url_list
    }

    print(f"Ready to submit {len(url_list)} URLs to IndexNow:")
    for u in url_list:
        print(f"  - {u}")

    if dry_run:
        print("Dry run enabled. Skipping network request.")
        return

    req_data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        "https://api.indexnow.org/indexnow",
        data=req_data,
        headers={"Content-Type": "application/json; charset=utf-8"}
    )

    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            status = response.status
            print(f"✓ IndexNow API returned status {status} (Success: URLs queued for immediate crawl).")
    except urllib.error.HTTPError as e:
        print(f"Notice: IndexNow returned code {e.code} ({e.reason}). (Key verification takes effect after next Pages deploy).")
    except Exception as e:
        print(f"Network error during IndexNow ping: {e}")

if __name__ == "__main__":
    generate_key_file()
    dry = "--dry-run" in sys.argv
    submit_urls(dry_run=dry)
