import { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import {
  AreaChart, Area, LineChart, Line, BarChart, Bar, Cell,
  XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend,
} from 'recharts';
import './index.css';

const API_BASE = '/api';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function useLocalStorage(key, initial) {
  const [value, setValue] = useState(() => {
    try {
      const stored = localStorage.getItem(key);
      return stored ? JSON.parse(stored) : initial;
    } catch { return initial; }
  });
  useEffect(() => {
    localStorage.setItem(key, JSON.stringify(value));
  }, [key, value]);
  return [value, setValue];
}

function useFetch(url, refreshIntervalMs = 0) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [lastFetched, setLastFetched] = useState(null);
  const fetchData = useCallback(async () => {
    if (!url) return;
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(url);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setData(await res.json());
      setLastFetched(new Date());
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }, [url]);
  useEffect(() => { fetchData(); }, [fetchData]);
  useEffect(() => {
    if (!refreshIntervalMs) return;
    const id = setInterval(fetchData, refreshIntervalMs);
    return () => clearInterval(id);
  }, [fetchData, refreshIntervalMs]);
  return { data, loading, error, refetch: fetchData, lastFetched };
}

const timeAgo = (ts) => {
  if (!ts) return 'Never';
  const diff = Date.now() - new Date(ts).getTime();
  const hours = Math.floor(diff / 3600000);
  if (hours < 1) return 'Just now';
  if (hours < 24) return `${hours}h ago`;
  return `${Math.floor(hours / 24)}d ago`;
};

const fmtPrice = (v) => v != null ? `$${Number(v).toFixed(2)}` : '--';
const fmtPct = (v) => v != null ? `${Number(v).toFixed(1)}%` : '--';
const fmtUnitPrice = (value, canonical) => {
  if (!value || !canonical) return '--';
  const formatted = value < 0.1 ? value.toFixed(4) : value.toFixed(2);
  return `$${formatted} ${canonical.replace('per_', '/')}`;
};

const CHART_COLORS = ['#3b82f6', '#8b5cf6', '#22c55e', '#f59e0b', '#ef4444', '#06b6d4', '#ec4899', '#84cc16'];

const RETAILER_COLORS = {
  'kroger':        '#0072CE',
  'meijer':        '#e01933',
  'walmart':       '#0071CE',
  'aldi':          '#ef7c00',
  'target':        '#cc0000',
  'whole foods':   '#00674b',
  'fresh thyme':   '#5aab19',
  'costco':        '#e31837',
  'giant eagle':   '#008000',
  'fresh market':  '#8b4513',
  'gfs':           '#1a5276',
  'needlers':      '#6a0dad',
  'harvest market':'#2e7d32',
  'gordon food':   '#1a5276',
};

const getRetailerColor = (name) => {
  if (!name) return '#64748b';
  const key = name.toLowerCase();
  for (const [k, v] of Object.entries(RETAILER_COLORS)) {
    if (key.includes(k)) return v;
  }
  return '#64748b';
};

const DEPT_ICONS = {
  'Produce': '🥦', 'Fruits': '🍎', 'Vegetables': '🥕', 'Dairy': '🥛', 'Eggs': '🥚',
  'Meat': '🥩', 'Seafood': '🐟', 'Bakery': '🍞', 'Frozen': '🧊', 'Beverages': '🧃',
  'Snacks': '🍿', 'Pantry': '🥫', 'Deli': '🧀', 'Cereal': '🌾', 'Pasta': '🍝',
  'Canned': '🥫', 'Cleaning': '🧹', 'Personal Care': '🧴', 'Baby': '🍼',
  'Pet': '🐾', 'Organic': '🌿', 'International': '🌍', 'Dips': '🫙',
};

const getDeptIcon = (name) => {
  if (!name) return '🛒';
  for (const [key, icon] of Object.entries(DEPT_ICONS)) {
    if (name.toLowerCase().includes(key.toLowerCase())) return icon;
  }
  return '🛒';
};

// ---------------------------------------------------------------------------
// Shared components
// ---------------------------------------------------------------------------

function StatusBadge({ status }) {
  const styles = {
    success:   { bg: 'rgba(34,197,94,0.15)',   color: '#4ade80',  border: 'rgba(34,197,94,0.3)',   dot: '#22c55e' },
    partial:   { bg: 'rgba(250,204,21,0.15)',   color: '#fde047',  border: 'rgba(250,204,21,0.3)',  dot: '#eab308' },
    failed:    { bg: 'rgba(239,68,68,0.15)',    color: '#fca5a5',  border: 'rgba(239,68,68,0.3)',   dot: '#ef4444' },
    running:   { bg: 'rgba(59,130,246,0.15)',   color: '#93c5fd',  border: 'rgba(59,130,246,0.3)',  dot: '#3b82f6' },
    never_run: { bg: 'rgba(100,116,139,0.12)',  color: '#94a3b8',  border: 'rgba(100,116,139,0.2)', dot: '#64748b' },
  };
  const s = styles[status] || styles.never_run;
  const label = status === 'never_run' ? 'Never Run' : status.charAt(0).toUpperCase() + status.slice(1);
  return (
    <span className="status-badge" style={{ background: s.bg, color: s.color, borderColor: s.border, border: `1px solid ${s.border}` }}>
      <span style={{ display: 'inline-block', width: 6, height: 6, borderRadius: '50%', background: s.dot, marginRight: 5, verticalAlign: 'middle', flexShrink: 0 }} />
      {label}
    </span>
  );
}

