"""Target scraper — weekly circular via api.target.com.

==============================================================================
ARCHITECTURE OVERVIEW
==============================================================================

Target runs its own proprietary weekly ad API. No Flipp, no Playwright, no
authentication required. API keys are embedded in the page's window.__CONFIG__
JS object and are stable across visits.

1. WEEKLY CIRCULAR (scrape_circular)
   ---------------------------------------------------------------------
   Three-step flow (Steps 1+2 are used; Step 3 is optional/deeper):

   Step 1 — Get active promotion for a store:
     GET https://api.target.com/weekly_ads/v1/store_promotions
         ?key=WEEKLYAD_KEY&store_id={store_id}
     Returns a list of promotions (current week + optional sneak peek).
     Promotion object fields:
       promotion_id   → "{store_id}-{YYYYMMDD}", e.g. "2391-20260315"
       code           → URL promo param, e.g. "Target-20260315"
       sale_start_date, sale_end_date
       sneak_peek     → true = future week, false = current/active

   Step 2 — Fetch all hotspot deals for the promotion:
     GET https://api.target.com/weekly_ads/v1/promotions/{promotion_id}
         ?key=WEEKLYAD_KEY
     Returns full circular (~35 pages, ~176 deal hotspots per store/week).
     Each hotspot has:
       title            → deal name (e.g. "Coffee & tea")
       price            → price string ("BOGO 50% off", "$14.99", "5/$25", "10% off")
       reg_price        → regular price string (often empty)
       tcin             → Target product ID (present for ~87% of deals)
       offer_id         → promotion ID for redsky detail lookup
       listing_id       → composite ID "{store_id}-{internal_id}" (always present)
       offer_product_count → number of eligible SKUs in the deal
       promotion_message   → e.g. "with ◎circle™" (loyalty requirement)
       circle_offer     → boolean — whether Target Circle membership is required
       multi_offer      → boolean — deal spans multiple products/categories

   Step 3 — Fetch individual SKUs for a hotspot (optional, expensive):
     GET https://redsky.target.com/redsky_aggregations/v1/weeklyad/
             get_marketing_id_search_v1
         ?marketing_id={listing_id}&promo_id={offer_id}
         &pricing_store_id={store_id}&visitor_id=scraper
         &channel=WEB&page=1&key=REDSKY_KEY
     Returns up to 24 products per page with:
       current_retail                → numeric shelf price
       formatted_current_price       → "$14.99", "2 for $5", etc.
       formatted_current_price_type  → "reg" or "sale"
     Use fetch_sku_details=True in scrape_circular() to enable.

2. PRODUCT SEARCH (search_products)
   ---------------------------------------------------------------------
   Target's product search (redsky) is available but requires pricing_store_id
   and returns shelf prices, not specifically sale prices.
   URL: GET https://redsky.target.com/redsky_aggregations/v1/web/plp_search_v2
        ?q={query}&pricing_store_id={store_id}&key=REDSKY_KEY&visitor_id=scraper
        &channel=WEB&count=24&offset=0
   Fields: tcin, item.desc.title, price.current_retail, price.formatted_current_price

==============================================================================
STORE IDs
==============================================================================

Store 2391: Indianapolis area (confirmed from promo pattern "2391-20260315").
Run TargetScraper.find_store_id() to verify exact address via store locator.

Store locator API:
  GET https://api.target.com/v3/stores/nearby?place={zip}&key=STORES_KEY
  → returns storeId, address, city, state, zip, distance

==============================================================================
PRICE STRING FORMATS
==============================================================================

Target's weekly ad price strings are human-readable and varied:
  "$14.99"            → price=14.99, unit=None
  "$3.99/lb"          → price=3.99, unit="lb"
  "5/$25"             → price=5.0 (per unit=25/5), deal_text="5/$25"
  "2 for $5"          → price=2.5, deal_text="2 for $5"
  "BOGO 50% off"      → price=0.0, deal_text="BOGO 50% off"
  "10% off"           → price=0.0, deal_text="10% off"
  "Buy 2 Get 1 Free"  → price=0.0, deal_text="Buy 2 Get 1 Free"
  "$5 off"            → price=0.0, deal_text="$5 off"

==============================================================================
INSTALL
==============================================================================

pip install requests
(No curl_cffi needed — no bot detection on these endpoints)
"""
import logging
import re
from typing import Optional

import requests

