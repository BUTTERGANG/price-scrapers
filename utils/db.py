"""PostgreSQL (NeonDB) price history database.

Stores every scraped price record with a timestamp so we can:
- Detect when a price drops (a real sale vs. already-low everyday price)
- Track price trends over time
- Find the lowest price ever seen for a product
- Alert when a price returns to normal after a sale ends

Schema:
  prices        — append-only price records
  runs          — one row per scraper execution (start/end time, status, counts)
  failed_queries — queries that errored during a run, for targeted reruns
"""
import json
import logging
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Optional

import psycopg2
import psycopg2.extras
import psycopg2.pool

logger = logging.getLogger(__name__)

# Connection pool — initialized lazily on first use.
_pool: Optional[psycopg2.pool.ThreadedConnectionPool] = None
_pool_lock = __import__("threading").Lock()
_schema_initialized = False


def _get_dsn() -> str:
    dsn = os.environ.get("NEONDB1") or os.environ.get("DATABASE_URL")
    if not dsn:
        raise RuntimeError("No database connection string found (NEONDB1 or DATABASE_URL)")
    return dsn


def _get_pool() -> psycopg2.pool.ThreadedConnectionPool:
    """Return the shared connection pool, creating it on first call."""
    global _pool
    if _pool is None:
        with _pool_lock:
            if _pool is None:
                _pool = psycopg2.pool.ThreadedConnectionPool(
                    minconn=1,
                    maxconn=20,
                    dsn=_get_dsn(),
                    cursor_factory=psycopg2.extras.RealDictCursor,
                )
    return _pool


def init_db() -> None:
    """Initialize the database schema. Call once at startup."""
    global _schema_initialized
    if _schema_initialized:
        return
    conn = get_conn()
    try:
        _ensure_schema(conn)
        _schema_initialized = True
    finally:
        release_conn(conn)


def get_conn():
    """Return a PostgreSQL connection from the pool. Tries NEONDB1, then DATABASE_URL."""
    pool = _get_pool()
    conn = pool.getconn()
    conn.autocommit = False
    with conn.cursor() as cur:
        # Prevent runaway queries from blocking indefinitely (30 second limit).
        cur.execute("SET statement_timeout = '30s'")
        # Neon's pooler runs in transaction mode, where session-level SETs from
        # other clients (e.g. test fixtures) can leak into reused server
        # sessions — pin the search_path so we never inherit one.
        cur.execute("SET search_path TO public")
    conn.commit()
    return conn


def release_conn(conn) -> None:
    """Return a connection to the pool instead of closing it."""
    if conn is None:
        return
    try:
        pool = _get_pool()
        pool.putconn(conn)
    except Exception:
        # If pool is closed or connection is broken, just close it
        try:
            conn.close()
        except Exception:
            pass


