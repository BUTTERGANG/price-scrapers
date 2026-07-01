import { useState } from 'react';
import {
  BarChart, Bar, Cell, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
} from 'recharts';
import { useLocalStorage } from '../lib/hooks';
import { API_BASE, fmtPrice, timeAgo, freshnessLevel } from '../lib/utils';
import { Spinner } from './Shared';

const STANDARD_GROCERY_LIST = [
  'eggs', 'almond milk', 'english muffins', 'bread',
  'chicken breast', 'ground beef', 'broccoli', 'spinach', 'carrots',
];

export default function CompareView() {
  const [query, setQuery] = useState('');
  // result is the /api/compare/standard payload:
  // { standard_unit, standard_unit_display, comparable[], comparable_count,
  //   uncomparable[], uncomparable_count }
  const [result, setResult] = useState(null);
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
    setLoading(true); setError(null); setResult(null);
    try {
      // Standard endpoint groups results by a common unit (per gallon, per
      // dozen, per lb…) so prices are genuinely like-for-like instead of
      // comparing a candy bar to a half-gallon of milk.
      const res = await fetch(`${API_BASE}/compare/standard?q=${encodeURIComponent(query)}`);
      if (!res.ok) throw new Error('Failed to fetch');
      setResult(await res.json());
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

  // Run promises in batches of `limit` concurrent requests to avoid
  // overwhelming the backend or hitting browser connection limits.
  const runBatched = async (items, fn, limit = 5) => {
    const results = [];
    for (let i = 0; i < items.length; i += limit) {
      const batch = items.slice(i, i + limit);
      const batchResults = await Promise.all(batch.map(fn));
      results.push(...batchResults);
    }
    return results;
  };

  const compareBasket = async () => {
    if (basket.length === 0) return;
    setBasketLoading(true);
    setBasketError(null);
    setBasketResults(null);
    try {
      const allResults = await runBatched(basket, item =>
        fetch(`${API_BASE}/compare?q=${encodeURIComponent(item)}`)
          .then(r => r.ok ? r.json() : null)
          .then(d => ({ item, data: d?.comparison || [] }))
          .catch(() => ({ item, data: [] }))
      , 5);

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

  const comparable = result?.comparable || [];
  const uncomparable = result?.uncomparable || [];
  const unitLabel = result?.standard_unit_display || null;
  const hasComparable = comparable.length > 0;

  // Chart of the standardized price per retailer (cheapest highlighted green).
  const chartData = comparable.map((item, idx) => ({
    retailer: item.retailer,
    price: item.standard_price,
    name: item.name?.substring(0, 30),
    fill: idx === 0 ? '#22c55e' : null,
  }));

  const stdLabelShort = unitLabel ? unitLabel.replace(/^per\s+/, '/') : '';

  return (
    <div>
      <form className="search-bar" onSubmit={doCompare} style={{ marginBottom: '1rem' }}>
        <input type="text" placeholder="Compare a single item across retailers (e.g. milk, eggs)..." value={query} onChange={(e) => setQuery(e.target.value)} />
        <button type="submit">Compare</button>
      </form>

      {loading && <Spinner />}
      {error && <div className="error">Error: {error}</div>}

      {!loading && !error && result && (
        <>
          {hasComparable && (
            <>
              <div className="compare-unit-banner">
                Comparing <strong>{query}</strong> {unitLabel
                  ? <>by a common unit — <strong>{unitLabel}</strong></>
                  : null}
              </div>

              <div className="chart-card" style={{ marginBottom: '1.5rem' }}>
                <h3>Standardized price ({unitLabel}) — {query}</h3>
                <ResponsiveContainer width="100%" height={Math.max(200, comparable.length * 44)}>
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
                      formatter={v => [`${fmtPrice(v)} ${stdLabelShort}`, unitLabel]}
                    />
                    <Bar dataKey="price" fill="url(#barGrad)" radius={[0, 6, 6, 0]}>
                      {chartData.map((item) => (
                        <Cell key={item.retailer} fill={item.fill || 'url(#barGrad)'} />
                      ))}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              </div>

              {comparable.length > 1 && (
                <div className="cheapest-callout">
                  <span className="cheapest-callout-icon">🏆</span>
                  <span>
                    <strong>{comparable[0].retailer}</strong> is cheapest at{' '}
                    <strong>{fmtPrice(comparable[0].standard_price)} {stdLabelShort}</strong>
                    {' — saves '}
                    <strong className="savings-highlight">
                      {fmtPrice(comparable[1].standard_price - comparable[0].standard_price)} {stdLabelShort}
                    </strong>
                    {' vs '}{comparable[1].retailer}
                  </span>
                </div>
              )}

              <div className="compare-table-wrap" style={{ marginBottom: '2rem' }}>
                <table className="compare-table">
                  <thead>
                    <tr>
                      <th>#</th><th>Retailer</th><th>Product</th><th>Shelf Price</th>
                      <th>{unitLabel || 'Unit Price'}</th><th>Updated</th>
                    </tr>
                  </thead>
                  <tbody>
                    {comparable.map((item, idx) => {
                      const isBest = idx === 0;
                      const shelf = item.sale_price != null ? item.sale_price : item.price;
                      return (
                        <tr key={`${item.retailer}-${item.product_id}-${idx}`} className={isBest ? 'best-row' : ''}>
                          <td style={{ fontVariantNumeric: 'tabular-nums', color: 'var(--text-secondary)', fontSize: '0.85rem' }}>{idx === 0 ? '🥇' : idx === 1 ? '🥈' : idx === 2 ? '🥉' : idx + 1}</td>
                          <td className="retailer-cell">
                            {item.retailer}
                            {isBest && <span className="best-price-label">★ Best</span>}
                          </td>
                          <td className="name-cell">{item.name}</td>
                          <td style={{ fontVariantNumeric: 'tabular-nums' }}>{fmtPrice(shelf)}</td>
                          <td style={{ fontVariantNumeric: 'tabular-nums', fontWeight: 700 }}>
                            {fmtPrice(item.standard_price)} <span style={{ color: 'var(--text-muted)', fontWeight: 400 }}>{stdLabelShort}</span>
                          </td>
                          <td className={`freshness-${freshnessLevel(item.scraped_at)}`} style={{ fontSize: '0.78rem', whiteSpace: 'nowrap' }}>
                            {item.scraped_at ? timeAgo(item.scraped_at) : '—'}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </>
          )}

          {/* Items that couldn't be standardized into the common unit */}
          {uncomparable.length > 0 && (
            <div className="compare-table-wrap" style={{ marginBottom: '2rem' }}>
              <h4 style={{ margin: '0 0 0.5rem', color: 'var(--text-secondary)', fontSize: '0.9rem', fontWeight: 600 }}>
                {hasComparable
                  ? 'Other matches (different size/unit — not directly comparable)'
                  : `Couldn't standardize "${query}" to a common unit — showing closest matches`}
              </h4>
              <table className="compare-table">
                <thead>
                  <tr><th>Retailer</th><th>Product</th><th>Price</th><th>Updated</th></tr>
                </thead>
                <tbody>
                  {uncomparable.map((item, idx) => {
                    const shelf = item.sale_price != null ? item.sale_price : item.price;
                    return (
                      <tr key={`${item.retailer}-${item.product_id}-u${idx}`}>
                        <td className="retailer-cell">{item.retailer}</td>
                        <td className="name-cell">{item.name}</td>
                        <td style={{ fontVariantNumeric: 'tabular-nums' }}>{fmtPrice(shelf)}</td>
                        <td className={`freshness-${freshnessLevel(item.scraped_at)}`} style={{ fontSize: '0.78rem', whiteSpace: 'nowrap' }}>
                          {item.scraped_at ? timeAgo(item.scraped_at) : '—'}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}

          {!hasComparable && uncomparable.length === 0 && (
            <div className="empty">
              <span className="empty-icon">⚖️</span>
              <div className="empty-title">No matches found</div>
              <div className="empty-desc">No products matched "{query}". Try a different term.</div>
            </div>
          )}
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
