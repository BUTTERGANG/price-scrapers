
import logging
import json
from pathlib import Path
from scrapers.fresh_thyme import FreshThymeScraper

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(name)s  %(message)s")

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