from .base import BaseScraper

logger = logging.getLogger(__name__)

# API keys extracted from window.__CONFIG__ on the weekly ad page
# (stable, embedded in page source, no auth required)
WEEKLYAD_API_KEY = "9ba599525edd204c560a2182ae1cbfaa3eeddca5"
REDSKY_API_KEY = "9f36aeafbe60771e321a7cc95a78140772ab3e96"

WEEKLYAD_BASE = "https://api.target.com/weekly_ads/v1"
REDSKY_BASE = "https://redsky.target.com/redsky_aggregations/v1"

STORE_PROMOTIONS_URL = f"{WEEKLYAD_BASE}/store_promotions"
PROMOTION_URL = f"{WEEKLYAD_BASE}/promotions/{{promotion_id}}"
REDSKY_WEEKLYAD_URL = f"{REDSKY_BASE}/weeklyad/get_marketing_id_search_v1"
REDSKY_SEARCH_URL = f"{REDSKY_BASE}/web/plp_search_v2"

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
    "Referer": "https://www.target.com/",
    "Origin": "https://www.target.com",
}

# Price string parsers
_DOLLAR_RE = re.compile(r"^\$([0-9]+(?:\.[0-9]{1,2})?)\s*/?(.*)$")
_MULTI_SLASH_RE = re.compile(r"^(\d+)/\$([0-9]+(?:\.[0-9]{1,2})?)$", re.IGNORECASE)
_MULTI_FOR_RE = re.compile(r"^(\d+)\s+for\s+\$([0-9]+(?:\.[0-9]{1,2})?)$", re.IGNORECASE)


