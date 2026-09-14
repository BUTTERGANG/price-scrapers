"""Walmart scraper — real-browser CDP method (residential IP).

ACCESS STATUS (verified live, 2026-09-14):
-------------------------------------------------------------------------
UNBLOCKED from a residential IP using the persistent headed Brave browser.
Walmart's PerimeterX (Akamai) WAF still challenges direct `curl_cffi` /
`requests` TLS-fingerprint calls — EVEN from a residential IP — by serving a
"Robot or human?" challenge page. But a real (non-headless) browser on the
residential IP loads the search/products page normally, and Walmart embeds the
first page of results as a large JSON blob (the Next.js `__NEXT_DATA__` script)
that contains every product's name, price, sale price, brand, rating, and
in-store availability.

History / what still blocks:
  * plain requests / urllib              -> PerimeterX challenge ("Robot or human?")
  * curl_cffi Safari/Chrome impersonation -> PerimeterX challenge (verified, residential IP)
  * Playwright headless / xvfb           -> PerimeterX challenge
  * real headed Brave, residential IP    -> 200 with full __NEXT_DATA__  ✅

Requirements to actually return products:
  1. A genuinely residential egress IP (verified working from the home ISP IP).
  2. The persistent minimized Brave browser running on CDP port 9345 (launched
     once with --start-minimized --remote-debugging-port=9345 --user-data-dir=...).
     This scraper ATTACHES to it via cdP and reuses the current tab / opens the
     search URL — it does NOT launch its own browser (avoids window popping).
  3. `browser_use` installed (uv tool). If it is unavailable at runtime, the
     scraper falls back to logging an error and returning [] (old blocked path).
-------------------------------------------------------------------------

Contract: subclasses BaseScraper. Implements authenticate(), search_products(),
get_product_price(). Uses `normalize_price()` from base so records match the
standard schema across all retailers.
"""
import json
import logging
import re
from typing import Optional

from .base import BaseScraper

logger = logging.getLogger(__name__)

SEARCH_URL = "https://www.walmart.com/search"
DEFAULT_STORE = "2787"  # Walmart Supercenter #2787, North Keystone, Indianapolis


def _browser_import():
    """Import browser_use lazily. Returns the BrowserSession class or raises ImportError."""
    from browser_use.browser.session import BrowserSession  # noqa: PLC0415
    return BrowserSession


def _extract_next_data(html: str) -> dict | None:
    """Pull the big Next.js __NEXT_DATA__ JSON blob out of a Walmart page.

    Walmart server-renders page 1 into a <script> with a large JSON object that
    contains props.pageProps.initialData.searchResult.itemStacks[].items[].
    It is not always an id="__NEXT_DATA__" script, so scan large script bodies
    for the initialData/searchResult signature and JSON.parse the best match.
    """
    scripts = re.findall(r"<script[^>]*>(.*?)</script>", html, re.S)
    best: dict | None = None
    for raw in scripts:
        s = raw.strip()
        if not s.startswith("{"):
            continue
        if '"initialData"' not in s or '"searchResult"' not in s:
            continue
        try:
            data = json.loads(s)
            # Prefer the blob that actually carries item data
            stacks = (
                data.get("props", {}).get("pageProps", {}).get("initialData", {})
                .get("searchResult", {}).get("itemStacks", [])
            )
            if best is None or sum(len(st.get("items", [])) for st in stacks) > \
               sum(len(st.get("items", [])) for st in best.get("_stacks", [])):
                data["_stacks"] = stacks
                best = data
        except json.JSONDecodeError:
            continue
    if best:
        best.pop("_stacks", None)
    return best