def _ensure_schema(conn) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS prices (
                id                    SERIAL PRIMARY KEY,
                retailer              TEXT    NOT NULL,
                store_id              TEXT    NOT NULL,
                product_id            TEXT    NOT NULL,
                upc                   TEXT,
                name                  TEXT    NOT NULL,
                brand                 TEXT,
                department            TEXT,
                price                 DOUBLE PRECISION,
                sale_price            DOUBLE PRECISION,
                unit                  TEXT,
                unit_price            DOUBLE PRECISION,
                unit_price_normalized DOUBLE PRECISION,
                unit_canonical        TEXT,
                url                   TEXT,
                extra_json            TEXT,
                scraped_at            TIMESTAMPTZ NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_prices_upc
                ON prices (upc)
                WHERE upc IS NOT NULL;

            CREATE INDEX IF NOT EXISTS idx_prices_lookup
                ON prices (retailer, product_id, scraped_at);

            CREATE INDEX IF NOT EXISTS idx_prices_brand
                ON prices (brand)
                WHERE brand IS NOT NULL;

            CREATE INDEX IF NOT EXISTS idx_prices_department
                ON prices (department)
                WHERE department IS NOT NULL;

            CREATE INDEX IF NOT EXISTS idx_prices_name_lower
                ON prices (LOWER(name));

            CREATE INDEX IF NOT EXISTS idx_prices_scraped_at
                ON prices (scraped_at);

            -- Prevent duplicate inserts for the same product in the same run.
            CREATE UNIQUE INDEX IF NOT EXISTS idx_prices_no_dup
                ON prices (retailer, product_id, scraped_at);

            -- One row per scraper execution.
            -- status: 'running' | 'success' | 'partial' | 'failed'
            CREATE TABLE IF NOT EXISTS runs (
                id              SERIAL PRIMARY KEY,
                retailer        TEXT    NOT NULL,
                store_id        TEXT    NOT NULL,
                status          TEXT    NOT NULL DEFAULT 'running',
                queries_total   INTEGER NOT NULL DEFAULT 0,
                queries_ok      INTEGER NOT NULL DEFAULT 0,
                queries_failed  INTEGER NOT NULL DEFAULT 0,
                records_saved   INTEGER NOT NULL DEFAULT 0,
                error           TEXT,
                started_at      TIMESTAMPTZ NOT NULL,
                finished_at     TIMESTAMPTZ
            );

            -- Individual query failures within a run, for targeted reruns.
            CREATE TABLE IF NOT EXISTS failed_queries (
                id          SERIAL PRIMARY KEY,
                run_id      INTEGER NOT NULL REFERENCES runs(id),
                retailer    TEXT    NOT NULL,
                query       TEXT    NOT NULL,
                error_type  TEXT,
                error_msg   TEXT,
                failed_at   TIMESTAMPTZ NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_failed_queries_retailer_at
                ON failed_queries (retailer, failed_at DESC);
            """
        )
        _migrate_text_timestamps(cur)
    conn.commit()

    # Trigram index speeds up the ILIKE / word-boundary-regex name searches.
    # Separate transaction: CREATE EXTENSION may be denied on some hosts and
    # must not roll back the schema setup above.
    try:
        with conn.cursor() as cur:
            cur.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
            cur.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_prices_name_trgm
                    ON prices USING gin (LOWER(name) gin_trgm_ops)
                """
            )
        conn.commit()
    except Exception as exc:
        conn.rollback()
        logger.warning(f"pg_trgm index unavailable (searches fall back to seq scan): {exc}")


def _migrate_text_timestamps(cur) -> None:
    """One-time migration: convert legacy TEXT timestamp columns (ISO-8601
    strings from the SQLite era) to native TIMESTAMPTZ."""
    for table, column in (
        ("prices", "scraped_at"),
        ("runs", "started_at"),
        ("runs", "finished_at"),
        ("failed_queries", "failed_at"),
    ):
        cur.execute(
            """
            SELECT data_type FROM information_schema.columns
            WHERE table_schema = current_schema()
              AND table_name = %s AND column_name = %s
            """,
            (table, column),
        )
        row = cur.fetchone()
        if row and row["data_type"] == "text":
            logger.info(f"Migrating {table}.{column} TEXT -> TIMESTAMPTZ")
            cur.execute(
                f"ALTER TABLE {table} ALTER COLUMN {column} TYPE TIMESTAMPTZ "
                f"USING NULLIF({column}, '')::timestamptz"
            )


def insert_price(conn, record: dict) -> int:
    """Insert one normalized price record. Returns the new row ID."""
    _KNOWN_COLS = {
        "retailer", "store_id", "product_id", "upc", "name",
        "brand", "department",
        "price", "sale_price", "unit", "unit_price",
        "unit_price_normalized", "unit_canonical",
        "url", "scraped_at",
    }
    extra = {k: v for k, v in record.items() if k not in _KNOWN_COLS}
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO prices
                (retailer, store_id, product_id, upc, name, brand, department,
                 price, sale_price, unit, unit_price, unit_price_normalized, unit_canonical,
                 url, extra_json, scraped_at)
            VALUES
                (%(retailer)s, %(store_id)s, %(product_id)s, %(upc)s, %(name)s, %(brand)s, %(department)s,
                 %(price)s, %(sale_price)s, %(unit)s, %(unit_price)s, %(unit_price_normalized)s, %(unit_canonical)s,
                 %(url)s, %(extra_json)s, %(scraped_at)s)
            ON CONFLICT (retailer, product_id, scraped_at) DO NOTHING
            RETURNING id
            """,
            {
                "retailer":             record.get("retailer", ""),
                "store_id":             record.get("store_id", ""),
                "product_id":           record.get("product_id", ""),
                "upc":                  record.get("upc"),
                "name":                 record.get("name", ""),
                "brand":                record.get("brand") or None,
                "department":           record.get("department") or None,
                "price":                record.get("price"),
                "sale_price":           record.get("sale_price"),
                "unit":                 record.get("unit"),
                "unit_price":           record.get("unit_price"),
                "unit_price_normalized": record.get("unit_price_normalized"),
                "unit_canonical":       record.get("unit_canonical"),
                "url":                  record.get("url"),
                "extra_json":           json.dumps(extra) if extra else None,
                "scraped_at":           record.get("scraped_at") or datetime.now(timezone.utc),
            },
        )
        row = cur.fetchone()
        row_id = row["id"] if row else None
    conn.commit()
    return row_id


def _insert_price_row(cur, record: dict) -> bool:
    """Insert one record using the given cursor. Returns True if a row was inserted."""
    _KNOWN_COLS = {
        "retailer", "store_id", "product_id", "upc", "name",
        "brand", "department",
        "price", "sale_price", "unit", "unit_price",
        "unit_price_normalized", "unit_canonical",
        "url", "scraped_at",
    }
    extra = {k: v for k, v in record.items() if k not in _KNOWN_COLS}
    cur.execute(
        """
        INSERT INTO prices
            (retailer, store_id, product_id, upc, name, brand, department,
             price, sale_price, unit, unit_price, unit_price_normalized, unit_canonical,
             url, extra_json, scraped_at)
        VALUES
            (%(retailer)s, %(store_id)s, %(product_id)s, %(upc)s, %(name)s, %(brand)s, %(department)s,
             %(price)s, %(sale_price)s, %(unit)s, %(unit_price)s, %(unit_price_normalized)s, %(unit_canonical)s,
             %(url)s, %(extra_json)s, %(scraped_at)s)
        ON CONFLICT (retailer, product_id, scraped_at) DO NOTHING
        """,
        {
            "retailer":             record.get("retailer", ""),
            "store_id":             record.get("store_id", ""),
            "product_id":           record.get("product_id", ""),
            "upc":                  record.get("upc"),
            "name":                 record.get("name", ""),
            "brand":                record.get("brand") or None,
            "department":           record.get("department") or None,
            "price":                record.get("price"),
            "sale_price":           record.get("sale_price"),
            "unit":                 record.get("unit"),
            "unit_price":           record.get("unit_price"),
            "unit_price_normalized": record.get("unit_price_normalized"),
            "unit_canonical":       record.get("unit_canonical"),
            "url":                  record.get("url"),
            "extra_json":           json.dumps(extra) if extra else None,
            "scraped_at":           record.get("scraped_at") or datetime.now(timezone.utc),
        },
    )
    return cur.rowcount > 0


def insert_many(conn, records: list[dict]) -> int:
    """Bulk insert inside a single transaction. Returns number of rows actually inserted."""
    if not records:
        return 0
    inserted = 0
    try:
        with conn.cursor() as cur:
            for record in records:
                if _insert_price_row(cur, record):
                    inserted += 1
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return inserted


# ---------------------------------------------------------------------------
# Run logging
# ---------------------------------------------------------------------------

def start_run(conn, retailer: str, store_id: str, queries_total: int) -> int:
    """Insert a 'running' run record. Returns the run ID."""
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO runs (retailer, store_id, status, queries_total, started_at)
            VALUES (%s, %s, 'running', %s, %s)
            RETURNING id
            """,
            (retailer, store_id, queries_total, datetime.now(timezone.utc)),
        )
        run_id = cur.fetchone()["id"]
    conn.commit()
    return run_id


