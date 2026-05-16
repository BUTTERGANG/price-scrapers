"""Quick smoke test — scrape each retailer's circular and print item counts + samples."""
import logging
import sys
import traceback

logging.basicConfig(level=logging.WARNING, format="%(levelname)s  %(name)s  %(message)s")

PASS = "\033[32m✓\033[0m"
FAIL = "\033[31m✗\033[0m"


def show(retailer, results):
    n = len(results)
    if n == 0:
        print(f"  {FAIL} {retailer}: 0 items returned")
        return
    print(f"  {PASS} {retailer}: {n} items")
    for r in results[:3]:
        name = r.get("name") or r.get("productName") or "?"
        price = r.get("price", "?")
        unit = r.get("unit") or ""
        deal = r.get("deal_text") or ""
        price_str = f"${price:.2f}" if isinstance(price, float) else str(price)
        extras = f"  [{deal or unit}]" if (deal or unit) else ""
        print(f"      {name[:55]:<55} {price_str}{extras}")


def run(label, fn):
    print(f"\n{'─'*60}")
    print(f"  {label}")
    print(f"{'─'*60}")
    try:
        results = fn()
        show(label, results)
    except Exception as e:
        print(f"  {FAIL} {label}: ERROR — {e}")
        traceback.print_exc()


# ── Aldi ────────────────────────────────────────────────────────────────────
def test_aldi():
    from scrapers.aldi import AldiScraper
    s = AldiScraper("444-086", {})
    return s.scrape_circular()

# ── Target ───────────────────────────────────────────────────────────────────
def test_target():
    from scrapers.target import TargetScraper
    s = TargetScraper("2391", {})
    return s.scrape_circular()

# ── GFS ──────────────────────────────────────────────────────────────────────
def test_gfs():
    from scrapers.gfs import GFSScraper
    s = GFSScraper("1905", {})
    return s.scrape_circular()

# ── Meijer ───────────────────────────────────────────────────────────────────
def test_meijer():
    from scrapers.meijer import MeijerScraper
    s = MeijerScraper("290", {})
    return s.scrape_circular()

# ── Needlers ─────────────────────────────────────────────────────────────────
def test_needlers():
    from scrapers.needlers import NeedlersScraper
    s = NeedlersScraper(store_id="1000-6062", config={})
    # Search a few common grocery items
    results = []
    for q in ["milk", "eggs", "bread"]:
        results.extend(s.search_products(q))
    return results


if __name__ == "__main__":
    run("Aldi (store 444-086)", test_aldi)
    run("Target (store 2391)", test_target)
    run("GFS (store 1905)", test_gfs)
    run("Meijer (store 290)", test_meijer)
    run("Needlers (store 929)", test_needlers)
    print(f"\n{'═'*60}\n  Done.\n{'═'*60}\n")
