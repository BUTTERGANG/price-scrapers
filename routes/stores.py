"""Store listing and analytics endpoints."""
import json
from pathlib import Path

from fastapi import APIRouter

from utils import get_conn, release_conn, get_store_status, get_store_analytics

router = APIRouter(tags=["stores"])

_STORES = json.loads(Path("config/stores.json").read_text())


@router.get("/api/stores")
def get_stores():
    """Return store run status from the DB."""
    conn = get_conn()
    try:
        runs = get_store_status(conn)
        configured = list(_STORES.get("stores", {}).keys())
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
        for r in runs:
            if r["retailer"] not in configured:
                result.append(r)
        return {"stores": result}
    finally:
        release_conn(conn)


@router.get("/api/stores/{retailer}/analytics")
def store_analytics(retailer: str):
    conn = get_conn()
    try:
        return get_store_analytics(conn, retailer)
    finally:
        release_conn(conn)
