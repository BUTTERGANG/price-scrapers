import { useMemo } from 'react';
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, ReferenceLine,
} from 'recharts';
import { useFetch } from '../lib/hooks';
import { API_BASE, fmtPrice, priceSignal } from '../lib/utils';
import { Spinner } from './Shared';

export default function PriceHistoryModal({ item, onClose }) {
  const { retailer, product_id, name } = item;
  const url = retailer && product_id
    ? `${API_BASE}/history?retailer=${encodeURIComponent(retailer)}&product_id=${encodeURIComponent(product_id)}&limit=500`
    : null;
  const { data, loading, error } = useFetch(url);

  const stats = useMemo(() => {
    const rows = data?.history || [];
    // API returns newest-first; chart wants chronological order.
    const chrono = [...rows].reverse().map(h => ({
      date: h.scraped_at,
      price: h.sale_price != null ? h.sale_price : h.price,
    })).filter(p => p.price != null && p.price > 0);

    if (chrono.length === 0) return null;

    const prices = chrono.map(p => p.price);
    const min = Math.min(...prices);
    const max = Math.max(...prices);
    const avg = prices.reduce((a, b) => a + b, 0) / prices.length;
    const current = prices[prices.length - 1];

    // Recharts' 'dataMin - 1' domain strings misbehave when the range is
    // zero (flat price history), so pad an explicit numeric domain instead.
    const range = max - min;
    const pad = range > 0 ? range * 0.15 : Math.max(avg * 0.08, 0.25);
    const yDomain = [Math.max(0, min - pad), max + pad];

    return { chrono, min, max, avg, current, count: prices.length, yDomain };
  }, [data]);

  const signal = stats ? priceSignal(stats.current, stats.min, stats.avg, stats.count) : null;

  return (
    <>
      <div className="history-modal-overlay" onClick={onClose} />
      <div className="history-modal" role="dialog" aria-modal="true" aria-label={`Price history for ${name}`}>
        <div className="history-modal-header">
          <div>
            <div className="history-modal-retailer">{retailer}</div>
            <h3 className="history-modal-title">{name}</h3>
          </div>
          <button className="history-modal-close" onClick={onClose} aria-label="Close">✕</button>
        </div>

        {loading && <Spinner />}
        {error && <div className="error">Error: {error}</div>}

        {!loading && !error && !stats && (
          <div className="empty">
            <span className="empty-icon">📈</span>
            <div className="empty-title">No price history yet</div>
            <div className="empty-desc">This item hasn't been scraped more than once. Check back after the next scrape run.</div>
          </div>
        )}

        {!loading && !error && stats && (
          <>
            <div className={`price-signal price-signal-${signal.tone}`}>
              <span className="price-signal-icon" aria-hidden="true">{signal.icon}</span>
              {signal.label}
            </div>

            <div className="price-stats-row">
              <div className="price-stat">
                <span className="price-stat-label">Current</span>
                <span className="price-stat-value">{fmtPrice(stats.current)}</span>
              </div>
              <div className="price-stat">
                <span className="price-stat-label">Lowest</span>
                <span className="price-stat-value price-stat-low">{fmtPrice(stats.min)}</span>
              </div>
              <div className="price-stat">
                <span className="price-stat-label">Average</span>
                <span className="price-stat-value">{fmtPrice(stats.avg)}</span>
              </div>
              <div className="price-stat">
                <span className="price-stat-label">Highest</span>
                <span className="price-stat-value price-stat-high">{fmtPrice(stats.max)}</span>
              </div>
            </div>

            <ResponsiveContainer width="100%" height={240}>
              <LineChart data={stats.chrono} margin={{ top: 8, right: 12, bottom: 0, left: -10 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.08)" vertical={false} />
                <XAxis
                  dataKey="date"
                  tick={{ fill: '#64748b', fontSize: 11 }}
                  tickFormatter={v => new Date(v).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })}
                  axisLine={false}
                  tickLine={false}
                />
                <YAxis
                  tick={{ fill: '#64748b', fontSize: 11 }}
                  tickFormatter={v => `$${v.toFixed(2)}`}
                  axisLine={false}
                  tickLine={false}
                  domain={stats.yDomain}
                />
                <Tooltip
                  contentStyle={{ background: '#0f172a', border: '1px solid rgba(255,255,255,0.1)', borderRadius: 10, color: '#f1f5f9', fontSize: 13 }}
                  labelFormatter={v => new Date(v).toLocaleString()}
                  formatter={v => [fmtPrice(v), 'Price']}
                />
                <ReferenceLine y={stats.avg} stroke="#8b5cf6" strokeDasharray="4 4" />
                <ReferenceLine y={stats.min} stroke="#22c55e" strokeDasharray="3 3" />
                <Line type="monotone" dataKey="price" stroke="#3b82f6" strokeWidth={2} dot={{ r: 2 }} activeDot={{ r: 5 }} connectNulls />
              </LineChart>
            </ResponsiveContainer>
            <div className="history-modal-legend">
              <span><span className="legend-dot" style={{ background: '#8b5cf6' }} /> Average</span>
              <span><span className="legend-dot" style={{ background: '#22c55e' }} /> Lowest ever</span>
            </div>
          </>
        )}
      </div>
    </>
  );
}