def finish_run(
    conn,
    run_id: int,
    queries_ok: int,
    queries_failed: int,
    records_saved: int,
    error: Optional[str] = None,
) -> None:
    """Update a run record with final counts and status."""
    if error:
        status = "failed"
    elif queries_failed > 0:
        status = "partial"
    else:
        status = "success"

    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE runs
            SET status         = %s,
                queries_ok     = %s,
                queries_failed = %s,
                records_saved  = %s,
                error          = %s,
                finished_at    = %s
            WHERE id = %s
            """,
            (status, queries_ok, queries_failed, records_saved,
             error, datetime.now(timezone.utc), run_id),
        )
    conn.commit()


def log_failed_query(
    conn,
    run_id: int,
    retailer: str,
    query: str,
    exc: Exception,
) -> None:
    """Record a single failed query for later rerun."""
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO failed_queries
                (run_id, retailer, query, error_type, error_msg, failed_at)
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (
                run_id,
                retailer,
                query,
                type(exc).__name__,
                str(exc),
                datetime.now(timezone.utc),
            ),
        )
    conn.commit()


def get_failed_queries(
    conn, retailer: str, run_id: Optional[int] = None
) -> list[str]:
    if run_id is not None:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT query FROM failed_queries WHERE retailer=%s AND run_id=%s",
                (retailer, run_id),
            )
            rows = cur.fetchall()
    else:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT DISTINCT query FROM failed_queries
                WHERE retailer = %s
                ORDER BY failed_at DESC
                """,
                (retailer,),
            )
            rows = cur.fetchall()
    return [r["query"] for r in rows]


def last_successful_run(conn, retailer: str) -> Optional[dict]:
    """Return the most recent run with status 'success' or 'partial' for a retailer."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT * FROM runs
            WHERE retailer = %s AND status IN ('success', 'partial')
            ORDER BY finished_at DESC
            LIMIT 1
            """,
            (retailer,),
        )
        row = cur.fetchone()
    return dict(row) if row else None


def price_history(
    conn,
    retailer: str,
    product_id: str,
    limit: int = 30,
) -> list[dict]:
    """Return the most recent price records for a product, newest first."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT * FROM prices
            WHERE retailer = %s AND product_id = %s
            ORDER BY scraped_at DESC
            LIMIT %s
            """,
            (retailer, product_id, limit),
        )
        rows = cur.fetchall()
    return [dict(r) for r in rows]


