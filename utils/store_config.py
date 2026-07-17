"""Load/save config/stores.json — the store location registry.

Schema (per retailer entry under "stores"):

    "aldi": {
        "name": "Aldi",
        "locations": [
            {"store_id": "444-086", "address": "...", "label": "86th-st"}
        ],
        "note": "..."
    }

- `locations` is a list; one entry per physical store to scrape.
- A location may carry extra scraper-specific fields (mp_number, store_number,
  store_slug, ...) which the runner copies into the scraper's config dict.
- `disabled: true` at the retailer level (with `disabled_reason`) skips the
  whole retailer; the same flag on a single location skips just that location.
- `label` customizes the registry key suffix when a retailer has multiple
  locations (key becomes "<retailer>_<label>", e.g. "fresh_market_146th").

The legacy single-store shape ({"store_id": "..."} directly on the retailer)
is still accepted by get_locations() so hand-edited configs don't break.
"""
import json
import threading
from pathlib import Path

STORES_PATH = Path("config/stores.json")

_write_lock = threading.Lock()


def load_config() -> dict:
    """Read the full stores.json (fresh from disk every call)."""
    return json.loads(STORES_PATH.read_text())


def load_stores() -> dict:
    """Return just the "stores" mapping (retailer key → config entry)."""
    return load_config().get("stores", {})


def save_config(config: dict) -> None:
    """Atomically write the full config back to stores.json."""
    with _write_lock:
        tmp = STORES_PATH.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(config, indent=2) + "\n")
        tmp.replace(STORES_PATH)


def get_locations(retailer_cfg: dict) -> list[dict]:
    """Locations list for a retailer entry; wraps the legacy single-store shape."""
    if "locations" in retailer_cfg:
        return retailer_cfg["locations"]
    if "store_id" in retailer_cfg:
        return [retailer_cfg]
    return []


def add_location(retailer: str, location: dict, name: str | None = None) -> dict:
    """Append a location to a retailer entry (creating the entry if needed).

    Returns the updated retailer entry. Raises ValueError on duplicates.
    """
    config = load_config()
    stores = config.setdefault("stores", {})
    entry = stores.setdefault(retailer, {"name": name or retailer, "locations": []})
    if "locations" not in entry:
        # Migrate a legacy single-store entry in place.
        legacy = {k: entry.pop(k) for k in list(entry.keys())
                  if k not in ("name", "note", "disabled", "disabled_reason")}
        entry["locations"] = [legacy] if legacy.get("store_id") else []
    existing_ids = {loc.get("store_id") for loc in entry["locations"]}
    if location.get("store_id") in existing_ids:
        raise ValueError(
            f"{retailer} already has a location with store_id {location.get('store_id')}"
        )
    entry["locations"].append(location)
    save_config(config)
    return entry


def remove_location(retailer: str, store_id: str) -> dict:
    """Remove a location from a retailer entry by store_id.

    Returns the updated retailer entry. Raises KeyError/ValueError if missing.
    """
    config = load_config()
    stores = config.get("stores", {})
    if retailer not in stores:
        raise KeyError(f"Unknown retailer '{retailer}'")
    entry = stores[retailer]
    locations = get_locations(entry)
    remaining = [loc for loc in locations if loc.get("store_id") != store_id]
    if len(remaining) == len(locations):
        raise ValueError(f"{retailer} has no location with store_id {store_id}")
    entry["locations"] = remaining
    save_config(config)
    return entry
