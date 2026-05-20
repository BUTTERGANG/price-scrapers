"""Health, status, and data freshness endpoints."""
from fastapi import APIRouter
from fastapi.responses import JSONResponse

from utils import (
    get_conn,
    release_conn,
    get_db_stats,
    get_data_freshness,
    get_store_status,
    get_scraper_stats,
)

router = APIRouter(tags=["health"])


@router.get("/api/status")
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


@router.get("/api/health")
def api_health():
    """Comprehensive health check — DB, scraper status, and data freshness."""
    conn = None
    try:
        conn = get_conn()
        stats = get_db_stats(conn)
        freshness = get_data_freshness(conn)
        store_status = get_store_status(conn)

        configured = set()
        for f in freshness:
            configured.add(f.get("retailer", ""))
        for s in store_status:
            configured.add(s["retailer"])
        configured.discard("")

        stale = []
        healthy = []
        never_run = []
        for f in freshness:
            retailer = f.get("retailer", "")
            hours = f.get("hours_ago")
            if hours is None:
                never_run.append(retailer)
            elif hours > 24:
                stale.append({"retailer": retailer, "hours_ago": hours})
            else:
                healthy.append(retailer)

        errors = [
            s for s in store_status
            if s.get("status") == "error" and s.get("error")
        ]

        overall = "ok"
        if stale or errors:
            overall = "degraded"
        if not healthy and not stale:
            overall = "down"

        return {
            "status": overall,
            "db": stats,
            "scrapers": {
                "total": len(configured),
                "healthy": len(healthy),
                "stale": stale,
                "never_run": never_run,
                "errors": [
                    {"retailer": e["retailer"], "error": e["error"]}
                    for e in errors
                ],
            },
            "freshness": freshness,
        }
    except Exception as e:
        return JSONResponse(
            status_code=503,
            content={"status": "error", "detail": str(e)},
        )
    finally:
        release_conn(conn)


@router.get("/api/scraper-stats")
def scraper_stats(days: int = 30):
    """Per-retailer performance metrics: success rate, avg records, avg duration."""
    conn = get_conn()
    try:
        stats = get_scraper_stats(conn, days=days)
        return {"stats": stats, "days": days, "count": len(stats)}
    finally:
        release_conn(conn)


@router.get("/api/freshness")
def freshness():
    conn = get_conn()
    try:
        return {"freshness": get_data_freshness(conn)}
    finally:
        release_conn(conn)
