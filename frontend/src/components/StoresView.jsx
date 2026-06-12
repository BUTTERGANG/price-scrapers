import { useState, useEffect, useCallback, useRef } from 'react';
import { API_BASE, timeAgo, fmtPrice, fmtPct, getDeptIcon } from '../lib/utils';
import { StatusBadge, Spinner, SummaryCard } from './Shared';

export default function StoresView() {
  const [stores, setStores] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [scraping, setScraping] = useState(false);
  const [selectedStore, setSelectedStore] = useState(null);
  const [analytics, setAnalytics] = useState(null);
  const [analyticsLoading, setAnalyticsLoading] = useState(false);
  const pollRef = useRef(null);

  // Clear any running poll on unmount
  useEffect(() => {
    return () => { if (pollRef.current) clearInterval(pollRef.current); };
  }, []);

  const fetchStores = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetch(`${API_BASE}/stores`);
      if (!res.ok) throw new Error('Failed to fetch stores');
      setStores((await res.json()).stores || []);
    } catch (err) { setError(err.message); }
    finally { setLoading(false); }
  }, []);

  useEffect(() => { fetchStores(); }, [fetchStores]);

  const triggerScrape = async () => {
    setScraping(true);
    setError(null);
    try {
      const res = await fetch(`${API_BASE}/scrape`, { method: 'POST' });
      if (res.status === 409) {
        setError('A scrape is already running. Please wait.');
        setScraping(false);
        return;
      }
      if (!res.ok) throw new Error('Failed to trigger scrape');
      // Poll for completion; interval is cleared on unmount via pollRef
      pollRef.current = setInterval(async () => {
        try {
          const statusRes = await fetch(`${API_BASE}/scrape/status`);
          if (statusRes.ok) {
            const statusData = await statusRes.json();
            if (!statusData.running) {
              clearInterval(pollRef.current);
              pollRef.current = null;
              setScraping(false);
              fetchStores();
            }
          }
        } catch (err) {
          console.warn('Scrape status poll failed:', err);
        }
      }, 3000);
    } catch (err) { setError(err.message); setScraping(false); }
  };

  const loadAnalytics = async (retailer) => {
    setSelectedStore(retailer);
    setAnalyticsLoading(true);
    try {
      const res = await fetch(`${API_BASE}/stores/${encodeURIComponent(retailer)}/analytics`);
      if (res.ok) setAnalytics(await res.json());
    } catch (err) {
      console.warn('Failed to load analytics:', err);
    } finally { setAnalyticsLoading(false); }
  };

  return (
    <div>
      <div className="filter-bar">
        <button className="scrape-btn" onClick={triggerScrape} disabled={scraping}>
          {scraping ? 'Starting...' : 'Run All Scrapers'}
        </button>
        <button className="refresh-btn" onClick={fetchStores}>Refresh</button>
      </div>
      {loading && <Spinner />}
      {error && <div className="error">Error: {error}</div>}
      {!loading && !error && (
        <div className="stores-grid">
          {stores.map((store) => (
            <div key={store.retailer} className={`store-card ${selectedStore === store.retailer ? 'store-selected' : ''}`} onClick={() => loadAnalytics(store.retailer)} style={{ cursor: 'pointer' }}>
              <div className="store-header">
                <span className="store-name">{store.retailer}</span>
                <StatusBadge status={store.status} />
              </div>
              <div className="store-stats">
                <div>
                  <span className="stat-label">Records</span>
                  <span className="stat-value">{store.records_saved || 0}</span>
                </div>
                <div>
                  <span className="stat-label">Last Run</span>
                  <span className="stat-value">{timeAgo(store.finished_at)}</span>
                </div>
              </div>
              {store.error && <div className="store-error">{store.error}</div>}
            </div>
          ))}
        </div>
      )}

      {selectedStore && (
        <div className="analytics-panel">
          <div className="analytics-panel-header">
            <span className="analytics-store-icon">🏪</span>
            <h3>{selectedStore} Analytics</h3>
          </div>
          {analyticsLoading ? <Spinner /> : analytics && (
            <div>
              <div className="summary-grid" style={{ marginBottom: '1.5rem' }}>
                <SummaryCard
                  label="Products"
                  value={analytics.summary?.product_count?.toLocaleString()}
                  icon="📦"
                  accent="linear-gradient(90deg, #3b82f6, #6366f1)"
                />
                <SummaryCard
                  label="Avg Price"
                  value={fmtPrice(analytics.summary?.avg_price)}
                  icon="💲"
                  accent="linear-gradient(90deg, #64748b, #475569)"
                />
                <SummaryCard
                  label="Deals"
                  value={analytics.summary?.deal_count?.toLocaleString()}
                  color="var(--green)"
                  icon="🏷️"
                  accent="linear-gradient(90deg, #22c55e, #16a34a)"
                />
                <SummaryCard
                  label="Avg Discount"
                  value={fmtPct(analytics.summary?.avg_discount_pct)}
                  color="#f59e0b"
                  icon="💰"
                  accent="linear-gradient(90deg, #f59e0b, #d97706)"
                />
              </div>

              {analytics.departments?.length > 0 && (
                <div className="analytics-section">
                  <h4>Departments</h4>
                  <div className="dept-list">
                    {analytics.departments.slice(0, 10).map((d, i) => (
                      <div key={i} className="dept-row">
                        <span className="dept-row-name">{getDeptIcon(d.department)} {d.department || 'Other'}</span>
                        <span className="dept-row-count">{d.cnt} items</span>
                        <span className="dept-row-price">avg {fmtPrice(d.avg_price)}</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {analytics.recent_runs?.length > 0 && (
                <div className="analytics-section">
                  <h4>Recent Runs</h4>
                  <div className="compare-table-wrap">
                    <table className="compare-table">
                      <thead>
                        <tr><th>Status</th><th>Records</th><th>Started</th><th>Finished</th></tr>
                      </thead>
                      <tbody>
                        {analytics.recent_runs.map((run, i) => (
                          <tr key={i}>
                            <td><StatusBadge status={run.status} /></td>
                            <td style={{ fontVariantNumeric: 'tabular-nums' }}>{run.records_saved}</td>
                            <td className="date-cell">{run.started_at ? new Date(run.started_at).toLocaleString() : '—'}</td>
                            <td className="date-cell">{run.finished_at ? new Date(run.finished_at).toLocaleString() : '—'}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
