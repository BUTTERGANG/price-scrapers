"""Kroger scraper — official Products API v1.3.0 (developer.kroger.com).

Rate limit: 10,000 calls/day across all /products endpoint operations.
  - Each paginated page of search results = 1 call.
  - 15 queries × up to 6 pages = up to 90 calls per full run.
  - Well within limits, but track usage if running multiple times per day.

Pagination:
  filter.limit  max=50 (results per page)
  filter.start  max=250 (skip offset)
  Maximum retrievable per query: ~300 results (start=0,50,...,250 × 50 per page)
  WARNING: fuzzy search order can change between pages — deduplicate by productId.

Price fields (only returned when filter.locationId is provided):
  items[].price.regular              — in-store shelf price
  items[].price.promo                — sale/promotional price (None if no sale)
  items[].price.regularPerUnitEstimate
  items[].price.promoPerUnitEstimate
  items[].price.expirationDate       — when the promo ends
  items[].nationalPrice.regular      — national chain-wide price (may differ)

Additional location-aware fields (require filter.locationId):
  items[].inventory.stockLevel       — HIGH | LOW | TEMPORARILY_OUT_OF_STOCK
  items[].fulfillment.instore        — sold at this location (not necessarily in stock)
  items[].fulfillment.curbside
  items[].fulfillment.delivery
  aisleLocations[]                   — aisle, bay, shelf position in this store
"""
import base64
import json
import logging
import re
import time
from typing import Optional

import requests

from .base import BaseScraper

logger = logging.getLogger(__name__)

TOKEN_URL = "https://api.kroger.com/v1/connect/oauth2/token"
LOCATIONS_URL = "https://api.kroger.com/v1/locations"
PRODUCTS_URL = "https://api.kroger.com/v1/products"
BASE_SITE = "https://www.kroger.com"
DIGITALADS_BASE = "https://api.kroger.com/digitalads/v1"
DACS_BASE = "https://oms-kroger-webapp-da-classic-api-prod.przone.net"
DACS_API_KEY = "bqwwosbzrzcvffztxzyczieljzsahmkp"

_PAGE_SIZE = 50   # API maximum per page
_MAX_START = 250  # API maximum start offset
_DAILY_CALL_LIMIT = 10_000

_DACS_HEADERS = {
    "Content-Type": "application/json",
    "XApiKey": DACS_API_KEY,
}