def lowest_price_ever(conn, retailer: str, product_id: str) -> Optional[float]:
    """Return the lowest regular price ever recorded for a product."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT MIN(price) AS min_price FROM prices WHERE retailer=%s AND product_id=%s AND price > 0",
            (retailer, product_id),
        )
        row = cur.fetchone()
    return row["min_price"] if row else None


def find_active_deals(
    conn,
    min_savings_pct: float = 10.0,
    limit: int = 500,
    offset: int = 0,
    max_age_days: int = 7,
) -> list[dict]:
    """
    Return the most recent price record for each product that is currently on deal.

    "Active" is scoped to the most recent scrape batch per retailer — products
    scraped within 30 minutes of that retailer's latest run. This prevents
    individual products that dropped out of the circular from showing stale deals
    while still surfacing data even if the last run was months ago.

    max_age_days (default 7): if the RETAILER'S most recent scrape is older than
    this many days, its products are excluded (the data is too old to be reliable).

    Two sources combined:
    1. sale_price < price deals — explicit regular vs. sale price pair.
    2. deal_text deals — BOGO / % off / multi-unit deals without a numeric price.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            -- Most recent scrape timestamp per retailer (no age filter yet)
            WITH retailer_latest AS (
                SELECT retailer, MAX(scraped_at) AS latest_run
                FROM prices
                GROUP BY retailer
            ),
            -- Products in their retailer's most recent batch
            -- (scraped within 30 minutes of the retailer's latest run)
            fresh_latest AS (
                SELECT p.retailer, p.product_id, MAX(p.scraped_at) AS latest
                FROM prices p
                JOIN retailer_latest rl ON p.retailer = rl.retailer
                WHERE p.scraped_at >= rl.latest_run - interval '30 minutes'
                  -- Exclude retailers whose most recent batch is older than max_age_days
                  AND rl.latest_run >= NOW() - (%s || ' days')::interval
                GROUP BY p.retailer, p.product_id
            ),

            -- Part 1: numeric sale_price deals
            price_deals AS (
                SELECT p.*,
                       ROUND(CAST((p.price - p.sale_price) / p.price * 100 AS numeric), 1) AS savings_pct
                FROM prices p
                INNER JOIN fresh_latest fl
                    ON p.retailer = fl.retailer
                   AND p.product_id = fl.product_id
                   AND p.scraped_at = fl.latest
                WHERE p.sale_price IS NOT NULL
                  AND p.sale_price < p.price
                  AND p.price > 0
                  AND ROUND(CAST((p.price - p.sale_price) / p.price * 100 AS numeric), 1) >= %s
            ),

            -- Part 2: text-only deals (BOGO, %% off, multi-unit, etc.)
            text_deals AS (
                SELECT p.*,
                       NULL::numeric AS savings_pct
                FROM prices p
                INNER JOIN fresh_latest fl
                    ON p.retailer = fl.retailer
                   AND p.product_id = fl.product_id
                   AND p.scraped_at = fl.latest
                WHERE (p.sale_price IS NULL OR p.sale_price >= p.price)
                  AND p.extra_json IS NOT NULL
                  AND p.extra_json::json->>'deal_text' IS NOT NULL
            )

            -- Combine deals; price deals first, then text deals interleaved by
            -- row-number per retailer so no single retailer dominates.
            SELECT combined.id, combined.retailer, combined.store_id, combined.product_id,
                   combined.upc, combined.name, combined.brand, combined.department,
                   combined.price, combined.sale_price, combined.unit, combined.unit_price,
                   combined.unit_price_normalized, combined.unit_canonical, combined.url,
                   combined.extra_json, combined.scraped_at, combined.savings_pct
            FROM (
                SELECT pd.*, 0 AS rn FROM price_deals pd
                UNION ALL
                SELECT td.*,
                       ROW_NUMBER() OVER (PARTITION BY td.retailer ORDER BY td.name)::int AS rn
                FROM text_deals td
            ) combined
            ORDER BY
                CASE WHEN combined.savings_pct IS NOT NULL THEN 0 ELSE 1 END,
                combined.savings_pct DESC NULLS LAST,
                combined.rn,
                combined.retailer,
                combined.name
            LIMIT %s OFFSET %s
            """,
            (max_age_days, min_savings_pct, limit, offset),
        )
        rows = cur.fetchall()
    return [dict(r) for r in rows]


def cheapest_per_retailer(conn, name_contains: str, limit: int = 50, offset: int = 0) -> list[dict]:
    """
    For a product matching a name substring, return the cheapest current price
    per retailer. Uses the latest record per product (no hard time cutoff)
    so results remain visible even if scrapers haven't run recently.

    Single-word queries use PostgreSQL word-boundary regex (\\m...\\M) so that
    searching "milk" matches "Whole Milk" and "Almond Milk" but not "Buttermilk"
    or "Milkshake Waffles". Multi-word queries fall back to LIKE.

    Zero-price items (price=0, no sale price) are excluded from numeric results.
    Text-only deal items (price IS NULL, deal_text present) are returned as a
    secondary group — only for retailers that have no numeric result.
    """
    q = name_contains.strip().lower()

    if " " not in q:
        # Word-boundary regex: \m = start-of-word, \M = end-of-word (PostgreSQL ARE)
        safe = re.escape(q)
        name_clause = "name ~* %(pat)s"
        pattern = rf"\m{safe}\M"
        # end_pat matches the query word as the LAST word in the name — a strong
        # signal that the product IS that thing (e.g. "Kroger Cheese", "Cheddar
        # Cheese") rather than containing it as an ingredient or flavor descriptor
        # (e.g. "Tortellini, Cheese", "RICE-A-RONI FOUR CHEESE" still end with it
        # but lose to shorter names in the next tiebreak).
        end_pat = rf"\m{safe}\M\s*$"
    else:
        name_clause = "LOWER(name) LIKE %(pat)s"
        pattern = f"%{q}%"
        end_pat = None

    params: dict = {"pat": pattern}

    if end_pat:
        params["end_pat"] = end_pat
        relevance_order = """
            -- Tier 0: query word ends the name (product category indicator)
            CASE WHEN LOWER(p.name) ~ %(end_pat)s THEN 0 ELSE 1 END ASC,
            -- Within same tier, fewer words = less ingredient/modifier noise
            cardinality(regexp_split_to_array(trim(p.name), '\\s+')) ASC,
        """
    else:
        relevance_order = ""

    with conn.cursor() as cur:
        # Part 1: numeric-price items (existing behaviour, keeps > 0 guard)
        cur.execute(
            f"""
            SELECT p.*
            FROM prices p
            INNER JOIN (
                SELECT retailer, product_id, MAX(scraped_at) AS latest
                FROM prices
                WHERE {name_clause}
                GROUP BY retailer, product_id
            ) latest_only
                ON p.retailer = latest_only.retailer
               AND p.product_id = latest_only.product_id
               AND p.scraped_at = latest_only.latest
            WHERE {name_clause}
              AND COALESCE(p.sale_price, p.price) > 0
            ORDER BY
                p.retailer,
                {relevance_order}
                COALESCE(p.sale_price, p.price) ASC
            """,
            params,
        )
        numeric_rows = [dict(r) for r in cur.fetchall()]

        # Part 2: text-only deal items (price IS NULL, deal_text present)
        cur.execute(
            f"""
            SELECT p.*
            FROM prices p
            INNER JOIN (
                SELECT retailer, product_id, MAX(scraped_at) AS latest
                FROM prices
                WHERE {name_clause}
                GROUP BY retailer, product_id
            ) latest_only
                ON p.retailer = latest_only.retailer
               AND p.product_id = latest_only.product_id
               AND p.scraped_at = latest_only.latest
            WHERE {name_clause}
              AND p.price IS NULL
              AND p.sale_price IS NULL
              AND p.extra_json IS NOT NULL
              AND p.extra_json::json->>'deal_text' IS NOT NULL
            ORDER BY
                p.retailer,
                p.name ASC
            """,
            params,
        )
        text_rows = [dict(r) for r in cur.fetchall()]

    # Numeric results take priority: collect cheapest numeric per retailer first.
    seen: set = set()
    results: list = []
    for row in numeric_rows:
        if row["retailer"] not in seen:
            seen.add(row["retailer"])
            results.append(row)

    # Then, for retailers with no numeric result, add the first text-deal row.
    for row in text_rows:
        if row["retailer"] not in seen:
            seen.add(row["retailer"])
            results.append(row)

    return results[offset:offset + limit]


def find_by_upc(conn, upc: str) -> list[dict]:
    """
    Return the most recent price record per retailer for a given UPC barcode.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT p.*
            FROM prices p
            INNER JOIN (
                SELECT retailer, product_id, MAX(scraped_at) AS latest
                FROM prices
                WHERE upc = %s
                GROUP BY retailer, product_id
            ) latest_only
                ON p.retailer = latest_only.retailer
               AND p.product_id = latest_only.product_id
               AND p.scraped_at = latest_only.latest
            WHERE p.upc = %s
            ORDER BY COALESCE(p.sale_price, p.price) ASC
            """,
            (upc, upc),
        )
        rows = cur.fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Additional query helpers (for API)
# ---------------------------------------------------------------------------

def get_all_retailers(conn) -> list[str]:
    """Return distinct retailer names that have price data."""
    with conn.cursor() as cur:
        cur.execute("SELECT DISTINCT retailer FROM prices ORDER BY retailer")
        rows = cur.fetchall()
    return [r["retailer"] for r in rows]


def get_store_status(conn) -> list[dict]:
    """Return last run info per retailer."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT DISTINCT ON (retailer) retailer, status, records_saved,
                   started_at, finished_at, error
            FROM runs
            ORDER BY retailer, finished_at DESC NULLS LAST
            """
        )
        rows = cur.fetchall()
    return [dict(r) for r in rows]


def get_price_history_by_name(conn, name_contains: str, limit: int = 100, since: str = None) -> list[dict]:
    """Return recent price records matching a name substring, across all retailers."""
    pattern = f"%{name_contains.lower()}%"
    params = [pattern, limit] if since is None else [pattern, since, limit]
    where_since = "" if since is None else "AND scraped_at >= %s"
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT retailer, product_id, name, brand, price, sale_price,
                   unit, unit_price_normalized, unit_canonical, scraped_at
            FROM prices
            WHERE LOWER(name) LIKE %s
            {where_since}
            ORDER BY scraped_at DESC
            LIMIT %s
            """,
            params,
        )
        rows = cur.fetchall()
    return [dict(r) for r in rows]


