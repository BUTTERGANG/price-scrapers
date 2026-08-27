"""Full scraper health check — test every scraper and report results."""
import logging, sys, traceback
logging.basicConfig(level=logging.WARNING, format="%(levelname)s  %(name)s  %(message)s")

PASS = "\033[32m✓\033[0m"
FAIL = "\033[31m✗\033[0m"
SKIP = "\033[33m~ SHA-SKIP\033[0m"

results = []

def check(label, fn):
    print(f"  Testing {label}...", end=" ", flush=True)
    try:
        items = fn()
        n = len(items)
        mark = PASS
        if n == 0:
            mark = f"{FAIL} (0 items)"
        print(f"{mark}  {n} items")
        if items:
            sample = items[0]
            name = sample.get("name") or sample.get("productName") or "?"
            price = sample.get("price", "?")
            if isinstance(price, float):
                print(f"      Sample: {name[:50]}  ${price:.2f}")
        results.append((label, n, None))
    except Exception as e:
        err = str(e)[:120]
        print(f"{FAIL}  {err}")
        results.append((label, 0, err))

# ── Need env credentials ──
def test_kroger():
    from scrapers.kroger import KrogerScraper
    s = KrogerScraper("01400441", {})
    return s.scrape_circular()

def test_kroger_products():
    from scrapers.kroger import KrogerScraper
    s = KrogerScraper("01400441", {})
    return s.search_products("milk") + s.search_products("eggs")

def test_needlers_circular():
    from scrapers.needlers_circular import NeedlersCircularScraper
    s = NeedlersCircularScraper("929", {})
    return s.scrape_circular()

def test_walmart():
    from scrapers.walmart import WalmartScraper
    s = WalmartScraper("2787", {})
    return s.search_products("milk") + s.search_products("eggs")

def test_costco():
    from scrapers.costco import CostcoScraper
    s = CostcoScraper("346", {})
    return s.search_products("milk") + s.search_products("eggs")

# ── No auth needed (just HTTP) ──
def test_whole_foods():
    from scrapers.whole_foods import WholeFoodsScraper
    s = WholeFoodsScraper("10378", {})
    return s.scrape_circular()

def test_fresh_market():
    from scrapers.fresh_market import FreshMarketScraper
    s = FreshMarketScraper("56", {})
    return s.scrape_circular()

def test_giant_eagle():
    from scrapers.giant_eagle import GiantEagleScraper
    s = GiantEagleScraper("6550", {})
    return s.scrape_circular()

def test_harvest_market():
    from scrapers.harvest_market import HarvestMarketScraper
    s = HarvestMarketScraper("17", {})
    return s.scrape_circular()

def test_fresh_thyme():
    from scrapers.fresh_thyme import FreshThymeScraper
    s = FreshThymeScraper("208", {})
    return s.scrape_circular()

print("=" * 60)
print("  FULL SCRAPER HEALTH CHECK")
print("=" * 60)

print("\n── No Auth Needed ──")
check("Whole Foods (store 10378)", test_whole_foods)
check("Fresh Market (store 56)", test_fresh_market)
check("Giant Eagle (store 6550)", test_giant_eagle)
check("Harvest Market (store 17)", test_harvest_market)
check("Fresh Thyme (store 208)", test_fresh_thyme)

print("\n── Needs API Keys (env) ──")
check("Kroger Circular", test_kroger)
check("Kroger Products", test_kroger_products)
check("Needlers Circular (Vision)", test_needlers_circular)

print("\n── Blocked / Problematic ──")
check("Walmart (PerimeterX)", test_walmart)
check("Costco (Playwright)", test_costco)

print("\n" + "=" * 60)
print("  SUMMARY")
print("=" * 60)
for label, n, err in results:
    if err:
        print(f"  {FAIL} {label}: {err}")
    elif n == 0:
        print(f"  {FAIL} {label}: 0 items (empty result)")
    else:
        print(f"  {PASS} {label}: {n} items")
