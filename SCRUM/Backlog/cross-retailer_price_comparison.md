---
status: backlog
priority: P2
agent_claimed: null
claimed_at: null
updated: 2026-08-20
---

# Cross-Retailer Price Comparison

> **Repo:** price-scrapers
> **Description:** Side-by-side comparison of same product across all tracked retailers

---

## Context

Match products across retailers by UPC, brand+size, or name similarity to show where each item is cheapest.

---

## Acceptance Criteria

- [ ] Product matching by UPC with manual merge for unmatched items
- [ ] Side-by-side comparison view with price per unit breakdown
- [ ] Savings total for building a basket at the cheapest store
- [ ] Price history mini-chart per product per retailer

---

## Technical Notes

- Fuzzy matching for product name alignment; Postgres for storage; Recharts for mini-charts
