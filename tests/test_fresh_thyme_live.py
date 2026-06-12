"""Live Fresh Thyme scraper test — hits the real site.

Skipped by default; run with RUN_LIVE_SCRAPER_TESTS=1 to enable.
"""
import logging
import json
import os
from pathlib import Path

import pytest

from scrapers.fresh_thyme import FreshThymeScraper

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(name)s  %(message)s")

pytestmark = pytest.mark.skipif(
    not os.environ.get("RUN_LIVE_SCRAPER_TESTS"),
    reason="live scraper test — set RUN_LIVE_SCRAPER_TESTS=1 to run",
)


def test_fresh_thyme_search():
    STORES = json.loads(Path("config/stores.json").read_text())
    store_id = STORES["stores"]["fresh_thyme"]["store_id"]

    scraper = FreshThymeScraper(store_id=store_id, config={})
    scraper.authenticate()

    results = scraper.search_products("milk")

    print(f"Found {len(results)} results for 'milk'.")
    for item in results[:5]:
        print(f"  - {item['name']}: ${item['price']:.2f}")

    assert len(results) > 0

if __name__ == "__main__":
    test_fresh_thyme_search()
