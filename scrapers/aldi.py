"""Aldi scraper — weekly circular via Flipp REST API (dam.flippenterprise.net).

==============================================================================
ARCHITECTURE OVERVIEW
==============================================================================

Aldi's platform is Nuxt.js (Vue) + Spryker e-commerce backend. The weekly
circular is powered by Flipp using the same dam.flippenterprise.net API as
Fresh Thyme — different token and retailer slug, same endpoints and response
structure. No Playwright, no authentication, no bot blocking.

1. WEEKLY CIRCULAR (scrape_circular)
   ---------------------------------------------------------------------
   Three-step flow:

   Step 1 — Locate the store:
     GET https://api.aldi.us/v2/service-points
         ?addressZipcode={zip}&serviceType=pickup
         &limit=10&includeNearbyServicePoints=true
     Returns service-point objects with:
       id      → Flipp store_code (format "444-086")
       name    → "ALDI"
       address → { street, city, zipCode, state }
       distance

   Step 2 — List publications for the store:
     GET https://dam.flippenterprise.net/flyerkit/publications/aldi
         ?store_code=444-086&languages[]=en&locale=en&access_token=TOKEN
     Returns publications (typically 2):
       "Weekly Ad"    — current week (type: weeklyad)
       "In Store Ad"  — next week preview (type: instoread)

   Step 3 — Fetch all deal items:
     GET https://dam.flippenterprise.net/flyerkit/publication/{pub_id}/products
         ?display_type=all&locale=en&access_token=TOKEN
     Returns ~109 items. Each item:
       id                → integer product ID
       name              → product name
       description       → size/weight (e.g. "Per 16-oz. Pkg.")
       price_text        → numeric string e.g. "2.99" — all items have a price
       pre_price_text    → special label: "PRICE DROPS" or empty
       post_price_text   → unit qualifier: "Each", "Per 1-Lb. Pkg.", etc. or empty
       sale_story        → deal text or null (typically null for Aldi; no BOGO deals)
       original_price    → original price before sale, or null
       categories        → Aldi category list, e.g. ["Dairy"], ["Meat & Seafood"]
       item_categories   → Google taxonomy (l1–l7 hierarchy)
       valid_from / valid_to → "YYYY-MM-DD" strings
       item_type         → 1 = product, 5 = flyer page/header (skip)
       in_store_only     → bool (always true for Aldi — all items are in-store)
       image_url, images → product images

2. PRODUCT SEARCH (search_products)
   ---------------------------------------------------------------------
   Aldi has a Spryker product catalog API at api.aldi.us, but product-level
   shelf pricing requires store context and session headers. The weekly
   circular is the primary (and most reliable) data source.
   search_products() falls back to scanning the current circular.

==============================================================================
STORE IDs
==============================================================================

Aldi store codes use a "444-NNN" format (Spryker service-point IDs).
The URL slug (e.g. "f252") is for web navigation only — not used by APIs.

Stores near ZIP 46220:
  444-075 — 5235 N. Keystone Ave, Indianapolis 46220  (3.7 mi — closest to Broad Ripple)
  444-088 — 5151 E. 82nd St, Indianapolis 46250        (1.9 mi)
  444-086 — 1440 E. 86th St, Indianapolis 46240        (4.4 mi — user-specified store)

Run AldiScraper.find_store_id(zip_code="46220") to list nearby stores.

==============================================================================
INSTALL
==============================================================================

pip install requests
(No curl_cffi needed — no bot detection on these endpoints)
"""
import logging
from typing import Optional

import requests

from .base import BaseScraper

logger = logging.getLogger(__name__)

# Flipp enterprise API — same host as Fresh Thyme, different credentials
# Token extracted from Nuxt JS bundle (LeafletSnippet component):
#   new window.Flipp.Storefront({ accessToken: "...", merchantId: "2353", ... })
FLIPP_API = "https://dam.flippenterprise.net/flyerkit"
FLIPP_TOKEN = "29d9bfdcf546dc601c10c64ed1e932f5"
FLIPP_RETAILER = "aldi"

# Spryker store locator API (no auth required)
STORE_LOCATOR_URL = "https://api.aldi.us/v2/service-points"

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
    "Referer": "https://www.aldi.us/",
    "Origin": "https://www.aldi.us",
}


