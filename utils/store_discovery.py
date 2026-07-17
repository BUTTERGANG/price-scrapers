"""Store discovery — find nearby store IDs for supported retailers.

Wraps each scraper's find_store*/find_stores classmethod and normalizes the
heterogeneous results to a common shape ready to append to stores.json:

    {"store_id": "...", "name": "...", "address": "...", "distance": "...",
     ...extra scraper-specific fields (store_slug, store_number, ...)}

All discovery calls hit live retailer APIs.
"""
import logging
import os

import requests

logger = logging.getLogger(__name__)


def _join_address(*parts: str) -> str:
    return ", ".join(p for p in (p.strip() for p in parts if p) if p)


def _flipp_stores(api: str, merchant: str, token: str, zip_code: str,
                  display_name: str) -> list[dict]:
    """Flipp flyerkit store locator — returns merchant_store_code per store.

    merchant_store_code is exactly the store_id the Flipp-based scrapers use
    (e.g. Aldi "444-075", Meijer "290"). No bot detection on this endpoint.
    """
    resp = requests.get(
        f"{api}/stores/{merchant}",
        params={"access_token": token, "postal_code": zip_code},
        headers={"User-Agent": "Mozilla/5.0"},
        timeout=15,
    )
    resp.raise_for_status()
    return [
        {
            "store_id": s.get("merchant_store_code", ""),
            "name": f"{display_name} — {s.get('name', '')}".strip(" —"),
            "address": _join_address(s.get("address", ""), s.get("city", ""),
                                     s.get("province", ""), s.get("postal_code", "")),
            "distance": "",
        }
        for s in resp.json()
        if s.get("merchant_store_code")
    ]


def _discover_aldi(zip_code: str) -> list[dict]:
    # Aldi's own locator API (api.aldi.us) is gone; Flipp covers it.
    from scrapers import aldi
    return _flipp_stores(aldi.FLIPP_API, aldi.FLIPP_RETAILER, aldi.FLIPP_TOKEN,
                         zip_code, "Aldi")


def _discover_meijer(zip_code: str) -> list[dict]:
    from scrapers import meijer
    return _flipp_stores(meijer.FLIPP_API, meijer.FLIPP_RETAILER,
                         meijer.FLIPP_TOKEN, zip_code, "Meijer")


def _discover_fresh_thyme(zip_code: str) -> list[dict]:
    from scrapers import fresh_thyme
    return _flipp_stores(fresh_thyme.FLIPP_API, fresh_thyme.FLIPP_RETAILER,
                         fresh_thyme.FLIPP_TOKEN, zip_code, "Fresh Thyme")


def _discover_target(zip_code: str) -> list[dict]:
    from scrapers.target import TargetScraper
    try:
        results = TargetScraper.find_store_id(zip_code=zip_code)
    except Exception as exc:
        raise LookupError(
            "Target's store locator API is currently unavailable "
            f"({exc}). Find your store ID at target.com/store-locator — it's "
            "the number in the store page URL — and add it manually."
        )
    return [
        {
            "store_id": str(s["storeId"]),
            "name": s.get("name") or "Target",
            "address": _join_address(s.get("address", ""), s.get("city", ""),
                                     s.get("state", ""), s.get("zip", "")),
            "distance": s.get("distance", ""),
        }
        for s in results
    ]


def _discover_harvest_market(zip_code: str) -> list[dict]:
    from scrapers.harvest_market import HarvestMarketScraper
    return [
        {
            "store_id": s["id"],
            "name": s.get("name") or "Harvest Market",
            "address": _join_address(s.get("address", ""), s.get("city_state_zip", "")),
            "distance": s.get("distance", ""),
        }
        for s in HarvestMarketScraper.find_store_id(zip_code=zip_code)
        if s.get("id")
    ]


def _discover_giant_eagle(zip_code: str) -> list[dict]:
    from scrapers.giant_eagle import GiantEagleScraper
    return [
        {
            "store_id": str(s["code"]),
            "store_slug": s.get("slug", ""),
            "name": s.get("name") or "Giant Eagle",
            "address": _join_address(s.get("address", ""), s.get("city", ""),
                                     s.get("state", ""), s.get("zip", "")),
            "distance": s.get("distance", ""),
        }
        for s in GiantEagleScraper.find_store(zip_code=zip_code)
        if s.get("code")
    ]