class TargetScraper(BaseScraper):
    """Scraper for Target weekly circular via api.target.com."""

    retailer = "target"

    def __init__(self, store_id: str, config: dict):
        super().__init__(store_id, config)
        self.session = requests.Session()
        self.session.headers.update(_HEADERS)

    def authenticate(self) -> None:
        # No authentication required — API keys are public (embedded in page JS).
        pass

    def search_products(self, query: str) -> list[dict]:
        """Search Target's product catalog for a store via redsky aggregations."""
        results = []
        offset = 0
        count = 24

        while True:
            resp = self.session.get(
                REDSKY_SEARCH_URL,
                params={
                    "q": query,
                    "pricing_store_id": self.store_id,
                    "key": REDSKY_API_KEY,
                    "visitor_id": "scraper",
                    "channel": "WEB",
                    "count": count,
                    "offset": offset,
                },
                timeout=20,
            )
            resp.raise_for_status()
            data = resp.json()

            if offset == 0:
                self.save_raw(data, f"search_{query.replace(' ', '_')}")

            items = (
                data.get("data", {})
                    .get("search", {})
                    .get("products", [])
            )
            if not items:
                break

            for item in items:
                item_data = item.get("item", {})
                price_data = item.get("price", {})
                desc = item_data.get("product_description", {})
                name = desc.get("title", "") or item_data.get("desc", {}).get("title", "")
                tcin = item.get("tcin", "")
                try:
                    price = float(price_data.get("current_retail", 0))
                except (ValueError, TypeError):
                    price = 0.0

                results.append(
                    self.normalize_price(
                        product_id=str(tcin),
                        name=name,
                        price=price,
                        url=f"https://www.target.com/p/-/A-{tcin}",
                        extra={
                            "formatted_price": price_data.get("formatted_current_price"),
                            "price_type": price_data.get("formatted_current_price_type"),
                            "brand": item_data.get("primary_brand", {}).get("name"),
                        },
                    )
                )

            total = (
                data.get("data", {})
                    .get("search", {})
                    .get("total_results", 0)
            )
            offset += count
            if offset >= total or len(items) < count:
                break

        return results

    def get_product_price(self, product_id: str) -> Optional[dict]:
        results = self.search_products(product_id)
        for r in results:
            if r["product_id"] == product_id:
                return r
        return results[0] if results else None

    def scrape_circular(
        self,
        promo_code: Optional[str] = None,
        fetch_sku_details: bool = False,
    ) -> list[dict]:
        """
        Scrape the current weekly ad for this store.

        Args:
            promo_code: Specific promo code to use (e.g. "Target-20260315").
                        If None, uses the most recent non-sneak-peek promotion.
            fetch_sku_details: If True, calls the redsky endpoint for each
                               hotspot to get individual SKU prices. Much slower
                               (~1 API call per deal) but returns per-item prices
                               instead of deal-level summaries. Default False.

        Returns list of normalized price dicts. Deal-only items (BOGO, % off)
        have price=0.0 with deal_text set in extra fields.
        """
        promotion_id = self._resolve_promotion_id(promo_code)
        hotspots = self._fetch_promotion_hotspots(promotion_id)

        results = []
        for hs in hotspots:
            if fetch_sku_details and hs.get("listing_id") and hs.get("offer_id"):
                skus = self._fetch_sku_details(hs["listing_id"], hs["offer_id"])
                results.extend(skus)
            else:
                record = self._parse_hotspot(hs)
                if record:
                    results.append(record)

        logger.info(
            f"[target] Scraped {len(results)} items from weekly ad "
            f"(promotion {promotion_id}, store {self.store_id})."
        )
        return results

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _resolve_promotion_id(self, promo_code: Optional[str]) -> str:
        """
        Get the promotion_id for the current week's circular.
        If promo_code is provided, finds the matching promotion.
        Otherwise returns the most recent active (non-sneak-peek) promotion.
        """
        resp = self.session.get(
            STORE_PROMOTIONS_URL,
            params={"key": WEEKLYAD_API_KEY, "store_id": self.store_id},
            timeout=15,
        )
        resp.raise_for_status()
        promotions = resp.json()

        self.save_raw(promotions, "store_promotions")

        if not promotions:
            raise RuntimeError(f"[target] No promotions found for store {self.store_id}.")

        # Match by promo code if provided
        if promo_code:
            for promo in promotions:
                if promo.get("code") == promo_code:
                    return promo["promotion_id"]
            logger.warning(
                f"[target] Promo code '{promo_code}' not found — using latest active promotion."
            )

        # Use the most recent non-sneak-peek promotion
        active = [p for p in promotions if not p.get("sneak_peek")]
        if not active:
            active = promotions  # fallback: use any if all are sneak peeks

        # Sort by sale_start_date descending and pick the latest
        active.sort(key=lambda p: p.get("sale_start_date", ""), reverse=True)
        promo = active[0]
        logger.info(
            f"[target] Using promotion '{promo['promotion_id']}' "
            f"({promo.get('sale_start_date')} – {promo.get('sale_end_date')})."
        )
        return promo["promotion_id"]

    def _fetch_promotion_hotspots(self, promotion_id: str) -> list[dict]:
        """Fetch all deal hotspots for a promotion."""
        resp = self.session.get(
            PROMOTION_URL.format(promotion_id=promotion_id),
            params={"key": WEEKLYAD_API_KEY},
            timeout=20,
        )
        resp.raise_for_status()
        data = resp.json()
        self.save_raw(data, f"promotion_{promotion_id}")

        # Hotspots may be nested: data.pages[].hotspots[] or data.hotspots[]
        hotspots = []
        if "hotspots" in data:
            hotspots = data["hotspots"]
        elif "pages" in data:
            for page in data.get("pages", []):
                hotspots.extend(page.get("hotspots", []))

        logger.debug(f"[target] {len(hotspots)} hotspots in promotion {promotion_id}.")
        return hotspots

    def _parse_hotspot(self, hs: dict) -> Optional[dict]:
        """Convert a hotspot dict into a normalized price record."""
        title = (hs.get("title") or "").strip()
        if not title:
            return None

        price_raw = (hs.get("price") or "").strip()
        reg_price_raw = (hs.get("reg_price") or "").strip()
        price, unit, deal_text = _parse_price(price_raw)

        tcin = str(hs.get("tcin") or "")
        listing_id = str(hs.get("listing_id") or "")
        product_id = tcin or listing_id or title.lower().replace(" ", "_")

        return self.normalize_price(
            product_id=product_id,
            name=title,
            price=price,
            unit=unit,
            url=f"https://www.target.com/p/-/A-{tcin}" if tcin else "https://www.target.com/weekly-ad",
            extra={
                "deal_text": deal_text or (price_raw if not price else None),
                "reg_price": reg_price_raw or None,
                "tcin": tcin or None,
                "offer_id": hs.get("offer_id"),
                "listing_id": listing_id or None,
                "circle_offer": hs.get("circle_offer", False),
                "promotion_message": (hs.get("promotion_message") or "").strip() or None,
                "offer_product_count": hs.get("offer_product_count"),
            },
        )

    def _fetch_sku_details(self, listing_id: str, offer_id: str) -> list[dict]:
        """
        Fetch individual SKU prices for a hotspot via the redsky aggregations endpoint.
        Returns a list of normalized price records (one per SKU, paginated 24/page).
        """
        results = []
        page = 1

        while True:
            resp = self.session.get(
                REDSKY_WEEKLYAD_URL,
                params={
                    "marketing_id": listing_id,
                    "promo_id": offer_id,
                    "pricing_store_id": self.store_id,
                    "visitor_id": "scraper",
                    "channel": "WEB",
                    "page": page,
                    "key": REDSKY_API_KEY,
                },
                timeout=20,
            )
            resp.raise_for_status()
            data = resp.json()

            products = (
                data.get("data", {})
                    .get("weekly_ad_product_search", {})
                    .get("products", [])
            )
            if not products:
                break

            for item in products:
                item_data = item.get("item", {})
                price_data = item.get("price", {})
                name = (
                    item_data.get("product_description", {}).get("title")
                    or item_data.get("desc", {}).get("title", "")
                )
                tcin = item.get("tcin", "")
                try:
                    price = float(price_data.get("current_retail", 0))
                except (ValueError, TypeError):
                    price = 0.0

                results.append(
                    self.normalize_price(
                        product_id=str(tcin),
                        name=name,
                        price=price,
                        url=f"https://www.target.com/p/-/A-{tcin}",
                        extra={
                            "formatted_price": price_data.get("formatted_current_price"),
                            "price_type": price_data.get("formatted_current_price_type"),
                            "listing_id": listing_id,
                            "offer_id": offer_id,
                        },
                    )
                )

            total = (
                data.get("data", {})
                    .get("weekly_ad_product_search", {})
                    .get("total_results", 0)
            )
            if len(results) >= total or len(products) < 24:
                break
            page += 1

        return results

    @classmethod
    def find_store_id(
        cls,
        zip_code: str = "46220",
        config: dict = None,
    ) -> list[dict]:
        """
        Query the Target store locator for stores near a ZIP code.
        Returns a list of stores with storeId, address, city, state.

        Example:
            stores = TargetScraper.find_store_id(zip_code="46220")
            for s in stores:
                print(s["storeId"], s["address"])
        """
        session = requests.Session()
        session.headers.update(_HEADERS)
        resp = session.get(
            "https://api.target.com/v3/stores/nearby",
            params={"place": zip_code, "key": WEEKLYAD_API_KEY},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        stores = []
        for s in data.get("locations", []):
            stores.append(
                {
                    "storeId": s.get("location_id") or s.get("store_id", ""),
                    "name": s.get("location_name", "Target"),
                    "address": s.get("address", {}).get("address_line1", ""),
                    "city": s.get("address", {}).get("city", ""),
                    "state": s.get("address", {}).get("state", ""),
                    "zip": s.get("address", {}).get("postal_code", ""),
                    "distance": s.get("distance_in_miles", ""),
                }
            )
        return stores


# ------------------------------------------------------------------
# Price parsing helpers
# ------------------------------------------------------------------

def _parse_price(price_raw: str) -> tuple[float, Optional[str], Optional[str]]:
    """
    Parse a Target weekly ad price string.

    Returns (price, unit, deal_text):
      - price: float (0.0 for deal/percent-off items)
      - unit: str or None (e.g. "lb")
      - deal_text: str or None (raw string if non-numeric deal)
    """
    if not price_raw:
        return 0.0, None, None

    # "$14.99" or "$3.99/lb" or "$3.99 lb"
    m = _DOLLAR_RE.match(price_raw)
    if m:
        price = float(m.group(1))
        unit_part = m.group(2).strip().lstrip("/").strip() or None
        return price, unit_part, None

    # "5/$25" → 5.00 per unit (25/5)
    m = _MULTI_SLASH_RE.match(price_raw)
    if m:
        count = int(m.group(1))
        total = float(m.group(2))
        return round(total / count, 4), None, price_raw

    # "2 for $5" → 2.50 per unit
    m = _MULTI_FOR_RE.match(price_raw)
    if m:
        count = int(m.group(1))
        total = float(m.group(2))
        return round(total / count, 4), None, price_raw

    # BOGO, % off, dollar-off, or any other deal text
    return 0.0, None, price_raw
