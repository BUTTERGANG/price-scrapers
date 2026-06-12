import { useState, useMemo } from 'react';
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend,
} from 'recharts';
import { API_BASE, CHART_COLORS, fmtPrice, fmtUnitPrice } from '../lib/utils';
import { Spinner } from './Shared';

export default function HistoryView() {
  const [query, setQuery] = useState('');
  const [history, setHistory] = useState([]);
  const [trends, setTrends] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [searched, setSearched] = useState(false);
  const [dateRange, setDateRange] = useState('30d');

  const doSearch = async (e) => {
    if (e) e.preventDefault();
    if (!query.trim()) return;
    setLoading(true); setError(null); setSearched(true);
    setHistory([]); setTrends([]);
    try {
      const [histRes, trendRes] = await Promise.all([
        fetch(`${API_BASE}/history?q=${encodeURIComponent(query)}&limit=200`),
        fetch(`${API_BASE}/trends?q=${encodeURIComponent(query)}&limit=500`),
      ]);
      if (!histRes.ok) throw new Error(`HTTP ${histRes.status}`);
      const histData = await histRes.json();
      setHistory(histData.history || []);
      if (trendRes.ok) {
        const trendData = await trendRes.json();
        setTrends(trendData.trends || []);
      } else {
        setTrends([]);
      }
    } catch (err) { setError(err.message); }
    finally { setLoading(false); }
  };

  const cutoffDate = useMemo(() => {
    if (dateRange === 'all') return null;
    const days = dateRange === '7d' ? 7 : dateRange === '30d' ? 30 : 90;
    const d = new Date();
    d.setDate(d.getDate() - days);
    return d.toISOString().slice(0, 10);
  }, [dateRange]);

  // Build chart data: group by date, one line per retailer
  const chartData = useMemo(() => {
    if (!trends.length) return { data: [], retailers: [] };
    const filtered = cutoffDate ? trends.filter(t => (t.scraped_at || '').slice(0, 10) >= cutoffDate) : trends;
    const byDate = {};
    const retailers = new Set();
    filtered.forEach(t => {
      const day = t.scraped_at?.slice(0, 10);
      if (!day) return;
      retailers.add(t.retailer);
      if (!byDate[day]) byDate[day] = { date: day };
      const effective = t.sale_price != null ? t.sale_price : t.price;
      if (!byDate[day][t.retailer] || effective < byDate[day][t.retailer]) {
        byDate[day][t.retailer] = effective;
      }
    });
    return { data: Object.values(byDate).sort((a, b) => a.date.localeCompare(b.date)), retailers: Array.from(retailers) };
  }, [trends, cutoffDate]);

  const grouped = useMemo(() => {
    const g = {};
    const filteredHistory = cutoffDate ? history.filter(h => (h.scraped_at || '').slice(0, 10) >= cutoffDate) : history;
    filteredHistory.forEach(h => {
      if (!g[h.retailer]) g[h.retailer] = [];
      g[h.retailer].push(h);
    });
    return g;
  }, [history, cutoffDate]);

  const hasResults = chartData.data.length > 0 || Object.keys(grouped).length > 0;

  return (
    <div>
      <form className="search-bar" onSubmit={doSearch} style={{ marginBottom: '2rem' }}>
        <input type="text" placeholder="Search price history (e.g. eggs, almond milk, chicken)..." value={query} onChange={(e) => setQuery(e.target.value)} />
        <button type="submit">Search</button>
      </form>
      {searched && !loading && (
        <div className="date-range-picker">
          {[['7d','7 Days'], ['30d','30 Days'], ['90d','90 Days'], ['all','All Time']].map(([val, label]) => (
            <button
              key={val}
              className={`date-range-btn ${dateRange === val ? 'active' : ''}`}
              onClick={() => setDateRange(val)}
            >
              {label}
            </button>
          ))}
        </div>
      )}
      {loading && <Spinner />}
      {error && <div className="error">Error: {error}</div>}

      {!loading && !error && searched && !hasResults && (
        <div className="empty">
          <span className="empty-icon">📈</span>
          <div className="empty-title">No price history found</div>
          <div className="empty-desc">No historical records for "{query}". Try a different term or run a scrape to collect fresh data.</div>
        </div>
      )}

      {!loading && !error && chartData.data.length > 0 && (
        <div className="chart-card" style={{ marginBottom: '2rem' }}>
          <h3>Price Trends — {query}</h3>
          <ResponsiveContainer width="100%" height={300}>
            <LineChart data={chartData.data}>
              <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.1)" />
              <XAxis dataKey="date" tick={{ fill: '#94a3b8', fontSize: 12 }} tickFormatter={v => v.slice(5)} />
              <YAxis tick={{ fill: '#94a3b8', fontSize: 12 }} tickFormatter={v => `$${v}`} />
              <Tooltip contentStyle={{ background: '#1e293b', border: '1px solid rgba(255,255,255,0.1)', borderRadius: 8, color: '#f8fafc' }} formatter={v => fmtPrice(v)} />
              <Legend />
              {chartData.retailers.map((r, i) => (
                <Line key={r} type="monotone" dataKey={r} stroke={CHART_COLORS[i % CHART_COLORS.length]} strokeWidth={2} dot={false} connectNulls />
              ))}
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}

      {!loading && !error && Object.keys(grouped).length > 0 && (
        <div className="history-groups">
          {Object.entries(grouped).map(([retailer, items]) => (
            <div key={retailer} className="history-group">
              <h3 className="history-retailer">{retailer}</h3>
              <table className="compare-table">
                <thead>
                  <tr><th>Product</th><th>Price</th><th>Sale</th><th>Unit Price</th><th>Scraped</th></tr>
                </thead>
                <tbody>
                  {items.map((h, idx) => (
                    <tr key={idx}>
                      <td className="name-cell">{h.name}</td>
                      <td>{fmtPrice(h.price)}</td>
                      <td>{h.sale_price ? <span className="sale-price">{fmtPrice(h.sale_price)}</span> : '--'}</td>
                      <td>{fmtUnitPrice(h.unit_price_normalized, h.unit_canonical)}</td>
                      <td className="date-cell">{new Date(h.scraped_at).toLocaleDateString()}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