class KrogerScraper(BaseScraper):
    retailer = "kroger"

    def __init__(self, store_id: str, config: dict):
        super().__init__(store_id, config)
        self._token: Optional[str] = None
        self._token_expires_at: float = 0
        self._calls_today: int = 0  # lightweight local counter; resets on process restart

    # ------------------------------------------------------------------ auth

    def authenticate(self) -> None:
        """Obtain or refresh the OAuth2 client-credentials token."""
        if time.time() < self._token_expires_at - 60:
            return  # token still valid with 60s buffer

        client_id = self.config["client_id"]
        client_secret = self.config["client_secret"]
        credentials = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()

        resp = requests.post(
            TOKEN_URL,
            headers={
                "Authorization": f"Basic {credentials}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            data="grant_type=client_credentials&scope=product.compact",
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        self._token = data["access_token"]
        self._token_expires_at = time.time() + data.get("expires_in", 1800)
        logger.info("Kroger token refreshed.")

    @property
    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self._token}", "Accept": "application/json"}

    def _get(self, url: str, params: dict, timeout: int = 15) -> dict:
        """Make a GET request, track call count, warn near rate limit."""
        self._calls_today += 1
        if self._calls_today >= _DAILY_CALL_LIMIT * 0.9:
            logger.warning(
                f"[kroger] Approaching daily rate limit: {self._calls_today} calls used."
            )
        resp = requests.get(url, headers=self._headers, params=params, timeout=timeout)
        resp.raise_for_status()
        return resp.json()

    def _dacs_get(self, path: str, location_id: str, timeout: int = 20) -> dict:
        url = f"{DACS_BASE}{path}"
        resp = requests.get(
            url,
            headers=_DACS_HEADERS,
            params={"location": location_id},
            timeout=timeout,
        )
        resp.raise_for_status()
        return resp.json()

    @staticmethod
    def _split_location_id(location_id: str) -> tuple[str, str]:
        if len(location_id) != 8:
            raise ValueError(f"location_id must be 8 digits, got {location_id!r}")
        return location_id[:3], location_id[3:]

    @staticmethod
    def _extract_price(pricing_text: str, pricing_html: str = "") -> tuple[float, Optional[str]]:
        """Extract price from pricingText, falling back to pricingHTML.

        Kroger's API sometimes returns empty or non-numeric pricingText (e.g.
        "See price in store") while pricingHTML contains the actual price in
        a data attribute or inner text. This method tries pricingText first,
        then falls back to parsing pricingHTML.
        """
        text = (pricing_text or "").strip()
        html = (pricing_html or "").strip()

        # Try pricingText first
        if text:
            match = re.search(r"\$([0-9]+(?:\.[0-9]{1,2})?)", text)
            if match:
                price = float(match.group(1))
                unit_match = re.search(r"\b(LB|EA|CT|PK|GAL|OZ)\b", text, re.IGNORECASE)
                return price, unit_match.group(1).upper() if unit_match else None
            if "¢" in text:
                cents_match = re.search(r"([0-9]{1,3})\s*¢", text)
                if cents_match:
                    return float(cents_match.group(1)) / 100, None

        # Fallback: parse pricingHTML
        if html:
            # Try data-price attribute first (e.g. data-price="3.99")
            data_price = re.search(r'data-price="([0-9]+(?:\.[0-9]{1,2})?)"', html, re.IGNORECASE)
            if data_price:
                price = float(data_price.group(1))
                unit_match = re.search(r"\b(LB|EA|CT|PK|GAL|OZ)\b", html, re.IGNORECASE)
                return price, unit_match.group(1).upper() if unit_match else None
            # Try dollar amount in inner text / between tags
            inner_price = re.search(r">\$([0-9]+(?:\.[0-9]{1,2})?)<", html)
            if inner_price:
                price = float(inner_price.group(1))
                unit_match = re.search(r"\b(LB|EA|CT|PK|GAL|OZ)\b", html, re.IGNORECASE)
                return price, unit_match.group(1).upper() if unit_match else None
            # Try cents in HTML
            cents_html = re.search(r">([0-9]{1,3})\s*¢<", html)
            if cents_html:
                return float(cents_html.group(1)) / 100, None

        return 0.0, None

    @staticmethod
    def _parse_store_list(stores_raw: str) -> set[str]:
        if not stores_raw:
            return set()
        try:
            parsed = json.loads(stores_raw)
        except json.JSONDecodeError:
            return set()
        locations: set[str] = set()
        for entry in parsed:
            numbers = (entry.get("locationNumbers") or "").split(",")
            for number in numbers:
                number = number.strip()
                if number:
                    locations.add(number)
        return locations

    def _fetch_weekly_ad_id(self, location_id: str) -> str:
        division, store = self._split_location_id(location_id)
        params = {
            "filter.tags": ["SHOPPABLE", "CLASSIC_VIEW"],
            "filter.div": division,
            "filter.store": store,
        }
        resp = requests.get(
            f"{DIGITALADS_BASE}/circulars",
            params=params,
            timeout=20,
        )
        if resp.status_code == 401:
            self.authenticate()
            resp = requests.get(
                f"{DIGITALADS_BASE}/circulars",
                params=params,
                headers=self._headers,
                timeout=20,
            )
        resp.raise_for_status()
        data = resp.json()
        self.save_raw(data, f"weeklyad_circulars_{location_id}")
        for circ in data.get("data", []):
            if circ.get("circularType") == "print":
                return circ["eventId"]
        raise ValueError(f"No Weekly Ad Print found for location {location_id}")

    def scrape_circular(self, location_id: Optional[str] = None) -> list[dict]:
        location_id = location_id or self.store_id
        ad_id = self._fetch_weekly_ad_id(location_id)
        pages = self._fetch_pages(ad_id, location_id)
        results: list[dict] = []
        offer_ids: dict[str, dict] = {}

        for page in pages:
            page_id = page.get("eventPageId")
            if not page_id:
                continue
            page_payload = self._fetch_page_contents(ad_id, page_id, location_id)
            if page_id == pages[0].get("eventPageId"):
                self.save_raw(page_payload, f"weeklyad_page_{location_id}_{page_id}")
            for content in page_payload.get("contents", []):
                map_config = content.get("mapConfig")
                if not map_config:
                    continue
                try:
                    map_obj = json.loads(map_config)
                except json.JSONDecodeError:
                    continue
                offer_content = map_obj.get("content") or {}
                offer_id = offer_content.get("offerVersionProductGroupId")
                if not offer_id:
                    continue
                store_list = self._parse_store_list(offer_content.get("stores", ""))
                if store_list and location_id not in store_list:
                    continue
                offer_ids[str(offer_id)] = {
                    "headline": offer_content.get("headline"),
                    "body_copy": offer_content.get("bodyCopy"),
                    "image_url": offer_content.get("imageURL"),
                    "page_id": page_id,
                }

        for idx, (offer_id, meta) in enumerate(offer_ids.items()):
            offer = self._fetch_offer(ad_id, offer_id, location_id)
            if idx < 3:
                self.save_raw(offer, f"weeklyad_offer_{location_id}_{offer_id}")
            price, unit = self._extract_price(
                offer.get("pricingText", ""),
                offer.get("pricingHTML", ""),
            )
            name = offer.get("headline") or meta.get("headline") or meta.get("body_copy") or ""
            results.append(
                self.normalize_price(
                    product_id=offer_id,
                    name=name,
                    price=price,
                    unit=unit,
                    url=offer.get("webURL"),
                    extra={
                        "deal_text": offer.get("pricingText"),
                        "pricing_html": offer.get("pricingHTML"),
                        "start_date": offer.get("startDate"),
                        "end_date": offer.get("endDate"),
                        "image_url": offer.get("imageURL") or meta.get("image_url"),
                        "body_copy": offer.get("bodyCopy") or meta.get("body_copy"),
                        "ad_id": ad_id,
                        "event_page_id": meta.get("page_id"),
                        "location_id": location_id,
                        "is_coupon": offer.get("isCoupon"),
                        "is_shoppable": offer.get("isShoppable"),
                    },
                )
            )

        self.save_raw(
            {
                "ad_id": ad_id,
                "location_id": location_id,
                "offer_count": len(results),
            },
            f"weeklyad_summary_{location_id}",
        )
        logger.info(f"[kroger] Scraped {len(results)} weekly ad offers for {location_id}.")
        return results

    # ---------------------------------------------------------- store lookup

    def _fetch_pages(self, ad_id: str, location_id: str) -> list[dict]:
        data = self._dacs_get(f"/api/dacs/{ad_id}", location_id)
        self.save_raw(data, f"weeklyad_pages_{location_id}")
        return data.get("pages") or []

    def _fetch_page_contents(self, ad_id: str, page_id: str, location_id: str) -> dict:
        return self._dacs_get(f"/api/dacs/{ad_id}/pages/{page_id}", location_id)

    def _fetch_offer(self, ad_id: str, offer_id: str, location_id: str) -> dict:
        return self._dacs_get(f"/api/dacs/{ad_id}/offers/{offer_id}", location_id)

    # ---------------------------------------------------------- store lookup

    @classmethod
    def find_stores(cls, zip_code: str, config: dict, radius_miles: int = 10) -> list[dict]:
        """Find Kroger locationIds near a ZIP code.

        Run once to confirm the store_id for config/stores.json.
        locationId must be exactly 8 characters.
        """
        scraper = cls(store_id="", config=config)
        scraper.authenticate()
        data = scraper._get(
            LOCATIONS_URL,
            params={
                "filter.zipCode.near": zip_code,
                "filter.radiusInMiles": radius_miles,
                "filter.limit": 5,
            },
        )
        scraper.save_raw(data, f"stores_{zip_code}")
        return [
            {
                "store_id": loc["locationId"],
                "name": loc.get("name", ""),
                "address": loc.get("address", {}).get("addressLine1", ""),
                "city": loc.get("address", {}).get("city", ""),
                "zip": loc.get("address", {}).get("zipCode", ""),
                "phone": loc.get("phone", {}).get("number", ""),
            }
            for loc in data.get("data", [])
        ]

    # --------------------------------------------------------- product search

    def search_products(self, query: str) -> list[dict]:
        """
        Search for products by keyword with full pagination.

        Pages through all results (up to filter.start=250) and deduplicates
        by productId, since fuzzy search order can vary between page requests.
        Returns normalized price records — prices only populated when
        filter.locationId is set (i.e. self.store_id is non-empty).
        """
        self.authenticate()
        seen_ids: set[str] = set()
        results: list[dict] = []
        start = 0

        while start <= _MAX_START:
            data = self._get(
                PRODUCTS_URL,
                params={
                    "filter.term": query,
                    "filter.locationId": self.store_id,
                    "filter.limit": _PAGE_SIZE,
                    "filter.start": start,
                    "filter.fulfillment": "ais",  # available in store
                },
            )

            if start == 0:
                self.save_raw(data, f"search_{query.replace(' ', '_')}")

            products = data.get("data", [])
            if not products:
                break  # no more results

            for item in products:
                product_id = item.get("productId", "")
                if product_id in seen_ids:
                    continue  # fuzzy search can repeat items across pages
                seen_ids.add(product_id)
                results.append(self._parse_product(item))

            # Stop if we got fewer than a full page — no more results to fetch
            if len(products) < _PAGE_SIZE:
                break

            start += _PAGE_SIZE

        logger.debug(f"[kroger] '{query}' → {len(results)} unique products across {start // _PAGE_SIZE + 1} page(s)")
        return results

    def get_product_price(self, product_id: str) -> Optional[dict]:
        """Fetch current price for a single product by its 13-digit productId."""
        self.authenticate()
        if len(product_id) != 13:
            logger.warning(f"[kroger] productId must be 13 digits, got: {product_id!r}")
        try:
            data = self._get(
                f"{PRODUCTS_URL}/{product_id}",
                params={"filter.locationId": self.store_id},
            )
        except requests.HTTPError as exc:
            if exc.response.status_code == 404:
                return None
            raise
        return self._parse_product(data.get("data", {}))

    # --------------------------------------------------------- parsing

    def _parse_product(self, item: dict) -> dict:
        """
        Map a Kroger API product object to a normalized price record.
        All field names are from the OpenAPI spec v1.3.0.
        """
        # Items array — typically one entry per product at a store
        first_item = (item.get("items") or [{}])[0]

        # Price (local store price — only present when locationId was supplied)
        price_obj = first_item.get("price") or {}
        national_price_obj = first_item.get("nationalPrice") or {}

        regular = price_obj.get("regular")          # shelf price
        promo = price_obj.get("promo")               # sale price (None = no sale)
        regular_upu = price_obj.get("regularPerUnitEstimate")
        promo_upu = price_obj.get("promoPerUnitEstimate")
        promo_expires = (price_obj.get("expirationDate") or {}).get("value")

        # Inventory & fulfillment (location-aware)
        inventory = first_item.get("inventory") or {}
        fulfillment = first_item.get("fulfillment") or {}

        # Aisle location — list of dicts with description, number, side, shelfNumber
        aisle_locs = item.get("aisleLocations") or []
        aisle = aisle_locs[0].get("description") if aisle_locs else None

        # Product page URL — use the API-provided URI, not a hardcoded pattern
        page_uri = item.get("productPageURI", "")
        url = (BASE_SITE + page_uri) if page_uri else None

        return self.normalize_price(
            product_id=item.get("productId", ""),
            name=item.get("description", ""),
            price=regular or 0.0,
            unit=first_item.get("size"),          # e.g. "1 gal"
            unit_price=regular_upu,
            url=url,
            upc=item.get("productId") or None,    # Kroger productId is a 13-digit UPC-A
            extra={
                # Sale info
                "sale_price": promo,
                "sale_unit_price": promo_upu,
                "sale_expires": promo_expires,
                # National price (chain-wide, may differ from local)
                "national_price": national_price_obj.get("regular"),
                "national_sale_price": national_price_obj.get("promo"),
                # Product attributes
                "brand": item.get("brand", ""),
                "category": (item.get("categories") or [None])[0],
                "sold_by": first_item.get("soldBy"),         # "unit" or "weight"
                "snap_eligible": item.get("snapEligible"),
                "temperature": (item.get("temperature") or {}).get("indicator"),
                # Location-aware availability
                "stock_level": inventory.get("stockLevel"),  # HIGH | LOW | TEMPORARILY_OUT_OF_STOCK
                "in_store": fulfillment.get("instore"),
                "curbside": fulfillment.get("curbside"),
                "delivery": fulfillment.get("delivery"),
                "aisle": aisle,
                # Ratings
                "rating": (item.get("ratingsAndReviews") or {}).get("averageOverallRating"),
                "review_count": (item.get("ratingsAndReviews") or {}).get("totalReviewCount"),
            },
        )
