"""Walmart scraper — parses __NEXT_DATA__ JSON embedded in product/search pages.

Uses curl_cffi to impersonate a real Chrome TLS handshake (JA3/JA4 fingerprint).
Plain requests/urllib are blocked by Walmart's Akamai + PerimeterX stack
immediately because their TLS fingerprint doesn't match any real browser.

Install: pip install curl-cffi parsel
"""
import json
import logging
from typing import Optional

from parsel import Selector

from .base import BaseScraper
from utils.http import make_curl_session, request_with_retry

logger = logging.getLogger(__name__)

SEARCH_URL = "https://www.walmart.com/search"


class WalmartScraper(BaseScraper):
    retailer = "walmart"

    def __init__(self, store_id: str, config: dict):
        super().__init__(store_id, config)
        self.session = make_curl_session(proxy=config.get("proxy"))
        self.session.headers.update(
            {
                "Accept": (
                    "text/html,application/xhtml+xml,application/xml;"
                    "q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8"
                ),
                "Referer": "https://www.walmart.com/",
            }
        )

    def authenticate(self) -> None:
        # Warm up the session by hitting the homepage first —
        # this sets anti-bot cookies (bm_sz, _abck) that Akamai
        # checks on subsequent requests.
        resp = request_with_retry(self.session, "GET", "https://www.walmart.com/", timeout=20)
        logger.info(f"Walmart session warmed up. Cookies: {list(self.session.cookies.keys())}")
        # Set store-specific pricing cookie
        self.session.cookies.set("assortment_store_id", self.store_id, domain=".walmart.com")

    def search_products(self, query: str) -> list[dict]:
        resp = request_with_retry(
            self.session,
            "GET",
            SEARCH_URL,
            params={"q": query, "store": self.store_id},
            timeout=25,
        )
        resp.raise_for_status()

        sel = Selector(resp.text)
        raw_json = sel.xpath('//script[@id="__NEXT_DATA__"]/text()').get()
        if not raw_json:
            logger.warning(f"[walmart] No __NEXT_DATA__ for '{query}' — page may have changed or bot was detected")
            return []

        data = json.loads(raw_json)
        self.save_raw(data, f"search_{query.replace(' ', '_')}")

        # Walmart nests results under itemStacks; first stack is usually
        # the main results, subsequent stacks are sponsored/related.
        item_stacks = (
            data.get("props", {})
            .get("pageProps", {})
            .get("initialData", {})
            .get("searchResult", {})
            .get("itemStacks", [])
        )
        items = []
        for stack in item_stacks:
            # Skip sponsored stacks
            if stack.get("stackType") in ("SPONSORED", "RELATED"):
                continue
            items.extend(stack.get("items", []))

        results = []
        for item in items:
            price_info = item.get("priceInfo") or {}
            # Price moved to top-level float in 2025/2026; priceInfo.currentPrice
            # is now often None. Fall back through linePrice string.
            raw_price = item.get("price") or price_info.get("currentPrice", {}) or 0.0
            if isinstance(raw_price, dict):
                raw_price = raw_price.get("price", 0.0)
            try:
                price = float(raw_price) if raw_price else 0.0
            except (ValueError, TypeError):
                price = 0.0
            if not price:
                line = str(price_info.get("linePrice") or "").lstrip("$")
                try:
                    price = float(line) if line else 0.0
                except ValueError:
                    price = 0.0

            # unitPrice is now a formatted display string e.g. "5.4 ¢/fl oz"
            unit_price_str = price_info.get("unitPrice") or ""

            # wasPrice is the original/regular price before the sale (e.g. "$22.99").
            # If set, the item is on sale: current price → sale_price, was_price → price.
            was_price_str = price_info.get("wasPrice") or ""
            try:
                was_price = float(str(was_price_str).lstrip("$").replace(",", "")) if was_price_str else None
            except ValueError:
                was_price = None

            # Correct semantics: price = regular shelf price, sale_price = current sale price
            if was_price:
                regular_price, sale_price = was_price, price
            else:
                regular_price, sale_price = price, None

            # Rating dict moved to top-level
            rating_obj = item.get("rating") or {}

            results.append(
                self.normalize_price(
                    product_id=item.get("usItemId", ""),
                    name=item.get("name", ""),
                    price=regular_price,
                    unit=unit_price_str or None,   # formatted unit string ("5.4 ¢/fl oz")
                    url=f"https://www.walmart.com{item.get('canonicalUrl', '')}",
                    extra={
                        "sale_price": sale_price,
                        "brand": item.get("brand") or None,
                        "category": item.get("catalogProductType") or None,
                        "aisle": item.get("productLocationDisplayValue") or None,
                        "snap_eligible": bool(item.get("snapWicBadgeText")),
                        "in_stock": item.get("availabilityStatusDisplayValue") == "In stock",
                        "average_rating": rating_obj.get("averageRating"),
                        "num_reviews": rating_obj.get("numberOfReviews"),
                    },
                )
            )
        return results

    def get_product_price(self, product_id: str) -> Optional[dict]:
        resp = request_with_retry(
            self.session,
            "GET",
            f"https://www.walmart.com/ip/{product_id}",
            timeout=25,
        )
        resp.raise_for_status()

        sel = Selector(resp.text)
        raw_json = sel.xpath('//script[@id="__NEXT_DATA__"]/text()').get()
        if not raw_json:
            return None

        data = json.loads(raw_json)
        product = (
            data.get("props", {})
            .get("pageProps", {})
            .get("initialData", {})
            .get("data", {})
            .get("product", {})
        )
        price_info = product.get("priceInfo", {})
        was = price_info.get("wasPrice", {})
        return self.normalize_price(
            product_id=product_id,
            name=product.get("name", ""),
            price=price_info.get("currentPrice", {}).get("price", 0.0),
            extra={"sale_price": was.get("price") if was else None},
        )
