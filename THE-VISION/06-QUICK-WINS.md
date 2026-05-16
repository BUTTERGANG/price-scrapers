# Quick Wins — High Impact, Low Effort

Changes that can be made in a single session with immediate user-visible improvement.

---

## 1. Fix the Schema-Per-Request Performance Issue
**Effort:** 15 minutes | **Impact:** Every API call gets faster

Move `_ensure_schema()` out of `get_conn()` and call it once at server startup:

```python
# server.py — at module level, after app creation
conn = get_conn()
_ensure_schema(conn)  # run once
conn.close()
```

Then remove the `_ensure_schema(conn)` call from inside `get_conn()`.

---

## 2. Add Scrape Concurrency Guard
**Effort:** 10 minutes | **Impact:** Prevents accidental double-scrapes

```python
_scrape_lock = threading.Lock()
_scrape_running = False

@app.post("/api/scrape")
def trigger_scrape(...):
    global _scrape_running
    if _scrape_running:
        return JSONResponse(status_code=409, content={"error": "Scrape already running"})
    ...
```

---

## 3. Extract Shared UI Helpers
**Effort:** 20 minutes | **Impact:** Cleaner code, consistent formatting

Pull `fmtPrice`, `fmtPct`, `timeAgo`, and add `fmtUnitPrice` into a `utils.js` file:

```javascript
export const fmtUnitPrice = (value, canonical) => {
  if (!value || !canonical) return '--';
  const formatted = value < 0.1 ? value.toFixed(4) : value.toFixed(2);
  return `$${formatted} ${canonical.replace('per_', '/')}`;
};
```

---

## 4. Add Console Logging to Empty Catches
**Effort:** 5 minutes | **Impact:** Debugging becomes possible

Replace all `catch {}` and `catch (e) {}` with `catch (e) { console.warn(e); }`.

---

## 5. Fix the SQLite Docstring
**Effort:** 1 minute | **Impact:** Correct documentation

In `runner.py:240`, change `SQLite connection from get_conn()` to `PostgreSQL connection from get_conn()`.

---

## 6. Add aria-labels to Icon Buttons
**Effort:** 10 minutes | **Impact:** Accessibility compliance

```jsx
<button aria-label={isWatched ? 'Remove from watchlist' : 'Add to watchlist'}>
  {isWatched ? '★' : '☆'}
</button>
```

---

## 7. Show "Backend Unavailable" State
**Effort:** 15 minutes | **Impact:** Users know when something's wrong

Add an error banner when the `/api/status` health check fails:

```jsx
function StatusBar() {
  const [offline, setOffline] = useState(false);
  // ...
  fetch(`${API_BASE}/status`).then(...).catch(() => setOffline(true));

  if (offline) return <div className="offline-banner">Backend unavailable</div>;
}
```

---

## 8. Add Popular Searches to Empty Search State
**Effort:** 10 minutes | **Impact:** Guides new users

```jsx
{!searched && (
  <div className="search-suggestions">
    <p>Popular searches:</p>
    {['milk', 'eggs', 'bread', 'chicken breast', 'bananas'].map(q => (
      <button key={q} onClick={() => { setQuery(q); doSearch(); }}>{q}</button>
    ))}
  </div>
)}
```

---

## 9. Disable "Run All Scrapers" While Scraping
**Effort:** 5 minutes | **Impact:** Prevents user confusion

The button already has `disabled={scraping}`, but the state resets after the POST returns (which is immediate). Keep it disabled until store status shows completion:

```jsx
const triggerScrape = async () => {
  setScraping(true);
  try {
    await fetch(`${API_BASE}/scrape`, { method: 'POST' });
    // Poll for completion instead of fixed 5s timeout
    const poll = setInterval(async () => {
      const res = await fetch(`${API_BASE}/stores`);
      const data = await res.json();
      const running = data.stores.some(s => s.status === 'running');
      if (!running) { clearInterval(poll); setScraping(false); fetchStores(); }
    }, 3000);
  } catch (err) { setError(err.message); setScraping(false); }
};
```

---

## 10. Add Retailer Count to Dashboard Header
**Effort:** 5 minutes | **Impact:** Users immediately see coverage

Add to the status bar: "14 retailers | 13 active | 2 blocked"
