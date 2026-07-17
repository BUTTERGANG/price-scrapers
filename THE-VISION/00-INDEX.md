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

> **Status (July 2026):** docs 01–06 below are frozen historical snapshots from the original
> March 2026 audit — most of what they flag has since shipped. For current status, check the
> checkboxes in [04-PRODUCT-ROADMAP.md](04-PRODUCT-ROADMAP.md) rather than the prose in 01/02/03/05/06,
> which was never updated after the fixes landed.
>
> Critical fixes, the high-value UX items, scheduling, price alerts, and the App.jsx split all
> shipped. Item 11 was implemented with a `pg_trgm` trigram index instead of tsvector — it
> accelerates the existing substring / word-boundary search without changing match semantics.
> Timestamps were also migrated from TEXT to TIMESTAMPTZ, and the Telegram bot's leftover
> SQLite-syntax queries were fixed.
>
> **2026-07-02:** fixed a scheduler bug that caused the auto-scrape job to fire 30+ times a day
> (seen as spikes to 130 runs/day on the Dashboard's "Scrape Activity" chart). Root cause:
> uvicorn's dev reloader restarts the worker on every backend file save, re-running the FastAPI
> lifespan; the scheduler recomputed "5 minutes from now" on every restart instead of anchoring
> to the last real run. See `server.py::_next_auto_scrape_time` and `tests/test_scheduler.py`.

### Fix Now (Critical)
1. ~~DB connection pooling + schema init at startup only~~ ✅ Done
2. ~~Thread-safe DB access in runner.py~~ ✅ Done (per-thread pool connections)
3. ~~Scrape concurrency guard~~ ✅ Done
4. ~~CORS configuration fix~~ ✅ Done

### Improve Soon (High Value)
5. ~~Market basket calculator (total per retailer)~~ ✅ Done
6. ~~Product images on cards~~ ✅ Done
7. ~~Watchlist data refresh~~ ✅ Done (live `/api/watchlist/prices`)
8. ~~Better empty states and search suggestions~~ ✅ Done

### Plan For (Strategic)
9. ~~Automated daily scrape scheduling~~ ✅ Done (APScheduler in FastAPI lifespan, every 6 h)
10. ~~Price alerts on watchlist items~~ ✅ Done
11. ~~Full-text search~~ ✅ Done via `pg_trgm` trigram index (better fit than tsvector)
12. ~~Split App.jsx into component files~~ ✅ Done (`src/components/` + `src/lib/`)

### Still Open
- Walmart & Costco scrapers blocked by bot detection (need residential proxy)
- Frontend bundle is >500 kB minified (recharts) — consider code-splitting if load time matters
