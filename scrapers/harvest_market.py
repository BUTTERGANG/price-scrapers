"""Niemann Harvest Market scraper — Webstop platform, weekly circular via SSR HTML.

==============================================================================
ARCHITECTURE OVERVIEW
==============================================================================

Harvest Market (Niemann Foods) uses the Webstop grocery platform hosted at
www2.goharvestmarket.com / www3.goharvestmarket.com. No Playwright, no auth,
no bot detection — plain requests works fine.

All scraping logic lives in the generic WebstopScraper (scrapers/webstop.py);
this subclass just pins the Harvest Market host and retailer ID.

WEEKLY CIRCULAR (scrape_circular)
----------------------------------------------------------------------
Three-step flow:

Step 1 — Set store:
  GET https://www3.goharvestmarket.com/retailers/3328/stores/{store_id}/choose_store
      ?filter=circulars&url=https://www2.goharvestmarket.com/circulars/
  → Sets session cookies: 3328_store_id, 3328_store_number
  → Redirects to the current circular URL (contains the circular code, e.g. "260624_HM")

Step 2 — Discover pagination links (/circulars/Page/{n}/...), fetch each page.
  Items are server-side rendered inside <article> modals — no JS required.
  NOTE (June 2026): Webstop deprecated the /department/{dept}/ filter URLs —
  they all return page-1 content now, which silently shrank scrapes to ~13
  items until pagination-based scraping replaced the department loop.

Step 3 — Parse item modals (see WebstopScraper._scrape_page).

==============================================================================
STORE IDs
==============================================================================

Webstop store IDs for Harvest Market (retailer 3328):
  Store 17 / store_number 584 — 2140 E 116th St, Carmel, IN 46032

Run HarvestMarketScraper.find_store_id(zip_code="46032") to list nearby stores.

There is one shared weekly circular across all Harvest Market locations.
"""
import logging

from .webstop import WebstopScraper, find_webstop_stores

logger = logging.getLogger(__name__)

BASE_URL = "https://www2.goharvestmarket.com"
API_HOST = "https://www3.goharvestmarket.com"
RETAILER_ID = "3328"

class HarvestMarketScraper(WebstopScraper):
    """Scraper for Niemann Harvest Market weekly circular (Webstop platform)."""

    retailer = "harvest_market"
    host = "goharvestmarket.com"
    retailer_id = RETAILER_ID

    @classmethod
    def find_store_id(cls, zip_code: str = "46032") -> list[dict]:
        """
        Search for Harvest Market stores near a ZIP code.
        Returns list of dicts with id, name, address, city_state_zip, distance.

        Example:
            stores = HarvestMarketScraper.find_store_id(zip_code="46032")
            for s in stores:
                print(s["id"], s["address"])
        """
        stores = find_webstop_stores(cls.host, cls.retailer_id, zip_code)
        for s in stores:
            s["name"] = s["name"] or "Harvest Market"
        return stores
