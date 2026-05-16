---
name: Database schema conventions
description: prices/runs/failed_queries schema — TEXT timestamps, extra_json overflow, append-only design
type: project
---

Three tables: prices (append-only), runs (one row per scraper execution), failed_queries (FK to runs.id).

Timestamps are stored as TEXT in ISO-8601 format (e.g. "2026-03-26T14:05:33.123456") — NOT as TIMESTAMP WITH TIME ZONE. This means interval arithmetic requires CAST(col AS timestamp) or LEFT(col,10) string slicing. The get_scrape_activity() function uses LEFT(started_at,10) for date grouping; get_data_freshness() uses MAX(scraped_at)::timestamp.

extra_json (TEXT) stores overflow fields as a JSON string. deal_text, sale_story, pre_price_text may appear here. Accessed via extra_json::json->>'field'. The compare.py helpers use json.loads() to parse it in Python.

Indexes: idx_prices_name_lower on LOWER(name) — used by all name-search queries. idx_prices_lookup on (retailer, product_id, scraped_at) — used by latest-record joins. idx_prices_scraped_at on scraped_at — used by time-range filters.

No TIMESTAMP type, no UNIQUE constraints on prices (fully append-only). Deduplication within a run is done in Python (validate_results) before insert.