function ProductCard({ item, onHistoryClick, onWatchlist, isWatched, isCheapest = false }) {
  const effectivePrice = item.sale_price != null ? item.sale_price : item.price;
  const isSale = item.sale_price != null && item.sale_price > 0;
  let savingsPct = null;
  let dealQuality = '';

  if (isSale && item.price && item.price > item.sale_price) {
    savingsPct = Math.round(((item.price - item.sale_price) / item.price) * 100);
    dealQuality = savingsPct >= 30 ? 'hot-deal' : savingsPct >= 20 ? 'good-deal' : '';
  }

  let dealText = null;
  let imageUrl = null;
  if (item.extra_json) {
    try {
      const extra = JSON.parse(item.extra_json);
      dealText = extra.deal_text || extra.sale_story;
      imageUrl = extra.image_url || null;
    } catch (e) {
      console.warn('Failed to parse extra_json:', e);
    }
  }

  const priceInt = effectivePrice != null && effectivePrice > 0
    ? Math.floor(effectivePrice).toString()
    : null;
  const priceCents = effectivePrice != null && effectivePrice > 0
    ? (effectivePrice % 1).toFixed(2).slice(1)
    : null;

  return (
    <div className="card">
      {/* Retailer row */}
      <div className="retailer">
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.35rem' }}>
          <span
            className="retailer-name-pill"
            style={{ borderLeftColor: getRetailerColor(item.retailer) }}
          >
            {item.retailer}
          </span>
          {isCheapest && <span className="cheapest-badge">Lowest Price</span>}
        </div>
        <div style={{ display: 'flex', gap: '0.35rem', alignItems: 'center' }}>
          {savingsPct != null ? (
            <span className={`tag ${dealQuality || 'sale-tag'}`}>
              {dealQuality === 'hot-deal' ? '🔥 ' : dealQuality === 'good-deal' ? '✓ ' : ''}-{savingsPct}%
            </span>
          ) : dealText ? (
            <span className="tag deal-tag">DEAL</span>
          ) : null}
          {onWatchlist && (
            <button
              className={`watch-btn ${isWatched ? 'watched' : ''}`}
              onClick={(e) => { e.stopPropagation(); onWatchlist(item); }}
              title={isWatched ? 'Remove from watchlist' : 'Add to watchlist'}
              aria-label={isWatched ? 'Remove from watchlist' : 'Add to watchlist'}
            >
              {isWatched ? '★' : '☆'}
            </button>
          )}
        </div>
      </div>

      {imageUrl && (
        <div className="card-image-wrap">
          <img
            src={imageUrl}
            alt={item.name}
            className="card-image"
            loading="lazy"
            onError={(e) => { e.currentTarget.style.display = 'none'; }}
          />
        </div>
      )}

      {/* Price display */}
      <div className="price">
        {effectivePrice != null && effectivePrice > 0 ? (
          <>
            <span className="price-currency">$</span>
            <span className="price-amount">{priceInt}<span style={{ fontSize: '1.4rem', fontWeight: 700 }}>{priceCents}</span></span>
            {item.unit && <span className="unit">/{item.unit}</span>}
            {isSale && item.price > 0 && <span className="was">${item.price.toFixed(2)}</span>}
            {savingsPct != null && savingsPct >= 15 && (
              <span className="savings-badge">Save {savingsPct}%</span>
            )}
          </>
        ) : (
          <span className="price-see-deal">See deal</span>
        )}
      </div>

      {/* Product name */}
      <div className="product-name">
        {item.name}
        {dealText && <span className="deal-text-badge">{dealText}</span>}
      </div>

      {/* Meta row */}
      <div className="meta">
        <span className="meta-brand">{item.brand || 'Unbranded'}</span>
        {item.unit_price_normalized && item.unit_canonical && (
          <span className="meta-unit-price">{fmtUnitPrice(item.unit_price_normalized, item.unit_canonical)}</span>
        )}
      </div>

      {onHistoryClick && (
        <button className="history-btn" onClick={() => onHistoryClick(item.retailer, item.product_id, item.name)}>
          View Price History
        </button>
      )}
    </div>
  );
}

function Spinner() {
  return (
    <div className="loading">
      <div className="spinner"></div><div>Loading...</div>
    </div>
  );
}

function SkeletonCard() {
  return (
    <div className="skeleton-card">
      <div className="skeleton-line short" />
      <div className="skeleton-price-block" />
      <div className="skeleton-line long" />
      <div className="skeleton-line medium" />
    </div>
  );
}

function SkeletonGrid({ count = 6 }) {
  return (
    <div className="grid">
      {Array.from({ length: count }).map((_, i) => <SkeletonCard key={i} />)}
    </div>
  );
}

