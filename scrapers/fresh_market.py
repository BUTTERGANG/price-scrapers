"""The Fresh Market scraper — weekly features via __NEXT_DATA__ JSON.

==============================================================================
ARCHITECTURE OVERVIEW
==============================================================================

The Fresh Market uses Next.js with Static Site Generation (SSG/ISR) backed by
Contentful CMS. All weekly deal data is **fully embedded in __NEXT_DATA__** on
the weekly features page — no XHR calls are made after page load, and the
client-side store dropdown just filters the pre-loaded data.

1. WEEKLY FEATURES (scrape_circular)
   - URL: https://www.thefreshmarket.com/features/weekly-features
   - Fetch with curl_cffi (Chrome impersonation) — plain requests works too,
     but curl_cffi is safer in case Cloudflare/Akamai is added later.
   - Extract: <script id="__NEXT_DATA__"> JSON blob
   - Navigate: props.pageProps.weeklySpecialsContent
     → dict of boards keyed by board name, e.g. "weekly-specials-board-national"
     Each board has:
       applicableStoresCollection.items  → list of {storeNumber, ...}
       specialItemsCollection.items      → list of SpecialItemEntity dicts

   Deal item (SpecialItemEntity) fields:
     specialItemName           → product name (e.g. "Asparagus")
     specialMarketingPrice     → price string (e.g. "$3.99 lb", "Buy 1, Get 1 50% Off", "3/$5")
     specialMarketingSavings   → savings callout (e.g. "Save at least $1.00 lb") or null
     overwriteImageUrl         → product image URL (Widen CDN) or null
     product.sku               → SKU/UPC string
     product.description       → size/variety text (e.g. "6 OZ, MUST BUY 2 TO RECEIVE DISCOUNT")
     product.department        → department name (Produce, Seafood, Dairy, Deli, Bakery, Grocery…)
     product.price             → always null in specials context (use specialMarketingPrice)

   Price parsing:
     "$3.99 lb"               → price=3.99, unit="lb"
     "$3.99"                  → price=3.99, unit=None
     "3/$5"                   → price=5/3≈1.67, unit=None, deal_text="3/$5"
     "Buy 1, Get 1 50% Off"   → price=0.0, deal_text=raw string
     "$X off" / "BOGO"        → price=0.0, deal_text=raw string

2. PRODUCT SEARCH (search_products)
   - Not implemented: The Fresh Market does not have a public search API.
   - The weekly features page is the primary source of current deals.
   - scrape_circular() is the main entry point.

==============================================================================
STORE IDs — INDIANA LOCATIONS
==============================================================================

All Indiana stores are assigned to "weekly-specials-board-national" and receive
the same national deal set each week.

| Store # | Address                    | City         | ZIP   | Notes            |
|---------|----------------------------|--------------|-------|------------------|
| 56      | 2490 E 146th St            | Carmel       | 46033 | "146th" location |
| 247     | 1392 S Rangeline Rd        | Carmel       | 46032 | newStore=true    |
| 92      | 5415 N College Ave         | Indianapolis | 46220 | Broad Ripple     |
| 64      | 6306 W Jefferson Blvd      | Fort Wayne   | 46804 |                  |
| 130     | 6401 E Lloyd Expy          | Evansville   | 47715 |                  |

Store numbers confirmed from __NEXT_DATA__ on 2026-03-20.

==============================================================================
INSTALL
==============================================================================

pip install curl-cffi
(requests and json are stdlib)
"""
import json
import logging
import re
from typing import Optional

from .base import BaseScraper
from utils.http import make_curl_session

logger = logging.getLogger(__name__)

WEEKLY_FEATURES_URL = "https://www.thefreshmarket.com/features/weekly-features"

# Default store IDs for the two user-requested Indiana locations.
# Pass store_id to __init__ to override.
STORE_146TH = "56"    # 2490 E 146th St, Carmel IN 46033
STORE_RANGELINE = "247"  # 1392 S Rangeline Rd, Carmel IN 46032
STORE_BROAD_RIPPLE = "92"  # 5415 N College Ave, Indianapolis IN 46220

_NEXT_DATA_RE = re.compile(
    r'<script\s+id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.DOTALL
)

# Matches "$3.99 lb", "$3.99/lb", "$3.99"
_DOLLAR_PRICE_RE = re.compile(r"^\$([0-9]+(?:\.[0-9]{1,2})?)\s*/?(.*)$")

# Matches "3/$5", "2/$6", "4/$10"
_MULTI_PRICE_RE = re.compile(r"^(\d+)/\$([0-9]+(?:\.[0-9]{1,2})?)$")