def get_db_stats(conn) -> dict:
    """Return basic database statistics for the health endpoint."""
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) AS cnt FROM prices")
        total_prices = cur.fetchone()["cnt"]
        cur.execute("SELECT COUNT(*) AS cnt FROM runs")
        total_runs = cur.fetchone()["cnt"]
        cur.execute("SELECT COUNT(DISTINCT retailer) AS cnt FROM prices")
        retailer_count = cur.fetchone()["cnt"]
        cur.execute("SELECT MAX(scraped_at) AS latest FROM prices")
        latest = cur.fetchone()["latest"]
    return {
        "total_prices": total_prices,
        "total_runs": total_runs,
        "retailer_count": retailer_count,
        "latest_scrape": latest,
    }


# ---------------------------------------------------------------------------
# Dashboard & analytics queries
# ---------------------------------------------------------------------------

def get_dashboard_summary(conn) -> dict:
    """Aggregate stats for the dashboard overview.

    Uses latest record per product (no hard time cutoff).
    """
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(DISTINCT retailer || '::' || product_id) AS cnt FROM prices")
        unique_products = cur.fetchone()["cnt"]

        cur.execute("""
            SELECT COUNT(*) AS cnt FROM prices p
            INNER JOIN (
                SELECT retailer, product_id, MAX(scraped_at) AS latest
                FROM prices GROUP BY retailer, product_id
            ) lp ON p.retailer = lp.retailer AND p.product_id = lp.product_id AND p.scraped_at = lp.latest
            WHERE (p.sale_price IS NOT NULL AND p.sale_price < p.price AND p.price > 0)
               OR (p.extra_json IS NOT NULL AND p.extra_json::json->>'deal_text' IS NOT NULL)
        """)
        active_deals = cur.fetchone()["cnt"]

        cur.execute("""
            SELECT COALESCE(AVG(
                CASE WHEN p.price > 0 AND p.sale_price IS NOT NULL AND p.sale_price < p.price
                THEN ROUND(CAST((p.price - p.sale_price) / p.price * 100 AS numeric), 1)
                END
            ), 0) AS avg_savings
            FROM prices p
            INNER JOIN (
                SELECT retailer, product_id, MAX(scraped_at) AS latest
                FROM prices GROUP BY retailer, product_id
            ) lp ON p.retailer = lp.retailer AND p.product_id = lp.product_id AND p.scraped_at = lp.latest
            WHERE p.sale_price IS NOT NULL AND p.sale_price < p.price AND p.price > 0
        """)
        avg_savings = float(cur.fetchone()["avg_savings"] or 0)

        cur.execute("SELECT COUNT(DISTINCT retailer) AS cnt FROM prices")
        retailer_count = cur.fetchone()["cnt"]

        cur.execute("SELECT MAX(scraped_at) AS latest FROM prices")
        latest = cur.fetchone()["latest"]

    return {
        "unique_products": unique_products,
        "active_deals": active_deals,
        "avg_savings_pct": round(avg_savings, 1),
        "retailer_count": retailer_count,
        "latest_scrape": latest,
    }


