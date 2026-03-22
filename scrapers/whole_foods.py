"""Whole Foods Market scraper — sales flyer via __NEXT_DATA__ JSON.

==============================================================================
ARCHITECTURE OVERVIEW
==============================================================================

Whole Foods is an Amazon-owned, custom Next.js application. The weekly sales
flyer is server-side rendered (SSP) — all promotion data is embedded directly
in the __NEXT_DATA__ JSON blob on the page. No JavaScript execution, no
browser automation, and no third-party circular system (Flipp, etc.) is used.
Amazon uses its own promotions infrastructure (UFG — Unified Fresh Grocery).

1. SALES FLYER (scrape_circular)
   ---------------------------------------------------------------------
   Single-request flow:

   GET https://www.wholefoodsmarket.com/sales-flyer?store-id={store_id}
     → parse <script id="__NEXT_DATA__"> JSON
     → navigate to props.pageProps.promotions (list of ~59 items)

   curl_cffi with Chrome impersonation is used for safety (Amazon CDN via
   Varnish; plain requests works today but Amazon infra may enforce TLS
   fingerprinting in the future).

   Promotion object fields:
     promotionId      → UUID (store-specific; same product has different UUID per store)
     productName      → product name + size, e.g. "Strawberries, 16 oz"
     originBrandName  → brand/origin label, e.g. "Organic", "365 by WFM"
     packageSize      → size string (often empty; size is usually in productName)
     regularPrice     → regular shelf price string, e.g. "$4.99" or "$3.49/lb"
     salePrice        → sale price string or deal text (see formats below) or ""
     primePrice       → Amazon Prime exclusive price/deal, or ""
     itemType         → "NSF" = standard sale item
                        "PMD" = Prime-exclusive deal (BOGO, larger discount)
     tier             → display tier: "SUPER_HERO", "SUB_HERO", "STANDARD_TILE"
     rank             → integer sort order (lower = more prominent)
     startDate        → ISO timestamp, e.g. "2026-03-18T07:00:00Z"
     endDate          → ISO timestamp, e.g. "2026-03-24T06:59:59Z"
     asinsList        → list of Amazon ASINs, e.g. ["B07NRSXJH6"]
     productImage     → https://m.media-amazon.com/images/I/... (product photo)
     description      → fine-print / promo terms (sometimes empty)
     headline         → marketing headline (sometimes empty)

   Price string formats:
     "$4.99"           → regular price 4.99, no unit
     "$3.49/lb"        → price 3.49, unit "lb"
     "$4.99 ea"        → price 4.99, unit "ea"
     "22% off"         → deal text (percentage discount, no absolute price)
     "30% off"         → deal text
     "Buy 1, Get 1 Free" → deal text (BOGO)
     ""                → empty — no separate sale price (use regularPrice)

   Pricing model:
     - `price` in normalized record = parsed regularPrice (shelf price)
     - `sale_price` in extra = parsed salePrice if it's a dollar amount
     - `prime_price` in extra = parsed primePrice if it's a dollar amount
     - `deal_text` in extra = salePrice string when it's a % or BOGO deal
     - `prime_deal_text` in extra = primePrice string when it's a % or BOGO deal
     - PMD items (Prime-exclusive): best price is in primePrice, not salePrice

   Note: Prices are **national** — identical across all WFM stores for a given
   week. The store_id parameter selects your store for display purposes, but the
   promotion dataset is the same regardless of which Indiana store ID you use.

2. PRODUCT SEARCH (search_products)
   ---------------------------------------------------------------------
   WFM's product detail API (/api/wwos/pdp?asin={ASIN}) returns product info
   but no pricing without Amazon auth. The sales flyer is the primary data
   source. search_products() scans the current week's flyer by name.

   For pricing on non-sale items, the Amazon Fresh / WFM ordering system
   requires authentication — those prices are not publicly available.

==============================================================================
STORE IDs
==============================================================================

Store IDs are 5-digit sequential Amazon internal identifiers. The store-id
param is required — the page returns a generic national flyer without it.

Known Indianapolis-area stores:
  10378 — "Eighty-Sixth St." Indianapolis (confirmed from __NEXT_DATA__ storeName)

The /api/wwos/location/store/closest endpoint requires Amazon auth (returns
403 unauthenticated). To find a store ID:
  1. Go to wholefoodsmarket.com/stores/list and navigate to your store
  2. The store page URL contains the store number (e.g. /stores/indineastside)
  3. Or inspect the sales-flyer page source — storeId is in __NEXT_DATA__

==============================================================================
INSTALL
==============================================================================

pip install curl-cffi
"""
import json
import logging
import re
from typing import Optional

from .base import BaseScraper
from utils.http import make_curl_session

logger = logging.getLogger(__name__)

SALES_FLYER_URL = "https://www.wholefoodsmarket.com/sales-flyer"

_NEXT_DATA_RE = re.compile(
    r'<script\s+id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.DOTALL
)

# Price string parsers
# "$4.99", "$3.49/lb", "$4.99 ea", "$4.99/lb"
_DOLLAR_RE = re.compile(r"^\$([0-9]+(?:\.[0-9]{1,2})?)\s*(?:/|\s)?\s*(.*)$")


