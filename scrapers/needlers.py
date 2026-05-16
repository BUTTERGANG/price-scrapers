"""Needler's Fresh Market scraper — storebyweb.com REST API (full store catalog).

==============================================================================
ARCHITECTURE OVERVIEW
==============================================================================

Needler's Fresh Market runs a React SPA on needler.storebyweb.com backed by
a simple unauthenticated REST API. No Playwright, no auth, no bot detection —
plain requests works fine.

PRODUCT SEARCH (search_products)
----------------------------------------------------------------------
  POST https://needler.storebyweb.com/s/{store_id}/api/b/
  Body: {"pn": 1, "ps": 100, "q": "milk"}
  Returns: {"totalCount": N, "items": [...]}

FULL CATALOG (scrape_catalog)
----------------------------------------------------------------------
Same endpoint, paginated, without the "q" field.
Max reliable page size is 120; use 100 for safety.
Indianapolis store has ~22,000+ items.

ITEM FIELDS
----------------------------------------------------------------------
  id              — internal ID ("INV-1000-XXXXX")
  name            — product name (uppercase)
  scanCode        — UPC/barcode
  actualPrice     — current shelf price (float, dollars)
  actualPriceDivider — 1 = unit price; 2 = "2/$X" deal
  suggestedPrice  — MSRP (usually 0.0, ignore)
  size            — package size string ("16 OZ", "1 LB", etc.)
  brand           — brand name
  department      — department name ("PRODUCE", "DAIRY", etc.)
  departmentId    — department ID string
  weightProfile   — present for by-weight items; .abbrv is unit ("lb")
  outOfStock      — bool

PRICE INTERPRETATION
----------------------------------------------------------------------
  Normal:          price = actualPrice                         e.g. $4.99
  Multi-unit deal: price = actualPrice / actualPriceDivider    e.g. 2/$5 → $2.50 ea
  By-weight:       price per weightProfile.abbrv               e.g. $6.99/lb

==============================================================================
STORE IDs (storebyweb.com)
==============================================================================

  1000-6062  number=929  Needler's Lockerbie, Indianapolis IN  ← user store
  1000-8119  number=933  Needler's Carmel, Carmel IN
  1000-4053  number=926  Needler's Elwood, Elwood IN
  1000-4054  number=928  Needler's Pendleton, Pendleton IN
  1000-4055  number=930  Needler's Richmond, Richmond IN
  1000-5054  number=922  Needler's Marion, Marion IN
  1000-5055  number=925  Needler's Hartford City, Hartford City IN
  1000-5056  number=927  Needler's Tipton, Tipton IN
  1000-6061  number=921  Needler's New Palestine, New Palestine IN
  1000-11168 number=2697 Needler's Anderson, Anderson IN
  1000-2054  number=952  Needler's Middletown, Middletown OH

Run NeedlersScraper.find_store_id() to refresh this list from the API.

==============================================================================
INSTALL
==============================================================================

pip install requests
(No curl_cffi, no parsel — JSON API, no HTML parsing needed)
"""
import logging
import math
from typing import Optional

import requests

from .base import BaseScraper

logger = logging.getLogger(__name__)

BASE_URL = "https://needler.storebyweb.com"
PAGE_SIZE = 100  # max tested: 120; using 100 for safety

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    ),
    "Content-Type": "application/json",
    "Accept": "application/json, text/plain, */*",
    "Origin": BASE_URL,
}


