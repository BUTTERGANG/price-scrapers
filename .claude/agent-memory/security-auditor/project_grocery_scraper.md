---
name: grocery_scraper_project_profile
description: Architecture, tech stack, and security posture of the grocery price scraper project
type: project
---

FastAPI backend (server.py) + React frontend (frontend/src/App.jsx) + PostgreSQL via psycopg2 (NeonDB).
Telegram bot interface (telegram_bot.py). Scrapers for ~13 retailers.

**Why:** Indianapolis-area grocery price tracking and comparison tool.

**How to apply:** All security reviews should focus on the API-to-DB boundary, the Telegram bot (no auth at all), and the f-string SQL construction pattern in utils/db.py and telegram_bot.py.

Key security facts:
- DB: psycopg2 with PostgreSQL (NeonDB). NOT SQLite despite some SQLite syntax (? placeholders) visible in telegram_bot.py — this is dead code that will error at runtime.
- CORS: allow_origins=["*"] with allow_credentials=False — wildcard but credentials disabled.
- Auth: Zero authentication on ALL FastAPI endpoints, including POST /api/scrape.
- Telegram bot: Zero user whitelist — any Telegram user who discovers the bot token can trigger scrapes and query price data.
- SQL injection risk area: cheapest_per_retailer() in utils/db.py uses f-string to interpolate name_clause and relevance_order strings into SQL, but these strings are constructed from hardcoded templates (not user input directly). User input flows only through parameterized %(pat)s and %(end_pat)s placeholders.
- _weekly_specials() in telegram_bot.py uses an f-string to insert category_filter, but category_filter is itself only ever "AND LOWER(p.name) LIKE ?" — user input goes through the ? placeholder.
- Error messages: /api/status returns str(e) of DB connection errors directly to callers.
- Raw scrape data saved to data/raw/{retailer}/ on disk — no path traversal possible (retailer names are hardcoded).
- No rate limiting on any endpoint.
- Dependencies use >= version pins (unpinned upper bounds).
- uvicorn runs with reload=True in __main__ block (dev mode in production).
