"""Gordon Food Service (GFS) Store scraper — gfsstore.com, WordPress SSR HTML.

==============================================================================
ARCHITECTURE OVERVIEW
==============================================================================

GFS Store is a WordPress site with a custom theme. All product data is
server-side rendered — no JavaScript execution, no API keys, no bot detection.
Plain requests + parsel works perfectly.

There are two data sources:

1. WEEKLY ADS (scrape_circular)
   Two tabs, each a separate URL, each with different validity windows:
     "Weekly Deals"      — /en-us/ads/weekly-deals/      (valid ~2 weeks)
     "In-Store Features" — /en-us/ads/in-store-features/ (valid ~6 weeks)
   Each page has ~25–35 sale/featured items. Valid-thru dates are parsed
   from the page's .ad-dates element.
   Products are .product-box divs with:
     h2 a        → display name (short, human-friendly)
     img alt     → full product name with brand and package type
     href        → /en-us/products/{id} — canonical product ID
     .product-box-price  → "$32.99"
     .product-box-per    → "case", "bag", "package", "each", etc.
     .product-image-overlay → weight/size badge, e.g. "10 POUNDS"

2. DEPARTMENT CATALOG (scrape_department / scrape_all_departments)
   12 departments, each a separate URL:
     /en-us/departments/{slug}/
   Products are .product-box divs with additional data attributes:
     data-id         → product ID (NOTE: may have trailing store-variant digit;
                        always prefer ID extracted from the product href)
     data-name       → product name
     data-brand      → brand name
     data-department → department name
     data-category   → sub-category name
     .product-box-price  → "$7.99" (may be empty for weight-based/unlisted items)
     .product-box-per    → unit qualifier
     .product-box__sale  → "Sale" badge (present if on sale)

PRODUCT SEARCH (search_products)
---------------------------------------------------------------------
GFS has no public search API returning structured JSON. search_products()
falls back to filtering the in-memory circular and/or department data.
For full catalog search, scrape_all_departments() returns all products.

==============================================================================
STORE DETAILS
==============================================================================

GFS identifies stores via:
  - store_id: numeric string embedded in page JS as
      var autocomplete = {"store_id": "1905"}
  - mp_number: marketing-partner number in data-mp_number attr (e.g. "MP153")
  - URL slug: /en-us/locations/{slug}/ (e.g. "fishers")

Fishers / Indianapolis-area store:
  store_id  = "1905"
  mp_number = "MP153"
  slug      = "fishers"
  address   = 9540 Masters Rd, Indianapolis, IN 46250
  phone     = 317-845-0712
  hours     = Mon–Sat 7:00am–7:00pm, Sun 9:00am–6:00pm
  NOTE: The URL says "Fishers" but the address is Indianapolis 46250.

==============================================================================
INSTALL
==============================================================================

pip install requests parsel
(No curl_cffi, no Playwright, no API keys needed)
"""
import logging
import re
from typing import Optional
from urllib.parse import urljoin

import requests
from parsel import Selector

from .base import BaseScraper

logger = logging.getLogger(__name__)

BASE_URL = "https://gfsstore.com/en-us"

AD_TABS = [
    {
        "name": "Weekly Deals",
        "url": f"{BASE_URL}/ads/weekly-deals/",
    },
    {
        "name": "In-Store Features",
        "url": f"{BASE_URL}/ads/in-store-features/",
    },
]

DEPARTMENTS = [
    "Produce",
    "Meat+%26+Seafood",
    "Deli",
    "Dairy",
    "Frozen+Foods",
    "Pantry",
    "International",
    "Beverages",
    "Disposables",
    "Cleaning+Supplies",
    "Kitchenware",
    "Cooking+Fuels",
]

_DEPT_DISPLAY = {
    "Meat+%26+Seafood": "Meat & Seafood",
    "Frozen+Foods": "Frozen Foods",
    "Cleaning+Supplies": "Cleaning Supplies",
    "Cooking+Fuels": "Cooking Fuels",
}

# Regex to extract product ID from href
_PID_RE = re.compile(r"/products/(\d+)/?$")

# Regex to extract valid-thru date from ".ad-dates" text
_VALID_THRU_RE = re.compile(r"Valid\s+thru\s+(\d{2}/\d{2}/\d{4})", re.IGNORECASE)

