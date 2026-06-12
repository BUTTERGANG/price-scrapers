import { useState, useEffect, useCallback, useMemo } from 'react';
import { API_BASE, FIVE_MIN } from '../lib/utils';
import { ProductCard, SkeletonGrid, DataFreshnessBar } from './Shared';

export default function WatchlistView({ watchlist, toggleWatchlist, priceAlerts, setPriceAlerts }) {
  const [liveItems, setLiveItems] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [lastFetched, setLastFetched] = useState(null);

  const fetchLivePrices = useCallback(async () => {
    if (watchlist.length === 0) { setLiveItems([]); return; }
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`${API_BASE}/watchlist/prices`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(watchlist.map(w => ({ retailer: w.retailer, product_id: w.product_id }))),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      // For items where live data was found, use it; otherwise fall back to stored stub
      const liveMap = {};
      (data.prices || []).forEach(p => { liveMap[`${p.retailer}::${p.product_id}`] = p; });
      const merged = watchlist.map(w => liveMap[`${w.retailer}::${w.product_id}`] || w);
      setLiveItems(merged);
      setLastFetched(new Date());
    } catch (err) {
      console.warn('Watchlist fetch failed:', err);
      setError(err.message);
      setLiveItems(watchlist); // fall back to stored data
    } finally {
      setLoading(false);
    }
  }, [watchlist]);

  useEffect(() => { fetchLivePrices(); }, [fetchLivePrices]);

  // Auto-refresh watchlist prices every 5 minutes
  useEffect(() => {
    if (watchlist.length === 0) return;
    const id = setInterval(fetchLivePrices, FIVE_MIN);
    return () => clearInterval(id);
  }, [fetchLivePrices, watchlist.length]);

  const watchedIds = new Set(watchlist.map(w => `${w.retailer}::${w.product_id}`));

  const triggeredAlerts = useMemo(() => {
    const triggered = new Set();
    liveItems.forEach(item => {
      const key = `${item.retailer}::${item.product_id}`;
      const target = priceAlerts[key];
      if (target != null) {
        const current = item.sale_price != null ? item.sale_price : item.price;
        if (current != null && current <= target) triggered.add(key);
      }
    });
    return triggered;
  }, [liveItems, priceAlerts]);

  if (watchlist.length === 0) {
    return (
      <div className="empty">
        <span className="empty-icon">⭐</span>
        <div className="empty-title">Your watchlist is empty</div>
        <div className="empty-desc">Star any product from Deals or Search to track its price here. Never miss a deal again.</div>
      </div>
    );
  }

  return (
    <div>
      <div className="filter-bar">
        <span className="result-count">{watchlist.length} item{watchlist.length !== 1 ? 's' : ''} tracked</span>
        <button className="refresh-btn" onClick={fetchLivePrices} disabled={loading}>
          {loading ? 'Refreshing...' : 'Refresh Prices'}
        </button>
        <DataFreshnessBar lastFetched={lastFetched} />
      </div>
      {loading && <SkeletonGrid />}
      {error && <div className="error" style={{ marginBottom: '1rem' }}>Could not fetch live prices: {error}</div>}
      {!loading && (
        <div className="grid">
          {liveItems.map((item, idx) => {
            const key = `${item.retailer}::${item.product_id}`;
            const targetPrice = priceAlerts[key] ?? '';
            const isTriggered = triggeredAlerts.has(key);
            return (
              <div key={`${item.retailer}-${item.product_id}-${idx}`} className={`watchlist-item-wrap ${isTriggered ? 'alert-triggered' : ''}`}>
                <ProductCard
                  item={item}
                  onWatchlist={toggleWatchlist}
                  isWatched={watchedIds.has(key)}
                />
                <div className="alert-row">
                  {isTriggered && <span className="alert-badge">🔔 Price alert!</span>}
                  <label className="alert-label">Alert when ≤</label>
                  <span className="alert-input-wrap">
                    <span className="alert-dollar">$</span>
                    <input
                      type="number"
                      className="alert-input"
                      placeholder="—"
                      min="0"
                      step="0.01"
                      value={targetPrice}
                      onChange={(e) => {
                        const val = e.target.value;
                        setPriceAlerts(prev => {
                          if (val === '' || val == null) {
                            const next = { ...prev };
                            delete next[key];
                            return next;
                          }
                          return { ...prev, [key]: parseFloat(val) };
                        });
                      }}
                    />
                  </span>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
