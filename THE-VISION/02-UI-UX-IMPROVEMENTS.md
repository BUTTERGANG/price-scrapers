# UI/UX Improvement Recommendations

## High Priority

### 1. Add Product Images
**Current:** Product cards show text-only with retailer name, price, and product name.
**Improvement:** Many scraper APIs return image URLs (Kroger, Target, Walmart, Whole Foods all provide product images in their API responses). Display thumbnails on product cards to help users visually identify products.
**Impact:** Massive improvement to scanability — users recognize products by sight faster than by reading names like "Kroger 2% Reduced Fat Milk 1 gal".

### 2. Search-as-you-Type with Debounce
**Current:** User must type a query and click "Search" or press Enter.
**Improvement:** Add debounced auto-search (300ms delay) as the user types, with a dropdown showing top 5 results. Keep the full search on Enter.
**Impact:** Reduces friction for quick price checks — the most common use case.

### 3. Better Empty States
**Current:** Empty states show plain text like "No results for 'xyz'" or "Your watchlist is empty."
**Improvement:** Add illustrations or icons, suggest popular searches, link to related actions. For example:
- Empty search: "Try searching for: milk, eggs, chicken breast, bread"
- Empty watchlist: Show a star icon with "Star items from Deals or Search to track prices here"
- No deals: "No deals above X%. Try lowering the threshold →"
**Impact:** Guides new users and reduces dead-ends.

### 4. Mobile Navigation
**Current:** 8 tabs wrap on mobile but become cramped and hard to tap.
**Improvement:** On mobile (< 768px), switch to a bottom navigation bar with icons for the top 4-5 tabs and a "More" overflow menu. Or use a hamburger menu.
**Impact:** Currently, the tab bar is nearly unusable on phones — tabs are too small to tap accurately.

### 5. Price Alert / Notification System
**Current:** Users must manually check the dashboard for price changes.
**Improvement:** Allow users to set a target price on watchlist items. When the price drops below the target, show a notification badge on the Watchlist tab and highlight the item.
**Impact:** This is the killer feature for a price tracker — "tell me when eggs are under $3."

---

## Medium Priority

### 6. Retailer Logos / Icons
**Current:** Retailer names shown as plain uppercase text.
**Improvement:** Add small retailer logos or colored icons next to retailer names. Use consistent color coding (e.g., Kroger = blue, Target = red, Aldi = orange) across all views.
**Impact:** Faster visual scanning; makes the dashboard feel more polished.

### 7. Compare View: Market Basket Calculator
**Current:** Market basket lets you add items but doesn't calculate a total per retailer.
**Improvement:** For each basket item, fetch the cheapest price at each retailer, then show a summary: "Your basket at Kroger: $24.50 | at Aldi: $19.80 | at Meijer: $22.10". Highlight the cheapest total.
**Impact:** This answers the #1 question: "Where should I shop this week?"

### 8. Deals View: Sort Options
**Current:** Deals are displayed with filters (min %, department, group by) but no sort.
**Improvement:** Add sort by: highest discount %, lowest price, alphabetical, retailer. Default to highest discount.
**Impact:** Users looking for the best deals want to see the steepest discounts first.

### 9. History View: Date Range Picker
**Current:** Shows last 200 history records and last 500 trend data points.
**Improvement:** Add a date range picker (7d, 30d, 90d, all time) to control the time window. Show the price change over the selected period.
**Impact:** Users want to see "how has this price changed over the last month?" not just an arbitrary window.

### 10. Loading Skeletons Instead of Spinners
**Current:** Loading states show a centered spinner with "Loading..." text.
**Improvement:** Use skeleton loading cards (gray pulsing rectangles in card shapes) to give a preview of the layout before data arrives.
**Impact:** Perceived performance improvement — the page feels faster because the layout doesn't shift.

---

## Lower Priority (Polish)

### 11. Dark/Light Theme Toggle
**Current:** Dark theme only.
**Improvement:** Add a theme toggle in the header. Some users prefer light mode, especially during daytime use.

### 12. Keyboard Shortcuts
- `/` to focus search
- `1-8` to switch tabs
- `Esc` to clear search
- `s` to star/unstar a focused card

### 13. Share / Export
- Share a comparison as a link
- Export deals or search results as CSV
- "Share this deal" button that copies a formatted text snippet

### 14. Accessibility Improvements
**Current issues found:**
- No `aria-label` on icon-only buttons (star button, close button)
- No `role="tab"` / `role="tabpanel"` on navigation tabs
- Color contrast on `var(--text-secondary)` (#94a3b8) against dark background is borderline (4.2:1 — passes AA but not AAA)
- No focus indicators on cards (only buttons have focus styles)
- `<table>` elements lack `<caption>` for screen readers

### 15. Onboarding / First-Run Experience
For new users who haven't run any scrapers yet:
- Show a welcome screen explaining what the app does
- Guide them to the Stores tab to run their first scrape
- Show progress as scrapers run

### 16. Real-Time Scrape Progress
**Current:** "Run All Scrapers" button starts scraping and refreshes store status after 5 seconds.
**Improvement:** Use Server-Sent Events (SSE) or WebSocket to stream real-time scraper progress: which scraper is running, how many items found so far, errors encountered.
