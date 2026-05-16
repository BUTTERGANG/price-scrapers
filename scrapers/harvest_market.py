"""Niemann Harvest Market scraper — Webstop platform, weekly circular via SSR HTML.

==============================================================================
ARCHITECTURE OVERVIEW
==============================================================================

Harvest Market (Niemann Foods) uses the Webstop grocery platform hosted at
www2.goharvestmarket.com / www3.goharvestmarket.com. No Playwright, no auth,
no bot detection — plain requests works fine.

WEEKLY CIRCULAR (scrape_circular)
----------------------------------------------------------------------
Three-step flow:

Step 1 — Set store:
  GET https://www3.goharvestmarket.com/retailers/3328/stores/{store_id}/choose_store
      ?filter=circulars&url=https://www2.goharvestmarket.com/circulars/
  → Sets session cookies: 3328_store_id, 3328_store_number
  → Redirects to the current circular URL (contains the circular code, e.g. "260318_HM")

Step 2 — Fetch department pages:
  GET https://www2.goharvestmarket.com/circulars/department/{dept}/
  One request per department (9 total). Items are server-side rendered inside
  <article> modals — no JavaScript or XHR required.

Step 3 — Parse item modals:
  Each item is an <article id="circular-item-{id}"> with:
    .circular-item-heading    → extra label (e.g. "USDA Choice", "DIGITAL COUPON",
                                 store name for location-specific items)
    .circular-item-title      → product name (h3)
    .circular-item-description → size/variety info
    .price-prefix             → multi-unit prefix, e.g. "2/" or "3/"
    .price-dollars            → dollar amount (no $ sign)
    .price-cents              → cents string with dot, e.g. ".99" (may be empty)
    .price-suffix             → unit qualifier, e.g. "lb.", "ea."
    .bg-secondary text        → "Valid MM/DD/YYYY to MM/DD/YYYY"
  Price examples:
    "$4.99 lb." → prefix="", dollars="4", cents=".99", suffix="lb."
    "$11"       → prefix="", dollars="11", cents="",    suffix=""
    "2/$5"      → prefix="2/", dollars="5", cents="",   suffix=""
    no price    → all empty (item has no listed price)

PRODUCT SEARCH (search_products)
----------------------------------------------------------------------
Webstop has no public product search API. search_products() scans the current
weekly circular in-memory.

==============================================================================
STORE IDs
==============================================================================

Webstop store IDs for Harvest Market (retailer 3328):
  Store 17 / store_number 584 — 2140 E 116th St, Carmel, IN 46032

Run HarvestMarketScraper.find_store_id(zip_code="46032") to list nearby stores.

The circular "Base" number (2) is a Webstop ad-type ID, not a store ID.
Each store page redirects to the same Base/2 ad (the weekly circular) — there
is one shared weekly circular across all Harvest Market locations.

==============================================================================
INSTALL
==============================================================================

pip install requests parsel
(No curl_cffi needed — no bot detection on these endpoints)
"""
import logging
import re
from typing import Optional

import requests
from parsel import Selector

from .base import BaseScraper

logger = logging.getLogger(__name__)

BASE_URL = "https://www2.goharvestmarket.com"
API_HOST = "https://www3.goharvestmarket.com"
RETAILER_ID = "3328"

DEPARTMENTS = [
    "Bakery",
    "Beer_and_Wine",
    "Dairy",
    "Deli",
    "Fresh_Meat",
    "Frozen",
    "Grocery",
    "Produce",
    "Seafood",
]

# Regex to parse "Valid MM/DD/YYYY to MM/DD/YYYY"
_VALID_RE = re.compile(
    r"Valid\s+(\d{2}/\d{2}/\d{4})\s+to\s+(\d{2}/\d{2}/\d{4})", re.IGNORECASE
)

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": BASE_URL + "/",
}