# Regex to strip leading "$" and parse dollar amount
_PRICE_RE = re.compile(r"^\$?([\d,]+\.?\d*)$")

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://gfsstore.com/en-us/",
}


class GFSScraper(BaseScraper):
    """Scraper for Gordon Food Service Store — weekly ads and department catalog."""

    retailer = "gfs"

    def __init__(self, store_id: str, config: dict):
        """
        Args:
            store_id: GFS store identifier string, e.g. "1905" for Fishers/Indianapolis.
            config may include:
              "mp_number": marketing-partner number, e.g. "MP153" (used for store selection)
        """
        super().__init__(store_id, config)
        self.session = requests.Session()
        self.session.headers.update(_HEADERS)
        self._mp_number: str = config.get("mp_number", "")

    def authenticate(self) -> None:
        """
        Select the store by hitting the homepage with ?dsr_id={mp_number}.
        This sets the wp-MyStore / MyStoreID session cookies that unlock the
        ad and department pages for this specific store location.
        Without this, all ad page requests redirect to the store-selector page.
        """
        if not self._mp_number:
            logger.warning("[gfs] No mp_number in config — ad pages may redirect to store selector.")
            return
        try:
            r = self.session.get(
                f"{BASE_URL}/?dsr_id={self._mp_number}",
                timeout=20,
            )
            r.raise_for_status()
            logger.info(f"[gfs] Store selected via dsr_id={self._mp_number} (cookies set).")
        except Exception as exc:
            logger.warning(f"[gfs] Store selection failed (non-fatal): {exc}")

    def search_products(self, query: str) -> list[dict]:
        """Search for products in the current weekly ads by name."""
        query_lower = query.lower()
        results = self.scrape_circular()
        return [
            r for r in results
            if query_lower in r["name"].lower()
            or query_lower in (r.get("full_name") or "").lower()
            or query_lower in (r.get("brand") or "").lower()
        ]

    def get_product_price(self, product_id: str) -> Optional[dict]:
        results = self.scrape_circular()
        for r in results:
            if r["product_id"] == product_id:
                return r
        return None

    def scrape_circular(self) -> list[dict]:
        """
        Scrape both weekly ad tabs and return a combined, deduplicated list.

        Returns price dicts from "Weekly Deals" and "In-Store Features".
        Each item includes a 'valid_thru' date string (MM/DD/YYYY) and
        'ad_tab' label identifying which ad it came from.

        Products appearing in both tabs are deduplicated by product_id;
        the Weekly Deals entry is kept (it typically has the lower sale price).
        """
        seen_ids: set[str] = set()
        results: list[dict] = []
        all_raw: list[dict] = []

        for tab in AD_TABS:
            items, raw = self._scrape_ad_page(tab["url"], tab["name"])
            all_raw.extend(raw)
            for item in items:
                if item["product_id"] not in seen_ids:
                    seen_ids.add(item["product_id"])
                    results.append(item)

        self.save_raw(all_raw, "circular_all")
        logger.info(
            f"[gfs] Scraped {len(results)} ad items "
            f"(Weekly Deals + In-Store Features, store {self.store_id})."
        )
        return results

    def scrape_department(self, dept_slug: str) -> list[dict]:
        """
        Scrape all products from a single department page.

        Args:
            dept_slug: URL slug from DEPARTMENTS list, e.g. "Produce",
                       "Meat+%26+Seafood", "Frozen+Foods", etc.

        Returns list of normalized price dicts. Items sold at multiple pack
        sizes (e.g. per bag and per case) have their individual/bag price as
        the primary price and full options in extra["price_options"].
        """
        url = f"{BASE_URL}/departments/{dept_slug}/"
        resp = self.session.get(url, timeout=20)
        resp.raise_for_status()

        sel = Selector(resp.text)
        dept_display = _DEPT_DISPLAY.get(dept_slug, dept_slug.replace("+", " "))
        items, raw = _parse_product_boxes(sel, source_url=url, dept_override=dept_display)

        self.save_raw(raw, f"dept_{dept_slug.replace('%26', 'and')}")
        logger.debug(f"[gfs] {dept_display}: {len(items)} products")
        return [
            self.normalize_price(
                product_id=i["product_id"],
                name=i["name"],
                price=i["price"],
                unit=i["unit"],
                url=i["url"],
                extra={k: v for k, v in i.items()
                       if k not in ("product_id", "name", "price", "unit", "url")},
            )
            for i in items
        ]

    def scrape_all_departments(self) -> list[dict]:
        """
        Scrape all 12 department pages and return a deduplicated full catalog.

        This is the full shelf-price catalog for the store. Items on sale will
        have is_sale=True and typically appear in scrape_circular() as well.
        """
        from utils.http import jitter_sleep

        seen_ids: set[str] = set()
        results: list[dict] = []

        for i, dept in enumerate(DEPARTMENTS):
            dept_items = self.scrape_department(dept)
            for item in dept_items:
                if item["product_id"] not in seen_ids:
                    seen_ids.add(item["product_id"])
                    results.append(item)
            logger.info(
                f"[gfs] Dept {dept}: {len(dept_items)} items "
                f"({len(results)} total so far)"
            )
            if i < len(DEPARTMENTS) - 1:
                jitter_sleep(self.request_delay)

        logger.info(
            f"[gfs] Full catalog: {len(results)} unique products "
            f"across {len(DEPARTMENTS)} departments."
        )
        return results

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _scrape_ad_page(
        self, url: str, tab_name: str
    ) -> tuple[list[dict], list[dict]]:
        """Fetch and parse one ad tab page. Returns (normalized, raw)."""
        resp = self.session.get(url, timeout=20)
        resp.raise_for_status()

        sel = Selector(resp.text)

        # Parse valid-thru date for this tab (each tab's date corresponds to its
        # own products — both dates appear in the nav, but we want the one that
        # matches this tab's content)
        valid_thru = _parse_valid_thru_for_tab(sel, tab_name)

        parsed, raw = _parse_product_boxes(sel, source_url=url)

        results = []
        for item in parsed:
            results.append(
                self.normalize_price(
                    product_id=item["product_id"],
                    name=item["name"],
                    price=item["price"],
                    unit=item["unit"],
                    url=item["url"],
                    extra={
                        "full_name": item.get("full_name"),
                        "brand": item.get("brand"),
                        "size_label": item.get("size_label"),
                        "is_sale": item.get("is_sale", False),
                        "ad_tab": tab_name,
                        "valid_thru": valid_thru,
                        "department": item.get("department"),
                        "category": item.get("category"),
                    },
                )
            )

        logger.debug(f"[gfs] {tab_name} ({valid_thru}): {len(results)} items")
        return results, raw


