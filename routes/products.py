"""Product search, comparison, UPC lookup, and price history endpoints."""
from fastapi import APIRouter, Query, HTTPException

from utils import (
    get_conn,
    release_conn,
    cheapest_per_retailer,
    cheapest_per_retailer_standard,
    price_history,
    find_by_upc,
    get_price_history_by_name,
    get_price_trend,
)

router = APIRouter(tags=["products"])


@router.get("/api/search")
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


@router.get("/api/compare")
def compare_prices(q: str = Query(..., min_length=2)):
    """Compare unit prices across retailers for a product."""
    conn = get_conn()
    try:
        results = cheapest_per_retailer(conn, q)
        def sort_key(item):
            sale = item.get("sale_price")
            return sale if sale is not None else (item.get("price") or 999999)
        results.sort(key=sort_key)
        return {"comparison": results, "count": len(results), "query": q}
    finally:
        release_conn(conn)


@router.get("/api/compare/standard")
def compare_prices_standard(q: str = Query(..., min_length=2)):
    """Compare standard unit prices across retailers for a product category.

    Returns results grouped by standard_unit (e.g., all milk compared per
    gallon, all eggs per dozen) so prices are truly like-for-like.
    """
    conn = get_conn()
    try:
        result = cheapest_per_retailer_standard(conn, q)
        return {"query": q, **result}
    finally:
        release_conn(conn)


@router.get("/api/upc/{upc}")
def lookup_upc(upc: str):
    conn = get_conn()
    try:
        results = find_by_upc(conn, upc)
        return {"results": results, "count": len(results), "upc": upc}
    finally:
        release_conn(conn)


@router.get("/api/history")
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


@router.get("/api/trends")
def trends(
    q: str = Query(..., min_length=2),
    limit: int = Query(500, ge=1, le=2000),
    since: str = Query(None),
):
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
