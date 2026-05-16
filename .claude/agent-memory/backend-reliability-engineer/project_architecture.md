---
name: Project architecture overview
description: Grocery price scraper stack — FastAPI, psycopg2 ThreadedConnectionPool, NeonDB, curl_cffi/Playwright scrapers
type: project
---

FastAPI backend (server.py) serves a React SPA from frontend/dist. Database is NeonDB (PostgreSQL) accessed via psycopg2 ThreadedConnectionPool (minconn=1, maxconn=10). Connection env vars: NEONDB1 or DATABASE_URL.

Scraper layer (runner.py + scrapers/) runs in background threads via ThreadPoolExecutor. Each scraper worker gets its own DB connection from the pool via get_conn()/release_conn(). Config lives in config/stores.json and config/items.json.

Two HTTP strategies: curl_cffi (TLS fingerprint impersonation) for Walmart/anti-bot sites; plain requests for simpler sites (Harvest Market). Playwright used for JS-heavy scrapers (Costco, Fresh Thyme).

**Why:** The ThreadedConnectionPool is sized to 10 — with 4 parallel scraper workers plus API request handlers, the pool can approach saturation under concurrent scrape+API load. Monitor for pool exhaustion.
**How to apply:** When suggesting connection pool changes or worker count increases, cross-check against maxconn=10.