class NeedlersScraper(BaseScraper):
    """Scraper for Needler's Fresh Market (storebyweb.com REST API)."""

    retailer = "needlers"

    def __init__(self, store_id: str, config: dict):
        """
        Args:
            store_id: storebyweb.com store ID, e.g. "1000-6062" for Indianapolis.
                      Run NeedlersScraper.find_store_id() to list all stores.
        """
        super().__init__(store_id, config)
        self.session = requests.Session()
        self.session.headers.update({
            **_HEADERS,
            "Referer": f"{BASE_URL}/s/{store_id}/b",
        })

    @property
    def _api_url(self) -> str:
        return f"{BASE_URL}/s/{self.store_id}/api/b/"

    def authenticate(self) -> None:
        """No authentication required — public API."""
        pass

    def search_products(self, query: str) -> list[dict]:
        """
        Search the store catalog by keyword.
        Returns normalized price records for all matching items.
        """
        results = []
        page = 1
        total_pages = 1

        while page <= total_pages:
            resp = self.session.post(
                self._api_url,
                json={"pn": page, "ps": PAGE_SIZE, "q": query},
                timeout=20,
            )
            resp.raise_for_status()
            data = resp.json()

            total_count = data.get("totalCount", 0)
            total_pages = math.ceil(total_count / PAGE_SIZE) if total_count else 1

            for item in data.get("items", []):
                results.append(self._normalize(item))

            page += 1

        return results

    def get_product_price(self, product_id: str) -> Optional[dict]:
        """
        Look up a single product by its internal ID or scanCode.
        Searches the catalog and returns the first exact match, or None.
        """
        # Try searching by name/code — storebyweb search handles barcodes too
        resp = self.session.post(
            self._api_url,
            json={"pn": 1, "ps": PAGE_SIZE, "q": product_id},
            timeout=20,
        )
        resp.raise_for_status()
        for item in resp.json().get("items", []):
            if item.get("id") == product_id or item.get("scanCode") == product_id:
                return self._normalize(item)
        return None

    def scrape_catalog(self) -> list[dict]:
        """
        Download the full store catalog (all items with current prices).
        For Indianapolis (~22,000 items) this takes ~220 paginated requests.

        Returns a list of normalized price records.
        """
        self.authenticate()
        results: list[dict] = []
        raw_all: list[dict] = []

        # First request to get totalCount
        resp = self.session.post(
            self._api_url,
            json={"pn": 1, "ps": PAGE_SIZE},
            timeout=20,
        )
        resp.raise_for_status()
        data = resp.json()
        total_count = data.get("totalCount", 0)
        total_pages = math.ceil(total_count / PAGE_SIZE) if total_count else 1

        logger.info(
            f"[needlers] Catalog: {total_count} items across {total_pages} pages "
            f"(store {self.store_id})"
        )

        for item in data.get("items", []):
            raw_all.append(item)
            results.append(self._normalize(item))

        for page in range(2, total_pages + 1):
            resp = self.session.post(
                self._api_url,
                json={"pn": page, "ps": PAGE_SIZE},
                timeout=20,
            )
            resp.raise_for_status()
            items = resp.json().get("items", [])
            for item in items:
                raw_all.append(item)
                results.append(self._normalize(item))
            if page % 50 == 0:
                logger.info(
                    f"[needlers] Page {page}/{total_pages} — {len(results)} items so far"
                )

        self.save_raw(raw_all, "catalog_all")
        logger.info(f"[needlers] Scraped {len(results)} items (store {self.store_id}).")
        return results

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _normalize(self, item: dict) -> dict:
        """Convert a raw API item dict to a normalized price record."""
        actual_price: float = item.get("actualPrice") or 0.0
        divider: int = item.get("actualPriceDivider") or 1

        # Multi-unit deal: e.g. actualPrice=5.00, actualPriceDivider=2 → $2.50 each
        unit_price = round(actual_price / divider, 4) if divider > 1 else None

        # Weight-based unit (e.g. "lb" for produce sold by weight)
        weight = item.get("weightProfile") or {}
        unit = weight.get("abbrv") or None  # "lb", "oz", etc.

        deal_text: Optional[str] = None
        if divider > 1:
            deal_text = f"{divider}/${actual_price:.2f}".rstrip("0").rstrip(".")

        # When actualPrice is 0 or None, the item is a text-only promo (BOGO,
        # multi-unit, etc.) with no numeric shelf price. Emit price=None so the
        # record is identifiable as a text-only deal and is not silently dropped
        # by > 0 filters in queries.
        if unit_price is not None:
            computed_price = unit_price
        elif actual_price:
            computed_price = actual_price
        else:
            computed_price = None

        raw_dept = item.get("department") or None
        department = raw_dept.title() if raw_dept else None

        return self.normalize_price(
            product_id=item.get("id", ""),
            name=item.get("name", ""),
            price=computed_price,
            unit=unit,
            url=f"{BASE_URL}/s/{self.store_id}/b",
            upc=item.get("scanCode") or None,  # scanCode is the UPC barcode
            extra={
                "deal_text": deal_text,
                "brand": item.get("brand") or None,
                "size": item.get("size") or None,
                "department": department,
                "department_id": item.get("departmentId") or None,
                "out_of_stock": item.get("outOfStock", False),
            },
        )

    # ------------------------------------------------------------------
    # Store locator
    # ------------------------------------------------------------------

    @classmethod
    def find_store_id(cls) -> list[dict]:
        """
        Fetch the list of all Needler's storebyweb.com stores.
        Returns list of dicts with id, number, name, city, state.

        Example:
            stores = NeedlersScraper.find_store_id()
            for s in stores:
                print(s["id"], s["name"], s["city"])
        """
        resp = requests.get(
            f"{BASE_URL}/s/1000-8119/api/stores",
            headers={k: v for k, v in _HEADERS.items() if k != "Content-Type"},
            timeout=15,
        )
        resp.raise_for_status()
        stores = []
        for st in resp.json().get("data", []):
            addr = st.get("addresses", [{}])[0]
            stores.append({
                "id": st["id"],
                "number": st.get("number", ""),
                "name": st.get("name", ""),
                "city": addr.get("city", ""),
                "state": addr.get("state", ""),
                "address": addr.get("street1", ""),
            })
        return stores
