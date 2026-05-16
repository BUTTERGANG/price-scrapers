"""FastAPI backend — REST API for the grocery price dashboard."""
import json
import logging
import os
import threading
from pathlib import Path

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, Query, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

load_dotenv()

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(name)s  %(message)s")

# ---------------------------------------------------------------------------
# Config loading — fail with a clear message if a required file is missing
# ---------------------------------------------------------------------------

def _load_config(path: str) -> dict:
    p = Path(path)
    if not p.exists():
        raise RuntimeError(
            f"Required config file not found: {path}. "
            "Copy the example from config/ and fill in your store IDs."
        )
    try:
        return json.loads(p.read_text())
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Config file {path} contains invalid JSON: {exc}") from exc


from utils import (
    get_conn,
    release_conn,
    init_db,
    find_active_deals,
    cheapest_per_retailer,
    price_history,
    find_by_upc,
    get_store_status,
    get_db_stats,
    get_price_history_by_name,
    get_dashboard_summary,
    get_market_pulse,
    get_scrape_activity,
    get_departments,
    get_department_products,
    get_price_trend,
    get_store_analytics,
    get_data_freshness,
    get_watchlist_prices,
    cleanup_old_prices,
)

logger = logging.getLogger(__name__)

app = FastAPI(title="Grocery Price Scrapers API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

STORES = _load_config("config/stores.json")
ITEMS = _load_config("config/items.json")

# Initialize DB schema once at startup
init_db()

# Scrape concurrency guard — prevents multiple simultaneous scrape runs
_scrape_lock = threading.Lock()
_scrape_running = False


# ---------------------------------------------------------------------------
# Background scheduler — auto-scrape every 6 hours + daily cleanup
# ---------------------------------------------------------------------------

def _scheduled_scrape():
    """Auto-scrape all configured retailers every 6 hours."""
    global _scrape_running
    with _scrape_lock:
        if _scrape_running:
            logger.info("Scheduled scrape skipped — another scrape is already running")
            return
        _scrape_running = True
    try:
        from runner import run_retailers
        stores = STORES.get("stores", {})
        items = ITEMS.get("queries", [])
        logger.info("Scheduled scrape starting...")
        run_retailers([], stores, items, workers=4)
        logger.info("Scheduled scrape completed.")
    except Exception as exc:
        logger.error(f"Scheduled scrape failed: {exc}")
    finally:
        with _scrape_lock:
            _scrape_running = False


def _scheduled_cleanup():
    """Daily cleanup: prune price records older than 90 days (keeps monthly samples)."""
    conn = None
    try:
        conn = get_conn()
        result = cleanup_old_prices(conn, days_to_keep=90)
        logger.info(f"Scheduled cleanup: {result}")
    except Exception as exc:
        logger.error(f"Scheduled cleanup failed: {exc}")
    finally:
        release_conn(conn)


try:
    from apscheduler.schedulers.background import BackgroundScheduler
    import atexit

    _scheduler = BackgroundScheduler(timezone="UTC")
    # Scrape every 6 hours, first run 5 minutes after startup
    _scheduler.add_job(
        _scheduled_scrape,
        "interval",
        hours=6,
        id="auto_scrape",
        replace_existing=True,
    )
    # Clean up old data daily at 03:00 UTC
    _scheduler.add_job(
        _scheduled_cleanup,
        "cron",
        hour=3,
        minute=0,
        id="daily_cleanup",
        replace_existing=True,
    )
    _scheduler.start()
    atexit.register(lambda: _scheduler.shutdown(wait=False))
    logger.info("Background scheduler started (scrape every 6h, cleanup daily at 03:00 UTC).")
except Exception as _sched_err:
    logger.warning(f"Could not start background scheduler: {_sched_err}")


# ---------------------------------------------------------------------------
# Health / status
# ---------------------------------------------------------------------------

@app.get("/api/status")
def api_status():
    """Health check with DB statistics."""
    conn = None
    try:
        conn = get_conn()
        stats = get_db_stats(conn)
        return {"status": "ok", "db": stats}
    except Exception as e:
        return JSONResponse(
            status_code=503,
            content={"status": "error", "detail": str(e)},
        )
    finally:
        release_conn(conn)


# ---------------------------------------------------------------------------
# Stores
# ---------------------------------------------------------------------------

@app.get("/api/stores")
def get_stores():
    """Return store run status from the DB (no telegram_bot dependency)."""
    conn = get_conn()
    try:
        runs = get_store_status(conn)
        # Also include configured stores that may not have run yet
        configured = list(STORES.get("stores", {}).keys())
        run_map = {r["retailer"]: r for r in runs}
        result = []
        for name in configured:
            if name in run_map:
                result.append(run_map[name])
            else:
                result.append({
                    "retailer": name,
                    "status": "never_run",
                    "records_saved": 0,
                    "started_at": None,
                    "finished_at": None,
                    "error": None,
                })
        # Add any retailers in DB not in config
        for r in runs:
            if r["retailer"] not in configured:
                result.append(r)
        return {"stores": result}
    finally:
        release_conn(conn)


# ---------------------------------------------------------------------------
# Deals
# ---------------------------------------------------------------------------

@app.get("/api/deals")
def get_deals(
    min_pct: float = Query(10.0, ge=0.0),
    limit: int = Query(500, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    max_age_days: int = Query(7, ge=1, le=365),
):
    conn = get_conn()
    try:
        deals = find_active_deals(conn, min_pct, limit=limit, offset=offset, max_age_days=max_age_days)
        # Include freshness metadata so the UI can warn when data is stale
        freshness = get_data_freshness(conn)
        stale = [f for f in freshness if f.get("hours_ago") is not None and f["hours_ago"] > 24]
        latest_scrape = max((f["latest_scrape"] for f in freshness if f.get("latest_scrape")), default=None) if freshness else None
        return {
            "deals": deals,
            "count": len(deals),
            "offset": offset,
            "limit": limit,
            "max_age_days": max_age_days,
            "stale_retailers": [s["retailer"] for s in stale],
            "latest_scrape": latest_scrape,
        }
    finally:
        release_conn(conn)


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------

@app.get("/api/search")
def search_items(
    q: str = Query(..., min_length=2),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    conn = get_conn()
    try:
        results = cheapest_per_retailer(conn, q, limit=limit, offset=offset)
        return {"results": results, "count": len(results), "query": q, "offset": offset, "limit": limit}
    finally:
        release_conn(conn)


# ---------------------------------------------------------------------------
# Price history
# ---------------------------------------------------------------------------

@app.get("/api/history")
def get_history(
    q: str = Query(None, min_length=2),
    retailer: str = Query(None),
    product_id: str = Query(None),
    limit: int = Query(100, ge=1, le=500),
    since: str = Query(None, description="ISO date string, e.g. 2026-01-01"),
):
    """Get price history — either by name search or by specific product."""
    if since:
        try:
            __import__("datetime").date.fromisoformat(since)
        except ValueError:
            raise HTTPException(400, f"Invalid 'since' date: {since!r}. Use ISO format e.g. 2026-01-01")
    conn = get_conn()
    try:
        if retailer and product_id:
            results = price_history(conn, retailer, product_id, limit)
        elif q:
            results = get_price_history_by_name(conn, q, limit, since=since)
        else:
            raise HTTPException(400, "Provide either ?q=<name> or ?retailer=&product_id=")
        return {"history": results, "count": len(results)}
    finally:
        release_conn(conn)


# ---------------------------------------------------------------------------
# Compare (unit price comparison)
# ---------------------------------------------------------------------------

@app.get("/api/compare")
def compare_prices(q: str = Query(..., min_length=2)):
    """Compare unit prices across retailers for a product."""
    conn = get_conn()
    try:
        results = cheapest_per_retailer(conn, q)
        # Sort by effective price (what you actually pay).
        # unit_price_normalized is surfaced in the UI as context but must not
        # drive sort order — unit prices use different canonical units (fl_oz,
        # lb, ct) and are not cross-comparable between products.
        def sort_key(item):
            sale = item.get("sale_price")
            return sale if sale is not None else (item.get("price") or 999999)
        results.sort(key=sort_key)
        return {"comparison": results, "count": len(results), "query": q}
    finally:
        release_conn(conn)


# ---------------------------------------------------------------------------
# UPC lookup
# ---------------------------------------------------------------------------

@app.get("/api/upc/{upc}")
def lookup_upc(upc: str):
    conn = get_conn()
    try:
        results = find_by_upc(conn, upc)
        return {"results": results, "count": len(results), "upc": upc}
    finally:
        release_conn(conn)


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------

@app.get("/api/dashboard")
def dashboard():
    """Aggregate dashboard stats, market pulse, and scrape activity."""
    conn = get_conn()
    try:
        summary = get_dashboard_summary(conn)
        pulse = get_market_pulse(conn, limit=8)
        activity = get_scrape_activity(conn, days=14)
        return {"summary": summary, "pulse": pulse, "activity": activity}
    finally:
        release_conn(conn)


# ---------------------------------------------------------------------------
# Departments
# ---------------------------------------------------------------------------

@app.get("/api/departments")
def departments():
    conn = get_conn()
    try:
        return {"departments": get_departments(conn)}
    finally:
        release_conn(conn)


@app.get("/api/departments/{dept}")
def department_products(
    dept: str,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    retailer: str = Query(None),
):
    conn = get_conn()
    try:
        products = get_department_products(conn, dept, limit, offset, retailer)
        return {"department": dept, "products": products, "count": len(products)}
    finally:
        release_conn(conn)


# ---------------------------------------------------------------------------
# Price trends (for charting)
# ---------------------------------------------------------------------------

@app.get("/api/trends")
def trends(q: str = Query(..., min_length=2), limit: int = Query(500, ge=1, le=2000), since: str = Query(None)):
    if since:
        try:
            __import__("datetime").date.fromisoformat(since)
        except ValueError:
            raise HTTPException(400, f"Invalid 'since' date: {since!r}. Use ISO format e.g. 2026-01-01")
    conn = get_conn()
    try:
        data = get_price_trend(conn, q, limit, since=since)
        return {"trends": data, "count": len(data), "query": q}
    finally:
        release_conn(conn)


# ---------------------------------------------------------------------------
# Store analytics
# ---------------------------------------------------------------------------

@app.get("/api/stores/{retailer}/analytics")
def store_analytics(retailer: str):
    conn = get_conn()
    try:
        return get_store_analytics(conn, retailer)
    finally:
        release_conn(conn)


# ---------------------------------------------------------------------------
# Data freshness
# ---------------------------------------------------------------------------

@app.get("/api/freshness")
def freshness():
    conn = get_conn()
    try:
        return {"freshness": get_data_freshness(conn)}
    finally:
        release_conn(conn)


# ---------------------------------------------------------------------------
# Watchlist — batch live price fetch
# ---------------------------------------------------------------------------

@app.post("/api/watchlist/prices")
def watchlist_prices(items: list[dict]):
    """
    Fetch current prices for a list of watchlist items.
    Body: [{"retailer": "kroger", "product_id": "abc123"}, ...]
    Returns the most recent price record per item.
    """
    if not items:
        return {"prices": []}
    # Validate each item has required fields
    for item in items:
        if not isinstance(item, dict) or "retailer" not in item or "product_id" not in item:
            raise HTTPException(400, "Each item must have 'retailer' and 'product_id'")
    conn = get_conn()
    try:
        prices = get_watchlist_prices(conn, items)
        return {"prices": prices}
    finally:
        release_conn(conn)


# ---------------------------------------------------------------------------
# Scraper trigger (runs in background thread)
# ---------------------------------------------------------------------------

@app.post("/api/scrape")
def trigger_scrape(retailers: list[str] = Query(default=[])):
    """Trigger a scrape run. Returns immediately; scrape runs in background."""
    global _scrape_running
    from runner import run_retailers, available_retailers

    # Prevent concurrent scrape runs
    with _scrape_lock:
        if _scrape_running:
            return JSONResponse(
                status_code=409,
                content={"error": "A scrape is already running. Please wait for it to finish."},
            )
        _scrape_running = True

    stores = STORES.get("stores", {})
    items = ITEMS.get("queries", [])
    available = available_retailers(stores)

    to_run = retailers if retailers else []
    invalid = [r for r in to_run if r not in available]
    if invalid:
        with _scrape_lock:
            _scrape_running = False
        raise HTTPException(400, f"Unknown retailers: {invalid}. Available: {available}")

    def _bg():
        global _scrape_running
        try:
            run_retailers(to_run, stores, items, workers=4)
        except Exception as e:
            logger.error(f"Background scrape failed: {e}")
        finally:
            _scrape_running = False

    thread = threading.Thread(target=_bg, daemon=True)
    try:
        thread.start()
    except Exception:
        with _scrape_lock:
            _scrape_running = False
        raise
    return {
        "message": "Scrape started",
        "retailers": to_run if to_run else available,
    }


@app.get("/api/scrape/status")
def scrape_status():
    """Check if a scrape is currently running."""
    return {"running": _scrape_running}


# ---------------------------------------------------------------------------
# Data cleanup (prune old price records, keep monthly history)
# ---------------------------------------------------------------------------

@app.post("/api/cleanup")
def trigger_cleanup(days_to_keep: int = Query(default=90, ge=30, le=730)):
    """
    Prune price records older than days_to_keep (default 90).
    Keeps one record per (retailer, product_id, month) for long-term trends.
    """
    conn = None
    try:
        conn = get_conn()
        result = cleanup_old_prices(conn, days_to_keep=days_to_keep)
        return {"status": "ok", **result}
    except Exception as exc:
        raise HTTPException(500, str(exc))
    finally:
        release_conn(conn)


# ---------------------------------------------------------------------------
# Serve frontend static build
# ---------------------------------------------------------------------------

if os.path.exists("frontend/dist"):
    app.mount("/", StaticFiles(directory="frontend/dist", html=True), name="static")


if __name__ == "__main__":
    uvicorn.run(
        "server:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
    )
