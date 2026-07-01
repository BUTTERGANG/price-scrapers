import { useState, useEffect, useCallback } from 'react';
import './index.css';

import { useLocalStorage } from './lib/hooks';
import DashboardView from './components/DashboardView';
import DealsView from './components/DealsView';
import SearchView from './components/SearchView';
import CompareView from './components/CompareView';
import HistoryView from './components/HistoryView';
import DepartmentsView from './components/DepartmentsView';
import WatchlistView from './components/WatchlistView';
import StoresView from './components/StoresView';
import StatusBar from './components/StatusBar';
import ErrorBoundary from './components/ErrorBoundary';
import PriceHistoryModal from './components/PriceHistoryModal';

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
  const [historyItem, setHistoryItem] = useState(null);

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme);
  }, [theme]);

  const alertCount = Object.keys(priceAlerts).length;

  const openHistory = useCallback((retailer, product_id, name) => {
    setHistoryItem({ retailer, product_id, name });
  }, []);

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
        <ErrorBoundary>
          {tab === 'dashboard' && <DashboardView onNavigate={setTab} />}
          {tab === 'deals' && <DealsView watchlist={watchlist} toggleWatchlist={toggleWatchlist} onHistoryClick={openHistory} />}
          {tab === 'search' && <SearchView watchlist={watchlist} toggleWatchlist={toggleWatchlist} onHistoryClick={openHistory} />}
          {tab === 'compare' && <CompareView />}
          {tab === 'history' && <HistoryView />}
          {tab === 'departments' && <DepartmentsView />}
          {tab === 'watchlist' && <WatchlistView watchlist={watchlist} toggleWatchlist={toggleWatchlist} priceAlerts={priceAlerts} setPriceAlerts={setPriceAlerts} onHistoryClick={openHistory} />}
          {tab === 'stores' && <StoresView />}
        </ErrorBoundary>
      </main>

      {historyItem && (
        <PriceHistoryModal item={historyItem} onClose={() => setHistoryItem(null)} />
      )}
    </>
  );
}

export default App;
