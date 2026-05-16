# Product Roadmap & Vision

## The Vision

**Price Board** is a local grocery intelligence platform that helps households in the Indianapolis area make smarter shopping decisions. The goal is to answer three questions:

1. **"Where is this cheapest?"** — Real-time cross-retailer price comparison
2. **"What's on sale this week?"** — Aggregated deals from 14 retailers in one view
3. **"When should I buy?"** — Historical price trends reveal cyclical sales patterns

---

## Phase 1: Stability & Performance (Now)

Focus: Fix critical issues, improve reliability, make what exists work better.

- [ ] **Connection pooling** — Replace per-request connections with a thread pool
- [ ] **Schema migration on startup only** — Remove `_ensure_schema()` from `get_conn()`
- [ ] **Scrape concurrency guard** — Prevent duplicate simultaneous scrape runs
- [ ] **Thread-safe DB access** — One connection per worker thread in runner.py
- [ ] **Fix CORS configuration** — Remove `allow_credentials=True` or restrict origins
- [ ] **Add basic API response caching** — In-memory TTL cache for dashboard, departments
- [ ] **Pin dependency versions** — Lock requirements.txt to exact versions
- [ ] **Error boundaries in React** — Catch rendering errors gracefully

---

## Phase 2: Core UX Improvements (Next)

Focus: Make the app genuinely useful for daily shopping decisions.

- [ ] **Market Basket Calculator** — "Your basket costs $X at Kroger, $Y at Aldi"
- [ ] **Price alerts** — Set target prices, get notified when price drops below
- [ ] **Product images** — Show product thumbnails from scraper APIs
- [ ] **Better search** — Full-text search with PostgreSQL tsvector, auto-suggest
- [ ] **Date range filters** — Control time windows on history/trend charts
- [ ] **Sort options on deals** — By discount %, price, retailer
- [ ] **Loading skeletons** — Replace spinners with skeleton cards
- [ ] **Refresh watchlist data** — Fetch current prices for watchlisted items

---

## Phase 3: Smart Features (Future)

Focus: Use the historical data to surface insights users can't get elsewhere.

- [ ] **Weekly shopping report** — Automated summary: "This week's best deals on your regular items"
- [ ] **Price prediction** — "Eggs typically go on sale every 3 weeks at Kroger — next expected: March 28"
- [ ] **Seasonal trends** — "Turkey prices drop 40% the week after Thanksgiving"
- [ ] **Store-specific profiles** — "Aldi is cheapest for staples, Kroger for variety, Fresh Thyme for organic"
- [ ] **Meal planning integration** — "Chicken breast is cheapest at Aldi this week — here are 3 recipes"
- [ ] **Automated scheduling** — Scrapers run daily on a cron schedule
- [ ] **Push notifications** — Via Telegram bot or browser push API

---

## Phase 4: Scale & Polish (Later)

- [ ] **Multi-city support** — Configurable ZIP code, auto-discover nearby stores
- [ ] **User accounts** — Persistent preferences, watchlists, and alerts across devices
- [ ] **PWA / Mobile app** — Install as app on phone for quick price checks in-store
- [ ] **Community features** — User-submitted in-store prices, clearance reports
- [ ] **Unblock Walmart & Costco** — Residential proxy integration for blocked scrapers
- [ ] **Component library** — Split App.jsx into proper component structure
- [ ] **API rate limiting** — Protect backend from abuse
- [ ] **Monitoring / alerting** — Know when scrapers break before users notice

---

## Key Metrics to Track

| Metric | Current | Target |
|--------|---------|--------|
| Working scrapers | 13/15 | 15/15 |
| Data freshness (all retailers < 24h old) | Unknown | 100% |
| API response time (p95) | Unknown | < 500ms |
| Frontend load time | Unknown | < 2s |
| Active deals displayed | Unknown | 200+ per week |
| User-facing errors | Unknown | 0 |

---

## Competitive Landscape

| App | Focus | Limitation Price Board Addresses |
|-----|-------|----------------------------------|
| Flipp | Weekly circulars | Generic, no price tracking over time |
| Basket | Price comparison | Limited retailers, crowd-sourced data |
| Instacart | Delivery prices | Not in-store prices, delivery markup |
| Google Shopping | Product search | No grocery focus, no local pricing |
| **Price Board** | Local grocery intelligence | Covers 14 local retailers, tracks trends, compares unit prices |
