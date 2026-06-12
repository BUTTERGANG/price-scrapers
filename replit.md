# Grocery Price Scrapers

An automated system for collecting, tracking, and comparing grocery prices across 14 retailers in the Indianapolis area (ZIP 46220).

## Architecture

- **Backend**: FastAPI (Python) — runs on `0.0.0.0:8000`
- **Frontend**: React + Vite — runs on `0.0.0.0:5000` (proxies `/api` → backend)
- **Database**: PostgreSQL (NeonDB via `NEONDB1`, fallback to Replit's `DATABASE_URL`)
- **Scrapers**: 14 modular scrapers in `scrapers/` — 12 working, 2 blocked by bot detection (Walmart, Costco)
- **Scheduler**: APScheduler inside the FastAPI lifespan — auto-scrape every 6 h (first run 5 min after startup), data cleanup daily at 03:00 UTC. Runs only in the serving process, so uvicorn reload can't duplicate it.

## Project Structure

```
scrapers/           # Individual store scraper implementations (14 scrapers)
utils/              # Shared utilities (db, http, browser, unit_price, validate)
frontend/           # React dashboard (Vite dev server on port 5000)
  src/App.jsx       #   App shell — tabs, navigation, watchlist state
  src/components/   #   One file per view + Shared.jsx (cards, badges, skeletons)
  src/lib/          #   hooks.js (useFetch, useLocalStorage), utils.js (formatters)
config/             # stores.json, items.json configuration
tests/              # pytest suite (DB tests run in a disposable PG schema)
server.py           # FastAPI backend (port 8000) — REST API for dashboard
main.py             # CLI entry point for running scrapers
runner.py           # Parallel scraper orchestration (ThreadPoolExecutor)
telegram_bot.py     # Telegram bot interface
replit.nix          # Nix system dependencies (Chromium libs for Playwright)
```

## Workflows

- **Project** — Runs frontend + backend in parallel
- **Start application** — `cd frontend && npm install && npm run dev` (port 5000, webview)
- **Backend API** — `python server.py` (port 8000, console; hot reload unless `REPLIT_DEPLOYMENT` is set)
- **Run Scrapers** — `python main.py --workers 4` (all retailers)
- **Run Single Scraper** — `python main.py aldi` (one retailer)

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/status` | GET | Health check with DB statistics |
| `/api/stores` | GET | Store status and last run times |
| `/api/stores/{retailer}/analytics` | GET | Per-store analytics (departments, recent runs) |
| `/api/deals?min_pct=10&max_age_days=7` | GET | Active deals (paginated, with freshness metadata) |
| `/api/search?q=<query>` | GET | Search items across retailers (paginated) |
| `/api/compare?q=<query>` | GET | Unit price comparison across retailers |
| `/api/history?q=<query>` | GET | Price history for a product (or `?retailer=&product_id=`) |
| `/api/trends?q=<query>` | GET | Time-series price data for charting |
| `/api/dashboard` | GET | Summary stats, market pulse, scrape activity |
| `/api/departments` | GET | Department list with counts/averages |
| `/api/departments/{dept}` | GET | Products in a department (paginated) |
| `/api/freshness` | GET | Per-retailer data freshness |
| `/api/upc/<upc>` | GET | Cross-retailer UPC lookup |
| `/api/watchlist/prices` | POST | Batch live prices for watchlist items |
| `/api/scrape` | POST | Trigger background scrape run (409 if one is running) |
| `/api/scrape/status` | GET | Whether a scrape is currently running |
| `/api/cleanup` | POST | Prune old price records (keeps monthly samples) |

## Database

PostgreSQL (NeonDB) with tables:
- `prices` — append-only price records with retailer, product, price, unit price data. `scraped_at` is `TIMESTAMPTZ`.
- `runs` — scraper execution metadata (status, timing, record counts). `started_at`/`finished_at` are `TIMESTAMPTZ`.
- `failed_queries` — failed queries for targeted reruns

Connection priority: `NEONDB1` env var first, falls back to `DATABASE_URL` (Replit built-in Postgres).
Connections come from a `ThreadedConnectionPool` with a 30 s `statement_timeout`; schema (incl. the
TEXT→TIMESTAMPTZ migration and the `pg_trgm` trigram index on `LOWER(name)`) is applied once at startup.

## Scraper Status

| Status | Scrapers |
|--------|----------|
| **Working (12 keys)** | Aldi, Fresh Thyme, GFS, Giant Eagle, Harvest Market, Kroger (weekly ads, one key per store ID), Meijer, Needler's, Target, Fresh Market (one key per store), Whole Foods |
| **Blocked (2)** | Walmart, Costco — bot detection from datacenter IPs. Need residential proxy. |

## Tests

`python -m pytest tests/` — 53 tests. DB tests create a disposable PostgreSQL schema per test and drop
it on teardown. Live scraper tests are skipped unless `RUN_LIVE_SCRAPER_TESTS=1`; Kroger API tests skip
without credentials.

## Environment Variables

- `NEONDB1` — NeonDB PostgreSQL connection string (primary)
- `DATABASE_URL` — Fallback PostgreSQL connection string (Replit built-in)
- `ANTHROPIC_API_KEY` — Required for Needler's circular vision scraping and Telegram `/ask`
- `TELEGRAM_BOT_TOKEN` — Required for Telegram bot

## Dependencies

- Python: `pip install -r requirements.txt`
- Frontend: `cd frontend && npm install`
- Playwright: `playwright install chromium` (for Costco scraper)
- System libs: Managed via `replit.nix` (Chromium dependencies)
