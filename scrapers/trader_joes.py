"""Trader Joe's scraper — Magento/Adobe Commerce GraphQL API.

==============================================================================
ARCHITECTURE OVERVIEW
==============================================================================

Trader Joe's runs a Magento/Adobe Commerce-based website with a public GraphQL
API at traderjoes.com/api/graphql. No auth required — behind Akamai WAF so
curl_cffi with Safari TLS impersonation is needed.

No weekly circulars or traditional sales — Trader Joe's uses everyday low
pricing with occasional item-level price changes. All scraping is done via
keyword-based product search (search_products mode).

GRAPHQL ENDPOINT
----------------------------------------------------------------------
  POST https://www.traderjoes.com/api/graphql
  Requires: curl_cffi with safari17_0 impersonation (Akamai WAF)
  Headers: Content-Type: application/json

PRODUCT SEARCH (search_products)
----------------------------------------------------------------------
  Query: products(filter: { store_code: { eq: "TJ" }, published: { eq: "1" },
                           item_title: { match: "milk" } },
                  pageSize: 50, currentPage: 1)

  Returns fields:
    sku                    — product SKU (zero-padded to 6 digits)
    item_title             — product name
    retail_price           — string price like "2.99"
    sales_size             — numeric size (e.g. 16.0)
    sales_uom_description  — unit of measure ("Oz", "Each", "Fl Oz", "Lb", etc.)
    category_hierarchy     — [{id, name, url_key}, ...]
    primary_image          — image path
    primary_image_meta     — {url, caption}
    fun_tags               — tags like "New", "Seasonal", "Limited"
    new_product            — "1" if new
    ingredients            — ingredients string (detail query only)
    nutrition_facts        — nutrition data (detail query only)

PRODUCT DETAIL (get_product_price)
----------------------------------------------------------------------
  Same query with sku filter:
    products(filter: { sku: { eq: "082606" } }, pageSize: 1)
  Returns full detail including ingredients, nutrition_facts, allergens, directions.

STORE INFO
----------------------------------------------------------------------
  Indianapolis-Castleton: 5473 E 82nd St, Indianapolis, IN 46250
  Indianapolis-W 86th: 2902 W 86th St, Indianapolis, IN 46268
  (No working GraphQL store locator found — using nearby address lookup)

PRICE FORMAT
----------------------------------------------------------------------
  retail_price is always a string like "2.99", "10.99", "8.99"
  Prices are national (same at all Trader Joe's stores).
  No traditional sales/promotions — consistent everyday low pricing.

==============================================================================
INSTALL
==============================================================================
  pip install curl-cffi
  (Akamai WAF requires TLS fingerprint impersonation)
"""  # noqa: E501
import logging
from typing import Optional

from .base import BaseScraper

logger = logging.getLogger(__name__)

GRAPHQL_URL = "https://www.traderjoes.com/api/graphql"

# Search query — filters by item_title for keyword search
SEARCH_QUERY = """query SearchProducts($storeCode: String, $published: String, $search: String, $pageSize: Int, $currentPage: Int) {
  products(
    filter: { store_code: { eq: $storeCode }, published: { eq: $published }, item_title: { match: $search } }
    pageSize: $pageSize
    currentPage: $currentPage
  ) {
    items {
      sku
      item_title
      retail_price
      sales_size
      sales_uom_description
      category_hierarchy { id name url_key }
      primary_image
      fun_tags
      new_product
    }
    total_count
    page_info { current_page page_size total_pages }
  }
}"""

# Detail query — fetches full product details by SKU
DETAIL_QUERY = """query GetProduct($storeCode: String, $published: String, $sku: String) {
  products(
    filter: { store_code: { eq: $storeCode }, published: { eq: $published }, sku: { eq: $sku } }
    pageSize: 1
  ) {
    items {
      sku
      item_title
      retail_price
      sales_size
      sales_uom_description
      category_hierarchy { id name url_key }
      primary_image
      primary_image_meta { url caption }
      fun_tags
      item_characteristics
      new_product
      ingredients
      nutrition_facts { calories total_fat saturated_fat trans_fat cholesterol sodium total_carbohydrate dietary_fiber total_sugars protein }
      allergens
      directions
    }
  }
}"""


