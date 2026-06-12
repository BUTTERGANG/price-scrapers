"""Watchlist and price alert endpoints."""
from fastapi import APIRouter, Query, HTTPException

from utils import (
    get_conn,
    release_conn,
    get_watchlist_prices,
    add_watchlist_item,
    remove_watchlist_item,
    get_watchlist,
    get_active_alerts,
    acknowledge_alert,
)

router = APIRouter(tags=["watchlist"])


@router.post("/api/watchlist/prices")
def watchlist_prices(items: list[dict]):
    """Fetch current prices for a list of watchlist items.

    Body: [{"retailer": "kroger", "product_id": "abc123"}, ...]
    Returns the most recent price record per item.
    """
    if not items:
        return {"prices": []}
    for item in items:
        if not isinstance(item, dict) or "retailer" not in item or "product_id" not in item:
            raise HTTPException(400, "Each item must have 'retailer' and 'product_id'")
    conn = get_conn()
    try:
        prices = get_watchlist_prices(conn, items)
        return {"prices": prices}
    finally:
        release_conn(conn)


@router.get("/api/watchlist")
def watchlist_list():
    """Return all watchlist items with their latest price."""
    conn = get_conn()
    try:
        items = get_watchlist(conn)
        return {"items": items, "count": len(items)}
    finally:
        release_conn(conn)


@router.post("/api/watchlist")
def watchlist_add(item: dict):
    """Add a watchlist item.

    Body: {"retailer": "kroger", "product_id": "abc123", "name": "Milk", "target_price": 2.99}
    """
    if not isinstance(item, dict) or "retailer" not in item or "product_id" not in item:
        raise HTTPException(400, "Each item must have 'retailer' and 'product_id'")
    conn = get_conn()
    try:
        row_id = add_watchlist_item(
            conn,
            retailer=item["retailer"],
            product_id=item["product_id"],
            name=item.get("name", ""),
            target_price=item.get("target_price"),
        )
        return {"id": row_id, "message": "Added to watchlist"}
    finally:
        release_conn(conn)


@router.delete("/api/watchlist/{retailer}/{product_id}")
def watchlist_remove(retailer: str, product_id: str):
    """Remove a watchlist item."""
    conn = get_conn()
    try:
        removed = remove_watchlist_item(conn, retailer, product_id)
        if not removed:
            raise HTTPException(404, f"Watchlist item not found: {retailer}/{product_id}")
        return {"message": "Removed from watchlist"}
    finally:
        release_conn(conn)


@router.get("/api/alerts")
def alerts_list(limit: int = Query(default=50, ge=1, le=200)):
    """Return unacknowledged price alerts."""
    conn = get_conn()
    try:
        alerts = get_active_alerts(conn, limit=limit)
        return {"alerts": alerts, "count": len(alerts)}
    finally:
        release_conn(conn)


@router.post("/api/alerts/{alert_id}/acknowledge")
def alert_acknowledge(alert_id: int):
    """Acknowledge a price alert."""
    conn = get_conn()
    try:
        updated = acknowledge_alert(conn, alert_id)
        if not updated:
            raise HTTPException(404, f"Alert {alert_id} not found")
        return {"message": "Alert acknowledged"}
    finally:
        release_conn(conn)
