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
        stores_cfg = _STORES.get("stores", {})
        configured = list(stores_cfg.keys())
        run_map = {r["retailer"]: r for r in runs}
        result = []
        for name in configured:
            cfg = stores_cfg.get(name, {})
            # Disabled retailers (e.g. Walmart/Costco, blocked by bot detection)
            # report as 'disabled' regardless of any stale historical run so they
            # never masquerade as healthy successes.
            if cfg.get("disabled"):
                result.append({
                    "retailer": name,
                    "status": "disabled",
                    "records_saved": 0,
                    "started_at": None,
                    "finished_at": None,
                    "error": cfg.get("disabled_reason"),
                })
            elif name in run_map:
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
