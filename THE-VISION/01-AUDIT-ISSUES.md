# Code Audit: Issues & Bugs Found

## Critical Issues

### 1. Database Connection Leak Risk
**File:** `server.py` — every endpoint
**Issue:** Each API endpoint opens a new `get_conn()` and closes it in a `finally` block, but `get_conn()` calls `_ensure_schema()` on every single request. This means every API call runs 6+ `CREATE TABLE IF NOT EXISTS` and `CREATE INDEX IF NOT EXISTS` statements — a significant performance hit on every request.
**Fix:** Run `_ensure_schema()` once at startup, not per-connection. Use connection pooling (e.g., `psycopg2.pool.ThreadedConnectionPool`) instead of creating a new connection per request.

### 2. Thread Safety with Shared DB Connection
**File:** `runner.py:264`
**Issue:** `run_retailers()` passes a single `conn` object to all parallel workers via `ThreadPoolExecutor`. While there's a `_write_lock` for writes, the psycopg2 connection object itself is not thread-safe for concurrent operations. Multiple threads sharing one connection can cause silent data corruption or `InterfaceError` exceptions.
**Fix:** Each worker thread should create its own database connection, or use a thread-safe connection pool.

### 3. CORS Wildcard with Credentials
**File:** `server.py:39-45`
```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,  # <-- problem
)
```
**Issue:** `allow_origins=["*"]` with `allow_credentials=True` is a security misconfiguration. Browsers actually reject this combination per the CORS spec, so credentials won't work. Either restrict origins or remove `allow_credentials`.

### 4. Validate.py Logic Bug
**File:** `utils/validate.py:120`
```python
if 0 < price > _PRICE_MAX:
```
**Issue:** This is a chained comparison that reads as `(0 < price) and (price > _PRICE_MAX)`. This only warns when price > 500. But it will never catch prices between 0 and 500 for the "unusually high" check — that's actually the *intended* behavior. However, the `0 <` prefix is misleading and unnecessary. It should just be `if price > _PRICE_MAX:`.

### 5. Background Scrape Has No Concurrency Guard
**File:** `server.py:278-305`
**Issue:** The `/api/scrape` POST endpoint spawns a background thread with no guard against multiple simultaneous scrape runs. Clicking "Run All Scrapers" multiple times will launch parallel full scrape runs competing for rate limits, DB writes, and browser instances.
**Fix:** Add a global `_scrape_running` flag or threading.Lock to prevent concurrent scrape runs.

---

## Backend Issues

### 6. Docstring Says "SQLite" but Using PostgreSQL
**File:** `runner.py:240`
```python
conn:    SQLite connection from get_conn().
```
**Issue:** The docstring references SQLite but the actual database is PostgreSQL (NeonDB). This is likely a leftover from an earlier version.

### 7. No Request Timeout on API Endpoints
**File:** `server.py` — all endpoints
**Issue:** Database queries have no timeout. A slow query (e.g., full-table scan on `prices` for a common search term) will hold the request open indefinitely and block the uvicorn worker.

### 8. `scraped_at` Stored as TEXT, Not TIMESTAMP
**File:** `utils/db.py:58`
**Issue:** The `scraped_at` column is `TEXT NOT NULL` instead of `TIMESTAMPTZ`. This means date comparisons and sorting rely on string ordering, which works for ISO 8601 but prevents using PostgreSQL's native date functions efficiently (e.g., `interval`, `date_trunc`).

### 9. No Pagination on Most Endpoints
**File:** `server.py` — `/api/deals`, `/api/search`, `/api/compare`, `/api/stores`
**Issue:** These endpoints return all matching records with no limit or pagination. As the database grows, these responses will become increasingly large and slow.

---

## Frontend Issues

### 10. useFetch Hook Has Deps Array Anti-Pattern
**File:** `frontend/src/App.jsx:44`
```javascript
}, [url, ...deps]);
```
**Issue:** Spreading `deps` into the dependency array of `useCallback` can cause infinite re-renders if the caller passes a new array reference on each render. The `deps` parameter should be avoided or the hook should use a ref to stabilize the dependency.

### 11. Watchlist Shows Stale Data
**File:** `frontend/src/App.jsx:674-695`
**Issue:** The `WatchlistView` renders items from `localStorage` — these are snapshots from when the item was added. Prices, sale status, and deal text are frozen at the time of starring. There's no mechanism to refresh watchlist items with current data.
**Fix:** Store only `{ retailer, product_id, name }` in the watchlist and fetch current data from the API.

### 12. Empty Catch Blocks Swallow Errors
**Files:** `App.jsx:97`, `App.jsx:629`, `App.jsx:738`
```javascript
try { ... } catch (e) {}   // silent failure
try { ... } catch {}        // silent failure
```
**Issue:** Multiple places silently swallow errors, making debugging impossible. At minimum, log to console.

### 13. No Loading/Error State for StatusBar
**File:** `frontend/src/App.jsx:840-841`
**Issue:** `StatusBar` fires two fetches on mount with `.catch(() => {})` — if the backend is down, the status bar silently shows nothing with no indication of a problem.

### 14. No Debounce on Search
**File:** `frontend/src/App.jsx:336-346`
**Issue:** Search fires immediately on form submit which is fine, but if someone adds real-time search-as-you-type later, there's no debounce infrastructure. Current UX requires explicit submit which is actually good — just noting for future.

---

## Data Quality Issues

### 15. Unit Price Display Inconsistency
**File:** `frontend/src/App.jsx:131` vs `App.jsx:457`
**Issue:** Two different formatting rules for unit prices:
- ProductCard: `< 0.1 ? .toFixed(4) : .toFixed(2)`
- Compare table: same logic but duplicated

This should be extracted into a shared `fmtUnitPrice()` helper to ensure consistency.

### 16. No Data Expiration / Retention Policy
**File:** `utils/db.py`
**Issue:** The `prices` table is append-only with no retention policy. Over time, this table will grow indefinitely, slowing down queries. There's no mechanism to archive or purge old data.
