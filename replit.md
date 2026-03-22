# Grocery Price Scrapers

An automated system for collecting, tracking, and comparing grocery prices across multiple retailers in the Indianapolis area (ZIP 46220).

## Architecture

- **Backend**: FastAPI (Python) — runs on `localhost:8000`
- **Frontend**: React + Vite — runs on `0.0.0.0:5000`
- **Database**: SQLite (`data/prices.db`) with WAL mode for concurrent access
- **Scrapers**: Modular scrapers in `scrapers/` for each retailer

## Project Structure

```
scrapers/       # Individual store scraper implementations
utils/          # Shared utilities (db, http, browser, unit_price)
frontend/       # React dashboard (Vite dev server on port 5000)
config/         # stores.json, items.json configuration
data/           # SQLite database and raw response cache (gitignored)
server.py       # FastAPI backend (port 8000)
main.py         # CLI entry point for running scrapers
runner.py       # Parallel scraper orchestration (ThreadPoolExecutor)
telegram_bot.py # Telegram bot interface
```

## Workflows

- **Start application** — `cd frontend && npm run dev` (port 5000, webview)
- **Backend API** — `python server.py` (port 8000, console)

## API Endpoints

- `GET /api/deals?min_pct=10` — Active deals above a discount threshold
- `GET /api/search?q=<query>` — Search items across retailers
- `GET /api/stores` — Store status and last run times

## Environment Variables

See `.env.example`:
- `ANTHROPIC_API_KEY` — Required for Needler's circular vision scraping and Telegram `/ask`
- `TELEGRAM_BOT_TOKEN` — Required for Telegram bot
- Kroger API credentials go in `config/stores.json`

## Dependencies

- Python: `pip install -r requirements.txt`
- Frontend: `cd frontend && npm install`
