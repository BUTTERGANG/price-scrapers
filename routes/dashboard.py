"""Dashboard and department endpoints."""
from fastapi import APIRouter, Query

from utils import (
    get_conn,
    release_conn,
    get_dashboard_summary,
    get_market_pulse,
    get_scrape_activity,
    get_departments,
    get_department_products,
)

router = APIRouter(tags=["dashboard"])


@router.get("/api/dashboard")
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


@router.get("/api/departments")
def departments():
    conn = get_conn()
    try:
        return {"departments": get_departments(conn)}
    finally:
        release_conn(conn)


@router.get("/api/departments/{dept}")
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
