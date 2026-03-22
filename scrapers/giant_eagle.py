"""Giant Eagle Market District scraper — weekly circular via GraphQL API.

==============================================================================
ARCHITECTURE OVERVIEW
==============================================================================

Giant Eagle is a React SPA backed by an Apollo GraphQL API at
core.shop.gianteagle.com. The weekly circular data is fully accessible via
public (unauthenticated) GraphQL queries — no login, no Playwright, no API
key required. The HTML page is a static shell served from S3/CloudFront;
all data is loaded client-side via GraphQL.

Flipp/Wishabi powers the visual flyer (image URLs, PDFs come from
f.wishabi.net), but Giant Eagle wraps it entirely in their own GraphQL —
there is no direct Flipp API endpoint to call.

1. WEEKLY CIRCULAR (scrape_circular)
   ---------------------------------------------------------------------
   Three-step flow:

   Step 1 — Resolve store slug:
     Queried once; store code "6550" maps to slug "carmel-bridges".
     Cached as class-level constant — use `find_store()` to look up others.

   Step 2 — Get current circular ID:
     POST https://core.shop.gianteagle.com/api/v2
       query CircularsQuery($storeSlug: String!)
     Returns circular metadata: id, displayDates, pages, pdfUrl.
     Current circular ID is the first item returned.

   Step 3 — Fetch all circular products (paginated):
     POST https://core.shop.gianteagle.com/api/v2
       query GetProducts($filters, $store, $count, $cursor)
     Variables: { filters: { query: "", circular: true }, store: { storeCode: "6550" } }
     Returns up to 24 items per page, cursor-paginated, ~178 items/week.

   Product fields (GetProducts):
     name                → product name
     brand               → brand name
     description         → size/variety text
     displayItemSize     → size string (e.g. "16 oz", "1 lb")
     sku                 → UPC barcode
     id                  → "{storeCode}-{upc}" composite key
     price               → current sale price (string, e.g. "$2.49")
     comparedPrice       → regular/compared price (string, e.g. "$3.99") or null
     scopedPromoPrice    → loyalty card price, if any
     displayPricePerUnit → formatted unit price (e.g. "$0.16/oz")
     pricingModel        → "unit_price" or "by_avg_weight"
     rewardPromos[]      → structured deal data:
       name              → deal description (e.g. "Buy 2, Get 1 Free")
       rewardType        → "BOGO", "PCT_OFF", "FIXED_OFF", etc.
       buyQuantity       → integer (buy N)
       getQuantity       → integer (get N)
       rewardAmount      → float (% off or $ off)
     images[].url        → product images (images.media.gianteagle.com)

   Optionally, ad blocks can be fetched per-page for display-formatted prices:
     query FlippAdBlocksForPageQuery($storeSlug, $circularId, $pageNumber)
     Returns displayPrice strings (e.g. "sale $0.99 lb.") for 169 visual hotspots.

2. PRODUCT SEARCH (search_products)
   ---------------------------------------------------------------------
     POST /api/v2 with GetProducts, filters: { query: "{query}", circular: false }
     Returns matching catalog products with current store pricing.

==============================================================================
STORE IDs
==============================================================================

Giant Eagle uses two identifiers:
  storeCode — numeric string in URL (e.g. "6550"), used in GetProducts queries
  storeSlug — URL-friendly string (e.g. "carmel-bridges"), used in CircularsQuery

Known Indianapolis-area stores:
  6550 / "carmel-bridges" — 11505 N Illinois Street, Carmel IN 46032
                             "Carmel Market District"

Run GiantEagleScraper.find_store(zip_code="46220") to list nearby stores.

==============================================================================
INSTALL
==============================================================================

pip install curl-cffi
"""
import logging
import re
from typing import Optional

from .base import BaseScraper
from utils.http import make_curl_session

logger = logging.getLogger(__name__)

GRAPHQL_URL = "https://core.shop.gianteagle.com/api/v2"

_GQL_HEADERS = {
    "content-type": "application/json;charset=utf-8",
    "X-HL-APP": "grocery",
    "X-HL-CLIENT": "web",
    "X-HL-REFERRER": "https://www.gianteagle.com/",
    "Origin": "https://www.gianteagle.com",
    "Referer": "https://www.gianteagle.com/",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
}

# Known store code → slug mappings (avoids an extra API call)
_STORE_SLUGS = {
    "6550": "carmel-bridges",
}

# GraphQL queries
_Q_CIRCULARS = """
query CircularsQuery($storeSlug: String!) {
  circulars(store: { storeSlug: $storeSlug }) {
    id
    title
    displayDates
    pdfUrl
    pages { pageNumber }
  }
}
"""

_Q_PRODUCTS = """
query GetProducts($filters: ProductFilters, $store: StoreInput!, $count: Int, $cursor: String) {
  products(filters: $filters store: $store first: $count after: $cursor) {
    edges {
      cursor
      node {
        id
        sku
        name
        brand
        description
        displayItemSize
        price
        comparedPrice
        scopedPromoPrice
        displayPricePerUnit
        pricingModel
        rewardPromos {
          name
          rewardType
          buyQuantity
          getQuantity
          rewardAmount
        }
        images { url }
      }
    }
    pageInfo { endCursor hasNextPage }
    totalCount
  }
}
"""