class AldiScraper(BaseScraper):
    """Scraper for Aldi weekly circular via Flipp REST API."""

    retailer = "aldi"

    def __init__(self, store_id: str, config: dict):
        """
        Args:
            store_id: Aldi Spryker service-point ID in "444-NNN" format.
                      e.g. "444-086" for 1440 E 86th St, Indianapolis.
        """
        super().__init__(store_id, config)
        self.session = requests.Session()
        self.session.headers.update(_HEADERS)

    def authenticate(self) -> None:
        # No authentication required.
        pass

    def search_products(self, query: str) -> list[dict]:
        """Search for products in the current week's circular by name."""
        query_lower = query.lower()
        try:
            results = self.scrape_circular()
        except Exception as exc:
            logger.error(f"[aldi] search_products failed for '{query}': {exc}")
            return []
        return [
            r for r in results
            if query_lower in r["name"].lower()
            or query_lower in (r.get("description") or "").lower()
        ]

    def get_product_price(self, product_id: str) -> Optional[dict]:
        try:
            results = self.scrape_circular()
        except Exception as exc:
            logger.error(f"[aldi] get_product_price failed for '{product_id}': {exc}")
            return None
        for r in results:
            if r["product_id"] == product_id:
                return r
        return None

    def scrape_circular(self, pub_name: str = "Weekly Ad") -> list[dict]:
        """
        Scrape the current weekly circular for this store.

        Args:
            pub_name: Publication to scrape.
                      "Weekly Ad"   — current week (default)
                      "In Store Ad" — next week preview
                      Pass None to use whichever publication is listed first.

        Returns list of normalized price dicts. Unlike some other retailers,
        Aldi items nearly always have a numeric price (no BOGO-only items).
        """
        pub_id = self._get_publication_id(pub_name)
        if not pub_id:
            raise RuntimeError(
                f"[aldi] No publication '{pub_name}' found for store {self.store_id}."
            )

        raw_items = self._fetch_publication_products(pub_id)
        self.save_raw(raw_items, f"circular_pub{pub_id}")

        results = []
        for item in raw_items:
            if item.get("item_type") != 1:
                continue

            name = (item.get("name") or "").strip()
            if not name:
                continue

            price_str = (item.get("price_text") or "").strip()
            try:
                price = float(price_str) if price_str else 0.0
            except ValueError:
                price = 0.0

            # post_price_text is the unit qualifier ("Each", "Per 1-Lb. Pkg.", etc.)
            unit = (item.get("post_price_text") or "").strip() or None
            pre = (item.get("pre_price_text") or "").strip() or None   # "PRICE DROPS"
            deal = (item.get("sale_story") or "").strip() or None
            description = (item.get("description") or "").strip() or None
            original_price = item.get("original_price")

            # categories is a list like ["Dairy"] or ["Meat & Seafood"]
            categories = item.get("categories") or []
            category = categories[0] if categories else None

            web_url = item.get("web_commission_url") or item.get("item_web_url") or ""

            results.append(
                self.normalize_price(
                    product_id=str(item["id"]),
                    name=name,
                    price=price,
                    unit=unit,
                    url=web_url or "https://www.aldi.us/weekly-specials/weekly-ads/",
                    extra={
                        "deal_text": deal,
                        "pre_price_text": pre,
                        "original_price": float(original_price) if original_price else None,
                        "description": description,
                        "category": category,
                        "in_store_only": item.get("in_store_only", True),
                        "valid_from": item.get("valid_from"),
                        "valid_to": item.get("valid_to"),
                        "image_url": item.get("image_url"),
                    },
                )
            )

        logger.info(
            f"[aldi] Scraped {len(results)} items from '{pub_name}' "
            f"(pub {pub_id}, store {self.store_id})."
        )
        return results

    # ------------------------------------------------------------------
    # Flipp API helpers
    # ------------------------------------------------------------------

    def _get_publication_id(self, pub_name: Optional[str]) -> Optional[int]:
        pubs = self._fetch_publications()
        if pub_name:
            for pub in pubs:
                if pub_name.lower() in (pub.get("name") or "").lower():
                    return pub["id"]
        return pubs[0]["id"] if pubs else None

    def _fetch_publications(self) -> list[dict]:
        """List active Flipp publications for this store."""
        resp = self.session.get(
            f"{FLIPP_API}/publications/{FLIPP_RETAILER}",
            params={
                "languages[]": "en",
                "locale": "en",
                "access_token": FLIPP_TOKEN,
                "store_code": self.store_id,
            },
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json()

    def _fetch_publication_products(self, pub_id: int) -> list[dict]:
        """Fetch all items for a Flipp publication."""
        resp = self.session.get(
            f"{FLIPP_API}/publication/{pub_id}/products",
            params={
                "display_type": "all",
                "locale": "en",
                "access_token": FLIPP_TOKEN,
            },
            timeout=20,
        )
        resp.raise_for_status()
        return resp.json()

    # ------------------------------------------------------------------
    # Store locator
    # ------------------------------------------------------------------

    @classmethod
    def find_store_id(
        cls,
        zip_code: str = "46220",
        limit: int = 10,
    ) -> list[dict]:
        """
        Query the Aldi store locator for stores near a ZIP code.
        Returns a list of stores with id (Flipp store_code), address, and distance.

        Example:
            stores = AldiScraper.find_store_id(zip_code="46220")
            for s in stores:
                print(s["id"], s["address"])
        """
        session = requests.Session()
        session.headers.update(_HEADERS)
        resp = session.get(
            STORE_LOCATOR_URL,
            params={
                "addressZipcode": zip_code,
                "serviceType": "pickup",
                "limit": limit,
                "includeNearbyServicePoints": "true",
            },
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()

        stores = []
        # Response may be a list or wrapped in a "data" key
        items = data if isinstance(data, list) else data.get("data", data.get("servicePoints", []))
        for s in items:
            addr = s.get("address", {})
            stores.append(
                {
                    "id": s.get("id", ""),
                    "name": s.get("name", "ALDI"),
                    "address": addr.get("street", ""),
                    "city": addr.get("city", ""),
                    "state": addr.get("state", ""),
                    "zip": addr.get("zipCode", ""),
                    "distance": s.get("distance", ""),
                }
            )
        return stores
