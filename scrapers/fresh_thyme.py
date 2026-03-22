"""Fresh Thyme scraper — ww2.freshthyme.com (mi9cloud platform, NOT Instacart).

==============================================================================
ARCHITECTURE OVERVIEW
==============================================================================

Fresh Thyme uses two separate systems:

1. PRODUCT SEARCH (search_products)
   - Server-side rendered HTML at ww2.freshthyme.com
   - No JavaScript required — plain requests + CSS selectors
   - URL: https://ww2.freshthyme.com/sm/planning/rsid/{store_id}/results?q={query}
   - Product IDs extracted from URL slug: ".../product/...-id-{barcode}"
   - CSS class names are styled-components hashes (can change on site rebuild)
     → use [class*='ProductCardName'], [class*='ProductPrice'], etc.

2. WEEKLY CIRCULAR (scrape_circular)
   - Powered by Flipp's SFML SDK — rendered dynamically inside iframes
   - BUT: the underlying data is available via Flipp's REST API directly
     → No Playwright needed; plain HTTP requests work fine
   - The circular page embeds Flipp config in __PRELOADED_STATE__ JSON:
       merchantId=3552, retailer=freshthymemarket,
       accessToken=69a8b46e89fdcd76ead41634ec35ac69
   - Two publication types exist per store:
       • "Weekly Ad"  — BOGO/sale items, valid ~7 days (use this for prices)
       • "Monthly Ad" — editorial/themed pages, valid ~30 days (skip)
   - Flipp API endpoints (dam.flippenterprise.net):
       GET /flyerkit/publications/{retailer}?languages[]=en&locale=en
           &access_token={token}&store_code={store_id}
         → returns list of active publications with IDs
       GET /flyerkit/publication/{pub_id}/products?display_type=all&locale=en
           &access_token={token}
         → returns all items with name, price, sale_story, unit, validity dates
   - Item JSON fields:
       id           → product ID (integer)
       name         → product name
       sale_story   → deal text: "BUY ONE GET ONE FREE", "2 for $5", etc.
       price_text   → numeric price string, e.g. "6.99" (empty for BOGO-only)
       pre_price_text  → prefix like "$" or empty
       post_price_text → unit suffix like "LB", "EA", or empty
       item_type    → 1 = individual product, 5 = flyer page/section header
       valid_from / valid_to → ISO date strings

==============================================================================
STORE IDs
==============================================================================

Broad Ripple, Indianapolis (6301 N College Ave, IN 46220): store_id = "104"
Circular URL: https://ww2.freshthyme.com/sm/planning/rsid/104/circular

==============================================================================
INSTALL
==============================================================================

pip install requests parsel
(playwright no longer required for circular scraping)
"""
import json
import logging
import re
from typing import Optional

import requests
from parsel import Selector

from .base import BaseScraper

logger = logging.getLogger(__name__)

BASE_URL = "https://ww2.freshthyme.com"
SEARCH_PATH = "/sm/planning/rsid/{store_id}/results"

# Flipp enterprise API — discovered by intercepting network requests on the
# circular page. The access token is embedded in the mi9cloud page's
# __PRELOADED_STATE__ JSON blob under settings.retailer.flyerConfiguration.flipp.
FLIPP_API = "https://dam.flippenterprise.net/flyerkit"
FLIPP_TOKEN = "69a8b46e89fdcd76ead41634ec35ac69"
FLIPP_RETAILER = "freshthymemarket"

# Regex to extract barcode/product ID from product page URLs:
# e.g. ".../product/organic-valley-whole-milk-gallon-id-00093966007428"
_ID_RE = re.compile(r"-id-(\d+)$")


HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://ww2.freshthyme.com/",
}

FLIPP_HEADERS = {
    "User-Agent": HEADERS["User-Agent"],
    "Accept": "application/json",
    "Referer": "https://ww2.freshthyme.com/",
    "Origin": "https://ww2.freshthyme.com",
}


