# Grocery Price Scrapers

An automated system for collecting, tracking, and comparing grocery prices across 15 retailers in the Indianapolis area (ZIP 46220).

## Architecture

- **Backend**: FastAPI (Python) — runs on `0.0.0.0:8000`
- **Frontend**: React + Vite — runs on `0.0.0.0:5000` (proxies `/api` → backend)
- **Database**: PostgreSQL (NeonDB via `NEONDB1`, fallback to Replit's `DATABASE_URL`)
- **Scrapers**: 14 modular scrapers in `scrapers/` — 13 working, 2 blocked by bot detection (Walmart, Costco)

## Project Structure

```
scrapers/           # Individual store scraper implementations (14 scrapers)
utils/              # Shared utilities (db, http, browser, unit_price, validate)
frontend/           # React dashboard (Vite dev server on port 5000)
config/             # stores.json, items.json configuration
server.py           # FastAPI backend (port 8000) — REST API for dashboard
main.py             # CLI entry point for running scrapers
runner.py           # Parallel scraper orchestration (ThreadPoolExecutor)
telegram_bot.py     # Telegram bot interface
replit.nix          # Nix system dependencies (Chromium libs for Playwright)
```

## Workflows

- **Project** — Runs frontend + backend in parallel
- **Start application** — `cd frontend && npm install && npm run dev` (port 5000, webview)
- **Backend API** — `python server.py` (port 8000, console)
- **Run Scrapers** — `python main.py --workers 4` (all retailers)
- **Run Single Scraper** — `python main.py aldi` (one retailer)

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/status` | GET | Health check with DB statistics |
| `/api/stores` | GET | Store status and last run times |
| `/api/deals?min_pct=10` | GET | Active deals above a discount threshold |
| `/api/search?q=<query>` | GET | Search items across retailers |
| `/api/compare?q=<query>` | GET | Unit price comparison across retailers |
| `/api/history?q=<query>` | GET | Price history for a product |
| `/api/history?retailer=X&product_id=Y` | GET | Price history for specific product |
| `/api/upc/<upc>` | GET | Cross-retailer UPC lookup |
| `/api/scrape` | POST | Trigger background scrape run |

## Database

PostgreSQL (NeonDB) with tables:
- `prices` — append-only price records with retailer, product, price, unit price data
- `runs` — scraper execution metadata (status, timing, record counts)
- `failed_queries` — failed queries for targeted reruns

Connection priority: `NEONDB1` env var first, falls back to `DATABASE_URL` (Replit built-in Postgres).

## Scraper Status

| Status | Scrapers |
|--------|----------|
| **Working (13)** | Aldi, Fresh Thyme, GFS, Giant Eagle, Harvest Market, Kroger (x2 weekly ads), Meijer, Needler's, Target, Fresh Market (x2), Whole Foods |
| **Blocked (2)** | Walmart, Costco — bot detection from datacenter IPs. Need residential proxy. |

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
