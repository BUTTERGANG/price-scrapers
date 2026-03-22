"""Costco scraper — search.costco.com internal API, warehouse #346 (Castleton, Indianapolis).

⚠️  IMPORTANT PRICING CAVEAT:
    Costco's policy is that in-warehouse prices are NOT published online.
    costco.com only shows online/delivery prices. The search API's
    `item_location_pricing_*` fields are location-aware but reflect
    the *online* price for that warehouse, not the physical shelf price.
    In-warehouse prices can differ significantly from online prices.
    The Costco app shows in-store prices (with 30-min delay) but requires
    member authentication. This scraper captures online prices only.

Search API endpoint:
    https://search.costco.com/api/apps/www_costco_com/query/www_costco_com_search

Key parameters:
    q        — search keyword
    whloc    — warehouse location filter: "{warehouse_num}-wh" (e.g. "346-wh")
    loc      — comma-separated: "346-wm,346-wh,346-bd" (member/warehouse/biz delivery)
    rows     — results per page (max ~48)
    start    — pagination offset
    locale   — "en-US"
    userLocation — two-letter state, "IN"

Price fields in response:
    item_location_pricing_listPrice  — regular price
    item_location_pricing_salePrice  — sale price (same as list if no sale)

Anti-bot: Akamai protects this endpoint. Direct requests return 401.
          Requires Playwright with stealth patches to obtain a valid session.
          The browser utility in utils/browser.py handles this.

Warehouse #346 confirmed: costco.com/warehouse-locations/castleton-in-346.html
"""
import logging
from typing import Optional

from .base import BaseScraper
from utils.browser import run_intercept

logger = logging.getLogger(__name__)

SEARCH_ENDPOINT = (
    "https://search.costco.com/api/apps/www_costco_com/query/www_costco_com_search"
)
# Costco's public-facing search page — Playwright navigates here first
# to establish a valid Akamai-authenticated session before the API fires
SEARCH_PAGE = "https://www.costco.com/CatalogSearch?keyword={query}&storeId=10301"

_WAREHOUSE = "346"


class CostcoScraper(BaseScraper):
    retailer = "costco"

    def authenticate(self) -> None:
        # Authentication is handled per-request via Playwright in search_products.
        # No persistent token to manage here.
        logger.info("Costco: auth handled per-request via Playwright stealth session.")

    def search_products(self, query: str) -> list[dict]:
        """
        Navigate to the Costco search page in a stealthy Playwright browser.
        Intercept the XHR response from search.costco.com and parse prices.
        """
        results_holder: list[dict] = []

        def on_response(data: dict) -> dict:
            """Called with the parsed JSON from the intercepted search API response."""
            items = (
                data.get("response", {})
                .get("docs", [])
            )
            for item in items:
                list_price = item.get("item_location_pricing_listPrice")
                sale_price = item.get("item_location_pricing_salePrice")
                try:
                    list_price = float(list_price) if list_price is not None else None
                    sale_price = float(sale_price) if sale_price is not None else None
                except (ValueError, TypeError):
                    list_price = None
                    sale_price = None

                # Flag items that only reveal price in cart
                price_in_cart = item.get("item_product_price_in_cart_only") == "1"

                results_holder.append(
                    self.normalize_price(
                        product_id=str(item.get("item_number", "")),
                        name=item.get("name", ""),
                        price=list_price or 0.0,
                        url=f"https://www.costco.com/{item.get('seo_url', '')}",
                        extra={
                            "sale_price": sale_price if sale_price != list_price else None,
                            "price_in_cart_only": price_in_cart,
                            "online_price_only": True,  # see module docstring
                            "rating": item.get("item_review_ratings"),
                            "review_count": item.get("item_product_review_count"),
                        },
                    )
                )
            return data  # return value unused

        page_url = SEARCH_PAGE.format(query=query)
        run_intercept(
            url=page_url,
            pattern="search.costco.com",
            on_response=on_response,
            proxy=self.config.get("proxy"),
        )

        if not results_holder:
            logger.warning(
                f"[costco] No results intercepted for '{query}'. "
                "Akamai may have blocked the session — check Playwright stealth config."
            )

        self.save_raw(
            {"query": query, "result_count": len(results_holder)},
            f"search_{query.replace(' ', '_')}",
        )
        return results_holder

    def get_product_price(self, product_id: str) -> Optional[dict]:
        results = self.search_products(product_id)
        for r in results:
            if r["product_id"] == product_id:
                return r
        return None
