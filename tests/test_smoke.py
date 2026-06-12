"""Smoke tests — verify each scraper can authenticate and return data.

These tests hit real APIs and are skipped when credentials or store IDs
are not configured. They are designed to catch silent breakage from site
changes, API deprecation, or expired tokens.

Run all smoke tests:
    pytest tests/test_smoke.py -v

Run for a specific retailer:
    pytest tests/test_smoke.py -v -k "target"

Run with a shorter timeout:
    pytest tests/test_smoke.py -v --timeout=30
"""
import os
import pytest

from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _has_env(*keys):
    return all(os.environ.get(k) for k in keys)


# ---------------------------------------------------------------------------
# Target smoke test
# ---------------------------------------------------------------------------

class TestTargetSmoke:
    """Target weekly ad API — no auth required."""

    @pytest.fixture
    def scraper(self):
        from scrapers.target import TargetScraper
        store_id = os.environ.get("TARGET_STORE_ID", "2391")
        return TargetScraper(store_id=store_id, config={})

    def test_scrape_circular_returns_items(self, scraper):
        results = scraper.scrape_circular()
        assert len(results) > 0, "Target circular returned 0 items — possible API change"
        # Verify basic record structure
        r = results[0]
        assert r["retailer"] == "target"
        assert r["name"]
        assert r["product_id"]
        assert isinstance(r["price"], float)
        print(f"\n[target] {len(results)} items, sample: {r['name']} @ ${r['price']}")

    def test_scrape_circular_has_deals(self, scraper):
        results = scraper.scrape_circular()
        deals = [r for r in results if r.get("deal_text")]
        assert len(deals) > 0, "No deals found in Target circular"
        print(f"[target] {len(deals)} deals with deal_text")

    def test_scrape_circular_no_category_headers(self, scraper):
        """Category headers like 'Hello Summer Sale' must be filtered out."""
        results = scraper.scrape_circular()
        category_headers = [
            r for r in results
            if r["price"] == 0.0
            and not r.get("deal_text")
            and not r.get("tcin")
        ]
        assert len(category_headers) == 0, (
            f"Found {len(category_headers)} category headers scraped as products: "
            f"{[r['name'] for r in category_headers[:5]]}"
        )


# ---------------------------------------------------------------------------
# Kroger smoke tests
# ---------------------------------------------------------------------------

SKIP_KROGER = not _has_env("KROGER_CLIENT_ID", "KROGER_CLIENT_SECRET")


@pytest.mark.skipif(SKIP_KROGER, reason="Kroger credentials not set")
class TestKrogerSmoke:
    @pytest.fixture
    def scraper(self):
        from scrapers.kroger import KrogerScraper
        return KrogerScraper(
            store_id=os.environ.get("KROGER_STORE_ID", "01400441"),
            config={
                "client_id": os.environ["KROGER_CLIENT_ID"],
                "client_secret": os.environ["KROGER_CLIENT_SECRET"],
            },
        )

    def test_authenticate(self, scraper):
        scraper.authenticate()
        assert scraper._token is not None

    def test_search_returns_results(self, scraper):
        scraper.authenticate()
        results = scraper.search_products("milk")
        assert len(results) > 0, "Kroger search returned 0 results"
        r = results[0]
        assert r["retailer"] == "kroger"
        assert r["name"]
        assert r["product_id"]
        print(f"\n[kroger] {len(results)} results, sample: {r['name']} @ ${r['price']}")

    def test_search_has_unit_info(self, scraper):
        """At least some results should have unit size info for normalization."""
        scraper.authenticate()
        results = scraper.search_products("milk")
        with_unit = [r for r in results if r.get("unit")]
        assert len(with_unit) > 0, "No results have unit info — unit price normalization will fail"
        print(f"[kroger] {len(with_unit)}/{len(results)} results have unit info")


# ---------------------------------------------------------------------------
# Meijer smoke tests
# ---------------------------------------------------------------------------

