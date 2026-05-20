"""Scraper control and data cleanup endpoints."""
import logging
import threading

from fastapi import APIRouter, Query, HTTPException, Request
from fastapi.responses import JSONResponse

from utils import get_conn, release_conn, cleanup_old_prices

logger = logging.getLogger(__name__)

router = APIRouter(tags=["scraper"])


@router.post("/api/scrape")
def trigger_scrape(request: Request, retailers: list[str] = Query(default=[])):
    """Trigger a scrape run. Returns immediately; scrape runs in background."""
    import json
    from pathlib import Path

    scrape_lock: threading.Lock = request.app.state.scrape_lock

    with scrape_lock:
        if request.app.state.scrape_running:
            return JSONResponse(
                status_code=409,
                content={"error": "A scrape is already running. Please wait for it to finish."},
            )
        request.app.state.scrape_running = True

    stores = json.loads(Path("config/stores.json").read_text()).get("stores", {})
    items = json.loads(Path("config/items.json").read_text()).get("queries", [])

    from runner import run_retailers, available_retailers
    available = available_retailers(stores)

    to_run = retailers if retailers else []
    invalid = [r for r in to_run if r not in available]
    if invalid:
        with scrape_lock:
            request.app.state.scrape_running = False
        raise HTTPException(400, f"Unknown retailers: {invalid}. Available: {available}")

    app_ref = request.app

    def _bg():
        try:
            run_retailers(to_run, stores, items, workers=4)
        except Exception as e:
            logger.error(f"Background scrape failed: {e}")
        finally:
            with scrape_lock:
                app_ref.state.scrape_running = False

    thread = threading.Thread(target=_bg, daemon=True)
    try:
        thread.start()
    except Exception:
        with scrape_lock:
            request.app.state.scrape_running = False
        raise
    return {
        "message": "Scrape started",
        "retailers": to_run if to_run else available,
    }


@router.get("/api/scrape/status")
def scrape_status(request: Request):
    """Check if a scrape is currently running."""
    return {"running": request.app.state.scrape_running}


@router.post("/api/cleanup")
def trigger_cleanup(days_to_keep: int = Query(default=90, ge=30, le=730)):
    """Prune price records older than days_to_keep (default 90).

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