class FreshThymeScraper(BaseScraper):
    retailer = "fresh_thyme"

    def __init__(self, store_id: str, config: dict):
        super().__init__(store_id, config)
        self.session = requests.Session()
        self.session.headers.update(HEADERS)

    def authenticate(self) -> None:
        # No auth needed — prices are publicly visible without login.
        # Warm the session with a homepage hit to get any session cookies.
        try:
            self.session.get(BASE_URL, timeout=15)
            logger.info("Fresh Thyme session warmed.")
        except Exception as exc:
            logger.warning(f"Fresh Thyme warmup failed (non-fatal): {exc}")

    def search_products(self, query: str) -> list[dict]:
        """Search the SSR product catalog at ww2.freshthyme.com."""
        url = BASE_URL + SEARCH_PATH.format(store_id=self.store_id)
        resp = self.session.get(url, params={"q": query}, timeout=20)
        resp.raise_for_status()

        self.save_raw({"url": resp.url, "html_length": len(resp.text)}, f"search_{query.replace(' ', '_')}")

        sel = Selector(resp.text)
        preloaded_state_script = sel.xpath('//script[contains(., "__PRELOADED_STATE__")]/text()').get()
        if not preloaded_state_script:
            logger.warning("[fresh_thyme] Could not find __PRELOADED_STATE__ script tag.")
            return []

        try:
            match = re.search(r"__PRELOADED_STATE__=({.+})", preloaded_state_script)
            if not match:
                logger.error("[fresh_thyme] Could not find __PRELOADED_STATE__ JSON object in script tag.")
                return []
            data = json.loads(match.group(1))
        except (IndexError, json.JSONDecodeError) as e:
            logger.error(f"[fresh_thyme] Failed to parse __PRELOADED_STATE__ JSON: {e}")
            return []

        products = data.get('products', {}).get('products', {}).values()

        results = []
        for product in products:
            product_id = product.get('barcode')
            name = product.get('name')
            price_info = product.get('price', {})
            price = price_info.get('sell')
            size = product.get('size')

            if not all([product_id, name, price]):
                continue

            results.append(
                self.normalize_price(
                    product_id=str(product_id),
                    name=name.strip(),
                    price=float(price),
                    unit=size,
                    url=BASE_URL + product.get('slug', ''),
                    upc=str(product_id),  # barcode field is a real UPC
                )
            )

        logger.debug(f"[fresh_thyme] Parsed {len(results)} products for '{query}' from JSON.")
        return results

    def get_product_price(self, product_id: str) -> Optional[dict]:
        results = self.search_products(product_id)
        for r in results:
            if r["product_id"] == product_id:
                return r
        return None

    def scrape_circular(self) -> list[dict]:
        """
        Scrape the weekly circular via Flipp's REST API.

        Flow:
          1. GET /flyerkit/publications/{retailer}?store_code={id}
             → find the "Weekly Ad" publication ID
          2. GET /flyerkit/publication/{pub_id}/products?display_type=all
             → get all items (name, price, sale_story, unit, validity)
          3. Filter to item_type=1 (individual products, not page headers)
          4. Normalize and return

        Returns list of price dicts. BOGO items have price=0.0 and
        deal_text set; priced items have the actual price.
        """
        pub_id = self._get_weekly_publication_id()
        if not pub_id:
            logger.warning("[fresh_thyme] No Weekly Ad publication found — trying Monthly Ad.")
            pub_id = self._get_any_publication_id()
        if not pub_id:
            raise RuntimeError("[fresh_thyme] No active Flipp publication found for store.")

        items = self._fetch_publication_products(pub_id)
        results = []
        for item in items:
            # item_type=1 → individual product; item_type=5 → flyer page/header
            if item.get("item_type") != 1:
                continue

            product_id = str(item["id"])
            name = (item.get("name") or "").strip()
            if not name:
                continue

            price_str = (item.get("price_text") or "").strip()
            try:
                price = float(price_str) if price_str else 0.0
            except ValueError:
                price = 0.0

            unit = (item.get("post_price_text") or "").strip() or None
            deal = (item.get("sale_story") or "").strip() or None
            web_url = item.get("web_commission_url") or item.get("item_web_url") or ""

            results.append(
                self.normalize_price(
                    product_id=product_id,
                    name=name,
                    price=price,
                    unit=unit,
                    url=web_url,
                    extra={
                        "deal_text": deal,
                        "valid_from": item.get("valid_from"),
                        "valid_to": item.get("valid_to"),
                    },
                )
            )

        self.save_raw(items, f"circular_pub{pub_id}")
        logger.info(f"[fresh_thyme] Scraped {len(results)} items from weekly circular (pub {pub_id}).")
        return results

    # ------------------------------------------------------------------
    # Flipp API helpers
    # ------------------------------------------------------------------

    def _get_weekly_publication_id(self) -> Optional[int]:
        """Return the publication ID for the current 'Weekly Ad', or None."""
        pubs = self._fetch_publications()
        for pub in pubs:
            if "weekly" in (pub.get("name") or "").lower():
                return pub["id"]
        return None

    def _get_any_publication_id(self) -> Optional[int]:
        """Return the first available publication ID regardless of type."""
        pubs = self._fetch_publications()
        return pubs[0]["id"] if pubs else None

    def _fetch_publications(self) -> list[dict]:
        """
        GET /flyerkit/publications/{retailer}?store_code={id}&languages[]=en&locale=en
        Returns list of active publications for this store.
        """
        url = f"{FLIPP_API}/publications/{FLIPP_RETAILER}"
        resp = requests.get(
            url,
            params={
                "languages[]": "en",
                "locale": "en",
                "access_token": FLIPP_TOKEN,
                "store_code": self.store_id,
            },
            headers=FLIPP_HEADERS,
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json()

    def _fetch_publication_products(self, pub_id: int) -> list[dict]:
        """
        GET /flyerkit/publication/{pub_id}/products?display_type=all
        Returns all items for a publication.
        """
        url = f"{FLIPP_API}/publication/{pub_id}/products"
        resp = requests.get(
            url,
            params={
                "display_type": "all",
                "locale": "en",
                "access_token": FLIPP_TOKEN,
            },
            headers=FLIPP_HEADERS,
            timeout=20,
        )
        resp.raise_for_status()
        return resp.json()


# ------------------------------------------------------------------
# HTML parsing helpers (used by search_products)
# ------------------------------------------------------------------