class FreshMarketScraper(BaseScraper):
    """Scraper for The Fresh Market weekly features page."""

    retailer = "fresh_market"

    def __init__(self, store_id: str, config: dict):
        super().__init__(store_id, config)
        self.session = make_curl_session(proxy=config.get("proxy"))
        self.session.headers.update(
            {
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Referer": "https://www.thefreshmarket.com/",
            }
        )

    def authenticate(self) -> None:
        # No authentication needed — page is publicly accessible.
        pass

    def search_products(self, query: str) -> list[dict]:
        # The Fresh Market has no public product search API.
        # Weekly deals are the primary data source — use scrape_circular().
        logger.warning(
            "[fresh_market] search_products() not available — use scrape_circular() instead."
        )
        return []

    def get_product_price(self, product_id: str) -> Optional[dict]:
        # Without a search API, look up by SKU in the current week's circular.
        items = self.scrape_circular()
        for item in items:
            if item.get("product_id") == product_id:
                return item
        return None

    def scrape_circular(self) -> list[dict]:
        """
        Scrape weekly deal items from __NEXT_DATA__ on the weekly features page.

        Finds the board that applies to self.store_id and returns its deals.
        All Indiana stores currently share the national board (~27 items/week).

        Returns a list of normalized price dicts. Deal-only items (BOGO, etc.)
        have price=0.0 with deal_text set in the extra fields.
        """
        raw = self._fetch_next_data()
        self.save_raw(
            {"source_url": WEEKLY_FEATURES_URL, "store_id": self.store_id},
            "circular_meta",
        )

        boards = raw.get("props", {}).get("pageProps", {}).get("weeklySpecialsContent", {})
        if not boards:
            raise RuntimeError("[fresh_market] weeklySpecialsContent not found in __NEXT_DATA__.")

        deals = self._find_deals_for_store(boards)
        if deals is None:
            # Store not found in any board — fall back to national board
            logger.warning(
                f"[fresh_market] Store {self.store_id} not found in any board. "
                "Falling back to national board."
            )
            for board_name, board in boards.items():
                if "national" in board_name:
                    deals = board.get("specialItemsCollection", {}).get("items", [])
                    break

        if not deals:
            raise RuntimeError(
                f"[fresh_market] No deals found for store {self.store_id}."
            )

        self.save_raw(deals, f"circular_store{self.store_id}")
        results = [self._parse_deal(item) for item in deals if item]
        results = [r for r in results if r is not None]
        logger.info(
            f"[fresh_market] Scraped {len(results)} deals for store {self.store_id}."
        )
        return results

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _fetch_next_data(self) -> dict:
        """Fetch the weekly features page and extract the __NEXT_DATA__ JSON."""
        resp = self.session.get(WEEKLY_FEATURES_URL, timeout=30)
        resp.raise_for_status()

        m = _NEXT_DATA_RE.search(resp.text)
        if not m:
            raise RuntimeError("[fresh_market] __NEXT_DATA__ not found in page HTML.")
        return json.loads(m.group(1))

    def _find_deals_for_store(self, boards: dict) -> Optional[list[dict]]:
        """
        Return the specialItemsCollection.items list for the board that contains
        self.store_id, or None if no matching board is found.
        """
        target = int(self.store_id) if self.store_id.isdigit() else None
        for board_name, board in boards.items():
            stores = board.get("applicableStoresCollection", {}).get("items", [])
            store_numbers = [
                s.get("storeNumber") for s in stores if s.get("storeNumber") is not None
            ]
            if target in store_numbers or self.store_id in store_numbers:
                logger.debug(
                    f"[fresh_market] Store {self.store_id} matched board '{board_name}'."
                )
                return board.get("specialItemsCollection", {}).get("items", [])
        return None

    def _parse_deal(self, item: dict) -> Optional[dict]:
        """
        Convert a SpecialItemEntity dict into a normalized price record.

        Price parsing rules:
          "$3.99 lb"  → price=3.99, unit="lb"
          "$3.99"     → price=3.99, unit=None
          "3/$5"      → price=5/3, unit=None, deal_text="3/$5"
          anything else → price=0.0, deal_text=raw string
        """
        name = (item.get("specialItemName") or "").strip()
        if not name:
            return None

        product = item.get("product") or {}
        sku = (product.get("sku") or "").strip()
        description = (product.get("description") or "").strip() or None
        department = (product.get("department") or "").strip() or None

        price_raw = (item.get("specialMarketingPrice") or "").strip()
        savings = (item.get("specialMarketingSavings") or "").strip() or None

        price, unit, deal_text = _parse_price(price_raw)

        return self.normalize_price(
            product_id=sku or name.lower().replace(" ", "_"),
            name=name,
            price=price,
            unit=unit,
            url=WEEKLY_FEATURES_URL,
            extra={
                "deal_text": deal_text,
                "savings_text": savings,
                "description": description,
                "department": department,
                "image_url": item.get("overwriteImageUrl"),
            },
        )


# ------------------------------------------------------------------
# Price parsing helpers
# ------------------------------------------------------------------

def _parse_price(price_raw: str) -> tuple[float, Optional[str], Optional[str]]:
    """
    Parse The Fresh Market's specialMarketingPrice field.

    Returns (price, unit, deal_text):
      - price: float (0.0 for deal-only items)
      - unit: str or None (e.g. "lb", "ea")
      - deal_text: str or None (raw price string if it can't be parsed as a number)
    """
    if not price_raw:
        return 0.0, None, None

    # "$3.99 lb" or "$3.99/lb" or "$3.99"
    m = _DOLLAR_PRICE_RE.match(price_raw)
    if m:
        price = float(m.group(1))
        unit_part = m.group(2).strip().lstrip("/").strip() or None
        return price, unit_part, None

    # "3/$5"
    m = _MULTI_PRICE_RE.match(price_raw)
    if m:
        count = int(m.group(1))
        total = float(m.group(2))
        price = round(total / count, 4)
        return price, None, price_raw

    # Deal-only: "Buy 1, Get 1 50% Off", "BOGO", "$1 off", etc.
    return 0.0, None, price_raw
