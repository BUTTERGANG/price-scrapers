import { useState, useEffect, useCallback } from 'react';
import { API_BASE } from '../lib/utils';

export default function StatusBar() {
  const [stats, setStats] = useState(null);
  const [freshness, setFreshness] = useState([]);
  const [offline, setOffline] = useState(false);

  const refresh = useCallback(() => {
    fetch(`${API_BASE}/status`)
      .then(r => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json(); })
      .then(d => { setStats(d.db); setOffline(false); })
      .catch((err) => { console.warn('Status check failed:', err); setOffline(true); });
    fetch(`${API_BASE}/freshness`)
      .then(r => r.json())
      .then(d => setFreshness(d.freshness || []))
      .catch((err) => console.warn('Freshness check failed:', err));
  }, []);

  useEffect(() => {
    refresh();
    // Re-check status every 10 minutes
    const id = setInterval(refresh, 10 * 60 * 1000);
    return () => clearInterval(id);
  }, [refresh]);

  const staleCount = freshness.filter(f => f.hours_ago != null && f.hours_ago > 24).length;

  if (offline) {
    return (
      <div className="status-bar">
        <span className="stale-warning">Backend unavailable</span>
      </div>
    );
  }

  if (!stats) return null;

  return (
    <div className="status-bar">
      <span>{stats.total_prices.toLocaleString()} prices</span>
      <span>{stats.retailer_count} retailers</span>
      <span>{stats.total_runs} runs</span>
      {stats.latest_scrape && <span>Last: {new Date(stats.latest_scrape).toLocaleString()}</span>}
      {staleCount > 0 && <span className="stale-warning">{staleCount} stale</span>}
    </div>
  );
}
