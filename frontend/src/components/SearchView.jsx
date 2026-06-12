import { useState, useRef } from 'react';
import { API_BASE } from '../lib/utils';
import { ProductCard, SkeletonGrid } from './Shared';

export default function SearchView({ watchlist, toggleWatchlist }) {
  const [query, setQuery] = useState('');
  const [results, setResults] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [searched, setSearched] = useState(false);
  const debounceRef = useRef(null);
  const abortRef = useRef(null);

  const doSearch = async (e) => {
    if (e) e.preventDefault();
    if (!query.trim()) return;
    // Cancel any in-flight request
    if (abortRef.current) abortRef.current.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    setLoading(true); setError(null); setSearched(true);
    try {
      const res = await fetch(`${API_BASE}/search?q=${encodeURIComponent(query)}`, {
        signal: controller.signal,
      });
      if (!res.ok) throw new Error('Failed to fetch');
      setResults((await res.json()).results || []);
    } catch (err) {
      if (err.name !== 'AbortError') setError(err.message);
    } finally {
      setLoading(false);
    }
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
            // Cancel any in-flight request before starting a new one
            if (abortRef.current) abortRef.current.abort();
            if (val.trim().length >= 2) {
              const controller = new AbortController();
              abortRef.current = controller;
              debounceRef.current = setTimeout(() => {
                setSearched(true);
                setLoading(true);
                setError(null);
                fetch(`${API_BASE}/search?q=${encodeURIComponent(val.trim())}`, {
                  signal: controller.signal,
                })
                  .then(r => { if (!r.ok) throw new Error('Failed to fetch'); return r.json(); })
                  .then(d => setResults(d.results || []))
                  .catch(err => { if (err.name !== 'AbortError') setError(err.message); })
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
