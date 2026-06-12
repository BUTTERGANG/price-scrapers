import { useState, useMemo } from 'react';
import { useFetch } from '../lib/hooks';
import { API_BASE, fmtPrice, getDeptIcon } from '../lib/utils';
import { Spinner, ProductCard } from './Shared';

export default function DepartmentsView() {
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
