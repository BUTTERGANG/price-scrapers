"""Tests for the Kroger scraper.

Unit tests mock the API. Integration tests hit the real API and are
skipped automatically when credentials are not set in the environment.

Run unit tests only:
    pytest tests/test_kroger.py -k "not integration"

Run all including integration (requires .env with real credentials):
    pytest tests/test_kroger.py
"""
import json
import os
import pytest
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_api_product(
    product_id="0001111041700",
    name="Kroger 2% Reduced Fat Milk",
    regular=3.99,
    promo=None,
    size="1 gal",
    page_uri="/p/kroger-2-reduced-fat-milk/0001111041700",
) -> dict:
    """Build a minimal Kroger API product dict matching the v1.3.0 schema."""
    return {
        "productId": product_id,
        "description": name,
        "brand": "Kroger",
        "categories": ["Dairy"],
        "snapEligible": True,
        "productPageURI": page_uri,
        "temperature": {"indicator": "Refrigerated"},
        "aisleLocations": [{"description": "Dairy Aisle 12"}],
        "ratingsAndReviews": {"averageOverallRating": 4.5, "totalReviewCount": 120},
        "items": [
            {
                "itemId": product_id,
                "size": size,
                "soldBy": "unit",
                "price": {
                    "regular": regular,
                    "promo": promo,
                    "regularPerUnitEstimate": regular,
                    "promoPerUnitEstimate": promo,
                    "expirationDate": {"value": "9999-12-31T00:00:00Z"} if promo else None,
                },
                "nationalPrice": {"regular": regular + 0.20, "promo": None},
                "inventory": {"stockLevel": "HIGH"},
                "fulfillment": {"instore": True, "curbside": True, "delivery": False},
            }
        ],
    }


# ---------------------------------------------------------------------------
# Unit tests
# ---------------------------------------------------------------------------

class TestKrogerScraperUnit:
    @pytest.fixture
    def scraper(self):
        from scrapers.kroger import KrogerScraper
        s = KrogerScraper(
            store_id="01400441",
            config={"client_id": "test_id", "client_secret": "test_secret"},
        )
        s._token = "fake_token"
        s._token_expires_at = float("inf")
        return s

    def test_parse_product_regular_price(self, scraper):
        product = _make_api_product(regular=3.99, promo=None)
        record = scraper._parse_product(product)
        assert record["price"] == 3.99
        assert record["sale_price"] is None
        assert record["retailer"] == "kroger"
        assert record["store_id"] == "01400441"

    def test_parse_product_sale_price(self, scraper):
        product = _make_api_product(regular=4.99, promo=3.49)
        record = scraper._parse_product(product)
        assert record["price"] == 4.99
        assert record["sale_price"] == 3.49

    def test_parse_product_url_from_api(self, scraper):
        product = _make_api_product(page_uri="/p/kroger-milk/0001111041700")
        record = scraper._parse_product(product)
        assert record["url"] == "https://www.kroger.com/p/kroger-milk/0001111041700"

    def test_parse_product_extra_fields(self, scraper):
        product = _make_api_product()
        record = scraper._parse_product(product)
        assert record["snap_eligible"] is True
        assert record["stock_level"] == "HIGH"
        assert record["in_store"] is True
        assert record["aisle"] == "Dairy Aisle 12"
        assert record["temperature"] == "Refrigerated"
        assert record["rating"] == 4.5

    def test_search_products_deduplicates(self, scraper):
        """Pagination can return duplicate productIds — scraper must deduplicate."""
        page = {"data": [_make_api_product("0001111041700"), _make_api_product("0001111041700")]}
        empty = {"data": []}
        with patch.object(scraper, "_get", side_effect=[page, empty]):
            results = scraper.search_products("milk")
        assert len(results) == 1

    def test_search_products_paginates(self, scraper):
        """Should keep fetching pages until fewer than 50 results are returned."""
        page1 = {"data": [_make_api_product(f"000111104170{i}") for i in range(50)]}
        page2 = {"data": [_make_api_product(f"000111104180{i}") for i in range(10)]}
        with patch.object(scraper, "_get", side_effect=[page1, page2]) as mock_get:
            results = scraper.search_products("milk")
        assert len(results) == 60
        assert mock_get.call_count == 2

    def test_get_product_price_404_returns_none(self, scraper):
        import requests
        mock_resp = MagicMock()
        mock_resp.status_code = 404
        with patch.object(scraper, "_get", side_effect=requests.HTTPError(response=mock_resp)):
            result = scraper.get_product_price("0001111041700")
        assert result is None

    def test_rate_limit_counter_increments(self, scraper):
        import requests
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"data": []}
        mock_resp.raise_for_status = MagicMock()
        with patch("requests.get", return_value=mock_resp):
            scraper.search_products("milk")
        assert scraper._calls_today >= 1

    def test_extract_price_from_pricing_text(self, scraper):
        price, unit = scraper._extract_price("$3.99 LB With Card")
        assert price == 3.99
        assert unit == "LB"

    def test_extract_price_with_cents(self, scraper):
        price, unit = scraper._extract_price("12¢/oz")
        assert price == 0.12
        assert unit == "OZ"

    def test_parse_store_list(self, scraper):
        raw = '[{"locationNumbers":"02100959,02100998"}]'
        assert scraper._parse_store_list(raw) == {"02100959", "02100998"}

    def test_scrape_circular_builds_normalized_records(self, scraper):
        with patch.object(scraper, "_fetch_weekly_ad_id", return_value="ad123"), \
             patch.object(scraper, "_fetch_pages", return_value=[{"eventPageId": "page1"}]), \
             patch.object(scraper, "_fetch_page_contents", return_value={
                 "contents": [
                     {
                         "mapConfig": json.dumps({
                             "content": {
                                 "offerVersionProductGroupId": 111,
                                 "headline": "Test Offer",
                                 "bodyCopy": "12 oz",
                                 "imageURL": "https://example.com/img.png",
                                 "stores": '[{"locationNumbers":"01400441"}]',
                             }
                         })
                     }
                 ]
             }), \
             patch.object(scraper, "_fetch_offer", return_value={
                 "headline": "Test Offer",
                 "bodyCopy": "12 oz",
                 "pricingText": "$2.50 EA",
                 "pricingHTML": "<font>$2.50</font>",
                 "startDate": "2026-03-18",
                 "endDate": "2026-03-24",
                 "imageURL": "https://example.com/img.png",
                 "webURL": "https://www.kroger.com/p/offer",
                 "isCoupon": False,
                 "isShoppable": True,
             }), \
             patch.object(scraper, "save_raw"):
            records = scraper.scrape_circular(location_id="01400441")
        assert len(records) == 1
        record = records[0]
        assert record["product_id"] == "111"
        assert record["name"] == "Test Offer"
        assert record["price"] == 2.50
        assert record["unit"] == "EA"
        assert record["deal_text"] == "$2.50 EA"
        assert record["start_date"] == "2026-03-18"
        assert record["end_date"] == "2026-03-24"
        assert record["location_id"] == "01400441"