class WholeFoodsScraper(BaseScraper):
    """Scraper for Whole Foods Market weekly sales flyer."""

    retailer = "whole_foods"

    def __init__(self, store_id: str, config: dict):
        """
        Args:
            store_id: 5-digit WFM store ID, e.g. "10378" for Eighty-Sixth St., Indianapolis.
        """
        super().__init__(store_id, config)
        self.session = make_curl_session(proxy=config.get("proxy"))
        self.session.headers.update(
            {
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Referer": "https://www.wholefoodsmarket.com/",
            }
        )

    def authenticate(self) -> None:
        # No authentication required — flyer data is publicly accessible.
        pass

    def search_products(self, query: str) -> list[dict]:
        """Search current week's sales flyer by product name."""
        query_lower = query.lower()
        results = self.scrape_circular()
        return [
            r for r in results
            if query_lower in r["name"].lower()
            or query_lower in (r.get("brand") or "").lower()
        ]

    def get_product_price(self, product_id: str) -> Optional[dict]:
        """Look up a promotion by promotionId or ASIN in the current flyer."""
        results = self.scrape_circular()
        for r in results:
            if r["product_id"] == product_id:
                return r
            if product_id in (r.get("asins") or []):
                return r
        return None

    def scrape_circular(self) -> list[dict]:
        """
        Scrape all promotions from the current weekly sales flyer.

        Fetches the sales flyer page, parses __NEXT_DATA__, and returns a
        normalized price record for each promotion. Both standard sale items
        (NSF) and Prime-exclusive deals (PMD) are included.

        Returns list of normalized price dicts. Items with only percentage or
        BOGO deals (no absolute dollar price in salePrice) will have
        price = regularPrice and deal_text set in extra fields.
        """
        resp = self.session.get(
            SALES_FLYER_URL,
            params={"store-id": self.store_id},
            timeout=30,
        )
        resp.raise_for_status()

        m = _NEXT_DATA_RE.search(resp.text)
        if not m:
            raise RuntimeError(
                "[whole_foods] __NEXT_DATA__ not found in sales flyer page."
            )

        data = json.loads(m.group(1))
        page_props = data.get("props", {}).get("pageProps", {})
        promotions = page_props.get("promotions", [])

        self.save_raw(
            {
                "store_id": self.store_id,
                "store_name": page_props.get("storeName", ""),
                "promotions": promotions,
            },
            f"circular_store{self.store_id}",
        )

        results = []
        for promo in promotions:
            record = self._parse_promotion(promo)
            if record:
                results.append(record)

        logger.info(
            f"[whole_foods] Scraped {len(results)} promotions for store "
            f"{self.store_id} ({page_props.get('storeName', '')})."
        )
        return results

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _parse_promotion(self, promo: dict) -> Optional[dict]:
        """Convert a WFM promotion dict into a normalized price record."""
        name = (promo.get("productName") or "").strip()
        if not name:
            return None

        regular_raw = (promo.get("regularPrice") or "").strip()
        sale_raw = (promo.get("salePrice") or "").strip()
        prime_raw = (promo.get("primePrice") or "").strip()

        # Parse regularPrice as the base price
        reg_price, reg_unit = _parse_dollar_string(regular_raw)

        # Parse salePrice — may be a dollar amount or a deal string
        sale_price, _ = _parse_dollar_string(sale_raw)
        deal_text = sale_raw if sale_raw and sale_price is None else None

        # Parse primePrice
        prime_price, _ = _parse_dollar_string(prime_raw)
        prime_deal_text = prime_raw if prime_raw and prime_price is None else None

        # Use the best available numeric price as the record's primary price
        price = reg_price if reg_price is not None else 0.0

        asins = promo.get("asinsList") or []
        product_id = promo.get("promotionId", "")

        return self.normalize_price(
            product_id=product_id,
            name=name,
            price=price,
            unit=reg_unit,
            url=SALES_FLYER_URL + f"?store-id={self.store_id}",
            extra={
                "brand": (promo.get("originBrandName") or "").strip() or None,
                "package_size": (promo.get("packageSize") or "").strip() or None,
                "regular_price_text": regular_raw or None,
                "sale_price": sale_price,
                "sale_price_text": sale_raw or None,
                "deal_text": deal_text,
                "prime_price": prime_price,
                "prime_price_text": prime_raw or None,
                "prime_deal_text": prime_deal_text,
                "item_type": promo.get("itemType"),   # "NSF" or "PMD"
                "tier": promo.get("tier"),
                "asins": asins or None,
                "valid_from": promo.get("startDate"),
                "valid_to": promo.get("endDate"),
                "description": (promo.get("description") or "").strip() or None,
            },
        )


# ------------------------------------------------------------------
# Price parsing helpers
# ------------------------------------------------------------------

def _parse_dollar_string(text: str) -> tuple[Optional[float], Optional[str]]:
    """
    Parse a WFM price string like "$4.99", "$3.49/lb", "$4.99 ea".

    Returns (price, unit) or (None, None) if the string is not a dollar amount
    (e.g. "22% off", "Buy 1 Get 1 Free", "").
    """
    if not text or not text.startswith("$"):
        return None, None

    m = _DOLLAR_RE.match(text)
    if not m:
        return None, None

    try:
        price = float(m.group(1))
    except ValueError:
        return None, None

    unit = m.group(2).strip() or None
    return price, unit