def get_market_pulse(conn, limit: int = 10) -> dict:
    """Find biggest price drops and increases vs. previous scrape."""
    _CTE = """
        WITH ranked AS (
            SELECT retailer, product_id, name, price, sale_price, scraped_at,
                   ROW_NUMBER() OVER (PARTITION BY retailer, product_id ORDER BY scraped_at DESC) AS rn
            FROM prices
            WHERE price > 0
        ),
        compared AS (
            SELECT c.retailer, c.product_id, c.name,
                   c.price AS current_price,
                   COALESCE(c.sale_price, c.price) AS current_effective,
                   p.price AS previous_price,
                   COALESCE(p.sale_price, p.price) AS previous_effective,
                   c.scraped_at
            FROM ranked c
            JOIN ranked p ON c.retailer = p.retailer AND c.product_id = p.product_id
            WHERE c.rn = 1 AND p.rn = 2
              AND COALESCE(c.sale_price, c.price) != COALESCE(p.sale_price, p.price)
        )
        SELECT *, ROUND(CAST(
            (current_effective - previous_effective) / NULLIF(previous_effective, 0) * 100
        AS numeric), 1) AS change_pct
        FROM compared
    """
    with conn.cursor() as cur:
        cur.execute(_CTE + " ORDER BY (current_effective - previous_effective) ASC LIMIT %s", (limit,))
        drops = [dict(r) for r in cur.fetchall()]

        cur.execute(_CTE + " ORDER BY (current_effective - previous_effective) DESC LIMIT %s", (limit,))
        increases = [dict(r) for r in cur.fetchall()]

    return {"biggest_drops": drops, "biggest_increases": increases}


