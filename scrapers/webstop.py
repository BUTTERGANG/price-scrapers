"""Generic Webstop circular scraper — config-only support for new retailers.

Webstop (grocerywebsite.com) hosts weekly circulars for hundreds of regional
US grocers (Niemann Harvest Market, County Market, IGA affiliates, ...). The
convention is www2.{domain} for content and www3.{domain} for the store API,
with a numeric retailer ID. Any such grocer can be added purely via
config/stores.json:

    "county_market": {
        "name": "County Market",
        "platform": "webstop",
        "locations": [
            {
                "store_id": "42",
                "webstop_host": "mycountymarket.com",
                "webstop_retailer_id": "2470",
                "address": "..."
            }
        ]
    }

The runner's PLATFORM_SPECS picks the entry up automatically — no code change.

Circular pages are discovered from the pagination links at scrape time.
(Webstop's old /department/{dept}/ filter URLs still exist in the nav but have
been deprecated server-side — they all return page-1 content — so items are
scraped per page and department attribution comes from each item's own badge
when present.)
"""
import logging
import re
from typing import Optional

import requests
from parsel import Selector

from .base import BaseScraper

logger = logging.getLogger(__name__)

# Regex to parse "Valid MM/DD/YYYY to MM/DD/YYYY"
_VALID_RE = re.compile(
    r"Valid\s+(\d{2}/\d{2}/\d{4})\s+to\s+(\d{2}/\d{2}/\d{4})", re.IGNORECASE
)

_PAGE_HREF_RE = re.compile(r"/circulars/Page/(\d+)/")
_PAGE_SEG_RE = re.compile(r"/Page/\d+/")

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


