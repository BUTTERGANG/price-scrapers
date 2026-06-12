"""Deal discovery endpoints."""
from fastapi import APIRouter, Query

from utils import get_conn, release_conn, find_active_deals, get_data_freshness

router = APIRouter(tags=["deals"])


@router.get("/api/deals")
def get_deals(
    min_pct: float = Query(10.0, ge=0.0),
    limit: int = Query(500, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    max_age_days: int = Query(7, ge=1, le=365),
):
    conn = get_conn()
    try:
        deals = find_active_deals(conn, min_pct, limit=limit, offset=offset, max_age_days=max_age_days)
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