def get_scrape_activity(conn, days: int = 14) -> list:
    """Daily record counts from runs table for activity chart."""
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    with conn.cursor() as cur:
        cur.execute("""
            SELECT TO_CHAR(started_at, 'YYYY-MM-DD') AS day,
                   COUNT(*) AS runs,
                   SUM(records_saved) AS records
            FROM runs
            WHERE started_at >= %s::date
            GROUP BY TO_CHAR(started_at, 'YYYY-MM-DD')
            ORDER BY day
        """, (cutoff,))
        rows = cur.fetchall()
    return [dict(r) for r in rows]


def get_departments(conn) -> list:
    """Distinct departments with counts and average prices.

    Returns product_count (retailer-inflated SKU count) and unique_name_count
    (COUNT DISTINCT on lowercased name — an approximate unique-product count
    that is not inflated by the same item appearing at multiple retailers).
    """
    with conn.cursor() as cur:
        cur.execute("""
            SELECT p.department,
                   COUNT(DISTINCT p.retailer || '::' || p.product_id) AS product_count,
                   COUNT(DISTINCT LOWER(p.name)) AS unique_name_count,
                   COUNT(DISTINCT p.retailer) AS retailer_count,
                   ROUND(AVG(COALESCE(p.sale_price, p.price))::numeric, 2) AS avg_price
            FROM prices p
            INNER JOIN (
                SELECT retailer, product_id, MAX(scraped_at) AS latest
                FROM prices GROUP BY retailer, product_id
            ) lp ON p.retailer = lp.retailer AND p.product_id = lp.product_id AND p.scraped_at = lp.latest
            WHERE p.department IS NOT NULL AND p.department != ''
            GROUP BY p.department
            ORDER BY product_count DESC
        """)
        rows = cur.fetchall()
    return [dict(r) for r in rows]


def get_department_products(
    conn,
    department: str,
    limit: int = 200,
    offset: int = 0,
    retailer: str = None,
) -> list:
    """Latest prices for products in a department.

    Args:
        department: exact department name to filter by.
        limit: max rows to return (default 200).
        offset: number of rows to skip for pagination.
        retailer: optional retailer name to narrow results.
    """
    base_where = "department = %(dept)s"
    params: dict = {"dept": department, "limit": limit, "offset": offset}

    if retailer:
        retailer_clause = "AND p.retailer = %(retailer)s"
        inner_retailer_clause = "AND retailer = %(retailer)s"
        params["retailer"] = retailer
    else:
        retailer_clause = ""
        inner_retailer_clause = ""

    with conn.cursor() as cur:
        cur.execute(f"""
            SELECT p.*
            FROM prices p
            INNER JOIN (
                SELECT retailer, product_id, MAX(scraped_at) AS latest
                FROM prices
                WHERE {base_where} {inner_retailer_clause}
                GROUP BY retailer, product_id
            ) lp ON p.retailer = lp.retailer AND p.product_id = lp.product_id AND p.scraped_at = lp.latest
            WHERE p.{base_where} {retailer_clause}
            ORDER BY COALESCE(p.sale_price, p.price) ASC, p.name ASC
            LIMIT %(limit)s
            OFFSET %(offset)s
        """, params)
        rows = cur.fetchall()
    return [dict(r) for r in rows]


def get_price_trend(conn, name_contains: str, limit: int = 500, since: str = None) -> list:
    """Time-series price data for charting."""
    pattern = f"%{name_contains.lower()}%"
    where_since = "" if since is None else "AND scraped_at >= %s"
    params = [pattern, limit] if since is None else [pattern, since, limit]
    with conn.cursor() as cur:
        cur.execute(f"""
            SELECT retailer, product_id, name, price, sale_price, scraped_at
            FROM prices
            WHERE LOWER(name) LIKE %s AND price > 0
            {where_since}
            ORDER BY retailer, product_id, scraped_at ASC
            LIMIT %s
        """, params)
        rows = cur.fetchall()
    return [dict(r) for r in rows]