def find_webstop_stores(host: str, retailer_id: str, zip_code: str) -> list[dict]:
    """Search a Webstop retailer's store list by ZIP code."""
    session = requests.Session()
    session.headers.update({**_HEADERS, "X-Requested-With": "XMLHttpRequest"})
    resp = session.post(
        f"https://www3.{host}/retailers/{retailer_id}/stores/search",
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
        choose_href = li.css("a[href*='choose_store']").attrib.get("href", "")
        store_id_match = re.search(r"/stores/(\d+)/choose_store", choose_href)
        stores.append(
            {
                "id": store_id_match.group(1) if store_id_match else "",
                "name": name,
                "address": addr_parts[0] if addr_parts else "",
                "city_state_zip": addr_parts[1] if len(addr_parts) > 1 else "",
                "distance": li.css(".badge.rounded-pill ::text").get("").strip(),
            }
        )
    return stores


class WebstopScraper(BaseScraper):
    """Weekly circular scraper for any Webstop-based grocer, driven by config."""

    retailer = "webstop"
    # Subclasses may pin these instead of passing config keys.
    host: str = ""
    retailer_id: str = ""

    def __init__(self, store_id: str, config: dict):
        """
        Required config keys (unless pinned by a subclass):
            webstop_host        — bare domain, e.g. "goharvestmarket.com"
            webstop_retailer_id — numeric Webstop retailer ID, e.g. "3328"
        Optional:
            retailer            — retailer key for price records (set by the runner)
        """
        self.retailer = config.get("retailer") or self.retailer
        super().__init__(store_id, config)
        host = config.get("webstop_host") or self.host
        if not host:
            raise ValueError(f"[{self.retailer}] webstop_host config is required")
        self.base_url = f"https://www2.{host}"
        self.api_host = f"https://www3.{host}"
        self.retailer_id = str(config.get("webstop_retailer_id") or self.retailer_id)
        if not self.retailer_id:
            raise ValueError(f"[{self.retailer}] webstop_retailer_id config is required")
        self.session = requests.Session()
        self.session.headers.update({**_HEADERS, "Referer": self.base_url + "/"})
        self._circular_url: Optional[str] = None  # set by authenticate()
        self._circular_html: str = ""

    def authenticate(self) -> None:
        """Set the Webstop store cookie by visiting the choose_store endpoint."""
        url = f"{self.api_host}/retailers/{self.retailer_id}/stores/{self.store_id}/choose_store"
        resp = self.session.get(
            url,
            params={"filter": "circulars", "url": f"{self.base_url}/circulars/"},
            timeout=15,
            allow_redirects=True,
        )
        resp.raise_for_status()

        # The redirect target is the circular base URL (e.g.
        # .../circulars/Page/1/Base/1/260624_HM/). Department pages must be
        # fetched relative to it — the bare /circulars/department/{dept}/ path
        # returns empty HTML.
        self._circular_url = resp.url.rstrip("/")
        self._circular_html = resp.text
        logger.info(f"[{self.retailer}] Store set: id={self.store_id} "
                    f"(circular {resp.url})")

    def _discover_pages(self) -> list[int]:
        """Circular page numbers from the pagination links (always ≥ [1])."""
        pages = sorted({int(p) for p in _PAGE_HREF_RE.findall(self._circular_html or "")})
        return pages or [1]

    def _page_url(self, page: int) -> str:
        if not self._circular_url:
            raise RuntimeError(
                f"[{self.retailer}] _circular_url not set — call authenticate() first."
            )
        return _PAGE_SEG_RE.sub(f"/Page/{page}/", self._circular_url) + "/"

    def scrape_circular(self) -> list[dict]:
        """Scrape the current weekly circular across all its pages.

        Price formats handled:
          "$4.99 lb."  → price=4.99, unit="lb."
          "$11"        → price=11.0, unit=None
          "2/$5"       → price=5.0, unit=None, deal_text="2/$5"
          no price     → price=0.0
        """
        self.authenticate()

        pages = self._discover_pages()
        seen_ids: set[str] = set()
        results: list[dict] = []
        all_raw: list[dict] = []

        for page in pages:
            page_items, page_raw = self._scrape_page(page)
            all_raw.extend(page_raw)
            for item in page_items:
                if item["product_id"] not in seen_ids:
                    seen_ids.add(item["product_id"])
                    results.append(item)
            logger.debug(f"[{self.retailer}] page {page}: {len(page_items)} items "
                         f"({len(results)} total)")

        self.save_raw(all_raw, "circular_all")
        logger.info(
            f"[{self.retailer}] Scraped {len(results)} items across "
            f"{len(pages)} circular pages (store {self.store_id})."
        )
        return results

    def _scrape_page(self, page: int) -> tuple[list[dict], list[dict]]:
        """Fetch and parse one circular page. Returns (normalized, raw)."""
        resp = self.session.get(self._page_url(page), timeout=20)
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

            # Validity dates from the "Valid MM/DD/YYYY to MM/DD/YYYY" badge
            valid_from: Optional[str] = None
            valid_to: Optional[str] = None
            vm = _VALID_RE.search(article.css(".bg-secondary ::text").get("").strip())
            if vm:
                valid_from, valid_to = vm.group(1), vm.group(2)

            raw.append({
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
                "page": page,
            })

            items.append(
                self.normalize_price(
                    product_id=product_id,
                    name=name,
                    price=price,
                    unit=suffix if suffix else None,
                    url=f"{self.base_url}/circulars/",
                    extra={
                        "deal_text": deal_text,
                        "heading": heading or None,
                        "description": description or None,
                        "valid_from": valid_from,
                        "valid_to": valid_to,
                        "page": page,
                    },
                )
            )

        return items, raw

    def search_products(self, query: str) -> list[dict]:
        """Search the current circular by name/description."""
        q = query.lower()
        return [
            r for r in self.scrape_circular()
            if q in r["name"].lower()
            or q in (r.get("description") or "").lower()
        ]

    def get_product_price(self, product_id: str) -> Optional[dict]:
        for r in self.scrape_circular():
            if r["product_id"] == product_id:
                return r
        return None