# ------------------------------------------------------------------
# Shared HTML parsing helpers
# ------------------------------------------------------------------

def _parse_product_boxes(
    sel: Selector,
    source_url: str,
    dept_override: Optional[str] = None,
) -> tuple[list[dict], list[dict]]:
    """
    Parse all .product-box elements from a page selector.

    Works for both ad pages and department pages. Two price layouts exist:

    Standard layout (most items, ad pages + most dept items):
      .product-box-price / .product-box-per
      e.g. "$32.99" / "case"

    Multi-price layout (items sold both individually and by the case):
      .product-card__bottom-case containing N × .product-card__case-price-container,
      each with an <h4> (price) and <p> (unit).
      e.g. "$8.99 bag" + "$30.00 case"
      The individual/bag price is used as the primary price; all options are
      stored in extra["price_options"] as a list of {"price", "unit"} dicts.
      The JSON in data-each_products / data-case_products on the Add-to-Cart
      buttons duplicates this data and is not separately parsed.
    """
    items: list[dict] = []
    raw: list[dict] = []

    for box in sel.css(".product-box"):
        # --- Product ID ---
        # Prefer ID from the product page href (canonical); fall back to data-id
        href = (
            box.css('a[href*="/products/"]').attrib.get("href", "")
            or box.css("a.gallery-more-details").attrib.get("href", "")
        )
        pid_match = _PID_RE.search(href)
        if pid_match:
            product_id = pid_match.group(1)
        else:
            # data-id on dept pages often has a trailing store-variant digit;
            # fall back to it as-is only if no href found
            product_id = box.attrib.get("data-id", "").rstrip("0")
            if not product_id:
                continue

        # --- Name ---
        # data-name (dept pages) or h2 a text (ad pages)
        name = (
            box.attrib.get("data-name", "").strip()
            or box.css("h2 a ::text").get("").strip()
        )
        if not name:
            continue

        # Full product name from img alt (includes brand + package type)
        full_name = box.css("img").attrib.get("alt", "").strip()
        # Brand from data-brand attr
        brand = box.attrib.get("data-brand", "").strip() or None

        # --- Price ---
        # Standard layout: single .product-box-price + .product-box-per
        price_text = box.css(".product-box-price ::text").get("").strip()
        price = _parse_price(price_text)
        unit = box.css(".product-box-per ::text").get("").strip() or None
        price_options: Optional[list] = None

        # Multi-price layout: .product-card__bottom-case with per-unit and per-case prices
        if not price_text:
            containers = box.css(".product-card__case-price-container")
            if containers:
                options = []
                for c in containers:
                    opt_price_text = c.css("h4 ::text").get("").strip()
                    opt_unit = c.css("p ::text").get("").strip() or None
                    opt_price = _parse_price(opt_price_text)
                    if opt_price_text:
                        options.append({"price": opt_price, "unit": opt_unit})
                if options:
                    # Primary price = first option (individual/bag unit)
                    price = options[0]["price"]
                    unit = options[0]["unit"]
                    price_options = options if len(options) > 1 else None

        # Size/weight overlay badge (e.g. "10 POUNDS")
        size_label = box.css(".product-image-overlay ::text").get("").strip() or None

        # Sale badge
        is_sale = bool(box.css(".product-box__sale"))

        # Department / category
        department = dept_override or box.attrib.get("data-department", "").strip() or None
        category = box.attrib.get("data-category", "").strip() or None

        product_url = (
            href if href.startswith("http")
            else ("https://gfsstore.com" + href if href.startswith("/") else source_url)
        )

        raw_item = {
            "id": product_id,
            "name": name,
            "full_name": full_name,
            "brand": brand,
            "price_text": price_text,
            "unit": unit,
            "size_label": size_label,
            "is_sale": is_sale,
            "department": department,
            "category": category,
            "url": product_url,
            "price_options": price_options,
        }
        raw.append(raw_item)

        items.append(
            {
                "product_id": product_id,
                "name": name,
                "full_name": full_name or None,
                "brand": brand,
                "price": price,
                "unit": unit,
                "size_label": size_label,
                "is_sale": is_sale,
                "department": department,
                "category": category,
                "url": product_url,
                "price_options": price_options,
            }
        )

    return items, raw