class TraderJoesScraper(BaseScraper):
    """Scraper for Trader Joe's product catalog via Magento GraphQL API.

    Trader Joe's doesn't use weekly circulars — all prices are everyday low
    prices. The scraper uses keyword search to find products and their prices.
    Store IDs are informational (prices are national).
    """

    retailer = "trader_joes"
    PAGE_SIZE = 50

    def __init__(self, store_id: str, config: dict):
        super().__init__(store_id, config)
        self._session = None

    def _get_session(self):
        """Lazy-init curl_cffi session with Safari TLS impersonation."""
        if self._session is None:
            from curl_cffi import requests as curl_requests
            self._session = curl_requests.Session()
            self._session.headers.update({
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/605.1.15 (KHTML, like Gecko) "
                    "Version/17.0 Safari/605.1.15"
                ),
                "Content-Type": "application/json",
                "Accept": "application/json",
                "Referer": "https://www.traderjoes.com/",
                "Origin": "https://www.traderjoes.com",
            })
        return self._session

    def _graphql(self, query: str, variables: dict) -> dict:
        """Execute a GraphQL query and return the response data."""
        session = self._get_session()
        resp = session.post(
            GRAPHQL_URL,
            impersonate="safari17_0",
            json={"query": query, "variables": variables},
            timeout=20,
        )
        resp.raise_for_status()
        data = resp.json()
        if "errors" in data:
            raise Exception(
                f"GraphQL errors: {[e['message'] for e in data['errors']]}"
            )
        return data["data"]

    def authenticate(self) -> None:
        """No authentication required — public GraphQL API."""
        pass

    def search_products(self, query: str) -> list[dict]:
        """Search for Trader Joe's products by keyword.

        Returns normalized price records for all matching items.
        """
        results = []
        page = 1
        total_pages = 1

        while page <= total_pages:
            data = self._graphql(SEARCH_QUERY, {
                "storeCode": "TJ",
                "published": "1",
                "search": query,
                "pageSize": self.PAGE_SIZE,
                "currentPage": page,
            })

            products = data.get("products", {})
            items = products.get("items", [])
            page_info = products.get("page_info", {})
            total_pages = page_info.get("total_pages", 1)

            for item in items:
                results.append(self._normalize(item))

            page += 1

        return results

    def get_product_price(self, product_id: str) -> Optional[dict]:
        """Fetch full price detail for a single product by SKU.

        Args:
            product_id: Product SKU (zero-padded or bare, e.g. "082606" or "82606")

        Returns:
            Normalized price record with ingredients/nutrition, or None.
        """
        data = self._graphql(DETAIL_QUERY, {
            "storeCode": "TJ",
            "published": "1",
            "sku": product_id,
        })

        items = data.get("products", {}).get("items", [])
        if not items:
            return None

        return self._normalize(items[0], detail=True)

    def _normalize(self, item: dict, detail: bool = False) -> dict:
        """Convert a raw GraphQL product item to a normalized price record."""
        price_str = item.get("retail_price") or "0"
        try:
            price = float(price_str)
        except (ValueError, TypeError):
            price = 0.0

        sales_size = item.get("sales_size")
        uom = item.get("sales_uom_description") or ""

        # Build unit: combine size and UOM (e.g. "16 Oz", "1 Each")
        unit = None
        if sales_size and uom:
            size_str = str(sales_size).rstrip(".0") if isinstance(sales_size, float) else str(sales_size)
            unit = f"{size_str} {uom}"
        elif uom:
            unit = uom

        # Category hierarchy
        category_hierarchy = item.get("category_hierarchy", [])
        department = category_hierarchy[-1]["name"] if category_hierarchy else None

        fun_tags = item.get("fun_tags") or None
        new_product = item.get("new_product") == "1"

        extra = {
            "brand": "Trader Joe's",  # Nearly everything is private label
            "department": department,
            "category_hierarchy": [c["name"] for c in category_hierarchy],
            "fun_tags": fun_tags,
            "new_product": new_product,
        }

        if detail:
            extra["ingredients"] = item.get("ingredients")
            extra["allergens"] = item.get("allergens")
            nutrition = item.get("nutrition_facts") or {}
            if nutrition:
                extra["nutrition"] = {
                    k: v for k, v in nutrition.items() if v is not None
                }

        return self.normalize_price(
            product_id=item.get("sku", ""),
            name=item.get("item_title", ""),
            price=price,
            unit=unit,
            url=f"https://www.traderjoes.com/home/products/pdp/{item.get('sku', '')}",
            upc=None,  # No UPC/barcode in the API response
            extra=extra,
        )
