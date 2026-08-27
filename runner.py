"""Scraper orchestration — runs retailer scrapers with DB logging.

Retailers are wired in declaratively via RETAILER_SPECS; store locations live
in config/stores.json. Adding a location to an already-supported retailer is a
config-only change. Adding a new retailer = one RetailerSpec entry plus the
scraper module (or, for Flipp/Webstop-platform grocers, a config entry with a
"platform" field and no code at all — see PLATFORM_SPECS).
"""
import importlib
import logging
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass

from utils import finish_run, insert_many, last_successful_run, start_run, get_conn, release_conn, check_price_alerts
from utils.notify import notify
from utils.store_config import get_locations
from utils.validate import check_count_drop, validate_results

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Retailer specs
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class RetailerSpec:
    key: str                       # registry base name; DB `retailer` run key
    module: str                    # scrapers.<module>
    cls: str                       # scraper class name in that module
    mode: str = "circular"         # "circular" → scrape_circular(); "search" → scrape_items(queries)
    config_key: str = ""           # stores.json entry to read (defaults to key)
    store_id_field: str = "store_id"  # location field used as the scraper's store_id
    auth_first: bool = False       # call authenticate() before a circular scrape
    config_fields: tuple = ()      # location fields copied into the scraper's config dict
    requires_env: str = ""         # skip registration unless this env var is set


RETAILER_SPECS: tuple[RetailerSpec, ...] = (
    RetailerSpec("kroger", "kroger", "KrogerScraper"),
    RetailerSpec("meijer", "meijer", "MeijerScraper"),
    RetailerSpec("fresh_thyme", "fresh_thyme", "FreshThymeScraper"),
    RetailerSpec("target", "target", "TargetScraper"),
    RetailerSpec("aldi", "aldi", "AldiScraper"),
    RetailerSpec("whole_foods", "whole_foods", "WholeFoodsScraper"),
    RetailerSpec("harvest_market", "harvest_market", "HarvestMarketScraper"),
    RetailerSpec("gfs", "gfs", "GFSScraper", auth_first=True, config_fields=("mp_number",)),
    RetailerSpec("giant_eagle", "giant_eagle", "GiantEagleScraper"),
    RetailerSpec("fresh_market", "fresh_market", "FreshMarketScraper"),
    RetailerSpec("needlers", "needlers", "NeedlersScraper", mode="search"),
    RetailerSpec("trader_joes", "trader_joes", "TraderJoesScraper", mode="search"),
    RetailerSpec(
        "needlers_circular", "needlers_circular", "NeedlersCircularScraper",
        config_key="needlers", store_id_field="store_number",
        requires_env="ANTHROPIC_API_KEY",
    ),
    # Blocked retailers keep their specs; their stores.json entries carry
    # "disabled": true. Flipping that flag re-enables them — no code change.
    RetailerSpec("walmart", "walmart", "WalmartScraper", mode="search"),
    RetailerSpec("costco", "costco", "CostcoScraper", mode="search"),
)

# Config-only retailers: a stores.json entry with a "platform" field (and the
# platform's required fields on each location) is picked up here without a
# RetailerSpec. Populated by scrapers/flipp.py and scrapers/webstop.py.
PLATFORM_SPECS: dict[str, dict] = {
    "flipp": {"module": "flipp", "cls": "FlippScraper",
              "config_fields": ("flipp_host", "flipp_token", "flipp_merchant")},
    "webstop": {"module": "webstop", "cls": "WebstopScraper",
                "config_fields": ("webstop_retailer_id", "webstop_host")},
}


@dataclass(frozen=True)
class RegistryEntry:
    key: str          # unique run key, e.g. "aldi" or "fresh_market_146th"
    retailer: str     # base retailer key, e.g. "fresh_market"
    store_id: str
    location: dict
    fn: "object"      # callable(items: list[str]) -> list[dict]


def _load_class(module: str, cls: str):
    return getattr(importlib.import_module(f"scrapers.{module}"), cls)


def _make_runner(module: str, cls_name: str, mode: str, store_id: str,
                 config: dict, auth_first: bool):
    def _run(items: list[str]) -> list[dict]:
        cls = _load_class(module, cls_name)
        scraper = cls(store_id=store_id, config=config)
        if auth_first:
            scraper.authenticate()
        if mode == "search":
            results, _failed = scraper.scrape_items(items)
            return results
        return scraper.scrape_circular()
    return _run


def _registry_key(base: str, location: dict, enabled_count: int) -> str:
    if enabled_count == 1 and not location.get("label"):
        return base
    return f"{base}_{location.get('label') or location.get('store_id')}"


