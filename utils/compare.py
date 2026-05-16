"""In-memory price comparison helpers.

These operate on a list[dict] of normalized price records — useful for
reporting on the results of a single scraper run without querying the DB.

For historical queries (trends, lowest-ever price, active deals across all
past runs) use the DB functions in utils/db.py instead.
"""
import json
from typing import Optional

from utils.unit_price import format_unit_price


def _effective_price(r: dict) -> float:
    """Return the real shelf price: sale_price when set (even $0), else price."""
    sale = r.get("sale_price")
    if sale is not None:
        return sale
    return r.get("price") or float("inf")


def _get_deal_text(r: dict) -> Optional[str]:
    """Return deal_text from top-level field or from extra_json (DB round-trip)."""
    if r.get("deal_text"):
        return r["deal_text"]
    raw = r.get("extra_json")
    if raw:
        try:
            extra = json.loads(raw) if isinstance(raw, str) else raw
            return extra.get("deal_text") or extra.get("sale_story") or None
        except (ValueError, TypeError):
            pass
    return None


def compare_by_name(records: list[dict], query: str) -> list[dict]:
    """Filter records whose name contains query (case-insensitive), sorted by effective price."""
    q = query.lower()
    matches = [r for r in records if q in r.get("name", "").lower()]
    return sorted(matches, key=_effective_price)


def compare_by_unit_price(
    records: list[dict], query: str, canonical: Optional[str] = None
) -> list[dict]:
    """Filter records by name query and sort by unit_price_normalized.

    Args:
        records:   List of normalized price records from a scraper run.
        query:     Name substring to filter on (case-insensitive).
        canonical: Restrict to one canonical unit ('per_fl_oz', 'per_oz',
                   'per_lb', 'per_ct'). When None, groups are sorted together
                   but labelled so mixed units are visible.

    Returns:
        Matching records sorted by (unit_canonical, unit_price_normalized).
        Records without a normalized unit price are appended at the end.
    """
    q = query.lower()
    matches = [r for r in records if q in r.get("name", "").lower()]

    if canonical:
        matches = [r for r in matches if r.get("unit_canonical") == canonical]

    with_norm = [r for r in matches if r.get("unit_price_normalized") is not None]
    without_norm = [r for r in matches if r.get("unit_price_normalized") is None]

    with_norm.sort(key=lambda r: (
        r.get("unit_canonical") or "",
        r.get("unit_price_normalized") or float("inf"),
    ))

    return with_norm + without_norm


def print_unit_price_comparison(records: list[dict], query: str) -> None:
    """Print a formatted unit price comparison table for a search query."""
    results = compare_by_unit_price(records, query)
    if not results:
        print(f"No results for '{query}'")
        return

    print(f"\n=== Unit price comparison: '{query}' ===")
    current_canonical = None
    for r in results:
        canon = r.get("unit_canonical")
        if canon != current_canonical:
            current_canonical = canon
            label = canon or "no unit"
            print(f"\n  [{label}]")
        up = format_unit_price(r) or "  n/a  "
        effective = _effective_price(r) if _effective_price(r) != float("inf") else 0.0
        sale_tag = " (SALE)" if r.get("sale_price") is not None else ""
        print(
            f"  {r.get('retailer', ''):18s}  "
            f"${effective:.2f}{sale_tag:7s}  "
            f"{up:14s}  {r.get('name', '')}"
        )


def find_deals(records: list[dict]) -> list[dict]:
    """Return records with an active sale, sorted by dollar savings descending."""
    deals = []
    for r in records:
        sale = r.get("sale_price")
        regular = r.get("price")
        # Use `is not None` so sale_price=0 (BOGO free) is included
        if sale is not None and regular and sale < regular:
            deals.append({**r, "savings": round(regular - sale, 2)})
    return sorted(deals, key=lambda r: r["savings"], reverse=True)


def find_text_deals(records: list[dict]) -> dict[str, list[dict]]:
    """Return items that have a deal_text label (BOGO, % off, multi-unit, etc.),
    grouped by retailer.  Items already captured by find_deals() (where
    sale_price < price) are excluded to avoid duplication.

    Returns:
        dict mapping retailer name → list of matching records (unsorted).
    """
    already_dealt = {
        (r["retailer"], r["product_id"])
        for r in records
        if r.get("sale_price") is not None and r.get("price") and r["sale_price"] < r["price"]
    }

    grouped: dict[str, list[dict]] = {}
    for r in records:
        if not _get_deal_text(r):
            continue
        key = (r.get("retailer", ""), r.get("product_id", ""))
        if key in already_dealt:
            continue
        retailer = r.get("retailer", "unknown")
        grouped.setdefault(retailer, []).append(r)
    return grouped


def best_price_per_retailer(records: list[dict], query: str) -> dict[str, Optional[dict]]:
    """Return the cheapest matching item per retailer for a search term."""
    best: dict[str, Optional[dict]] = {}
    for record in compare_by_name(records, query):
        retailer = record.get("retailer", "unknown")
        if retailer not in best:
            best[retailer] = record
    return best
