"""Meijer scraper — JSON API at meijer.com/bin/meijer/ + Flipp weekly circular.

==============================================================================
ARCHITECTURE OVERVIEW
==============================================================================

1. PRODUCT SEARCH (search_products)
   - Meijer uses Adobe Experience Manager (AEM). Product data is served via
     XHR JSON endpoints, publicly accessible with no API key.
   - Store locator : GET /bin/meijer/store/storelocator.json?lat=&lon=&maxCount=
   - Product search: GET /bin/meijer/product/search.json
                         ?query=&storeId=&pageSize=&currentPage=
   - Requires Referer: https://www.meijer.com/ header (403 otherwise)
   - Use curl_cffi with browser impersonation (Akamai bot detection on main site)

2. WEEKLY CIRCULAR (scrape_circular)
   - Powered by Flipp (same system as Fresh Thyme, different API host/version)
   - Credentials extracted from clientlib-react JS bundle at:
       /etc.clientlibs/meijer-spa/clientlibs/clientlib-react.lc-*.js
     (search for `publications/meijer` to find the token)
   - Flipp API base: https://api.flipp.com/flyerkit/v4.0/
   - Access token : 81771d0c149847a93bc30b8e5b65bffb  (var h in bundle)
   - Merchant ID  : 2281                               (var p in bundle)
   - Retailer slug: meijer                             (var f in bundle)
   - Step 1 — list publications:
       GET /flyerkit/v4.0/publications/meijer
           ?access_token=TOKEN&locale=en-US&store_code=STORE_ID
     Returns e.g.: Weekly Ad, Pullout GM, Super Sale
   - Step 2 — fetch items:
       GET /flyerkit/v4.0/publication/{pub_id}/products?display_type=all
           &locale=en-US&access_token=TOKEN
     Item JSON fields:
       id              → integer product ID
       name            → product name
       sale_story      → deal text ("BOGO 50% off", "Buy 2 Save $1", etc.) or null
       price_text      → numeric string e.g. "8.99" (empty for deal-only items)
       pre_price_text  → prefix e.g. "sale price", "3/", "sale"
       post_price_text → unit suffix e.g. "lb", "ea", or empty
       item_type       → 1 = individual product, 5 = flyer page/section header
       valid_from / valid_to → "YYYY-MM-DD" strings

==============================================================================
STORE IDs
==============================================================================

5550 N Keystone Ave, Indianapolis IN 46220: store_id = "290"
  (confirmed via meijer.com/shopping/store-locator/290.html URL pattern)
  Run MeijerScraper.find_store_id() to verify.

==============================================================================
INSTALL
==============================================================================

pip install curl-cffi requests
"""
import logging
from typing import Optional

import requests

from .base import BaseScraper
from utils.http import make_curl_session, request_with_retry

logger = logging.getLogger(__name__)

BASE_URL = "https://www.meijer.com"
STORE_LOCATOR_URL = BASE_URL + "/bin/meijer/store/storelocator.json"
PRODUCT_SEARCH_URL = BASE_URL + "/bin/meijer/product/search.json"

# Flipp API — extracted from clientlib-react JS bundle (search "publications/meijer")
FLIPP_API = "https://api.flipp.com/flyerkit/v4.0"
FLIPP_TOKEN = "81771d0c149847a93bc30b8e5b65bffb"
FLIPP_RETAILER = "meijer"
FLIPP_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
    "Referer": "https://www.meijer.com/",
    "Origin": "https://www.meijer.com",
}

# Broad Ripple coordinates for store locator
_BROAD_RIPPLE_LAT = 39.8676
_BROAD_RIPPLE_LON = -86.1354


