"""Store listing, analytics, discovery, and location management endpoints."""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from utils import get_conn, release_conn, get_store_status, get_store_analytics
from utils.store_config import add_location, load_stores, remove_location

router = APIRouter(tags=["stores"])


@router.get("/api/stores")
def get_stores():
    """Return per-store run status, derived from the runner registry + runs DB."""
    from runner import expected_stores

    conn = get_conn()
    try:
        runs = get_store_status(conn)
        run_map = {r["retailer"]: r for r in runs}
        expected = expected_stores(load_stores())
        result = []
        for exp in expected:
            key = exp["key"]
            # Disabled retailers (e.g. Walmart/Costco, blocked by bot detection)
            # report as 'disabled' regardless of any stale historical run so they
            # never masquerade as healthy successes.
            if exp["disabled"]:
                result.append({
                    "retailer": key,
                    "status": "disabled",
                    "records_saved": 0,
                    "started_at": None,
                    "finished_at": None,
                    "error": exp.get("disabled_reason"),
                    "name": exp.get("name"),
                    "address": exp.get("address"),
                })
            elif key in run_map:
                result.append({
                    **run_map[key],
                    "name": exp.get("name"),
                    "address": exp.get("address"),
                })
            else:
                result.append({
                    "retailer": key,
                    "status": "never_run",
                    "records_saved": 0,
                    "started_at": None,
                    "finished_at": None,
                    "error": None,
                    "name": exp.get("name"),
                    "address": exp.get("address"),
                })
        known = {e["key"] for e in expected}
        for r in runs:
            if r["retailer"] not in known:
                result.append(r)
        return {"stores": result}
    finally:
        release_conn(conn)


@router.get("/api/stores/discover")
def discover_stores(retailer: str = "", zip: str = "46220"):
    """Find nearby store IDs for a retailer via its live store locator.

    Without a retailer param, just returns the list of discoverable retailers.
    """
    from utils.store_discovery import discover, discoverable_retailers

    if not retailer:
        return {"discoverable": discoverable_retailers(), "results": []}
    if not (zip.isdigit() and len(zip) == 5):
        raise HTTPException(400, "zip must be a 5-digit US ZIP code")
    try:
        results = discover(retailer, zip)
    except LookupError as exc:
        raise HTTPException(400, str(exc))
    except Exception as exc:
        raise HTTPException(502, f"Store lookup failed: {exc}")
    return {
        "retailer": retailer,
        "zip": zip,
        "results": results,
        "discoverable": discoverable_retailers(),
    }


class AddLocationBody(BaseModel):
    retailer: str
    location: dict
    name: str | None = None


@router.post("/api/stores/locations")
def add_store_location(body: AddLocationBody):
    """Append a location to a retailer entry in config/stores.json."""
    if not body.location.get("store_id"):
        raise HTTPException(400, "location.store_id is required")
    stores = load_stores()
    from runner import PLATFORM_SPECS, RETAILER_SPECS
    known = {s.config_key or s.key for s in RETAILER_SPECS}
    is_platform = stores.get(body.retailer, {}).get("platform") in PLATFORM_SPECS
    if body.retailer not in known and not is_platform:
        raise HTTPException(
            400,
            f"Unknown retailer '{body.retailer}'. Supported: {sorted(known)}; "
            "or create a platform entry (flipp/webstop) in config/stores.json first.",
        )
    try:
        entry = add_location(body.retailer, body.location, name=body.name)
    except ValueError as exc:
        raise HTTPException(409, str(exc))
    return {"status": "ok", "retailer": body.retailer, "entry": entry}


@router.delete("/api/stores/{retailer}/locations/{store_id}")
def delete_store_location(retailer: str, store_id: str):
    """Remove a location from a retailer entry in config/stores.json."""
    try:
        entry = remove_location(retailer, store_id)
    except KeyError as exc:
        raise HTTPException(404, str(exc))
    except ValueError as exc:
        raise HTTPException(404, str(exc))
    return {"status": "ok", "retailer": retailer, "entry": entry}


@router.get("/api/stores/{retailer}/analytics")
def store_analytics(retailer: str):
    conn = get_conn()
    try:
        return get_store_analytics(conn, retailer)
    finally:
        release_conn(conn)
