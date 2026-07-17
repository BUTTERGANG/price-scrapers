"""Generic Flipp circular scraper — config-only support for new retailers.

Aldi, Meijer, and Fresh Thyme each have dedicated scrapers built on Flipp's
flyerkit API; hundreds of other US grocers publish their weekly ad through the
same system. This class lets any of them be added purely via config/stores.json:

    "dollar_general": {
        "name": "Dollar General",
        "platform": "flipp",
        "locations": [
            {
                "store_id": "07136",
                "flipp_merchant": "dollargeneral",
                "flipp_token": "<token from the retailer's weekly-ad page JS>",
                "address": "..."
            }
        ]
    }

The runner's PLATFORM_SPECS picks the entry up automatically — no code change.

Finding the token: open the retailer's weekly-ad page, look for a
`flippenterprise.net/flyerkit` or `api.flipp.com/flyerkit` request in DevTools;
`access_token` is in the query string and the merchant slug is in the
`/publications/{merchant}` path. `store_id` must be the retailer's
merchant_store_code (list them via the flyerkit /stores/{merchant} endpoint,
or the dashboard's store discovery once the entry exists).
"""
import logging
from typing import Optional

import requests

from .base import BaseScraper

logger = logging.getLogger(__name__)

DEFAULT_FLIPP_API = "https://dam.flippenterprise.net/flyerkit"

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
}


def fetch_publications(session, api: str, merchant: str, token: str,
                       store_code: str) -> list[dict]:
    """List active Flipp publications for a store."""
    resp = session.get(
        f"{api}/publications/{merchant}",
        params={
            "languages[]": "en",
            "locale": "en",
            "access_token": token,
            "store_code": store_code,
        },
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()


def fetch_publication_products(session, api: str, pub_id: int,
                               token: str) -> list[dict]:
    """Fetch all items for a Flipp publication."""
    resp = session.get(
        f"{api}/publication/{pub_id}/products",
        params={"display_type": "all", "locale": "en", "access_token": token},
        timeout=20,
    )
    resp.raise_for_status()
    return resp.json()


def fetch_stores(api: str, merchant: str, token: str, zip_code: str) -> list[dict]:
    """Flipp store locator — returns merchant_store_code per store."""
    resp = requests.get(
        f"{api}/stores/{merchant}",
        params={"access_token": token, "postal_code": zip_code},
        headers=_HEADERS,
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()


class FlippScraper(BaseScraper):
    """Weekly circular scraper for any Flipp-based grocer, driven by config."""

    retailer = "flipp"

    def __init__(self, store_id: str, config: dict):
        """
        Required config keys:
            flipp_merchant — Flipp merchant slug (e.g. "dollargeneral")
            flipp_token    — flyerkit access_token
        Optional:
            retailer       — retailer key for price records (set by the runner)
            flipp_host     — flyerkit API base (default dam.flippenterprise.net)
        """
        # BaseScraper.__init__ derives raw_dir from self.retailer, so the
        # per-instance retailer name must be set first.
        self.retailer = config.get("retailer") or self.retailer
        super().__init__(store_id, config)
        self.api = (config.get("flipp_host") or DEFAULT_FLIPP_API).rstrip("/")
        self.merchant = config["flipp_merchant"]
        self.token = config["flipp_token"]
        self.session = requests.Session()
        self.session.headers.update(_HEADERS)

    def authenticate(self) -> None:
        # Token-in-query-string API; nothing to do.
        pass

    def scrape_circular(self, pub_name: Optional[str] = None) -> list[dict]:
        """Scrape the current circular (first publication, or one matching pub_name)."""
        pubs = fetch_publications(self.session, self.api, self.merchant,
                                  self.token, self.store_id)
        pub_id = None
        if pub_name:
            for pub in pubs:
                if pub_name.lower() in (pub.get("name") or "").lower():
                    pub_id = pub["id"]
                    break
        elif pubs:
            pub_id = pubs[0]["id"]
        if not pub_id:
            raise RuntimeError(
                f"[{self.retailer}] No Flipp publication found for store "
                f"{self.store_id} (merchant {self.merchant})."
            )

        raw_items = fetch_publication_products(self.session, self.api, pub_id,
                                               self.token)
        self.save_raw(raw_items, f"circular_pub{pub_id}")

        results = []
        for item in raw_items:
            if item.get("item_type") != 1:  # 5 = flyer page/section header
                continue
            name = (item.get("name") or "").strip()
            if not name:
                continue

            price_str = (item.get("price_text") or "").strip()
            try:
                price = float(price_str) if price_str else 0.0
            except ValueError:
                price = 0.0

            unit = (item.get("post_price_text") or "").strip() or None
            pre = (item.get("pre_price_text") or "").strip() or None
            deal = (item.get("sale_story") or "").strip() or None
            original_price = item.get("original_price")
            categories = item.get("categories") or []

            results.append(
                self.normalize_price(
                    product_id=str(item["id"]),
                    name=name,
                    price=price,
                    unit=unit,
                    url=item.get("web_commission_url") or item.get("item_web_url") or "",
                    extra={
                        "deal_text": deal,
                        "pre_price_text": pre,
                        "original_price": float(original_price) if original_price else None,
                        "description": (item.get("description") or "").strip() or None,
                        "category": categories[0] if categories else None,
                        "valid_from": item.get("valid_from"),
                        "valid_to": item.get("valid_to"),
                        "image_url": item.get("image_url"),
                    },
                )
            )

        logger.info(
            f"[{self.retailer}] Scraped {len(results)} items from Flipp pub "
            f"{pub_id} (store {self.store_id})."
        )
        return results

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