function SummaryCard({ label, value, sub, color, icon, accent }) {
  return (
    <div className="summary-card" style={accent ? { '--summary-card-accent': accent } : {}}>
      {icon && <span className="summary-icon">{icon}</span>}
      <div className="summary-label">{label}</div>
      <div className="summary-value" style={color ? { color } : {}}>{value ?? '—'}</div>
      {sub && <div className="summary-sub">{sub}</div>}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Dashboard View
// ---------------------------------------------------------------------------

const THIRTY_MIN = 30 * 60 * 1000;
const FIVE_MIN = 5 * 60 * 1000;

function DataFreshnessBar({ lastFetched }) {
  if (!lastFetched) return null;
  return (
    <div className="data-freshness-bar">
      <span>Updated {timeAgo(lastFetched)}</span>
    </div>
  );
}

function DashboardView({ onNavigate }) {
  const { data, loading, error, lastFetched } = useFetch(`${API_BASE}/dashboard`, THIRTY_MIN);

  if (loading) return <Spinner />;
  if (error) return <div className="error">Error: {error}</div>;
  if (!data) return null;

  const { summary, pulse, activity } = data;

  return (
    <div className="dashboard">
      <div className="summary-grid">
        <SummaryCard
          label="Products Tracked"
          value={summary.unique_products?.toLocaleString()}
          icon="📦"
          accent="linear-gradient(90deg, #3b82f6, #6366f1)"
        />
        <SummaryCard
          label="Active Deals"
          value={summary.active_deals?.toLocaleString()}
          color="var(--green)"
          icon="🏷️"
          accent="linear-gradient(90deg, #22c55e, #16a34a)"
        />
        <SummaryCard
          label="Avg Savings"
          value={fmtPct(summary.avg_savings_pct)}
          color="#f59e0b"
          icon="💰"
          accent="linear-gradient(90deg, #f59e0b, #d97706)"
        />
        <SummaryCard
          label="Retailers"
          value={summary.retailer_count}
          color="var(--accent)"
          icon="🏪"
          accent="linear-gradient(90deg, #8b5cf6, #6366f1)"
        />
      </div>

      {activity && activity.length > 0 && (
        <div className="chart-card">
          <h3>Scrape Activity — Last 14 Days</h3>
          <ResponsiveContainer width="100%" height={240}>
            <AreaChart data={activity} margin={{ top: 4, right: 4, bottom: 0, left: -10 }}>
              <defs>
                <linearGradient id="gradRecords" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#3b82f6" stopOpacity={0.35} />
                  <stop offset="95%" stopColor="#3b82f6" stopOpacity={0.02} />
                </linearGradient>
                <linearGradient id="gradRuns" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#8b5cf6" stopOpacity={0.3} />
                  <stop offset="95%" stopColor="#8b5cf6" stopOpacity={0.02} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.06)" vertical={false} />
              <XAxis dataKey="day" tick={{ fill: '#64748b', fontSize: 11 }} tickFormatter={v => v.slice(5)} axisLine={false} tickLine={false} />
              <YAxis tick={{ fill: '#64748b', fontSize: 11 }} axisLine={false} tickLine={false} />
              <Tooltip
                contentStyle={{ background: '#0f172a', border: '1px solid rgba(255,255,255,0.1)', borderRadius: 10, color: '#f1f5f9', fontSize: 13 }}
                cursor={{ stroke: 'rgba(255,255,255,0.08)', strokeWidth: 1 }}
              />
              <Area type="monotone" dataKey="records" stroke="#3b82f6" strokeWidth={2} fill="url(#gradRecords)" name="Records" dot={false} />
              <Area type="monotone" dataKey="runs" stroke="#8b5cf6" strokeWidth={2} fill="url(#gradRuns)" name="Runs" dot={false} />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      )}

      {pulse && (pulse.biggest_drops?.length > 0 || pulse.biggest_increases?.length > 0) && (
        <div className="pulse-section">
          <div className="pulse-section-header">
            <span style={{ fontSize: '1rem' }}>⚡</span>
            <h3>Market Pulse</h3>
          </div>
          <div className="pulse-grid">
            {pulse.biggest_drops?.length > 0 && (
              <div className="pulse-col">
                <div className="pulse-col-header">
                  <span>📉</span>
                  <h4 className="pulse-drops-title">Biggest Drops</h4>
                </div>
                {pulse.biggest_drops.slice(0, 5).map((item, i) => (
                  <div key={i} className="pulse-item drop-item">
                    <div className="pulse-name">{item.name}</div>
                    <div className="pulse-detail">
                      <span className="pulse-retailer">{item.retailer}</span>
                      <span className="pulse-change drop">{fmtPct(item.change_pct)}</span>
                    </div>
                  </div>
                ))}
              </div>
            )}
            {pulse.biggest_increases?.length > 0 && (
              <div className="pulse-col">
                <div className="pulse-col-header">
                  <span>📈</span>
                  <h4 className="pulse-increases-title">Biggest Increases</h4>
                </div>
                {pulse.biggest_increases.slice(0, 5).map((item, i) => (
                  <div key={i} className="pulse-item increase-item">
                    <div className="pulse-name">{item.name}</div>
                    <div className="pulse-detail">
                      <span className="pulse-retailer">{item.retailer}</span>
                      <span className="pulse-change increase">+{fmtPct(Math.abs(item.change_pct))}</span>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      )}

      <div className="dashboard-actions">
        <button className="action-btn" onClick={() => onNavigate('deals')}>🏷️ Browse Deals</button>
        <button className="action-btn" onClick={() => onNavigate('compare')}>⚖️ Compare Prices</button>
        <button className="action-btn" onClick={() => onNavigate('departments')}>🗂️ Browse Departments</button>
      </div>
      <DataFreshnessBar lastFetched={lastFetched} />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Deals View (enhanced with retailer grouping and department filter)
// ---------------------------------------------------------------------------

function DealsView({ watchlist, toggleWatchlist }) {
  const [minPct, setMinPct] = useState(10);
  const [deptFilter, setDeptFilter] = useState('');
  const [groupBy, setGroupBy] = useState('none');
  const [showPromo, setShowPromo] = useState(true);
  const [sortOrder, setSortOrder] = useState('savings_desc');
  const [maxAgeDays, setMaxAgeDays] = useState(7);
  const { data, loading, error, lastFetched } = useFetch(
    `${API_BASE}/deals?min_pct=${minPct}&max_age_days=${maxAgeDays}`,
    THIRTY_MIN,
  );

  const deals = data?.deals || [];
  const latestScrape = data?.latest_scrape;
  const staleRetailers = data?.stale_retailers || [];

  const departments = useMemo(() => {
    const set = new Set(deals.map(d => d.department).filter(Boolean));
    return Array.from(set).sort();
  }, [deals]);

  const filtered = useMemo(() => {
    let list = deals.filter(d => {
      if (!showPromo && d.savings_pct === null) return false;
      if (deptFilter && d.department !== deptFilter) return false;
      return true;
    });
    if (sortOrder === 'savings_desc') list = [...list].sort((a, b) => (b.savings_pct ?? -1) - (a.savings_pct ?? -1));
    if (sortOrder === 'price_asc') list = [...list].sort((a, b) => (a.sale_price ?? a.price ?? 999) - (b.sale_price ?? b.price ?? 999));
    if (sortOrder === 'name_asc') list = [...list].sort((a, b) => (a.name || '').localeCompare(b.name || ''));
    return list;
  }, [deals, deptFilter, showPromo, sortOrder]);

  const grouped = useMemo(() => {
    if (groupBy === 'none') return { 'All Deals': filtered };
    const groups = {};
    filtered.forEach(d => {
      const key = groupBy === 'retailer' ? d.retailer : (d.department || 'Other');
      if (!groups[key]) groups[key] = [];
      groups[key].push(d);
    });
    return groups;
  }, [filtered, groupBy]);

  const watchedIds = new Set(watchlist.map(w => `${w.retailer}::${w.product_id}`));

  return (
    <div>
      <div className="filter-bar">
        <label>Min discount:</label>
        <select value={minPct} onChange={(e) => setMinPct(Number(e.target.value))}>
          {[5, 10, 15, 20, 25, 30, 50].map(v => (
            <option key={v} value={v}>{v}%+</option>
          ))}
        </select>
        <label>Data age:</label>
        <select value={maxAgeDays} onChange={(e) => setMaxAgeDays(Number(e.target.value))}>
          <option value={7}>7 days</option>
          <option value={14}>14 days</option>
          <option value={30}>30 days</option>
          <option value={90}>90 days</option>
          <option value={365}>All time</option>
        </select>
        <label style={{display:'flex',alignItems:'center',gap:'4px',cursor:'pointer'}}>
          <input type="checkbox" checked={showPromo} onChange={(e) => setShowPromo(e.target.checked)} />
          Promo deals
        </label>
        <label>Department:</label>
        <select value={deptFilter} onChange={(e) => setDeptFilter(e.target.value)}>
          <option value="">All</option>
          {departments.map(d => <option key={d} value={d}>{d}</option>)}
        </select>
        <label>Group by:</label>
        <select value={groupBy} onChange={(e) => setGroupBy(e.target.value)}>
          <option value="none">None</option>
          <option value="retailer">Retailer</option>
          <option value="department">Department</option>
        </select>
        <label>Sort:</label>
        <select value={sortOrder} onChange={(e) => setSortOrder(e.target.value)}>
          <option value="savings_desc">Biggest Discount</option>
          <option value="price_asc">Lowest Price</option>
          <option value="name_asc">A–Z</option>
        </select>
        <span className="result-count">{filtered.length} deals</span>
      <DataFreshnessBar lastFetched={lastFetched} />
      </div>
      {latestScrape && (
        <div className={`data-age-banner ${staleRetailers.length > 0 ? 'stale' : 'fresh'}`}>
          {staleRetailers.length > 0
            ? `⚠️ Data last scraped ${timeAgo(latestScrape)} — prices may have changed. Run scrapers to refresh.`
            : `✓ Data up to date as of ${new Date(latestScrape).toLocaleString()}`}
        </div>
      )}
      {loading && <SkeletonGrid />}
      {error && <div className="error">Error: {error}</div>}
      {!loading && !error && filtered.length === 0 && (
        <div className="empty">
          <span className="empty-icon">🏷️</span>
          <div className="empty-title">No active deals found</div>
          <div className="empty-desc">
            {maxAgeDays < 365
              ? `No deals from the last ${maxAgeDays} days. Try widening the time window below, lowering the discount threshold, or run the scrapers to collect fresh data.`
              : 'No deals match your filters. Try lowering the discount threshold or enabling promo deals.'}
          </div>
          {maxAgeDays <= 30 && (
            <button
              className="action-btn"
              style={{ marginTop: '1rem' }}
              onClick={() => setMaxAgeDays(365)}
            >
              Show All Historical Deals
            </button>
          )}
        </div>
      )}
      {!loading && !error && Object.entries(grouped).map(([group, items]) => (
        <div key={group}>
          {groupBy !== 'none' && <h3 className="group-heading">{group} <span className="group-count">({items.length})</span></h3>}
          <div className="grid">
            {items.map((item, idx) => (
              <ProductCard
                key={`${item.retailer}-${item.product_id}-${idx}`}
                item={item}
                onWatchlist={toggleWatchlist}
                isWatched={watchedIds.has(`${item.retailer}::${item.product_id}`)}
              />
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Search View
// ---------------------------------------------------------------------------

function SearchView({ watchlist, toggleWatchlist }) {
  const [query, setQuery] = useState('');
  const [results, setResults] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [searched, setSearched] = useState(false);
  const debounceRef = useRef(null);

  const doSearch = async (e) => {
    if (e) e.preventDefault();
    if (!query.trim()) return;
    setLoading(true); setError(null); setSearched(true);
    try {
      const res = await fetch(`${API_BASE}/search?q=${encodeURIComponent(query)}`);
      if (!res.ok) throw new Error('Failed to fetch');
      setResults((await res.json()).results || []);
    } catch (err) { setError(err.message); }
    finally { setLoading(false); }
  };

  const watchedIds = new Set(watchlist.map(w => `${w.retailer}::${w.product_id}`));

  return (
    <div>
      <form className="search-bar" onSubmit={doSearch} style={{ marginBottom: '2rem' }}>
        <input
          type="text"
          placeholder="Search groceries (e.g. eggs, chicken breast, milk)..."
          value={query}
          onChange={(e) => {
            const val = e.target.value;
            setQuery(val);
            if (debounceRef.current) clearTimeout(debounceRef.current);
            if (val.trim().length >= 2) {
              debounceRef.current = setTimeout(() => {
                setSearched(true);
                setLoading(true);
                setError(null);
                fetch(`${API_BASE}/search?q=${encodeURIComponent(val.trim())}`)
                  .then(r => { if (!r.ok) throw new Error('Failed to fetch'); return r.json(); })
                  .then(d => setResults(d.results || []))
                  .catch(err => setError(err.message))
                  .finally(() => setLoading(false));
              }, 400);
            } else if (val.trim().length === 0) {
              setSearched(false);
              setResults([]);
            }
          }}
        />
        <button type="submit">Search</button>
      </form>
      {!searched && !loading && (
        <div className="search-suggestions">
          <p className="suggestions-label">Popular searches:</p>
          <div className="suggestions-chips">
            {['milk', 'eggs', 'bread', 'chicken breast', 'bananas', 'butter', 'cheese', 'coffee'].map(q => (
              <button
                key={q}
                className="suggestion-chip"
                onClick={() => { setQuery(q); }}
              >
                {q}
              </button>
            ))}
          </div>
        </div>
      )}
      {loading && <SkeletonGrid />}
      {error && <div className="error">Error: {error}</div>}
      {!loading && !error && searched && results.length === 0 && (
        <div className="empty">
          <span className="empty-icon">🔍</span>
          <div className="empty-title">No results found</div>
          <div className="empty-desc">No products matched "{query}". Try a different term or check spelling.</div>
        </div>
      )}
      {!loading && !error && results.length > 0 && (
        <div className="grid">
          {results.map((item, idx) => (
            <ProductCard
              key={`${item.retailer}-${item.product_id}-${idx}`}
              item={item}
              onWatchlist={toggleWatchlist}
              isWatched={watchedIds.has(`${item.retailer}::${item.product_id}`)}
              isCheapest={idx === 0}
            />
          ))}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Compare View (with bar chart + market basket totals)
// ---------------------------------------------------------------------------

const STANDARD_GROCERY_LIST = [
  'eggs', 'almond milk', 'english muffins', 'bread',
  'chicken breast', 'ground beef', 'broccoli', 'spinach', 'carrots',
];

function CompareView() {
  const [query, setQuery] = useState('');
  const [results, setResults] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [basket, setBasket] = useLocalStorage('market_basket', []);
  const [basketInput, setBasketInput] = useState('');
  const [basketResults, setBasketResults] = useState(null);
  const [basketLoading, setBasketLoading] = useState(false);
  const [basketError, setBasketError] = useState(null);

  const doCompare = async (e) => {
    if (e) e.preventDefault();
    if (!query.trim()) return;
    setLoading(true); setError(null);
    try {
      const res = await fetch(`${API_BASE}/compare?q=${encodeURIComponent(query)}`);
      if (!res.ok) throw new Error('Failed to fetch');
      setResults((await res.json()).comparison || []);
    } catch (err) { setError(err.message); }
    finally { setLoading(false); }
  };

  const addToBasket = () => {
    const item = basketInput.trim().toLowerCase();
    if (item && !basket.includes(item)) {
      setBasket([...basket, item]);
      setBasketInput('');
      setBasketResults(null);
    }
  };

  const removeFromBasket = (idx) => {
    setBasket(basket.filter((_, j) => j !== idx));
    setBasketResults(null);
  };

  const loadStandardList = () => {
    const merged = Array.from(new Set([...basket, ...STANDARD_GROCERY_LIST]));
    setBasket(merged);
    setBasketResults(null);
  };

  const compareBasket = async () => {
    if (basket.length === 0) return;
    setBasketLoading(true);
    setBasketError(null);
    setBasketResults(null);
    try {
      const fetches = basket.map(item =>
        fetch(`${API_BASE}/compare?q=${encodeURIComponent(item)}`)
          .then(r => r.ok ? r.json() : null)
          .then(d => ({ item, data: d?.comparison || [] }))
          .catch(() => ({ item, data: [] }))
      );
      const allResults = await Promise.all(fetches);

      const itemPrices = {};
      const allRetailers = new Set();

      allResults.forEach(({ item, data }) => {
        itemPrices[item] = {};
        data.forEach(r => {
          allRetailers.add(r.retailer);
          const price = r.sale_price != null ? r.sale_price : r.price;
          if (price > 0) {
            itemPrices[item][r.retailer] = { price, name: r.name };
          }
        });
      });

      const retailers = Array.from(allRetailers).sort();
      const totals = retailers.map(retailer => {
        let total = 0;
        let found = 0;
        const itemDetails = {};
        basket.forEach(item => {
          const p = itemPrices[item]?.[retailer];
          if (p) { total += p.price; found++; itemDetails[item] = p; }
          else { itemDetails[item] = null; }
        });
        return { retailer, total, found, missing: basket.length - found, itemDetails };
      });

      // Sort: most items found first, then by lowest total
      totals.sort((a, b) => b.found !== a.found ? b.found - a.found : a.total - b.total);

      setBasketResults({ totals });
    } catch (err) {
      setBasketError(err.message);
    } finally {
      setBasketLoading(false);
    }
  };

  const chartData = results.map((item, idx) => ({
    retailer: item.retailer,
    price: item.sale_price != null ? item.sale_price : (item.price || 0),
    name: item.name?.substring(0, 30),
    fill: idx === 0 ? '#22c55e' : null,
  }));

  return (
    <div>
      <form className="search-bar" onSubmit={doCompare} style={{ marginBottom: '2rem' }}>
        <input type="text" placeholder="Compare a single item across retailers (e.g. milk, eggs)..." value={query} onChange={(e) => setQuery(e.target.value)} />
        <button type="submit">Compare</button>
      </form>

      {loading && <Spinner />}
      {error && <div className="error">Error: {error}</div>}

      {!loading && !error && results.length > 0 && (
        <>
          <div className="chart-card" style={{ marginBottom: '1.5rem' }}>
            <h3>Price Comparison — {query}</h3>
            <ResponsiveContainer width="100%" height={Math.max(200, results.length * 44)}>
              <BarChart data={chartData} layout="vertical" margin={{ left: 20, right: 20, top: 4, bottom: 4 }}>
                <defs>
                  <linearGradient id="barGrad" x1="0" y1="0" x2="1" y2="0">
                    <stop offset="0%" stopColor="#3b82f6" stopOpacity={0.9} />
                    <stop offset="100%" stopColor="#6366f1" stopOpacity={0.8} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.06)" horizontal={false} />
                <XAxis type="number" tick={{ fill: '#64748b', fontSize: 11 }} tickFormatter={v => `$${v.toFixed(2)}`} axisLine={false} tickLine={false} />
                <YAxis type="category" dataKey="retailer" tick={{ fill: '#94a3b8', fontSize: 11, fontWeight: 600 }} width={110} axisLine={false} tickLine={false} />
                <Tooltip
                  contentStyle={{ background: '#0f172a', border: '1px solid rgba(255,255,255,0.1)', borderRadius: 10, color: '#f1f5f9', fontSize: 13 }}
                  cursor={{ fill: 'rgba(255,255,255,0.04)' }}
                  formatter={v => [fmtPrice(v), 'Price']}
                />
                <Bar dataKey="price" fill="url(#barGrad)" radius={[0, 6, 6, 0]}>
                  {chartData.map((item) => (
                    <Cell key={item.retailer} fill={item.fill || 'url(#barGrad)'} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>

          {results.length > 1 && (() => {
            const effectivePrice = (item) => item.sale_price != null ? item.sale_price : item.price;
            return (
              <div className="cheapest-callout">
                <span className="cheapest-callout-icon">🏆</span>
                <span>
                  <strong>{results[0].retailer}</strong> is cheapest at <strong>{fmtPrice(effectivePrice(results[0]))}</strong>
                  {' — saves '}<strong className="savings-highlight">{fmtPrice(effectivePrice(results[1]) - effectivePrice(results[0]))}</strong>
                  {' vs '}{results[1].retailer}
                </span>
              </div>
            );
          })()}

          <div className="compare-table-wrap" style={{ marginBottom: '2rem' }}>
            <table className="compare-table">
              <thead>
                <tr>
                  <th>#</th><th>Retailer</th><th>Product</th><th>Price</th><th>Sale</th><th>Unit Price</th>
                </tr>
              </thead>
              <tbody>
                {results.map((item, idx) => {
                  const isBest = idx === 0;
                  return (
                    <tr key={`${item.retailer}-${item.product_id}-${idx}`} className={isBest ? 'best-row' : ''}>
                      <td style={{ fontVariantNumeric: 'tabular-nums', color: 'var(--text-secondary)', fontSize: '0.85rem' }}>{idx === 0 ? '🥇' : idx === 1 ? '🥈' : idx === 2 ? '🥉' : idx + 1}</td>
                      <td className="retailer-cell">
                        {item.retailer}
                        {isBest && <span className="best-price-label">★ Best</span>}
                      </td>
                      <td className="name-cell">{item.name}</td>
                      <td style={{ fontVariantNumeric: 'tabular-nums' }}>{fmtPrice(item.price)}</td>
                      <td>{item.sale_price ? <span className="sale-price">{fmtPrice(item.sale_price)}</span> : <span style={{ color: 'var(--text-muted)' }}>—</span>}</td>
                      <td style={{ fontVariantNumeric: 'tabular-nums' }}>
                        {item.unit_price_normalized && item.unit_canonical
                          ? fmtUnitPrice(item.unit_price_normalized, item.unit_canonical)
                          : fmtPrice(item.sale_price != null ? item.sale_price : item.price)}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </>
      )}

      {/* Market Basket */}
      <div className="basket-section">
        <div className="basket-header-row">
          <h3>Market Basket</h3>
          <button className="standard-list-btn" onClick={loadStandardList}>+ Standard List</button>
        </div>
        <p className="basket-desc">Add items to compare your total grocery bill across all retailers.</p>
        <div className="basket-input-row">
          <input
            type="text"
            placeholder="Add item (e.g. milk, bread, chicken)..."
            value={basketInput}
            onChange={(e) => setBasketInput(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && (e.preventDefault(), addToBasket())}
          />
          <button onClick={addToBasket}>Add</button>
        </div>
        {basket.length > 0 && (
          <>
            <div className="basket-items">
              {basket.map((item, i) => (
                <span key={i} className="basket-tag">
                  {item}
                  <button onClick={() => removeFromBasket(i)}>&times;</button>
                </span>
              ))}
              <button className="basket-clear" onClick={() => { setBasket([]); setBasketResults(null); }}>Clear All</button>
            </div>
            <div style={{ marginTop: '1rem' }}>
              <button className="compare-basket-btn" onClick={compareBasket} disabled={basketLoading}>
                {basketLoading ? 'Comparing...' : `⚖️ Compare ${basket.length} Item${basket.length !== 1 ? 's' : ''} Across Retailers`}
              </button>
            </div>
          </>
        )}
        {basketError && <div className="error" style={{ marginTop: '1rem' }}>Error: {basketError}</div>}
        {basketLoading && <div style={{ paddingTop: '1rem' }}><Spinner /></div>}
        {basketResults && !basketLoading && (
          <div style={{ marginTop: '1.5rem' }}>
            <h4 style={{ margin: '0 0 1rem 0', color: 'var(--text-secondary)', fontSize: '0.9rem', fontWeight: 600 }}>
              Total basket cost by retailer — {basket.length} items
            </h4>
            <div className="compare-table-wrap">
              <table className="compare-table basket-totals-table">
                <thead>
                  <tr>
                    <th>Retailer</th>
                    {basket.map(item => (
                      <th key={item} style={{ textTransform: 'capitalize', whiteSpace: 'nowrap' }}>{item}</th>
                    ))}
                    <th>Total</th>
                    <th>Items</th>
                  </tr>
                </thead>
                <tbody>
                  {basketResults.totals.map((row, idx) => {
                    const isBest = idx === 0 && row.found === basket.length;
                    return (
                      <tr key={row.retailer} className={isBest ? 'best-row' : ''}>
                        <td className="retailer-cell">
                          {row.retailer}
                          {isBest && <span className="best-price-label">★ Best</span>}
                        </td>
                        {basket.map(item => {
                          const p = row.itemDetails[item];
                          return (
                            <td key={item} style={{ fontVariantNumeric: 'tabular-nums', fontSize: '0.85rem' }}>
                              {p
                                ? <span title={p.name}>{fmtPrice(p.price)}</span>
                                : <span style={{ color: 'var(--text-muted)' }}>—</span>
                              }
                            </td>
                          );
                        })}
                        <td style={{ fontVariantNumeric: 'tabular-nums', fontWeight: 700, color: isBest ? 'var(--green)' : undefined }}>
                          {fmtPrice(row.total)}
                          {row.missing > 0 && <span style={{ fontSize: '0.7rem', color: 'var(--text-muted)', marginLeft: 4 }}>*</span>}
                        </td>
                        <td style={{ fontSize: '0.8rem', color: row.missing > 0 ? 'var(--yellow)' : 'var(--green)' }}>
                          {row.found}/{basket.length}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
            {basketResults.totals.some(r => r.missing > 0) && (
              <p style={{ fontSize: '0.8rem', color: 'var(--text-muted)', marginTop: '0.75rem' }}>
                * One or more items not available at this retailer or not yet scraped.
              </p>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// History View (with line chart)
// ---------------------------------------------------------------------------

function HistoryView() {
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

// ---------------------------------------------------------------------------
// Department Browser View
// ---------------------------------------------------------------------------

function DepartmentsView() {
  const { data, loading, error } = useFetch(`${API_BASE}/departments`);
  const [selected, setSelected] = useState(null);
  const [products, setProducts] = useState([]);
  const [prodLoading, setProdLoading] = useState(false);
  const [retailerFilter, setRetailerFilter] = useState('');
  const [sortOrder, setSortOrder] = useState('price_asc');
  const [deptSearch, setDeptSearch] = useState('');
  const [hasMore, setHasMore] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);

  const loadDept = async (dept) => {
    setSelected(dept);
    setProducts([]);
    setRetailerFilter('');
    setSortOrder('price_asc');
    setHasMore(false);
    setProdLoading(true);
    try {
      const res = await fetch(`${API_BASE}/departments/${encodeURIComponent(dept)}?limit=200`);
      if (res.ok) {
        const d = await res.json();
        const items = d.products || [];
        setProducts(items);
        setHasMore(items.length === 200);
      }
    } catch (err) {
      console.warn('Failed to load department:', err);
    } finally { setProdLoading(false); }
  };

  const loadMore = async () => {
    setLoadingMore(true);
    try {
      const res = await fetch(`${API_BASE}/departments/${encodeURIComponent(selected)}?limit=200&offset=${products.length}`);
      if (res.ok) {
        const d = await res.json();
        const more = d.products || [];
        setProducts(prev => [...prev, ...more]);
        setHasMore(more.length === 200);
      }
    } catch (err) {
      console.warn('Failed to load more:', err);
    } finally { setLoadingMore(false); }
  };

  const retailers = useMemo(() => {
    const s = new Set(products.map(p => p.retailer));
    return Array.from(s).sort();
  }, [products]);

  const filteredProducts = useMemo(() => {
    let list = products;
    if (retailerFilter) list = list.filter(p => p.retailer === retailerFilter);
    if (sortOrder === 'price_asc') list = [...list].sort((a, b) => (a.sale_price ?? a.price ?? 999) - (b.sale_price ?? b.price ?? 999));
    if (sortOrder === 'price_desc') list = [...list].sort((a, b) => (b.sale_price ?? b.price ?? 0) - (a.sale_price ?? a.price ?? 0));
    if (sortOrder === 'name_asc') list = [...list].sort((a, b) => (a.name || '').localeCompare(b.name || ''));
    return list;
  }, [products, retailerFilter, sortOrder]);

  if (loading) return <Spinner />;
  if (error) return <div className="error">Error: {error}</div>;

  const departments = data?.departments || [];
  const filteredDepts = departments.filter(d =>
    !deptSearch || d.department?.toLowerCase().includes(deptSearch.toLowerCase())
  );

  return (
    <div>
      {!selected ? (
        <>
          <div className="dept-search-bar">
            <input
              type="text"
              placeholder="Filter departments..."
              value={deptSearch}
              onChange={e => setDeptSearch(e.target.value)}
            />
          </div>
          <div className="dept-grid">
            {filteredDepts.map((d, i) => (
              <div key={i} className="dept-card" onClick={() => loadDept(d.department)}>
                <span className="dept-icon">{getDeptIcon(d.department)}</span>
                <div className="dept-name">{d.department}</div>
                <div className="dept-stats">
                  <span className="dept-stat-chip">{d.retailer_count} stores</span>
                  <span className="dept-stat-chip">avg {fmtPrice(d.avg_price)}</span>
                  <span className="dept-stat-chip">
                    {d.unique_name_count != null ? `~${d.unique_name_count} items` : `${d.product_count} listings`}
                  </span>
                </div>
              </div>
            ))}
          </div>
        </>
      ) : (
        <div>
          <div className="dept-view-header">
            <button className="back-btn" onClick={() => setSelected(null)}>&larr; All Departments</button>
            <h3 className="group-heading" style={{ margin: 0 }}>{getDeptIcon(selected)} {selected}</h3>
          </div>
          <div className="filter-bar" style={{ marginBottom: '1.5rem' }}>
            <label>Retailer:</label>
            <select value={retailerFilter} onChange={e => setRetailerFilter(e.target.value)}>
              <option value="">All ({products.length})</option>
              {retailers.map(r => (
                <option key={r} value={r}>{r}</option>
              ))}
            </select>
            <label>Sort:</label>
            <select value={sortOrder} onChange={e => setSortOrder(e.target.value)}>
              <option value="price_asc">Price ↑</option>
              <option value="price_desc">Price ↓</option>
              <option value="name_asc">Name A–Z</option>
            </select>
            <span className="result-count">{filteredProducts.length} items</span>
          </div>
          {prodLoading ? <Spinner /> : (
            <>
              <div className="grid">
                {filteredProducts.map((item, idx) => (
                  <ProductCard key={`${item.retailer}-${item.product_id}-${idx}`} item={item} />
                ))}
              </div>
              {filteredProducts.length === 0 && !prodLoading && (
                <div className="empty">
                  <span className="empty-icon">🗂️</span>
                  <div className="empty-title">No products found</div>
                  <div className="empty-desc">Try changing the retailer filter.</div>
                </div>
              )}
              {hasMore && (
                <div style={{ textAlign: 'center', marginTop: '1.5rem' }}>
                  <button className="action-btn" onClick={loadMore} disabled={loadingMore}>
                    {loadingMore ? 'Loading...' : 'Load More'}
                  </button>
                </div>
              )}
            </>
          )}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Watchlist View
// ---------------------------------------------------------------------------

function WatchlistView({ watchlist, toggleWatchlist, priceAlerts, setPriceAlerts }) {
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

// ---------------------------------------------------------------------------
// Stores View (enhanced with analytics panel)
// ---------------------------------------------------------------------------

function StoresView() {
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

// ---------------------------------------------------------------------------
// Status Bar (enhanced with freshness)
// ---------------------------------------------------------------------------

function StatusBar() {
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

// ---------------------------------------------------------------------------
// App
// ---------------------------------------------------------------------------

const TABS = [
  { id: 'dashboard',   label: 'Dashboard',   icon: '📊' },
  { id: 'deals',       label: 'Deals',        icon: '🏷️' },
  { id: 'search',      label: 'Search',       icon: '🔍' },
  { id: 'compare',     label: 'Compare',      icon: '⚖️' },
  { id: 'history',     label: 'History',      icon: '📈' },
  { id: 'departments', label: 'Departments',  icon: '🗂️' },
  { id: 'watchlist',   label: 'Watchlist',    icon: '⭐' },
  { id: 'stores',      label: 'Stores',       icon: '🏪' },
];

const PRIMARY_TABS = ['dashboard', 'deals', 'search', 'watchlist', 'stores'];
const OVERFLOW_TABS = ['compare', 'history', 'departments'];

function App() {
  const [tab, setTab] = useState('dashboard');
  const [watchlist, setWatchlist] = useLocalStorage('watchlist', []);
  const [priceAlerts, setPriceAlerts] = useLocalStorage('price_alerts', {});
  const [moreOpen, setMoreOpen] = useState(false);
  const [theme, setTheme] = useLocalStorage('theme', 'dark');

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme);
  }, [theme]);

  const alertCount = Object.keys(priceAlerts).length;

  const toggleWatchlist = useCallback((item) => {
    setWatchlist(prev => {
      const key = `${item.retailer}::${item.product_id}`;
      const exists = prev.some(w => `${w.retailer}::${w.product_id}` === key);
      if (exists) return prev.filter(w => `${w.retailer}::${w.product_id}` !== key);
      return [...prev, { retailer: item.retailer, product_id: item.product_id, name: item.name }];
    });
  }, [setWatchlist]);

  return (
    <>
      <header>
        <div className="header-logo">
          <span className="header-icon" aria-hidden="true">🛒</span>
          <h1>Price Board</h1>
        </div>
        <p>Market basket intelligence &amp; price discovery</p>
        <button
          className="theme-toggle"
          onClick={() => setTheme(t => t === 'dark' ? 'light' : 'dark')}
          aria-label={theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'}
          title={theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'}
        >
          {theme === 'dark' ? '☀️' : '🌙'}
        </button>
        <StatusBar />
      </header>

      {/* Desktop / tablet nav */}
      <nav className="tabs desktop-tabs" role="tablist" aria-label="Main navigation">
        {TABS.map(t => (
          <button
            key={t.id}
            role="tab"
            aria-selected={tab === t.id}
            className={`tab ${tab === t.id ? 'active' : ''}`}
            onClick={() => setTab(t.id)}
          >
            <span className="tab-icon" aria-hidden="true">{t.icon}</span>
            {t.label}
            {t.id === 'watchlist' && (watchlist.length > 0 || alertCount > 0) && (
              <span className="tab-badge">{alertCount > 0 ? '🔔' : watchlist.length}</span>
            )}
          </button>
        ))}
      </nav>

      {/* Mobile bottom nav */}
      <nav className="mobile-bottom-nav" role="tablist" aria-label="Main navigation">
        {TABS.filter(t => PRIMARY_TABS.includes(t.id)).map(t => (
          <button
            key={t.id}
            role="tab"
            aria-selected={tab === t.id}
            className={`mobile-nav-btn ${tab === t.id ? 'active' : ''}`}
            onClick={() => { setTab(t.id); setMoreOpen(false); }}
          >
            <span className="mobile-nav-icon" aria-hidden="true">{t.icon}</span>
            <span className="mobile-nav-label">{t.label}</span>
            {t.id === 'watchlist' && (watchlist.length > 0 || alertCount > 0) && (
              <span className="tab-badge mobile-badge">{alertCount > 0 ? '🔔' : watchlist.length}</span>
            )}
          </button>
        ))}
        <button
          className={`mobile-nav-btn ${OVERFLOW_TABS.includes(tab) ? 'active' : ''}`}
          onClick={() => setMoreOpen(o => !o)}
          aria-expanded={moreOpen}
          aria-label="More tabs"
        >
          <span className="mobile-nav-icon" aria-hidden="true">⋯</span>
          <span className="mobile-nav-label">More</span>
        </button>
      </nav>

      {/* More drawer */}
      {moreOpen && (
        <>
          <div className="more-overlay" onClick={() => setMoreOpen(false)} />
          <div className="more-drawer">
            {TABS.filter(t => OVERFLOW_TABS.includes(t.id)).map(t => (
              <button
                key={t.id}
                className={`more-drawer-btn ${tab === t.id ? 'active' : ''}`}
                onClick={() => { setTab(t.id); setMoreOpen(false); }}
              >
                <span aria-hidden="true">{t.icon}</span>
                {t.label}
              </button>
            ))}
          </div>
        </>
      )}

      <main>
        {tab === 'dashboard' && <DashboardView onNavigate={setTab} />}
        {tab === 'deals' && <DealsView watchlist={watchlist} toggleWatchlist={toggleWatchlist} />}
        {tab === 'search' && <SearchView watchlist={watchlist} toggleWatchlist={toggleWatchlist} />}
        {tab === 'compare' && <CompareView />}
        {tab === 'history' && <HistoryView />}
        {tab === 'departments' && <DepartmentsView />}
        {tab === 'watchlist' && <WatchlistView watchlist={watchlist} toggleWatchlist={toggleWatchlist} priceAlerts={priceAlerts} setPriceAlerts={setPriceAlerts} />}
        {tab === 'stores' && <StoresView />}
      </main>
    </>
  );
}

export default App;