_Q_AD_BLOCKS = """
query FlippAdBlocksForPageQuery($storeSlug: String!, $circularId: ID!, $pageNumber: Int!) {
  circularAdBlocks(
    store: { storeSlug: $storeSlug }
    circularId: $circularId
    pageNumber: $pageNumber
  ) {
    id
    name
    displayPrice
    description
    disclaimer
    saleStory
    displayDates
    images
  }
}
"""

_Q_STORES = """
query GetStores($zipcode: ZipCode!) {
  stores(zipcode: $zipcode) {
    code
    slug
    name
    address { line1 city state zip }
    distance
  }
}
"""

# Price string parsers
_DOLLAR_RE = re.compile(r"\$([0-9]+(?:\.[0-9]{1,2})?)")
_MULTI_RE = re.compile(r"(\d+)\s*/\s*\$([0-9]+(?:\.[0-9]{1,2})?)")
_FOR_RE = re.compile(r"(\d+)\s+for\s+\$([0-9]+(?:\.[0-9]{1,2})?)", re.IGNORECASE)


class GiantEagleScraper(BaseScraper):
    """Scraper for Giant Eagle Market District weekly circular via GraphQL."""

    retailer = "giant_eagle"

    def __init__(self, store_id: str, config: dict):
        """
        Args:
            store_id: Giant Eagle numeric store code, e.g. "6550".
        """
        super().__init__(store_id, config)
        self.session = make_curl_session(proxy=config.get("proxy"))
        self.session.headers.update(_GQL_HEADERS)
        self._store_slug: Optional[str] = _STORE_SLUGS.get(store_id)

    def authenticate(self) -> None:
        # No authentication required — circular data is publicly accessible.
        pass

    def search_products(self, query: str) -> list[dict]:
        """Search the store's full product catalog (not circular-filtered)."""
        return self._fetch_products(query=query, circular=False)

    def get_product_price(self, product_id: str) -> Optional[dict]:
        results = self.search_products(product_id)
        for r in results:
            if r["product_id"] == product_id or r.get("sku") == product_id:
                return r
        return results[0] if results else None

    def scrape_circular(self) -> list[dict]:
        """
        Scrape all sale items from the current weekly circular.

        Uses the GetProducts GraphQL query with circular=true, which returns
        structured pricing data for all ~178 items on sale this week.

        Returns list of normalized price dicts. Items with BOGO/reward promos
        have deal_text set in extra fields. comparedPrice (regular shelf price)
        is in extra.compared_price when available.
        """
        results = self._fetch_products(query="", circular=True)
        logger.info(
            f"[giant_eagle] Scraped {len(results)} circular items "
            f"(store {self.store_id})."
        )
        return results

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _gql(self, query: str, variables: dict) -> dict:
        """Execute a GraphQL query and return the response data dict."""
        resp = self.session.post(
            GRAPHQL_URL,
            json={"query": query, "variables": variables},
            timeout=20,
        )
        resp.raise_for_status()
        body = resp.json()
        if "errors" in body:
            raise RuntimeError(f"[giant_eagle] GraphQL error: {body['errors']}")
        return body.get("data", {})

    def _resolve_slug(self) -> str:
        """Return the store slug, fetching it from the API if not cached."""
        if self._store_slug:
            return self._store_slug
        data = self._gql(_Q_STORES, {"zipcode": "46032"})
        for store in data.get("stores", []):
            if str(store.get("code")) == str(self.store_id):
                self._store_slug = store["slug"]
                return self._store_slug
        raise RuntimeError(
            f"[giant_eagle] Could not resolve slug for store {self.store_id}."
        )

    def _fetch_products(self, query: str, circular: bool) -> list[dict]:
        """
        Fetch products via GetProducts GraphQL query, handling cursor pagination.
        circular=True → sale items only; circular=False → full catalog search.
        """
        results = []
        cursor = None
        page = 0

        while True:
            variables = {
                "filters": {"query": query, "circular": circular},
                "store": {"storeCode": self.store_id},
                "count": 24,
            }
            if cursor:
                variables["cursor"] = cursor

            data = self._gql(_Q_PRODUCTS, variables)

            if page == 0 and circular:
                self.save_raw(data, f"circular_store{self.store_id}")
            elif page == 0:
                self.save_raw(data, f"search_{query.replace(' ', '_')}")

            products_data = data.get("products", {})
            edges = products_data.get("edges", [])

            for edge in edges:
                node = edge.get("node", {})
                record = self._parse_product(node)
                if record:
                    results.append(record)

            page_info = products_data.get("pageInfo", {})
            if not page_info.get("hasNextPage"):
                break
            cursor = page_info.get("endCursor")
            page += 1

        return results

    def _parse_product(self, node: dict) -> Optional[dict]:
        """Convert a GraphQL product node into a normalized price record."""
        name = (node.get("name") or "").strip()
        if not name:
            return None

        price_str = (node.get("price") or "").strip()
        compared_str = (node.get("comparedPrice") or "").strip()
        scoped_str = (node.get("scopedPromoPrice") or "").strip()
        unit_price_str = (node.get("displayPricePerUnit") or "").strip()
        size_str = (node.get("displayItemSize") or "").strip() or None

        price, unit, deal_text = _parse_price_string(price_str)
        compared_price, _, _ = _parse_price_string(compared_str)
        scoped_price, _, _ = _parse_price_string(scoped_str)

        # Parse unit price (e.g. "$0.16/oz" → 0.16, "oz")
        up_val, up_unit = _parse_unit_price(unit_price_str)

        # Build deal text from rewardPromos if present
        reward_promos = node.get("rewardPromos") or []
        if reward_promos and not deal_text:
            deal_text = "; ".join(
                p["name"] for p in reward_promos if p.get("name")
            ) or None

        sku = (node.get("sku") or "").strip()
        product_id = node.get("id") or sku or name.lower().replace(" ", "_")

        images = node.get("images") or []
        image_url = images[0].get("url") if images else None

        return self.normalize_price(
            product_id=str(product_id),
            name=name,
            price=price,
            unit=unit or size_str,
            unit_price=up_val,
            url=f"https://www.gianteagle.com/{self.store_id}/weekly-flyer",
            upc=sku or None,  # Giant Eagle sku is the UPC barcode
            extra={
                "brand": (node.get("brand") or "").strip() or None,
                "description": (node.get("description") or "").strip() or None,
                "sku": sku or None,
                "compared_price": compared_price,
                "scoped_promo_price": scoped_price,
                "unit_price_text": unit_price_str or None,
                "unit_price_unit": up_unit,
                "deal_text": deal_text,
                "reward_promos": reward_promos or None,
                "pricing_model": node.get("pricingModel"),
                "image_url": image_url,
            },
        )

    # ------------------------------------------------------------------
    # Store locator
    # ------------------------------------------------------------------

    @classmethod
    def find_store(cls, zip_code: str = "46220", config: dict = None) -> list[dict]:
        """
        Query the Giant Eagle store locator for stores near a ZIP code.

        Example:
            stores = GiantEagleScraper.find_store(zip_code="46032")
            for s in stores:
                print(s["code"], s["slug"], s["name"], s["address"])
        """
        session = make_curl_session()
        session.headers.update(_GQL_HEADERS)
        resp = session.post(
            GRAPHQL_URL,
            json={"query": _Q_STORES, "variables": {"zipcode": zip_code}},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json().get("data", {})
        stores = []
        for s in data.get("stores", []):
            addr = s.get("address", {})
            stores.append(
                {
                    "code": s.get("code", ""),
                    "slug": s.get("slug", ""),
                    "name": s.get("name", ""),
                    "address": addr.get("line1", ""),
                    "city": addr.get("city", ""),
                    "state": addr.get("state", ""),
                    "zip": addr.get("zip", ""),
                    "distance": s.get("distance", ""),
                }
            )
        return stores


# ------------------------------------------------------------------
# Price parsing helpers
# ------------------------------------------------------------------

def _parse_price_string(text: str) -> tuple[float, Optional[str], Optional[str]]:
    """
    Parse a Giant Eagle price string.

    Returns (price, unit, deal_text):
      "5.97"            → (5.97, None, None)   ← plain numeric (most common)
      "$2.49"           → (2.49, None, None)
      "$0.99 lb."       → (0.99, "lb.", None)
      "3/ $8.00"        → (2.67, None, "3/ $8.00")
      "2 for $5.00"     → (2.50, None, "2 for $5.00")
      "" / None         → (0.0, None, None)
    """
    if not text:
        return 0.0, None, None

    # Plain numeric string e.g. "5.97", "10.00"
    try:
        return float(text.strip()), None, None
    except ValueError:
        pass

    # "3/ $8.00" or "3/$8.00"
    m = _MULTI_RE.search(text)
    if m:
        count, total = int(m.group(1)), float(m.group(2))
        return round(total / count, 4), None, text.strip()

    # "2 for $5.00"
    m = _FOR_RE.search(text)
    if m:
        count, total = int(m.group(1)), float(m.group(2))
        return round(total / count, 4), None, text.strip()

    # "$2.49" or "$0.99 lb." or "sale $0.99 lb."
    m = _DOLLAR_RE.search(text)
    if m:
        price = float(m.group(1))
        after = text[m.end():].strip().lstrip(".").strip()
        unit = after if after and len(after) < 20 else None
        return price, unit, None

    return 0.0, None, text.strip() or None


def _parse_unit_price(text: str) -> tuple[Optional[float], Optional[str]]:
    """
    Parse a unit price string like "$0.16/oz" → (0.16, "oz").
    Returns (None, None) if not parseable.
    """
    if not text:
        return None, None
    m = re.match(r"\$([0-9]+(?:\.[0-9]+)?)/(.+)", text.strip())
    if m:
        try:
            return float(m.group(1)), m.group(2).strip()
        except ValueError:
            pass
    return None, None
