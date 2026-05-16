"""Query the price history database.

Usage:
    python scripts/query_prices.py milk
    python scripts/query_prices.py "chicken breast" --deals
    python scripts/query_prices.py --deals --min-savings 15
    python scripts/query_prices.py --runs
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from utils import get_conn, release_conn, cheapest_per_retailer, find_active_deals, last_successful_run


def cmd_search(conn, item: str) -> None:
    rows = cheapest_per_retailer(conn, item)
    if not rows:
        print(f"No results for '{item}' in the last 24 hours.")
        return
    print(f"\nCheapest '{item}' per retailer (last 24h):\n")
    for r in rows:
        effective = r["sale_price"] if r["sale_price"] else r["price"]
        tag = f"  ON SALE (was ${r['price']:.2f})" if r["sale_price"] else ""
        print(f"  {r['retailer']:15s}  ${effective:.2f}{tag}  —  {r['name']}")


def cmd_deals(conn, min_savings_pct: float) -> None:
    deals = find_active_deals(conn, min_savings_pct=min_savings_pct)
    if not deals:
        print(f"No deals with {min_savings_pct}%+ savings in the last 24 hours.")
        return
    print(f"\nActive deals ({min_savings_pct}%+ off, last 24h):\n")
    for d in deals:
        print(
            f"  {d['retailer']:15s}  "
            f"${d['sale_price']:.2f} (was ${d['price']:.2f}, -{d['savings_pct']}%)  "
            f"{d['name']}"
        )


def cmd_runs(conn) -> None:
    print("\nLast successful run per retailer:\n")
    for retailer in ("kroger", "walmart", "meijer", "fresh_thyme", "costco"):
        run = last_successful_run(conn, retailer)
        if run:
            print(
                f"  {retailer:15s}  {run['finished_at']}  "
                f"({run['records_saved']} records, "
                f"{run['queries_ok']}/{run['queries_total']} queries ok)"
            )
        else:
            print(f"  {retailer:15s}  no successful run yet")


def main():
    parser = argparse.ArgumentParser(description="Query the grocery price database.")
    parser.add_argument("item", nargs="?", help="Item to search for (e.g. 'milk')")
    parser.add_argument("--deals", action="store_true", help="Show active deals")
    parser.add_argument("--min-savings", type=float, default=10.0, metavar="PCT",
                        help="Minimum savings %% for --deals (default: 10)")
    parser.add_argument("--runs", action="store_true", help="Show last run status per retailer")
    args = parser.parse_args()

    conn = get_conn()
    try:
        if args.runs:
            cmd_runs(conn)
        elif args.deals:
            cmd_deals(conn, args.min_savings)
        elif args.item:
            cmd_search(conn, args.item)
        else:
            parser.print_help()
    finally:
        release_conn(conn)


if __name__ == "__main__":
    main()