def _parse_price(price_text: str) -> float:
    """Parse a price string like '$32.99' → 32.99. Returns 0.0 if unparseable."""
    if not price_text:
        return 0.0
    m = _PRICE_RE.match(price_text.strip())
    if m:
        try:
            return float(m.group(1).replace(",", ""))
        except ValueError:
            pass
    return 0.0


def _parse_valid_thru_for_tab(sel: Selector, tab_name: str) -> Optional[str]:
    """
    Parse the valid-thru date for the given tab from the page's #ad_tabs nav.

    The nav contains two links, one per tab, each with an .ad-dates span:
      "Valid thru 04/04/2026"  → Weekly Deals
      "Valid thru 05/02/2026"  → In-Store Features

    We match by the adjacent .ad-title text.
    """
    for tab_link in sel.css("#ad_tabs .ad-title-outer"):
        title = tab_link.css(".ad-title ::text").get("").strip().upper()
        dates_text = tab_link.css(".ad-dates ::text").get("").strip()
        # Match tab_name loosely
        if (
            ("WEEKLY" in title and "WEEKLY" in tab_name.upper())
            or ("FEATURE" in title and "FEATURE" in tab_name.upper())
            or tab_name.upper().replace("-", " ") in title
        ):
            m = _VALID_THRU_RE.search(dates_text)
            if m:
                return m.group(1)

    # Fallback: return whichever date appears on the page
    dates = sel.css(".ad-dates ::text").getall()
    for d in dates:
        m = _VALID_THRU_RE.search(d)
        if m:
            return m.group(1)
    return None