class MeijerScraper(BaseScraper):
    retailer = "meijer"

    def __init__(self, store_id: str, config: dict):
        super().__init__(store_id, config)
        self.session = make_curl_session(proxy=config.get("proxy"))
        # Meijer checks Referer — requests without it return 403
        self.session.headers.update(
            {
                "Accept": "application/json, text/plain, */*",
                "Referer": "https://www.meijer.com/",
                "Origin": "https://www.meijer.com",
            }
        )

    def authenticate(self) -> None:
        # Warm the session with the homepage to receive session cookies
        try:
            request_with_retry(self.session, "GET", BASE_URL, timeout=15)
            logger.info("Meijer session warmed.")
        except Exception as exc:
            logger.warning(f"Meijer warmup failed (non-fatal): {exc}")

    @classmethod
    def find_store_id(
        cls,
        config: dict,
        lat: float = _BROAD_RIPPLE_LAT,
        lon: float = _BROAD_RIPPLE_LON,
        max_count: int = 5,
    ) -> list[dict]:
        """
        Query the Meijer store locator for stores near a coordinate.
        Returns a list of stores with storeNumber, name, and address.
        Run this once to confirm the correct store ID for 5550 N Keystone Ave.

        Example:
            stores = MeijerScraper.find_store_id(config={})
            for s in stores:
                print(s["storeNumber"], s["address"])
        """
        scraper = cls(store_id="", config=config)
        scraper.authenticate()
        resp = request_with_retry(
            scraper.session,
            "GET",
            STORE_LOCATOR_URL,
            params={"lat": lat, "lon": lon, "maxCount": max_count},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        scraper.save_raw(data, "store_locator")

        stores = []
        for s in data if isinstance(data, list) else data.get("stores", []):
            stores.append(
                {
                    "storeNumber": s.get("storeNumber") or s.get("storeId", ""),
                    "name": s.get("name", "Meijer"),
                    "address": s.get("address", ""),
                    "city": s.get("city", ""),
                    "state": s.get("state", ""),
                    "zip": s.get("zip", ""),
                    "distance": s.get("distance", ""),
                }
            )
        return stores

    def search_products(self, query: str) -> list[dict]:
        results = []
        page = 0
        page_size = 24

        while True:
            resp = request_with_retry(
                self.session,
                "GET",
                PRODUCT_SEARCH_URL,
                params={
                    "query": query,
                    "storeId": self.store_id,
                    "pageSize": page_size,
                    "currentPage": page,
                },
                timeout=20,
            )
            resp.raise_for_status()
            data = resp.json()

            if page == 0:
                self.save_raw(data, f"search_{query.replace(' ', '_')}")

            products = data.get("products", [])
            if not products:
                break

            for item in products:
                price_obj = item.get("price", {})
                sale_obj = item.get("salePrice", {})

                regular = price_obj.get("value") or price_obj.get("formattedValue", "").lstrip("$")
                try:
                    regular = float(regular) if regular else None
                except (ValueError, TypeError):
                    regular = None

                sale = sale_obj.get("value") if sale_obj else None

                code = str(item.get("code", ""))
                results.append(
                    self.normalize_price(
                        product_id=code,
                        name=item.get("name", ""),
                        price=regular or 0.0,
                        unit=item.get("unitOfMeasurement") or item.get("packageSize"),
                        url=BASE_URL + "/shopping/product/" + code + ".html",
                        upc=code or None,  # Meijer code — may be UPC; unverified
                        extra={
                            "sale_price": sale,
                            "brand": item.get("brandName", ""),
                            "mperks_eligible": item.get("mPerksEligible", False),
                        },
                    )
                )

            # Check if there are more pages
            total = data.get("pagination", {}).get("totalResults", 0)
            if len(results) >= total or len(products) < page_size:
                break
            page += 1

        return results

    def scrape_circular(self, pub_name: str = "Weekly Ad") -> list[dict]:
        """
        Scrape the Meijer weekly circular via Flipp's REST API.

        Args:
            pub_name: Publication name to use. Meijer typically has:
                      "Weekly Ad"  — main weekly sale items (~7 days)
                      "Pullout GM" — general merchandise supplement
                      "Super Sale" — short-duration flash sales (1-2 days)
                      Pass pub_name=None to use whichever publication is found first.

        Returns list of normalized price dicts. Items with no explicit price
        (BOGO/deal-only) have price=0.0 and deal_text set in extra fields.
        """
        pubs = self._fetch_publications()
        pub_id = None
        if pub_name:
            for pub in pubs:
                if pub_name.lower() in (pub.get("name") or "").lower():
                    pub_id = pub["id"]
                    break
        if not pub_id and pubs:
            pub_id = pubs[0]["id"]
        if not pub_id:
            raise RuntimeError(f"[meijer] No Flipp publication found for store {self.store_id}.")

        raw_items = self._fetch_publication_products(pub_id)
        results = []
        for item in raw_items:
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
            pre = (item.get("pre_price_text") or "").strip() or None
            deal = (item.get("sale_story") or "").strip() or None
            description = (item.get("description") or "").strip() or None
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
                        "pre_price_text": pre,
                        "valid_from": item.get("valid_from"),
                        "valid_to": item.get("valid_to"),
                        "image_url": item.get("image_url"),
                        "description": description,
                    },
                )
            )

        self.save_raw(raw_items, f"circular_pub{pub_id}")
        logger.info(f"[meijer] Scraped {len(results)} items from '{pub_name}' circular (pub {pub_id}).")
        return results

    def _fetch_publications(self) -> list[dict]:
        """List active Flipp publications for this store."""
        resp = requests.get(
            f"{FLIPP_API}/publications/{FLIPP_RETAILER}",
            params={"access_token": FLIPP_TOKEN, "locale": "en-US", "store_code": self.store_id},
            headers=FLIPP_HEADERS,
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json()

    def _fetch_publication_products(self, pub_id: int) -> list[dict]:
        """Fetch all items for a Flipp publication."""
        resp = requests.get(
            f"{FLIPP_API}/publication/{pub_id}/products",
            params={"display_type": "all", "locale": "en-US", "access_token": FLIPP_TOKEN},
            headers=FLIPP_HEADERS,
            timeout=20,
        )
        resp.raise_for_status()
        return resp.json()

    def get_product_price(self, product_id: str) -> Optional[dict]:
        resp = request_with_retry(
            self.session,
            "GET",
            PRODUCT_SEARCH_URL,
            params={"query": product_id, "storeId": self.store_id, "pageSize": 1, "currentPage": 0},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        products = data.get("products", [])
        if not products:
            return None
        item = products[0]
        price_obj = item.get("price", {})
        try:
            price = float(price_obj.get("value", 0))
        except (ValueError, TypeError):
            price = 0.0
        return self.normalize_price(
            product_id=str(item.get("code", "")),
            name=item.get("name", ""),
            price=price,
        )
