import { useState, useMemo } from 'react';
import { useFetch } from '../lib/hooks';
import { API_BASE, THIRTY_MIN, timeAgo } from '../lib/utils';
import { ProductCard, SkeletonGrid, DataFreshnessBar } from './Shared';

export default function DealsView({ watchlist, toggleWatchlist }) {
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
