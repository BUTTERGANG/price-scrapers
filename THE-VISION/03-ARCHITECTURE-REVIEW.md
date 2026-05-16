# Architecture Review & Technical Debt

## Current Architecture Summary

```
┌─────────────────────────────────────────────────────────────┐
│                    React Dashboard (Vite)                     │
│               Port 5000 → proxies /api → 8000                │
│                                                               │
│  Dashboard │ Deals │ Search │ Compare │ History │ Stores     │
└─────────────────────────┬───────────────────────────────────┘
                          │ REST API
┌─────────────────────────┴───────────────────────────────────┐
│                   FastAPI Backend                              │
│                     Port 8000                                 │
│                                                               │
│  17 endpoints │ Static file serving │ Background scrape thread│
└──────────┬──────────────────────────────────┬───────────────┘
           │                                  │
     ┌─────┴──────┐                    ┌──────┴──────┐
     │ PostgreSQL  │                    │   Scrapers  │
     │  (NeonDB)   │                    │  (14 impl)  │
     │             │                    │             │
     │ prices      │◄───────────────────│ runner.py   │
     │ runs        │                    │ ThreadPool  │
     │ failed_q    │                    │ 4 workers   │
     └─────────────┘                    └─────────────┘
```

## What's Working Well

1. **Modular scraper design** — `BaseScraper` abstract class gives consistent interface; each retailer is isolated in its own file. Adding a new retailer is straightforward.

2. **Data validation pipeline** — `validate.py` catches HTML garbage, deduplicates, warns on anomalies. `unit_price.py` normalizes across different units for true apples-to-apples comparison. This is genuinely well-designed.

3. **Multiple scraping strategies** — The codebase pragmatically uses the right tool for each retailer: plain `requests` where possible, `curl_cffi` for TLS fingerprinting, Playwright for JS-rendered sites, even Claude Vision for PDF circulars. Good engineering tradeoffs.

4. **Frontend UX** — Clean dark theme, responsive grid, good use of Recharts for data visualization. The tab-based navigation covers all the key use cases. Product cards are well-structured.

5. **Error resilience** — Scrapers never crash each other (`_run_one` catches all exceptions), circuit breaker in base class, count-drop detection catches parser breakage.

---

## Architectural Concerns

### 1. Monolithic Frontend (App.jsx = 925 lines)
**Problem:** The entire React app is in a single file. Every component, hook, and view is in `App.jsx`. This makes it hard to navigate, test, or modify individual views.
**Recommendation:** Split into:
```
frontend/src/
  hooks/useLocalStorage.js, useFetch.js
  components/ProductCard.jsx, StatusBadge.jsx, SummaryCard.jsx, Spinner.jsx
  views/Dashboard.jsx, Deals.jsx, Search.jsx, Compare.jsx, History.jsx, ...
  App.jsx (just routing/layout)
```

### 2. Server.py is Manageable but Growing
**Current:** ~310 lines (not 9945 as reported — the file is clean and well-structured).
**Recommendation:** This is fine for now. If more endpoints are added, split into a `routes/` package with FastAPI routers.

### 3. No Connection Pooling
**Problem:** Every API request creates a new PostgreSQL connection, runs schema creation, uses it for one query, then closes it. Under load, this will exhaust connection limits (NeonDB free tier: 5 concurrent).
**Recommendation:** Use `psycopg2.pool.ThreadedConnectionPool` with min=2, max=5 connections. Initialize pool at startup, check out connections per request.

### 4. No Caching Layer
**Problem:** Dashboard summary, store status, departments — these change slowly but are re-queried on every page load.
**Recommendation:** Add simple in-memory caching with TTL:
- Dashboard: 5-minute cache
- Departments: 1-hour cache
- Deals: 5-minute cache
- Store status: 30-second cache

### 5. No Automated Scheduling
**Problem:** Scrapers only run when manually triggered via the UI button or CLI. There's no cron/scheduler.
**Recommendation:** Add a scheduler (APScheduler or cron via Replit) to run scrapers daily. Weekly ad scrapers should run on the day new circulars publish (typically Wednesday for most retailers).

### 6. Frontend Build Not Automated
**Problem:** The `frontend/dist/` directory is committed to git. Changes to `App.jsx` or `index.css` require manually running `npm run build`.
**Recommendation:** Either:
- Add a pre-commit hook that rebuilds the frontend, or
- In production, serve via Vite dev server and remove dist from git, or
- Add a build step to the deployment pipeline

---

## Database Schema Improvements

### Current Schema Gaps

| Issue | Current | Recommended |
|-------|---------|-------------|
| Timestamps | `TEXT` (ISO string) | `TIMESTAMPTZ` for native date math |
| No composite unique index | Allows duplicate inserts for same product in same run | `UNIQUE (retailer, product_id, scraped_at)` |
| No retention policy | Append-only forever | Partition by month, archive after 12 months |
| Missing full-text search | `LOWER(name)` index, `LIKE '%query%'` | `tsvector` column + GIN index for fast text search |
| `extra_json` as TEXT | Stored as JSON string, parsed client-side | Use `JSONB` column for server-side queries |

---

## Dependency Notes

| Package | Version | Notes |
|---------|---------|-------|
| `react` | 19.2 | Latest stable, good |
| `fastapi` | >=0.110 | Good, but pin exact version for reproducibility |
| `psycopg2-binary` | >=2.9.9 | Binary wheel — fine for Replit but use `psycopg2` for production |
| `curl-cffi` | >=0.7.0 | Niche package, watch for breaking changes |
| `playwright` | >=1.43.0 | Heavy dependency only needed for Costco (which is blocked anyway) |
| `anthropic` | >=0.20.0 | Only needed for Needler's circular; good optional dep |

**Recommendation:** Pin exact versions in `requirements.txt` for reproducible builds. Use `>=` only in setup.py/pyproject.toml.