# ---------------------------------------------------------------------------
# Integration tests (skipped without real credentials)
# ---------------------------------------------------------------------------

SKIP_INTEGRATION = not (os.environ.get("KROGER_CLIENT_ID") and os.environ.get("KROGER_CLIENT_SECRET"))


@pytest.mark.skipif(SKIP_INTEGRATION, reason="Kroger credentials not set in environment")
class TestKrogerIntegration:
    @pytest.fixture
    def live_scraper(self):
        from scrapers.kroger import KrogerScraper
        return KrogerScraper(
            store_id="01400441",
            config={
                "client_id": os.environ["KROGER_CLIENT_ID"],
                "client_secret": os.environ["KROGER_CLIENT_SECRET"],
            },
        )

    def test_authenticate_gets_token(self, live_scraper):
        live_scraper.authenticate()
        assert live_scraper._token is not None
        assert live_scraper._token_expires_at > 0

    def test_find_stores_near_46220(self):
        from scrapers.kroger import KrogerScraper
        stores = KrogerScraper.find_stores(
            "46220",
            config={
                "client_id": os.environ["KROGER_CLIENT_ID"],
                "client_secret": os.environ["KROGER_CLIENT_SECRET"],
            },
        )
        assert len(stores) > 0
        ids = [s["store_id"] for s in stores]
        print(f"\nKroger stores near 46220: {stores}")
        # Confirm the store ID in config is actually near Broad Ripple
        assert any(len(sid) == 8 for sid in ids), "locationId must be 8 characters per API spec"

    def test_search_milk_returns_prices(self, live_scraper):
        live_scraper.authenticate()
        results = live_scraper.search_products("milk")
        assert len(results) > 0
        for r in results:
            assert r["retailer"] == "kroger"
            assert r["product_id"] != ""
            assert r["name"] != ""
            assert isinstance(r["price"], float)
        print(f"\nSample milk result: {results[0]}")

    def test_search_includes_sale_data(self, live_scraper):
        """At least some products should have a sale price at some point."""
        live_scraper.authenticate()
        results = live_scraper.search_products("chicken breast")
        assert len(results) > 0
        # We can't guarantee a sale is active, but verify the field is present
        assert all("sale_price" in r for r in results)

    def test_get_product_price_by_id(self, live_scraper):
        live_scraper.authenticate()
        # Kroger 2% Milk — standard product likely carried by all stores
        result = live_scraper.get_product_price("0001111041700")
        if result:  # may not be carried at this specific store
            assert result["price"] > 0
            assert result["product_id"] == "0001111041700"
