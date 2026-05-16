---
name: Price Board project overview
description: Key facts about the Price Board grocery price tracking app's frontend architecture and patterns
type: project
---

Single-page React app at `frontend/src/App.jsx` + `frontend/src/index.css`. Uses Vite as the build tool. All views are in one file — no routing library, tab state managed with `useState`.

**Stack:** React (hooks only, no class components), Recharts for charts, Inter font via Google Fonts.

**Why:** Grocery price scraping dashboard — tracks prices across multiple retailers, shows deals, price history, comparisons, and per-store analytics.

**Architecture notes:**
- All views live in `App.jsx`: DashboardView, DealsView, SearchView, CompareView, HistoryView, DepartmentsView, WatchlistView, StoresView
- Shared components: ProductCard, SummaryCard, StatusBadge, Spinner
- API calls go to `/api/*` endpoints via `useFetch` hook and direct `fetch` calls
- Watchlist persisted in localStorage via `useLocalStorage` hook
- Recharts components used: AreaChart, LineChart, BarChart with ResponsiveContainer

**Design system (as of March 2026):**
- Dark theme: `--bg-color: #080d19`, cards use `rgba(15, 23, 42, 0.8)`
- Accent blue `#3b82f6`, purple `#8b5cf6`
- CSS custom properties for all tokens in `:root`
- CSS file ~27KB gzipped after improvements
- Bundle ~176KB gzipped (Recharts is the major weight contributor)

**How to apply:** When adding new views or components, follow the same hook-based patterns and use the CSS custom properties for colors/spacing. Do not add new npm dependencies without checking bundle impact.
