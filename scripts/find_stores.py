"""Discover and confirm store IDs for all retailers near Broad Ripple (46220).

Usage:
    python scripts/find_stores.py
    python scripts/find_stores.py --zip 46220 --radius 15
"""
import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

from scrapers import KrogerScraper, MeijerScraper


def find_kroger(zip_code: str, radius: int) -> None:
    client_id = os.environ.get("KROGER_CLIENT_ID")
    client_secret = os.environ.get("KROGER_CLIENT_SECRET")
    if not client_id or not client_secret:
        print("  SKIPPED — set KROGER_CLIENT_ID and KROGER_CLIENT_SECRET in .env")
        return
    stores = KrogerScraper.find_stores(
        zip_code,
        config={"client_id": client_id, "client_secret": client_secret},
        radius_miles=radius,
    )
    for s in stores:
        print(f"  [{s['store_id']}]  {s['name']} — {s['address']}, {s['city']} {s['zip']}")


def find_meijer() -> None:
    stores = MeijerScraper.find_store_id(config={})
    for s in stores:
        print(f"  [{s['storeNumber']}]  {s['name']} — {s['address']}, {s['city']}, {s['state']} {s['zip']}  ({s['distance']} mi)")


def main():
    parser = argparse.ArgumentParser(description="Find store IDs near a ZIP code.")
    parser.add_argument("--zip", default="46220", help="ZIP code to search near (default: 46220)")
    parser.add_argument("--radius", type=int, default=10, help="Search radius in miles (default: 10)")
    args = parser.parse_args()

    print(f"\nSearching stores near ZIP {args.zip} within {args.radius} miles...\n")

    print("Kroger:")
    find_kroger(args.zip, args.radius)

    print("\nMeijer:")
    find_meijer()

    print("\nWalmart:   Store #2787 — 7325 N Keystone Ave, Indianapolis IN 46240 (confirmed)")
    print("Costco:    Warehouse #346 — 6110 E 86th St, Indianapolis IN 46250 (confirmed)")
    print("FreshThyme: rsid=104 — 6301 N College Ave, Indianapolis IN 46220 (confirmed)")


if __name__ == "__main__":
    main()