class HarvestMarketScraper(BaseScraper):
    """Scraper for Niemann Harvest Market weekly circular (Webstop platform)."""

    retailer = "harvest_market"

    def __init__(self, store_id: str, config: dict):
        """
        Args:
            store_id: Webstop store ID (integer string). e.g. "17" for Carmel, IN.
                      Run HarvestMarketScraper.find_store_id() to discover IDs.
        """
        super().__init__(store_id, config)
        self.session = requests.Session()
        self.session.headers.update(_HEADERS)
        self._circular_url: Optional[str] = None  # set by authenticate()

    def authenticate(self) -> None:
        """Set the Webstop store cookie by visiting the choose_store endpoint."""
        url = f"{API_HOST}/retailers/{RETAILER_ID}/stores/{self.store_id}/choose_store"
        resp = self.session.get(
            url,
            params={
                "filter": "circulars",
                "url": f"{BASE_URL}/circulars/",
            },
            timeout=15,
            allow_redirects=True,
        )
        resp.raise_for_status()

        # Store the circular base URL (e.g. .../circulars/Page/1/Base/2/260318_HM/).
        # Department pages must be fetched relative to this URL, not the generic
        # /circulars/department/{dept}/ path, which now returns empty HTML.
        self._circular_url = resp.url.rstrip("/")

        store_num = self.session.cookies.get(f"{RETAILER_ID}_store_number", "")
        logger.info(
            f"[harvest_market] Store set: id={self.store_id} number={store_num} "
            f"(redirected to {resp.url})"
        )

    def search_products(self, query: str) -> list[dict]:
        """Search for products in the current week's circular by name."""
        query_lower = query.lower()
        results = self.scrape_circular()
        return [
            r for r in results
            if query_lower in r["name"].lower()
            or query_lower in (r.get("description") or "").lower()
        ]

    def get_product_price(self, product_id: str) -> Optional[dict]:
        results = self.scrape_circular()
        for r in results:
            if r["product_id"] == product_id:
                return r
        return None

    def scrape_circular(self) -> list[dict]:
        """
        Scrape the current weekly circular by fetching all department pages.

        Returns a deduplicated list of normalized price dicts. Each item appears
        in exactly one department page, so deduplication by product_id is a
        safety measure only.

        Price formats handled:
          "$4.99 lb."  → price=4.99, unit="lb."
          "$11"        → price=11.0, unit=None
          "2/$5"       → price=5.0, unit=None, deal_text="2/$5"
          no price     → price=0.0
        """
        self.authenticate()

        seen_ids: set[str] = set()
        results: list[dict] = []
        all_raw: list[dict] = []

        for dept in DEPARTMENTS:
            dept_items, dept_raw = self._scrape_department(dept)
            all_raw.extend(dept_raw)
            for item in dept_items:
                if item["product_id"] not in seen_ids:
                    seen_ids.add(item["product_id"])
                    results.append(item)
            logger.debug(
                f"[harvest_market] {dept}: {len(dept_items)} items "
                f"({len(results)} total)"
            )

        self.save_raw(all_raw, "circular_all")
        logger.info(
            f"[harvest_market] Scraped {len(results)} items across "
            f"{len(DEPARTMENTS)} departments (store {self.store_id})."
        )
        return results

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _scrape_department(
        self, dept: str
    ) -> tuple[list[dict], list[dict]]:
        """Fetch and parse one department page. Returns (normalized, raw)."""
        if not self._circular_url:
            raise RuntimeError(
                "[harvest_market] _circular_url not set — call authenticate() first."
            )
        url = f"{self._circular_url}/department/{dept}/"
        resp = self.session.get(url, timeout=20)
        resp.raise_for_status()

        sel = Selector(resp.text)
        raw: list[dict] = []
        items: list[dict] = []

        for article in sel.css("article[id^='circular-item-']"):
            product_id = article.attrib["id"].replace("circular-item-", "")

            heading = article.css(".circular-item-heading ::text").get("").strip()
            name = article.css(".circular-item-title ::text").get("").strip()
            description = article.css(".circular-item-description ::text").get("").strip()

            if not name:
                continue

            prefix = article.css(".price-prefix ::text").get("").strip()
            dollars = article.css(".price-dollars ::text").get("").strip()
            cents = article.css(".price-cents ::text").get("").strip()   # e.g. ".99"
            suffix = article.css(".price-suffix ::text").get("").strip()

            price_str = dollars + cents  # e.g. "4.99", "11", "5"
            try:
                price = float(price_str) if price_str else 0.0
            except ValueError:
                price = 0.0

            # Multi-unit deal: prefix="2/" → "2/$5"; reconstruct deal text
            deal_text: Optional[str] = None
            if prefix:
                deal_text = f"{prefix}${price_str}" if price_str else prefix

            unit = suffix if suffix else None

            # Validity dates from the "Valid MM/DD/YYYY to MM/DD/YYYY" badge
            valid_from: Optional[str] = None
            valid_to: Optional[str] = None
            valid_text = article.css(".bg-secondary ::text").get("").strip()
            vm = _VALID_RE.search(valid_text)
            if vm:
                valid_from, valid_to = vm.group(1), vm.group(2)

            raw_item = {
                "id": product_id,
                "name": name,
                "heading": heading,
                "description": description,
                "price_dollars": dollars,
                "price_cents": cents,
                "price_prefix": prefix,
                "price_suffix": suffix,
                "valid_from": valid_from,
                "valid_to": valid_to,
                "department": dept.replace("_", " "),
            }
            raw.append(raw_item)

            items.append(
                self.normalize_price(
                    product_id=product_id,
                    name=name,
                    price=price,
                    unit=unit,
                    url=f"{BASE_URL}/circulars/",
                    extra={
                        "deal_text": deal_text,
                        "heading": heading or None,
                        "description": description or None,
                        "department": dept.replace("_", " "),
                        "valid_from": valid_from,
                        "valid_to": valid_to,
                    },
                )
            )

        return items, raw

    # ------------------------------------------------------------------
    # Store locator
    # ------------------------------------------------------------------

    @classmethod
    def find_store_id(
        cls,
        zip_code: str = "46032",
    ) -> list[dict]:
        """
        Search for Harvest Market stores near a ZIP code.
        Returns list of dicts with id, name, address, city, state, zip, distance.

        Example:
            stores = HarvestMarketScraper.find_store_id(zip_code="46032")
            for s in stores:
                print(s["id"], s["address"])
        """
        session = requests.Session()
        session.headers.update({**_HEADERS, "X-Requested-With": "XMLHttpRequest"})

        resp = session.post(
            f"{API_HOST}/retailers/{RETAILER_ID}/stores/search",
            data={
                "utf8": "✓",
                "filter": "circulars",
                "display": "results-only",
                "main_action": "set",
                "search": zip_code,
            },
            timeout=15,
        )
        resp.raise_for_status()

        sel = Selector(resp.text)
        stores = []
        for li in sel.css("li.list-group-item"):
            name = li.css("h5 ::text").get("").strip()
            addr_parts = [t.strip() for t in li.css("p.mb-1 ::text").getall() if t.strip()]
            # addr_parts typically: ["2140 E 116th Street", "Carmel, IN 46032"]
            address = addr_parts[0] if addr_parts else ""
            city_state_zip = addr_parts[1] if len(addr_parts) > 1 else ""

            choose_href = li.css("a[href*='choose_store']").attrib.get("href", "")
            store_id_match = re.search(r"/stores/(\d+)/choose_store", choose_href)
            store_id = store_id_match.group(1) if store_id_match else ""

            distance = li.css(".badge.rounded-pill ::text").get("").strip()

            stores.append(
                {
                    "id": store_id,
                    "name": name or "Harvest Market",
                    "address": address,
                    "city_state_zip": city_state_zip,
                    "distance": distance,
                }
            )
        return stores
