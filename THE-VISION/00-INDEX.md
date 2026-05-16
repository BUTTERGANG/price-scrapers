# THE VISION — Price Board Audit & Roadmap

A comprehensive review of the Price Board grocery price tracking application, covering code quality, UX, architecture, and product direction.

**Application:** Price Board — Market basket intelligence & price discovery
**Coverage:** 14 retailers in Indianapolis area (ZIP 46220)
**Stack:** FastAPI + React + PostgreSQL (NeonDB) + 14 modular scrapers
**Date:** March 2026

---

## Documents

| # | Document | Summary |
|---|----------|---------|
| 01 | [Audit: Issues & Bugs](01-AUDIT-ISSUES.md) | 16 issues found — 5 critical (DB thread safety, connection leak, CORS misconfig, no concurrency guard, validation logic), 4 backend, 5 frontend, 2 data quality |
| 02 | [UI/UX Improvements](02-UI-UX-IMPROVEMENTS.md) | 16 recommendations — product images, search-as-you-type, market basket calculator, mobile navigation, price alerts, loading skeletons, accessibility |
| 03 | [Architecture Review](03-ARCHITECTURE-REVIEW.md) | Strengths (modular scrapers, validation pipeline, multi-strategy scraping) and concerns (monolithic frontend, no connection pooling, no caching, no scheduling) |
| 04 | [Product Roadmap](04-PRODUCT-ROADMAP.md) | 4-phase plan — Stability → Core UX → Smart Features → Scale. Key vision: answer "where is this cheapest?", "what's on sale?", "when should I buy?" |
| 05 | [Scraper Status](05-SCRAPER-STATUS.md) | 13 working, 2 blocked. Risk assessment per scraper. Recommendations for improving reliability and coverage |
| 06 | [Quick Wins](06-QUICK-WINS.md) | 10 high-impact, low-effort fixes that can be done in a single session |

---

## Priority Summary

### Fix Now (Critical)
1. DB connection pooling + schema init at startup only
2. Thread-safe DB access in runner.py
3. Scrape concurrency guard
4. CORS configuration fix

### Improve Soon (High Value)
5. Market basket calculator (total per retailer)
6. Product images on cards
7. Watchlist data refresh (currently shows stale snapshots)
8. Better empty states and search suggestions

### Plan For (Strategic)
9. Automated daily scrape scheduling
10. Price alerts on watchlist items
11. Full-text search with PostgreSQL tsvector
12. Split App.jsx into component files
