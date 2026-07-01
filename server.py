"""FastAPI backend — REST API for the grocery price dashboard."""
import logging
import os
import threading
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

load_dotenv()

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(name)s  %(message)s")
logger = logging.getLogger(__name__)

from utils import init_db, cleanup_old_prices, reap_stale_runs, get_conn, release_conn


# ---------------------------------------------------------------------------
# Background scheduler — auto-scrape every 6 hours + daily cleanup
# ---------------------------------------------------------------------------
def _scheduled_scrape():
    import json
    with app.state.scrape_lock:
        if app.state.scrape_running:
            logger.info("Scheduled scrape skipped — another scrape is already running")
            return
        app.state.scrape_running = True
    try:
        from runner import run_retailers
        stores = json.loads(Path("config/stores.json").read_text()).get("stores", {})
        items = json.loads(Path("config/items.json").read_text()).get("queries", [])
        logger.info("Scheduled scrape starting...")
        run_retailers([], stores, items, workers=4)
        logger.info("Scheduled scrape completed.")
    except Exception as exc:
        logger.error(f"Scheduled scrape failed: {exc}")
    finally:
        with app.state.scrape_lock:
            app.state.scrape_running = False


def _scheduled_cleanup():
    conn = None
    try:
        conn = get_conn()
        result = cleanup_old_prices(conn, days_to_keep=90)
        logger.info(f"Scheduled cleanup: {result}")
    except Exception as exc:
        logger.error(f"Scheduled cleanup failed: {exc}")
    finally:
        release_conn(conn)


def _start_scheduler():
    """Start the background scheduler. Returns the scheduler or None on failure."""
    try:
        from apscheduler.schedulers.background import BackgroundScheduler

        scheduler = BackgroundScheduler(timezone="UTC")
        # Scrape every 6 hours, first run 5 minutes after startup
        scheduler.add_job(
            _scheduled_scrape,
            "interval",
            hours=6,
            next_run_time=datetime.now(timezone.utc) + timedelta(minutes=5),
            id="auto_scrape",
            replace_existing=True,
        )
        # Clean up old data daily at 03:00 UTC
        scheduler.add_job(
            _scheduled_cleanup,
            "cron",
            hour=3,
            minute=0,
            id="daily_cleanup",
            replace_existing=True,
        )
        scheduler.start()
        logger.info("Background scheduler started (scrape every 6h, cleanup daily at 03:00 UTC).")
        return scheduler
    except Exception as exc:
        logger.warning(f"Could not start background scheduler: {exc}")
        return None


# ---------------------------------------------------------------------------
# App setup — lifespan runs only in the serving process, so the scheduler is
# never duplicated by uvicorn's reload supervisor.
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    # Clear zombie 'running' runs left behind by a previous crash/redeploy.
    conn = None
    try:
        conn = get_conn()
        reap_stale_runs(conn, max_age_hours=6)
    except Exception as exc:
        logger.warning(f"Could not reap stale runs at startup: {exc}")
    finally:
        release_conn(conn)
    scheduler = _start_scheduler()
    yield
    if scheduler:
        scheduler.shutdown(wait=False)


app = FastAPI(title="Grocery Price Scrapers API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Global exception handlers — consistent JSON error responses
# ---------------------------------------------------------------------------
@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": True,
            "status_code": exc.status_code,
            "detail": exc.detail,
            "path": str(request.url.path),
        },
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.exception(f"Unhandled error on {request.method} {request.url.path}: {exc}")
    return JSONResponse(
        status_code=500,
        content={
            "error": True,
            "status_code": 500,
            "detail": "Internal server error",
            "path": str(request.url.path),
        },
    )


# ---------------------------------------------------------------------------
# Scraper state — shared with routes/scraper.py via app.state
# ---------------------------------------------------------------------------
app.state.scrape_lock = threading.Lock()
app.state.scrape_running = False

# ---------------------------------------------------------------------------
# Mount route modules
# ---------------------------------------------------------------------------
from routes import (
    health_router,
    stores_router,
    products_router,
    deals_router,
    watchlist_router,
    scraper_router,
    dashboard_router,
)

app.include_router(health_router)
app.include_router(stores_router)
app.include_router(products_router)
app.include_router(deals_router)
app.include_router(watchlist_router)
app.include_router(scraper_router)
app.include_router(dashboard_router)

# ---------------------------------------------------------------------------
# Serve frontend static build
# ---------------------------------------------------------------------------
if os.path.exists("frontend/dist"):
    app.mount("/", StaticFiles(directory="frontend/dist", html=True), name="static")

# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # Hot reload only during development — deployments run a single process.
    uvicorn.run(
        "server:app",
        host="0.0.0.0",
        port=8000,
        reload=not os.environ.get("REPLIT_DEPLOYMENT"),
    )
