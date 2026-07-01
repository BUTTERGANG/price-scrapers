import { getRetailerColor, fmtUnitPrice, timeAgo, freshnessLevel } from '../lib/utils';

export function StatusBadge({ status }) {
  const styles = {
    success:   { bg: 'rgba(34,197,94,0.15)',   color: '#4ade80',  border: 'rgba(34,197,94,0.3)',   dot: '#22c55e' },
    partial:   { bg: 'rgba(250,204,21,0.15)',   color: '#fde047',  border: 'rgba(250,204,21,0.3)',  dot: '#eab308' },
    empty:     { bg: 'rgba(249,115,22,0.15)',   color: '#fdba74',  border: 'rgba(249,115,22,0.3)',  dot: '#f97316' },
    failed:    { bg: 'rgba(239,68,68,0.15)',    color: '#fca5a5',  border: 'rgba(239,68,68,0.3)',   dot: '#ef4444' },
    running:   { bg: 'rgba(59,130,246,0.15)',   color: '#93c5fd',  border: 'rgba(59,130,246,0.3)',  dot: '#3b82f6' },
    disabled:  { bg: 'rgba(100,116,139,0.12)',  color: '#94a3b8',  border: 'rgba(100,116,139,0.2)', dot: '#64748b' },
    never_run: { bg: 'rgba(100,116,139,0.12)',  color: '#94a3b8',  border: 'rgba(100,116,139,0.2)', dot: '#64748b' },
  };
  const s = styles[status] || styles.never_run;
  const LABELS = { never_run: 'Never Run', empty: 'No Data', disabled: 'Disabled' };
  const label = LABELS[status] || status.charAt(0).toUpperCase() + status.slice(1);
  return (
    <span className="status-badge" style={{ background: s.bg, color: s.color, borderColor: s.border, border: `1px solid ${s.border}` }}>
      <span style={{ display: 'inline-block', width: 6, height: 6, borderRadius: '50%', background: s.dot, marginRight: 5, verticalAlign: 'middle', flexShrink: 0 }} />
      {label}
    </span>
  );
}

export function ProductCard({ item, onHistoryClick, onWatchlist, isWatched, isCheapest = false }) {
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
      // JSONB columns arrive as objects; legacy TEXT rows as JSON strings
      const extra = typeof item.extra_json === 'string'
        ? JSON.parse(item.extra_json)
        : item.extra_json;
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

      {/* Freshness — when this price was last pulled */}
      {item.scraped_at && (
        <div className={`freshness-chip freshness-${freshnessLevel(item.scraped_at)}`}>
          <span className="freshness-dot" aria-hidden="true" />
          Updated {timeAgo(item.scraped_at)}
        </div>
      )}

      {onHistoryClick && (
        <button className="history-btn" onClick={() => onHistoryClick(item.retailer, item.product_id, item.name)}>
          View Price History
        </button>
      )}
    </div>
  );
}

export function Spinner() {
  return (
    <div className="loading">
      <div className="spinner"></div><div>Loading...</div>
    </div>
  );
}

export function SkeletonCard() {
  return (
    <div className="skeleton-card">
      <div className="skeleton-line short" />
      <div className="skeleton-price-block" />
      <div className="skeleton-line long" />
      <div className="skeleton-line medium" />
    </div>
  );
}

export function SkeletonGrid({ count = 6 }) {
  return (
    <div className="grid">
      {Array.from({ length: count }).map((_, i) => <SkeletonCard key={i} />)}
    </div>
  );
}

export function SummaryCard({ label, value, sub, color, icon, accent }) {
  return (
    <div className="summary-card" style={accent ? { '--summary-card-accent': accent } : {}}>
      {icon && <span className="summary-icon">{icon}</span>}
      <div className="summary-label">{label}</div>
      <div className="summary-value" style={color ? { color } : {}}>{value ?? '—'}</div>
      {sub && <div className="summary-sub">{sub}</div>}
    </div>
  );
}

export function DataFreshnessBar({ lastFetched }) {
  if (!lastFetched) return null;
  return (
    <div className="data-freshness-bar">
      <span>Updated {timeAgo(lastFetched)}</span>
    </div>
  );
}