def _discover_needlers(zip_code: str) -> list[dict]:
    # storebyweb has no ZIP filter — returns the full (small) chain list.
    from scrapers.needlers import NeedlersScraper
    return [
        {
            "store_id": s["id"],
            "store_number": str(s.get("number", "")),
            "name": s.get("name") or "Needler's Fresh Market",
            "address": _join_address(s.get("address", ""), s.get("city", ""),
                                     s.get("state", "")),
            "distance": "",
        }
        for s in NeedlersScraper.find_store_id()
    ]


def _discover_kroger(zip_code: str) -> list[dict]:
    """Kroger locationIds (8-char division+store). Requires OAuth credentials.

    The returned locationId works for both the product API and — in most
    divisions — the DACS weekly-ad endpoints, which use the same
    division(3)+store(5) format.
    """
    client_id = os.environ.get("KROGER_CLIENT_ID")
    client_secret = os.environ.get("KROGER_CLIENT_SECRET")
    if not (client_id and client_secret):
        raise LookupError(
            "Kroger discovery needs KROGER_CLIENT_ID and KROGER_CLIENT_SECRET "
            "environment variables (register free at developer.kroger.com)."
        )
    from scrapers.kroger import KrogerScraper
    return [
        {
            "store_id": s["store_id"],
            "name": s.get("name") or "Kroger",
            "address": _join_address(s.get("address", ""), s.get("city", ""),
                                     s.get("zip", "")),
            "distance": "",
        }
        for s in KrogerScraper.find_stores(
            zip_code, config={"client_id": client_id, "client_secret": client_secret}
        )
    ]


DISCOVERERS = {
    "aldi": _discover_aldi,
    "meijer": _discover_meijer,
    "fresh_thyme": _discover_fresh_thyme,
    "target": _discover_target,
    "harvest_market": _discover_harvest_market,
    "giant_eagle": _discover_giant_eagle,
    "needlers": _discover_needlers,
    "kroger": _discover_kroger,
}


def _platform_discoverer(retailer: str):
    """Discovery for config-only platform retailers (flipp/webstop entries).

    Platform credentials may live on the retailer entry or its first location.
    Returns a zip→results callable, or None if the entry isn't a platform one.
    """
    from utils.store_config import get_locations, load_stores

    cfg = load_stores().get(retailer)
    if not cfg or not cfg.get("platform"):
        return None
    locs = get_locations(cfg)
    src = {**cfg, **(locs[0] if locs else {})}

    if cfg["platform"] == "flipp" and src.get("flipp_merchant") and src.get("flipp_token"):
        from scrapers import flipp

        def _flipp(zip_code):
            api = (src.get("flipp_host") or flipp.DEFAULT_FLIPP_API).rstrip("/")
            return [
                {
                    "store_id": s.get("merchant_store_code", ""),
                    "name": f"{cfg.get('name', retailer)} — {s.get('name', '')}".strip(" —"),
                    "address": _join_address(s.get("address", ""), s.get("city", ""),
                                             s.get("province", ""), s.get("postal_code", "")),
                    "distance": "",
                }
                for s in flipp.fetch_stores(api, src["flipp_merchant"],
                                            src["flipp_token"], zip_code)
                if s.get("merchant_store_code")
            ]
        return _flipp

    if cfg["platform"] == "webstop" and src.get("webstop_host") and src.get("webstop_retailer_id"):
        from scrapers.webstop import find_webstop_stores

        def _webstop(zip_code):
            return [
                {
                    "store_id": s["id"],
                    "name": s.get("name") or cfg.get("name", retailer),
                    "address": _join_address(s.get("address", ""),
                                             s.get("city_state_zip", "")),
                    "distance": s.get("distance", ""),
                }
                for s in find_webstop_stores(src["webstop_host"],
                                             str(src["webstop_retailer_id"]), zip_code)
                if s.get("id")
            ]
        return _webstop

    return None


def discoverable_retailers() -> list[str]:
    """Retailers with a built-in discoverer, plus configured platform entries."""
    from utils.store_config import load_stores

    names = set(DISCOVERERS)
    try:
        for name, cfg in load_stores().items():
            if cfg.get("platform") and _platform_discoverer(name):
                names.add(name)
    except Exception as exc:
        logger.warning(f"Could not scan platform entries: {exc}")
    return sorted(names)


def discover(retailer: str, zip_code: str) -> list[dict]:
    """Find stores for `retailer` near `zip_code`. Raises on unsupported retailer."""
    fn = DISCOVERERS.get(retailer) or _platform_discoverer(retailer)
    if fn is None:
        raise LookupError(
            f"No store discovery for '{retailer}'. "
            f"Supported: {', '.join(discoverable_retailers())}"
        )
    return fn(zip_code)
