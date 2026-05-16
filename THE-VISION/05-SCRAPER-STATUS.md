# Scraper Status & Health Report

## Overview

14 scrapers covering 15 retailer feeds (Kroger has 2 weekly ad store IDs, Fresh Market has 2 locations).

| Status | Count | Details |
|--------|-------|---------|
| Working | 13 | Actively returning data |
| Blocked | 2 | Walmart (PerimeterX), Costco (strict bot detection) |

---

## Per-Scraper Analysis

### Working Scrapers

| Scraper | Method | Reliability | Notes |
|---------|--------|-------------|-------|
| **Aldi** | Flipp REST API | High | Simple API, unlikely to break |
| **Fresh Thyme** | Flipp REST API | High | Same Flipp infrastructure as Aldi |
| **Meijer** | Flipp REST API | High | Same Flipp infrastructure |
| **Target** | api.target.com weekly ads | High | Public API, well-documented |
| **Kroger Weekly** | DACS public API | High | No credentials needed |
| **Whole Foods** | `__NEXT_DATA__` JSON parse | Medium | Will break if Amazon redesigns the site |
| **Fresh Market** | `__NEXT_DATA__` JSON parse | Medium | National deal board, 2 locations |
| **Harvest Market** | Webstop SSR HTML | Medium | Regional grocer, stable HTML structure |
| **GFS** | WordPress SSR HTML | Medium | Ad tabs + department catalog |
| **Giant Eagle** | Apollo GraphQL API | Medium | GraphQL schema changes could break queries |
| **Needler's (API)** | storebyweb.com REST | High | Product search API |
| **Needler's (Circular)** | Claude Vision | Medium | Depends on ANTHROPIC_API_KEY + PDF format |

### Blocked Scrapers

| Scraper | Method | Block Reason | Potential Fix |
|---------|--------|--------------|---------------|
| **Walmart** | curl_cffi (safari17_0) | PerimeterX bot detection from datacenter IPs | Residential proxy ($10-30/mo). The TLS fingerprinting works — it's the IP reputation that's blocked |
| **Costco** | Playwright stealth | Strict bot detection, JS challenges | Residential proxy + Playwright. Note: only returns online/delivery prices anyway — in-warehouse shelf prices are not available online |

### Scraper Risk Assessment

**High risk of breakage:**
- `__NEXT_DATA__` scrapers (Whole Foods, Fresh Market) — Next.js build changes can restructure the JSON at any time
- Giant Eagle GraphQL — Schema deprecations happen without notice

**Low risk of breakage:**
- Flipp-based scrapers (Aldi, Fresh Thyme, Meijer) — Flipp is a dedicated circular platform with a stable API
- Target — Public weekly ad API designed for third-party consumption

---

## Data Quality Observations

### What the Validation Pipeline Catches
- Empty product names (parser returned garbage)
- HTML tags in names (broken parsing)
- Duplicate product IDs within a run
- Prices > $500 (likely parse errors, except GFS bulk)
- Sale price >= regular price (won't display as a deal)
- Zero prices without deal context (missing deal text)
- Item count drops > 50% vs last run (parser breakage)

### What It Doesn't Catch
- **Stale circular data** — If a retailer's API serves last week's circular, the scraper won't know
- **Wrong store location** — If store IDs change, prices may silently come from a different location
- **Price format changes** — A retailer showing "$2.99/lb" vs "$2.99 each" may confuse unit price normalization
- **Phantom products** — Items that exist in the API but are actually out of stock at the physical store
- **Cross-retailer product matching** — "Kroger 2% Milk 1 gal" and "Great Value 2% Milk 128 fl oz" are the same thing but treated as different products

---

## Recommendations

1. **Add a freshness check** — Alert if any retailer's data is more than 48 hours old
2. **Add a smoke test per scraper** — Quick validation that the scraper returns >0 results with valid structure
3. **Monitor API response shapes** — Log the structure of each API response so you can detect when a retailer changes their schema
4. **Consider dropping Costco** — It's blocked and only returns online prices anyway. Focus effort on unblocking Walmart instead, which has in-store prices
5. **Add Trader Joe's** — Notable gap in the covered retailers. They publish prices on their website