def get_store_analytics(conn, retailer: str) -> dict:
    """Per-store deep analytics."""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT COUNT(DISTINCT p.product_id) AS product_count,
                   ROUND(AVG(p.price)::numeric, 2) AS avg_price,
                   ROUND(AVG(CASE WHEN p.sale_price IS NOT NULL AND p.sale_price < p.price AND p.price > 0
                       THEN (p.price - p.sale_price) / p.price * 100 END)::numeric, 1) AS avg_discount_pct,
                   COUNT(CASE WHEN p.sale_price IS NOT NULL AND p.sale_price < p.price THEN 1 END) AS deal_count
            FROM prices p
            INNER JOIN (
                SELECT retailer, product_id, MAX(scraped_at) AS latest
                FROM prices WHERE retailer = %s
                GROUP BY retailer, product_id
            ) lp ON p.retailer = lp.retailer AND p.product_id = lp.product_id AND p.scraped_at = lp.latest
            WHERE p.retailer = %s
        """, (retailer, retailer))
        row = cur.fetchone()
        summary = dict(row) if row else {
            "product_count": 0,
            "avg_price": None,
            "avg_discount_pct": None,
            "deal_count": 0,
        }

        cur.execute("""
            SELECT p.department, COUNT(*) AS cnt,
                   ROUND(AVG(COALESCE(p.sale_price, p.price))::numeric, 2) AS avg_price
            FROM prices p
            INNER JOIN (
                SELECT retailer, product_id, MAX(scraped_at) AS latest
                FROM prices WHERE retailer = %s
                GROUP BY retailer, product_id
            ) lp ON p.retailer = lp.retailer AND p.product_id = lp.product_id AND p.scraped_at = lp.latest
            WHERE p.retailer = %s AND p.department IS NOT NULL AND p.department != ''
            GROUP BY p.department ORDER BY cnt DESC
        """, (retailer, retailer))
        departments = [dict(r) for r in cur.fetchall()]

        # Use prefix match so "kroger" finds runs logged as "kroger_weekly_02100959" etc.
        cur.execute("""
            SELECT id, retailer, status, records_saved, started_at, finished_at, error
            FROM runs WHERE retailer LIKE %s
            ORDER BY started_at DESC LIMIT 10
        """, (retailer + '%',))
        recent_runs = [dict(r) for r in cur.fetchall()]

    return {
        "retailer": retailer,
        "summary": summary,
        "departments": departments,
        "recent_runs": recent_runs,
    }


def get_data_freshness(conn) -> list:
    """Per-retailer data freshness for quality indicators."""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT retailer,
                   MAX(scraped_at) AS latest_scrape,
                   COUNT(*) AS record_count,
                   ROUND(EXTRACT(EPOCH FROM (NOW() - MAX(scraped_at))) / 3600, 1) AS hours_ago
            FROM prices
            GROUP BY retailer
            ORDER BY latest_scrape DESC
        """)
        rows = cur.fetchall()
    return [dict(r) for r in rows]


def get_watchlist_prices(conn, items: list[dict]) -> list[dict]:
    """
    Fetch the most recent price record for each (retailer, product_id) pair.
    items: list of {"retailer": str, "product_id": str}
    Returns list of current price records (same shape as prices table).
    """
    if not items:
        return []
    with conn.cursor() as cur:
        results = []
        for item in items:
            cur.execute(
                """
                SELECT * FROM prices
                WHERE retailer = %s AND product_id = %s
                ORDER BY scraped_at DESC
                LIMIT 1
                """,
                (item["retailer"], item["product_id"]),
            )
            row = cur.fetchone()
            if row:
                results.append(dict(row))
    return results


def cleanup_old_prices(conn, days_to_keep: int = 90) -> dict:
    """
    Prune price records older than days_to_keep, while preserving long-term
    trend data by keeping one record per (retailer, product_id, month).

    Strategy:
    - Keep ALL records within the last days_to_keep days.
    - For records older than days_to_keep, keep the first record of each
      calendar month per (retailer, product_id) — this preserves monthly
      price history for trend charts without unbounded DB growth.
    - Delete everything else older than days_to_keep.

    Returns a dict with deleted count and kept count.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=days_to_keep)

    with conn.cursor() as cur:
        # Count before
        cur.execute("SELECT COUNT(*) AS cnt FROM prices WHERE scraped_at < %s", (cutoff,))
        old_count = cur.fetchone()["cnt"]

        if old_count == 0:
            return {"deleted": 0, "old_records": 0}

        # Delete old records EXCEPT the first-of-month keeper per product
        cur.execute(
            """
            DELETE FROM prices
            WHERE scraped_at < %s
              AND id NOT IN (
                  SELECT DISTINCT ON (retailer, product_id, DATE_TRUNC('month', scraped_at))
                      id
                  FROM prices
                  WHERE scraped_at < %s
                  ORDER BY retailer, product_id,
                           DATE_TRUNC('month', scraped_at),
                           scraped_at ASC
              )
            """,
            (cutoff, cutoff),
        )
        deleted = cur.rowcount
    conn.commit()

    logger.info(
        f"cleanup_old_prices: deleted {deleted} of {old_count} records older than {days_to_keep} days"
    )
    return {"deleted": deleted, "old_records": old_count, "kept_monthly_samples": old_count - deleted}
