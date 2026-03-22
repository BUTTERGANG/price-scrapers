import { useState, useEffect } from 'react';
import './index.css';

const API_BASE = '/api'; // proxied to localhost:8000 via vite.config.js

function ProductCard({ item }) {
  const effectivePrice = item.sale_price ? item.sale_price : item.price;
  const isSale = !!item.sale_price;
  let savingsTag = null;

  if (isSale && item.price && item.price > item.sale_price) {
    const pct = Math.round(((item.price - item.sale_price) / item.price) * 100);
    savingsTag = <span className="tag">-{pct}%</span>;
  }

  // extract deal_text if extra_json exists
  let dealText = null;
  if (item.extra_json) {
    try {
      const extra = JSON.parse(item.extra_json);
      dealText = extra.deal_text || extra.sale_story;
    } catch (e) {}
  }

  return (
    <div className="card">
      <div className="retailer">
        {item.retailer}
        {savingsTag || (dealText && <span className="tag" style={{background: 'rgba(59, 130, 246, 0.2)', color: '#93c5fd'}}>DEAL</span>)}
      </div>
      <div className="price">
        ${effectivePrice.toFixed(2)}
        {item.unit && <span className="unit">/ {item.unit}</span>}
        {isSale && item.price && <span className="was">${item.price.toFixed(2)}</span>}
      </div>
      <div className="product-name">
        {item.name}
        {dealText && <div style={{color: '#93c5fd', fontSize: '0.85rem', marginTop: '0.6rem', fontWeight: 600}}>{dealText}</div>}
      </div>
      <div className="meta">
        <span>{item.brand || 'Unbranded'}</span>
        {item.unit_price_normalized && item.unit_canonical && (
          <span>${item.unit_price_normalized < 0.1 ? item.unit_price_normalized.toFixed(4) : item.unit_price_normalized.toFixed(2)} {item.unit_canonical.replace('per_', '/')}</span>
        )}
      </div>
    </div>
  );
}

function App() {
  const [tab, setTab] = useState('deals'); // 'deals' or 'search'
  const [query, setQuery] = useState('');
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const fetchDeals = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`${API_BASE}/deals?min_pct=10`);
      if (!res.ok) throw new Error('Failed to fetch deals');
      const data = await res.json();
      setItems(data.deals || []);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  const executeSearch = async (e) => {
    if (e) e.preventDefault();
    if (!query.trim()) return;
    setTab('search');
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`${API_BASE}/search?q=${encodeURIComponent(query)}`);
      if (!res.ok) throw new Error('Failed to fetch search results');
      const data = await res.json();
      setItems(data.results || []);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (tab === 'deals') {
      fetchDeals();
    }
  }, [tab]);

  return (
    <>
      <header>
        <h1>Price Board</h1>
        <p>Market basket intelligence & price discovery</p>
      </header>

      <div className="search-container">
        <form className="search-bar" onSubmit={executeSearch}>
          <input 
            type="text" 
            placeholder="Search groceries (e.g. eggs, chicken breast, milk)..." 
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
          <button type="submit">Search</button>
        </form>
      </div>

      <div className="tabs">
        <button className={`tab ${tab === 'deals' ? 'active' : ''}`} onClick={() => setTab('deals')}>Current Deals</button>
        <button className={`tab ${tab === 'search' ? 'active' : ''}`} onClick={() => {
           if (query.trim()) { setTab('search'); executeSearch(); }
           else { setTab('search'); setItems([]); }
        }}>Search Results</button>
      </div>

      <main>
        {loading && (
          <div className="loading">
            <div className="spinner"></div><div>Loading...</div>
          </div>
        )}

        {error && <div className="error">Error: {error}</div>}

        {!loading && !error && items.length === 0 && (
          <div className="empty">
            {tab === 'deals' ? 'No active deals found > 10%.' : 'Search for a product to see prices across stores.'}
          </div>
        )}

        {!loading && !error && items.length > 0 && (
          <div className="grid">
            {items.map((item, idx) => (
              <ProductCard key={`${item.retailer}-${item.product_id}-${idx}`} item={item} />
            ))}
          </div>
        )}
      </main>
    </>
  );
}

export default App;
