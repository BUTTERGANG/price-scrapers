"""In-memory price comparison helpers.

These operate on a list[dict] of normalized price records — useful for
reporting on the results of a single scraper run without querying the DB.

For historical queries (trends, lowest-ever price, active deals across all
past runs) use the DB functions in utils/db.py instead.
"""
from typing import Optional

from utils.unit_price import format_unit_price


def compare_by_name(records: list[dict], query: str) -> list[dict]:
    """Filter records whose name contains query (case-insensitive), sorted by price."""
    q = query.lower()
    matches = [r for r in records if q in r.get("name", "").lower()]
    return sorted(matches, key=lambda r: r.get("price") or float("inf"))


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
        effective = r.get("sale_price") or r.get("price") or 0.0
        sale_tag = " (SALE)" if r.get("sale_price") else ""
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
        if sale and regular and sale < regular:
            deals.append({**r, "savings": round(regular - sale, 2)})
    return sorted(deals, key=lambda r: r["savings"], reverse=True)


def best_price_per_retailer(records: list[dict], query: str) -> dict[str, Optional[dict]]:
    """Return the cheapest matching item per retailer for a search term."""
    best: dict[str, Optional[dict]] = {}
    for record in compare_by_name(records, query):
        retailer = record.get("retailer", "unknown")
        if retailer not in best:
            best[retailer] = record
    return best
