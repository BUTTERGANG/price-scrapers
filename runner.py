"""Scraper orchestration — runs retailer scrapers with DB logging."""
import inspect
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional

from utils import finish_run, insert_many, last_successful_run, start_run, get_conn, release_conn
from utils.validate import check_count_drop, validate_results

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Retailer registry
# Each entry: (scraper_class_or_factory, store_config_key, mode)
# mode: "circular" = scrape_circular(), "search" = scrape_items()
# ---------------------------------------------------------------------------

def _build_registry(stores: dict) -> dict:
    """
    Returns a dict mapping retailer name → callable that returns list[dict].
    Only registers retailers whose store config is present.
    """
    from scrapers import (
        AldiScraper,
        FreshThymeScraper,
        GFSScraper,
        KrogerScraper,
        MeijerScraper,
        TargetScraper,
    )
    from scrapers.fresh_market import FreshMarketScraper
    from scrapers.giant_eagle import GiantEagleScraper
    from scrapers.harvest_market import HarvestMarketScraper
    from scrapers.whole_foods import WholeFoodsScraper
    from scrapers.needlers import NeedlersScraper

    registry: dict[str, callable] = {}

    # ── Kroger weekly ad (no OAuth needed) ──────────────────────────────────
    kroger_cfg = stores.get("kroger", {})
    for loc_id in kroger_cfg.get("weekly_ad_store_ids", []):
        key = f"kroger_weekly_{loc_id}"
        def _make_kroger(lid):
            def _kroger_circular():
                s = KrogerScraper(store_id=lid, config={})
                return s.scrape_circular(location_id=lid)
            return _kroger_circular
        registry[key] = _make_kroger(loc_id)

    # ── Walmart ─────────────────────────────────────────────────────────────
    # Disabled: PerimeterX bot detection blocks requests from datacenter IPs.
    # Re-enable when a residential proxy or alternative API is available.
    # if "walmart" in stores:
    #     def _walmart(items):
    #         s = WalmartScraper(store_id=stores["walmart"]["store_id"], config={})
    #         s.authenticate()
    #         return s.scrape_items(items)
    #     registry["walmart"] = _walmart

    # ── Meijer ──────────────────────────────────────────────────────────────
    if "meijer" in stores:
        def _meijer():
            s = MeijerScraper(store_id=stores["meijer"]["store_id"], config={})
            return s.scrape_circular()
        registry["meijer"] = _meijer

    # ── Fresh Thyme ──────────────────────────────────────────────────────────
    if "fresh_thyme" in stores:
        def _fresh_thyme():
            s = FreshThymeScraper(store_id=stores["fresh_thyme"]["store_id"], config={})
            return s.scrape_circular()
        registry["fresh_thyme"] = _fresh_thyme

    # ── Target ──────────────────────────────────────────────────────────────
    if "target" in stores:
        def _target():
            s = TargetScraper(store_id=stores["target"]["store_id"], config={})
            return s.scrape_circular()
        registry["target"] = _target

    # ── Aldi ────────────────────────────────────────────────────────────────
    if "aldi" in stores:
        def _aldi():
            s = AldiScraper(store_id=stores["aldi"]["store_id"], config={})
            return s.scrape_circular()
        registry["aldi"] = _aldi

    # ── Whole Foods ─────────────────────────────────────────────────────────
    if "whole_foods" in stores:
        def _whole_foods():
            s = WholeFoodsScraper(store_id=stores["whole_foods"]["store_id"], config={})
            return s.scrape_circular()
        registry["whole_foods"] = _whole_foods

    # ── Harvest Market ──────────────────────────────────────────────────────
    if "harvest_market" in stores:
        def _harvest_market():
            s = HarvestMarketScraper(store_id=stores["harvest_market"]["store_id"], config={})
            return s.scrape_circular()
        registry["harvest_market"] = _harvest_market

    # ── GFS Store ───────────────────────────────────────────────────────────
    if "gfs" in stores:
        def _gfs():
            cfg = stores["gfs"]
            s = GFSScraper(
                store_id=cfg["store_id"],
                config={"mp_number": cfg.get("mp_number", "")},
            )
            s.authenticate()
            return s.scrape_circular()
        registry["gfs"] = _gfs

    # ── Giant Eagle ─────────────────────────────────────────────────────────
    if "giant_eagle" in stores:
        def _giant_eagle():
            s = GiantEagleScraper(store_id=stores["giant_eagle"]["store_id"], config={})
            return s.scrape_circular()
        registry["giant_eagle"] = _giant_eagle

    # ── The Fresh Market ────────────────────────────────────────────────────
    if "fresh_market" in stores:
        store_ids = stores["fresh_market"].get("store_ids", {})
        for label, meta in store_ids.items():
            key = f"fresh_market_{label}"
            def _make_fresh_market(sid):
                def _fresh_market():
                    s = FreshMarketScraper(store_id=sid, config={})
                    return s.scrape_circular()
                return _fresh_market
            registry[key] = _make_fresh_market(meta["store_id"])

    # ── Costco ──────────────────────────────────────────────────────────────
    # Disabled: strict bot detection blocks all automated access.
    # Re-enable when a workaround is available.
    # if "costco" in stores:
    #     def _costco(items):
    #         s = CostcoScraper(store_id=stores["costco"]["store_id"], config={})
    #         s.authenticate()
    #         return s.scrape_items(items)
    #     registry["costco"] = _costco

    # ── Needlers ────────────────────────────────────────────────────────────
    if "needlers" in stores:
        def _needlers(items):
            s = NeedlersScraper(store_id=stores["needlers"]["store_id"], config={})
            results = []
            for query in items:
                results.extend(s.search_products(query))
            return results
        registry["needlers"] = _needlers

    return registry


