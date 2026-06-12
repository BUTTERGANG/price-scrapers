"""Category-aware standard unit resolution.

Given a product record (name, department, category fields), determines
the appropriate standard unit for price comparison.

Usage:
    from utils.category_resolver import resolve_standard_unit

    result = resolve_standard_unit({"name": "Kroger Whole Milk 1 gal", "department": "Dairy"})
    # → {"standard_unit": "per_gal", "display_name": "per gallon", "canonical_base": "volume_liquid"}
"""
import json
import logging
import re
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_CONFIG_PATH = Path(__file__).parent.parent / "config" / "category_units.json"

# Module-level cache
_categories: Optional[list] = None
_fallback: Optional[dict] = None


def _load_config():
    global _categories, _fallback
    if _categories is not None:
        return
    try:
        data = json.loads(_CONFIG_PATH.read_text())
        _categories = data.get("categories", [])
        _fallback = data.get("fallback", {})
        _categories.sort(key=lambda c: c.get("priority", 0), reverse=True)
    except FileNotFoundError:
        logger.warning("category_units.json not found — category resolution disabled")
        _categories = []
        _fallback = {}
    except (json.JSONDecodeError, KeyError) as exc:
        logger.error("Failed to load category_units.json: %s", exc)
        _categories = []
        _fallback = {}


def resolve_standard_unit(record: dict) -> Optional[dict]:
    """Determine the standard comparison unit for a product record.

    Args:
        record: A normalized price record with at least 'name' field.
                May also have 'department', 'category' (from extra_json).

    Returns:
        dict with keys: standard_unit, display_name, canonical_base
        or None if no match and no fallback.

    Example:
        resolve_standard_unit({"name": "Kroger Whole Milk 1 gal", "department": "Dairy"})
        → {"standard_unit": "per_gal", "display_name": "per gallon", "canonical_base": "volume_liquid"}
    """
    _load_config()
    if not _categories:
        return _fallback if _fallback else None

    name = (record.get("name") or "").lower()
    department = (record.get("department") or "").lower()

    category = ""
    extra = record.get("extra_json") or record.get("category") or ""
    if isinstance(extra, dict):
        category = (extra.get("category") or "").lower()
    elif isinstance(extra, str):
        # extra_json may be a JSON string (e.g. from API responses) — try to parse it
        try:
            parsed = json.loads(extra)
            if isinstance(parsed, dict):
                category = (parsed.get("category") or "").lower()
            else:
                category = extra.lower()
        except (json.JSONDecodeError, TypeError):
            category = extra.lower()

    search_text = f"{name} {department} {category}".strip()

    for cat in _categories:
        for keyword in cat.get("keywords", []):
            kw_lower = keyword.lower()
            if len(kw_lower) <= 3:
                pattern = rf"\b{re.escape(kw_lower)}\b"
                if re.search(pattern, search_text):
                    return {
                        "standard_unit": cat["standard_unit"],
                        "display_name": cat["display_name"],
                        "canonical_base": cat["canonical_base"],
                    }
            else:
                if kw_lower in search_text:
                    return {
                        "standard_unit": cat["standard_unit"],
                        "display_name": cat["display_name"],
                        "canonical_base": cat["canonical_base"],
                    }

    return _fallback if _fallback else None