class WalmartScraper(BaseScraper):
    retailer = "walmart"

    def __init__(self, store_id: str, config: dict):
        super().__init__(store_id, config)
        self.store_id = store_id or DEFAULT_STORE
        self.cdp_url = config.get("cdp_url") or "http://127.0.0.1:9345"
        # Give the page time to run JS & clear any pending challenge.
        self.load_wait_s = float(config.get("load_wait_seconds", 7))

    # -- auth is a no-op: the browser holds the session ----------------------
    def authenticate(self) -> None:
        """No-op — the persistent headed browser already holds a warm Walmart
        session on the residential IP. Nothing to refresh here."""
        logger.info("[walmart] using persistent browser session (no auth needed)")

    # -- real-browser fetch helpers ------------------------------------------
    def _fetch_html(self, url: str) -> str | None:
        """Attach to the persistent CDP browser (reuse current tab), navigate to
        url, wait for JS, and return the rendered outerHTML. Returns None if
        browser_use is unavailable or navigation fails."""
        try:
            BrowserSession = _browser_import()
        except ImportError:
            logger.error(
                "[walmart] browser_use not installed. Cannot drive real browser. "
                "Install: uv tool install browser-use  (or pip install browser-use)"
            )
            return None

        import asyncio

        async def _go() -> str | None:
            session = BrowserSession(cdp_url=self.cdp_url)
            await session.start()
            try:
                page = await session.new_page(url)
                import time
                time.sleep(self.load_wait_s)
                html = await page.evaluate("() => document.documentElement.outerHTML")
                return html or None
            finally:
                await session.close()

        try:
            return asyncio.run(_go())
        except Exception as exc:  # noqa: BLE001
            logger.error("[walmart] browser fetch failed for %s: %s", url, exc)
            return None

    def _is_challenge(self, html: str) -> bool:
        # A real Walmart result page ALWAYS embeds the PX SDK (window._pxAppId=...),
        # so presence of "_px*" or "captcha" is NOT a challenge. The only reliable
        # bot-wall signals are the challenge page title / body marker and the
        # Akamai access-denied text.
        low = (html or "").lower()
        return ("robot or human" in low or
                "access denied" in low or
                "<title>robot or human</title>" in low)

    # -- public methods -------------------------------------------------------
    def search_products(self, query: str) -> list[dict]:
        url = f"{SEARCH_URL}?q={query.replace(' ', '%20')}&store={self.store_id}"
        html = self._fetch_html(url)
        if not html:
            logger.warning("[walmart] no HTML for '%s' (browser failed)", query)
            return []

        if self._is_challenge(html):
            logger.warning("[walmart] PerimeterX challenge on '%s'", query)
            return []

        data = _extract_next_data(html)
        if not data:
            logger.warning("[walmart] no __NEXT_DATA__ for '%s'", query)
            return []

        self.save_raw(data, f"search_{query.replace(' ', '_')}")

        stacks = (
            data.get("props", {}).get("pageProps", {}).get("initialData", {})
            .get("searchResult", {}).get("itemStacks", [])
        )
        items = []
        for stack in stacks:
            if stack.get("stackType") in ("SPONSORED", "RELATED"):
                continue
            items.extend(stack.get("items", []))
        return [self._normalize_item(it) for it in items]

    def get_product_price(self, product_id: str) -> Optional[dict]:
        url = f"https://www.walmart.com/ip/{product_id}"
        html = self._fetch_html(url)
        if not html or self._is_challenge(html or ""):
            return None
        data = _extract_next_data(html)
        if not data:
            return None
        product = (
            data.get("props", {}).get("pageProps", {}).get("initialData", {})
            .get("data", {}).get("product", {})
        )
        if not product:
            return None
        return self.normalize_price(
            product_id=product_id,
            name=product.get("name", ""),
            price=float(product.get("priceInfo", {}).get("currentPrice", {}).get("price", 0.0) or 0.0),
            extra={"sale_price": None},
        )

    # -- record shaping --------------------------------------------------------
    def _normalize_item(self, item: dict) -> dict:
        price_info = item.get("priceInfo") or {}
        raw_price = item.get("price") or price_info.get("currentPrice", {}) or 0.0
        if isinstance(raw_price, dict):
            raw_price = raw_price.get("price", 0.0)
        try:
            price = float(raw_price) if raw_price else 0.0
        except (ValueError, TypeError):
            price = 0.0
        if not price:
            m = re.search(r"\$?([\d]+\.\d+|[\d]+)", str(price_info.get("linePrice") or ""))
            try:
                price = float(m.group(1)) if m else 0.0
            except (ValueError, AttributeError):
                price = 0.0

        unit_price_str = price_info.get("unitPrice") or ""
        was_str = price_info.get("wasPrice") or ""
        try:
            was_price = float(str(was_str).lstrip("$").replace(",", "")) if was_str else None
        except ValueError:
            was_price = None
        if was_price:
            regular_price, sale_price = was_price, price
        else:
            regular_price, sale_price = price, None

        rating_obj = item.get("rating") or {}
        brand = (item.get("productBrand") or item.get("brand")
                 or item.get("sellerName") or None)
        return self.normalize_price(
            product_id=item.get("usItemId", ""),
            name=item.get("name", ""),
            price=regular_price,
            unit=unit_price_str or None,
            url=f"https://www.walmart.com{item.get('canonicalUrl', '')}",
            extra={
                "sale_price": sale_price,
                "brand": brand,
                "category": item.get("catalogProductType") or None,
                "aisle": item.get("productLocationDisplayValue") or None,
                "snap_eligible": bool(item.get("snapWicBadgeText")),
                "in_stock": item.get("availabilityStatusDisplayValue") == "In stock",
                "average_rating": rating_obj.get("averageRating"),
                "num_reviews": rating_obj.get("numberOfReviews"),
            },
        )