# ---------------------------------------------------------------------------
# Single-scraper runner (used by both serial and parallel paths)
# ---------------------------------------------------------------------------

def _run_one(
    name: str,
    fn: callable,
    items: list[str],
) -> list[dict]:
    """Run one scraper, validate results, persist to DB. Returns saved records.

    Each call creates its own DB connection for thread safety.
    Never raises — exceptions are caught, logged, and recorded in the DB so
    other scrapers in a parallel run continue unaffected.
    """
    conn = get_conn()
    try:
        run_id = start_run(conn, name, "", 0)
        logger.info(f"[{name}] Starting...")

        try:
            sig = inspect.signature(fn)
            raw = fn(items) if sig.parameters else fn()
            # scrape_items() returns (results, failed_queries) — unpack if needed
            if isinstance(raw, tuple):
                raw = raw[0]
            raw = raw or []

            # Validate — drops hard errors, deduplicates, collects warnings
            valid, issues = validate_results(raw, name)
            for issue in issues:
                logger.warning(issue)

            # Item count drop check (compare against last successful run)
            last = last_successful_run(conn, name)
            last_count = last["records_saved"] if last else None
            drop_warn = check_count_drop(name, len(valid), last_count)
            if drop_warn:
                logger.warning(drop_warn)

            saved = insert_many(conn, valid)
            # queries_ok=1 represents the single scrape call succeeding
            finish_run(conn, run_id, 1, 0, saved, None)

            logger.info(
                f"[{name}] Done — {len(raw)} scraped, "
                f"{len(valid)} valid ({len(raw) - len(valid)} dropped), "
                f"{saved} saved to DB."
            )
            return valid

        except Exception as e:
            logger.error(f"[{name}] Failed: {e}")
            finish_run(conn, run_id, 0, 0, 0, str(e))
            return []
    finally:
        release_conn(conn)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def available_retailers(stores: dict) -> list[str]:
    """Return sorted list of retailer keys that can be run."""
    return sorted(_build_registry(stores).keys())


def run_retailers(
    names: list[str],
    stores: dict,
    items: list[str],
    workers: int = 1,
) -> list[dict]:
    """Run scrapers for the given retailer names and return all collected records.

    Args:
        names:   Retailer keys to run (from available_retailers()).
                 Pass an empty list to run all.
        stores:  The 'stores' dict from config/stores.json.
        items:   Search query list from config/items.json.
        workers: Number of scrapers to run in parallel (default 1 = serial).
                 Recommended: 4-5. Costco (Playwright) is safe to parallelize
                 since each scraper creates its own browser instance.
    """
    registry = _build_registry(stores)

    to_run = names if names else list(registry.keys())
    unknown = [n for n in to_run if n not in registry]
    if unknown:
        logger.warning(f"Unknown retailer(s): {unknown}. Available: {sorted(registry.keys())}")
        to_run = [n for n in to_run if n in registry]

    if not to_run:
        return []

    all_results: list[dict] = []

    if workers > 1:
        logger.info(
            f"Running {len(to_run)} retailer(s) with up to {workers} parallel workers."
        )
        with ThreadPoolExecutor(max_workers=min(workers, len(to_run))) as executor:
            futures = {
                executor.submit(_run_one, name, registry[name], items): name
                for name in to_run
            }
            for future in as_completed(futures):
                name = futures[future]
                try:
                    all_results.extend(future.result())
                except Exception as e:
                    # _run_one already catches and logs; this is a safety net
                    logger.error(f"[{name}] Unhandled exception in worker: {e}")
    else:
        for name in to_run:
            all_results.extend(_run_one(name, registry[name], items))

    return all_results


def run_all(stores: dict, items: list[str], workers: int = 1) -> list[dict]:
    """Run every registered retailer."""
    return run_retailers([], stores, items, workers=workers)
