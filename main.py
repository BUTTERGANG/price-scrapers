"""Entry point — run grocery price scrapers and report results."""
import argparse
import json
import logging
from pathlib import Path

from dotenv import load_dotenv

from runner import available_retailers, run_all, run_retailers
from utils import best_price_per_retailer, find_deals, get_conn, release_conn, init_db, last_successful_run
from utils.compare import find_text_deals

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(name)s  %(message)s")
logger = logging.getLogger(__name__)

STORES = json.loads(Path("config/stores.json").read_text())
ITEMS = json.loads(Path("config/items.json").read_text())


def main():
    parser = argparse.ArgumentParser(
        description="Run grocery price scrapers.",
        epilog="Examples:\n"
               "  python main.py                       # run all retailers (4 parallel workers)\n"
               "  python main.py aldi target gfs       # run specific retailers\n"
               "  python main.py --workers 1           # serial execution\n"
               "  python main.py --list                # list available retailer names\n",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "retailers",
        nargs="*",
        metavar="RETAILER",
        help="Retailer names to run (default: all). Use --list to see options.",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="Print available retailer names and exit.",
    )
    parser.add_argument(
        "--workers", "-w",
        type=int,
        default=4,
        metavar="N",
        help="Number of scrapers to run in parallel (default: 4). Use 1 for serial.",
    )
    args = parser.parse_args()

    if args.list:
        retailers = available_retailers(STORES["stores"])
        print("Available retailers:")
        for name in retailers:
            print(f"  {name}")
        return

    init_db()

    if args.retailers:
        all_results = run_retailers(
            args.retailers, STORES["stores"], ITEMS["queries"],
            workers=args.workers,
        )
    else:
        all_results = run_all(STORES["stores"], ITEMS["queries"], workers=args.workers)

    conn = get_conn()
    try:
        _print_staleness(conn)
    finally:
        release_conn(conn)

    if not all_results:
        logger.warning("No results collected this run.")
        return

    logger.info(f"Total records this run: {len(all_results)}")
    _print_summary(all_results)


def _print_staleness(conn) -> None:
    all_retailers = available_retailers(STORES["stores"])
    for retailer in all_retailers:
        run = last_successful_run(conn, retailer)
        ts = run["finished_at"] if run else "never"
        logger.info(f"[{retailer}] Last successful run: {ts}")


def _print_summary(results: list[dict]) -> None:
    print("\n=== Best prices for 'milk' ===")
    for retailer, item in best_price_per_retailer(results, "milk").items():
        if item:
            effective = item.get("sale_price") or item["price"]
            tag = " (ON SALE)" if item.get("sale_price") else ""
            print(f"  {retailer:20s}  ${effective:.2f}{tag}  {item['name']}")

    print("\n=== Current deals (sale < regular) ===")
    price_deals = find_deals(results)
    if price_deals:
        for deal in price_deals[:10]:
            pct = round((deal["savings"] / deal["price"]) * 100)
            print(
                f"  {deal['retailer']:20s}  "
                f"${deal['sale_price']:.2f} (was ${deal['price']:.2f}, -{pct}%)  "
                f"{deal['name']}"
            )
    else:
        print("  (none)")

    print("\n=== Promotional deals (BOGO, % off, multi-unit, etc.) ===")
    text_deals = find_text_deals(results)
    if text_deals:
        for retailer in sorted(text_deals):
            items = text_deals[retailer]
            print(f"  {retailer}")
            for item in items[:5]:
                deal_text = item.get("deal_text", "")
                price = item.get("price") or 0.0
                price_str = f"${price:.2f}" if price else "price n/a"
                print(f"    {price_str:9s}  [{deal_text}]  {item['name'][:55]}")
            if len(items) > 5:
                print(f"    ... and {len(items) - 5} more")
    else:
        print("  (none)")


if __name__ == "__main__":
    main()
