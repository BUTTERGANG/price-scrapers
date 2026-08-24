---
status: backlog
priority: P2
agent_claimed: null
claimed_at: null
updated: 2026-08-20
---

# Kroger and Walmart Scraper Integration

> **Repo:** price-scrapers
> **Description:** Add Kroger API and Walmart scraper to current retailer list

---

## Context

Currently scraping limited retailers. Kroger API and Walmart are essential for Broad Ripple grocery coverage.

---

## Acceptance Criteria

- [ ] Kroger API connection with OAuth token refresh
- [ ] Walmart product page scraper with search and category browsing
- [ ] Normalized product schema with UPC and store-specific IDs
- [ ] Scheduled scrape cadence with per-retailer rate limiting

---

## Technical Notes

- Kroger API docs; Playwright for Walmart; NeonDB for storage; Python asyncio for concurrent scrapes