class TestMeijerSmoke:
    @pytest.fixture
    def scraper(self):
        from scrapers.meijer import MeijerScraper
        store_id = os.environ.get("MEIJER_STORE_ID", "")
        if not store_id:
            pytest.skip("MEIJER_STORE_ID not set")
        return MeijerScraper(store_id=store_id, config={})

    def test_scrape_circular_returns_items(self, scraper):
        results = scraper.scrape_circular()
        assert len(results) > 0, "Meijer circular returned 0 items"
        r = results[0]
        assert r["retailer"] == "meijer"
        assert r["name"]
        print(f"\n[meijer] {len(results)} items, sample: {r['name']} @ ${r['price']}")


# ---------------------------------------------------------------------------
# Aldi smoke tests
# ---------------------------------------------------------------------------

class TestAldiSmoke:
    @pytest.fixture
    def scraper(self):
        from scrapers.aldi import AldiScraper
        store_id = os.environ.get("ALDI_STORE_ID", "")
        if not store_id:
            pytest.skip("ALDI_STORE_ID not set")
        return AldiScraper(store_id=store_id, config={})

    def test_scrape_circular_returns_items(self, scraper):
        results = scraper.scrape_circular()
        assert len(results) > 0, "Aldi circular returned 0 items"
        r = results[0]
        assert r["retailer"] == "aldi"
        assert r["name"]
        print(f"\n[aldi] {len(results)} items, sample: {r['name']} @ ${r['price']}")


# ---------------------------------------------------------------------------
# Unit price normalization smoke test
# ---------------------------------------------------------------------------

class TestUnitPriceNormalization:
    """Verify unit price normalization works on real scraper output."""

    def test_normalization_from_name(self):
        """Items with size in the name should normalize."""
        from utils.unit_price import normalize_unit_price
        record = {
            "retailer": "test",
            "store_id": "001",
            "product_id": "test1",
            "name": "Kroger Whole Milk 1 gal",
            "price": 3.99,
            "unit": None,
        }
        result = normalize_unit_price(record)
        assert result["unit_price_normalized"] is not None
        assert result["unit_canonical"] == "per_fl_oz"
        assert abs(result["unit_price_normalized"] - 0.031172) < 0.001

    def test_normalization_from_unit_field(self):
        """Items with unit field like '1 gal' should normalize."""
        from utils.unit_price import normalize_unit_price
        record = {
            "retailer": "test",
            "store_id": "001",
            "product_id": "test2",
            "name": "Cereal",
            "price": 4.99,
            "unit": "12 oz",
        }
        result = normalize_unit_price(record)
        assert result["unit_price_normalized"] is not None
        assert result["unit_canonical"] == "per_oz"

    def test_normalization_from_extra_fields(self):
        """Items with size in extra fields (e.g. formatted_price) should normalize."""
        from utils.unit_price import normalize_unit_price
        record = {
            "retailer": "test",
            "store_id": "001",
            "product_id": "test3",
            "name": "Chicken Breast",
            "price": 8.99,
            "unit": None,
            "formatted_price": "$3.99/lb",
        }
        result = normalize_unit_price(record)
        assert result["unit_price_normalized"] is not None
        assert result["unit_canonical"] == "per_lb"

    def test_normalization_countable(self):
        """Items with count units should normalize to per_ct."""
        from utils.unit_price import normalize_unit_price
        record = {
            "retailer": "test",
            "store_id": "001",
            "product_id": "test4",
            "name": "Eggs",
            "price": 3.49,
            "unit": "12 ct",
        }
        result = normalize_unit_price(record)
        assert result["unit_price_normalized"] is not None
        assert result["unit_canonical"] == "per_ct"
        assert abs(result["unit_price_normalized"] - 0.290833) < 0.001

    def test_normalization_sold_by_unit(self):
        """Kroger items with sold_by='unit' should normalize to per_ct."""
        from utils.unit_price import normalize_unit_price
        record = {
            "retailer": "kroger",
            "store_id": "01400441",
            "product_id": "test5",
            "name": "Kroger Milk",
            "price": 3.99,
            "unit": None,
            "sold_by": "unit",
        }
        result = normalize_unit_price(record)
        assert result["unit_price_normalized"] is not None
        assert result["unit_canonical"] == "per_ct"