def _build_registry(stores: dict) -> dict[str, RegistryEntry]:
    """Map run key → RegistryEntry for every enabled spec×location pair."""
    registry: dict[str, RegistryEntry] = {}

    def _register(base_key, module, cls, mode, store_id_field, auth_first,
                  config_fields, cfg):
        if cfg.get("disabled"):
            return
        locations = [l for l in get_locations(cfg) if not l.get("disabled")]
        for loc in locations:
            store_id = loc.get(store_id_field)
            if not store_id:
                continue
            key = _registry_key(base_key, loc, len(locations))
            # Config fields may live on the retailer entry (shared across
            # locations, e.g. a Flipp token) or on the location (overrides).
            config = {k: cfg[k] for k in config_fields if k in cfg}
            config.update({k: loc[k] for k in config_fields if k in loc})
            # Platform scrapers (flipp/webstop) label their price records with
            # this; retailer-specific scrapers ignore it.
            config["retailer"] = base_key
            registry[key] = RegistryEntry(
                key=key,
                retailer=base_key,
                store_id=str(store_id),
                location=loc,
                fn=_make_runner(module, cls, mode, str(store_id), config, auth_first),
            )

    for spec in RETAILER_SPECS:
        cfg = stores.get(spec.config_key or spec.key)
        if not cfg:
            continue
        if spec.requires_env and not os.environ.get(spec.requires_env):
            logger.info(f"[{spec.key}] Skipped — {spec.requires_env} not set.")
            continue
        _register(spec.key, spec.module, spec.cls, spec.mode,
                  spec.store_id_field, spec.auth_first, spec.config_fields, cfg)

    # Config-only platform retailers (no RetailerSpec needed)
    spec_keys = {s.config_key or s.key for s in RETAILER_SPECS}
    for name, cfg in stores.items():
        platform = cfg.get("platform")
        if not platform or name in spec_keys:
            continue
        pspec = PLATFORM_SPECS.get(platform)
        if not pspec:
            logger.warning(f"[{name}] Unknown platform '{platform}' — skipped.")
            continue
        _register(name, pspec["module"], pspec["cls"], "circular", "store_id",
                  False, pspec["config_fields"], cfg)

    return registry


def expected_stores(stores: dict) -> list[dict]:
    """Every spec×location pair including disabled ones — for /api/stores.

    Each item: {key, retailer, store_id, name, address, disabled, disabled_reason}.
    """
    out = []
    seen_cfg_keys = set()

    def _walk(base_key, store_id_field, cfg, skip_reason=None):
        retailer_disabled = cfg.get("disabled", False)
        locations = get_locations(cfg)
        enabled_count = len([l for l in locations if not l.get("disabled")])
        for loc in locations:
            disabled = retailer_disabled or loc.get("disabled", False) or bool(skip_reason)
            key = _registry_key(base_key, loc, max(enabled_count, 1))
            out.append({
                "key": key,
                "retailer": base_key,
                "store_id": str(loc.get(store_id_field) or loc.get("store_id") or ""),
                "name": loc.get("name") or cfg.get("name") or base_key,
                "address": loc.get("address"),
                "disabled": disabled,
                "disabled_reason": (
                    cfg.get("disabled_reason") or loc.get("disabled_reason") or skip_reason
                ),
            })

    for spec in RETAILER_SPECS:
        cfg = stores.get(spec.config_key or spec.key)
        if not cfg:
            continue
        seen_cfg_keys.add(spec.config_key or spec.key)
        skip = None
        if spec.requires_env and not os.environ.get(spec.requires_env):
            skip = f"{spec.requires_env} not set"
        _walk(spec.key, spec.store_id_field, cfg, skip_reason=skip)

    for name, cfg in stores.items():
        if cfg.get("platform") and name not in seen_cfg_keys:
            _walk(name, "store_id", cfg,
                  skip_reason=None if cfg.get("platform") in PLATFORM_SPECS
                  else f"unknown platform '{cfg.get('platform')}'")

    return out


# ---------------------------------------------------------------------------
# Single-scraper runner (used by both serial and parallel paths)
# ---------------------------------------------------------------------------

def _run_one(entry: RegistryEntry, items: list[str]) -> list[dict]:
    """Run one scraper, validate results, persist to DB. Returns saved records.

    Each call creates its own DB connection for thread safety.
    Never raises — exceptions are caught, logged, and recorded in the DB so
    other scrapers in a parallel run continue unaffected.
    """
    name = entry.key
    conn = get_conn()
    try:
        run_id = start_run(conn, name, entry.store_id, 0)
        logger.info(f"[{name}] Starting...")

        try:
            raw = entry.fn(items)
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

            # Check watchlist alerts for any price drops
            triggered: list[dict] = []
            for rec in valid:
                effective_price = rec.get("sale_price") or rec.get("price")
                if effective_price is None:
                    continue
                alert = check_price_alerts(
                    conn,
                    retailer=rec["retailer"],
                    product_id=rec["product_id"],
                    new_price=effective_price,
                    name=rec.get("name", ""),
                )
                if alert:
                    triggered.append(alert)
                    logger.info(
                        f"[{name}] Price alert triggered: {rec.get('name')} "
                        f"at ${effective_price} (target: ${alert['target_price']})"
                    )
            if triggered:
                logger.info(f"[{name}] {len(triggered)} price alert(s) triggered.")
                lines = [
                    f"• {a['name'] or a['product_id']} — ${a['triggered_price']} "
                    f"(target ${a['target_price']}) at {a['retailer']}"
                    for a in triggered
                ]
                notify("🔔 Price alert\n" + "\n".join(lines))

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
            notify(f"❌ Scraper failed: {name}\n{str(e)[:500]}")
            return []
    finally:
        release_conn(conn)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def available_retailers(stores: dict) -> list[str]:
    """Return sorted list of retailer run keys that can be run."""
    return sorted(_build_registry(stores).keys())


def run_retailers(
    names: list[str],
    stores: dict,
    items: list[str],
    workers: int = 1,
) -> list[dict]:
    """Run scrapers for the given retailer run keys and return all records.

    Args:
        names:   Run keys to run (from available_retailers()).
                 Pass an empty list to run all.
        stores:  The 'stores' dict from config/stores.json.
        items:   Search query list from config/items.json.
        workers: Number of scrapers to run in parallel (default 1 = serial).
                 Recommended: 4-5.
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
                executor.submit(_run_one, registry[name], items): name
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
            all_results.extend(_run_one(registry[name], items))

    return all_results


def run_all(stores: dict, items: list[str], workers: int = 1) -> list[dict]:
    """Run every registered retailer."""
    return run_retailers([], stores, items, workers=workers)
