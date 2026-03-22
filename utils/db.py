"""SQLite price history database.

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
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

DEFAULT_DB = Path("data/prices.db")


def get_conn(db_path: Path = DEFAULT_DB) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, check_same_thread=False, timeout=30)
    conn.row_factory = sqlite3.Row
    # WAL mode: allows concurrent reads while a write is in progress.
    # Combined with application-level write serialization in runner.py,
    # this makes the DB safe for multi-threaded parallel scraper runs.
    conn.execute("PRAGMA journal_mode=WAL")
    _ensure_schema(conn)
    return conn


def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS prices (
            id                    INTEGER PRIMARY KEY AUTOINCREMENT,
            retailer              TEXT    NOT NULL,
            store_id              TEXT    NOT NULL,
            product_id            TEXT    NOT NULL,
            upc                   TEXT,
            name                  TEXT    NOT NULL,
            brand                 TEXT,
            department            TEXT,
            price                 REAL,
            sale_price            REAL,
            unit                  TEXT,
            unit_price            REAL,
            unit_price_normalized REAL,
            unit_canonical        TEXT,
            url                   TEXT,
            extra_json            TEXT,
            scraped_at            TEXT    NOT NULL
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

        -- One row per scraper execution.
        -- status: 'running' | 'success' | 'partial' | 'failed'
        CREATE TABLE IF NOT EXISTS runs (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            retailer        TEXT    NOT NULL,
            store_id        TEXT    NOT NULL,
            status          TEXT    NOT NULL DEFAULT 'running',
            queries_total   INTEGER NOT NULL DEFAULT 0,
            queries_ok      INTEGER NOT NULL DEFAULT 0,
            queries_failed  INTEGER NOT NULL DEFAULT 0,
            records_saved   INTEGER NOT NULL DEFAULT 0,
            error           TEXT,               -- top-level error message if status='failed'
            started_at      TEXT    NOT NULL,
            finished_at     TEXT
        );

        -- Individual query failures within a run, for targeted reruns.
        CREATE TABLE IF NOT EXISTS failed_queries (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id      INTEGER NOT NULL REFERENCES runs(id),
            retailer    TEXT    NOT NULL,
            query       TEXT    NOT NULL,
            error_type  TEXT,   -- exception class name
            error_msg   TEXT,
            failed_at   TEXT    NOT NULL
        );
        """
    )
    conn.commit()
    _migrate(conn)


def _migrate(conn: sqlite3.Connection) -> None:
    """Add columns introduced after the initial schema — safe to run repeatedly."""
    existing = {
        row[1]
        for row in conn.execute("PRAGMA table_info(prices)").fetchall()
    }
    new_cols = [
        ("unit_price_normalized", "REAL"),
        ("unit_canonical",        "TEXT"),
        ("upc",                   "TEXT"),
        ("brand",                 "TEXT"),
        ("department",            "TEXT"),
    ]
    for col, col_type in new_cols:
        if col not in existing:
            conn.execute(f"ALTER TABLE prices ADD COLUMN {col} {col_type}")
    conn.commit()


def insert_price(conn: sqlite3.Connection, record: dict) -> int:
    """Insert one normalized price record. Returns the new row ID."""
    _KNOWN_COLS = {
        "retailer", "store_id", "product_id", "upc", "name",
        "brand", "department",
        "price", "sale_price", "unit", "unit_price",
        "unit_price_normalized", "unit_canonical",
        "url", "scraped_at",
    }
    extra = {k: v for k, v in record.items() if k not in _KNOWN_COLS}
    conn.execute(
        """
        INSERT INTO prices
            (retailer, store_id, product_id, upc, name, brand, department,
             price, sale_price, unit, unit_price, unit_price_normalized, unit_canonical,
             url, extra_json, scraped_at)
        VALUES
            (:retailer, :store_id, :product_id, :upc, :name, :brand, :department,
             :price, :sale_price, :unit, :unit_price, :unit_price_normalized, :unit_canonical,
             :url, :extra_json, :scraped_at)
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
            "scraped_at":           record.get("scraped_at", datetime.now().isoformat()),
        },
    )
    conn.commit()
    return conn.execute("SELECT last_insert_rowid()").fetchone()[0]


def insert_many(conn: sqlite3.Connection, records: list[dict]) -> int:
    """Bulk insert. Returns number of rows inserted."""
    for record in records:
        insert_price(conn, record)
    return len(records)


# ---------------------------------------------------------------------------
# Run logging
# ---------------------------------------------------------------------------

def start_run(
    conn: sqlite3.Connection, retailer: str, store_id: str, queries_total: int
) -> int:
    """Insert a 'running' run record. Returns the run ID."""
    conn.execute(
        """
        INSERT INTO runs (retailer, store_id, status, queries_total, started_at)
        VALUES (?, ?, 'running', ?, ?)
        """,
        (retailer, store_id, queries_total, datetime.now().isoformat()),
    )
    conn.commit()
    return conn.execute("SELECT last_insert_rowid()").fetchone()[0]


def finish_run(
    conn: sqlite3.Connection,
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

    conn.execute(
        """
        UPDATE runs
        SET status         = ?,
            queries_ok     = ?,
            queries_failed = ?,
            records_saved  = ?,
            error          = ?,
            finished_at    = ?
        WHERE id = ?
        """,
        (status, queries_ok, queries_failed, records_saved,
         error, datetime.now().isoformat(), run_id),
    )
    conn.commit()


def log_failed_query(
    conn: sqlite3.Connection,
    run_id: int,
    retailer: str,
    query: str,
    exc: Exception,
) -> None:
    """Record a single failed query for later rerun."""
    conn.execute(
        """
        INSERT INTO failed_queries
            (run_id, retailer, query, error_type, error_msg, failed_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            run_id,
            retailer,
            query,
            type(exc).__name__,
            str(exc),
            datetime.now().isoformat(),
        ),
    )
    conn.commit()


def get_failed_queries(
    conn: sqlite3.Connection, retailer: str, run_id: Optional[int] = None
) -> list[str]:
    """
    Return queries that failed for a retailer.
    If run_id is given, return only failures from that run.
    Otherwise return all distinct failed queries not yet succeeded.
    """
    if run_id is not None:
        rows = conn.execute(
            "SELECT query FROM failed_queries WHERE retailer=? AND run_id=?",
            (retailer, run_id),
        ).fetchall()
    else:
        # All failed queries for this retailer that have never appeared
        # in a successful run (i.e. no price record exists for them).
        rows = conn.execute(
            """
            SELECT DISTINCT query FROM failed_queries
            WHERE retailer = ?
            ORDER BY failed_at DESC
            """,
            (retailer,),
        ).fetchall()
    return [r["query"] for r in rows]


def last_successful_run(
    conn: sqlite3.Connection, retailer: str
) -> Optional[dict]:
    """Return the most recent run with status 'success' or 'partial' for a retailer."""
    row = conn.execute(
        """
        SELECT * FROM runs
        WHERE retailer = ? AND status IN ('success', 'partial')
        ORDER BY finished_at DESC
        LIMIT 1
        """,
        (retailer,),
    ).fetchone()
    return dict(row) if row else None


def price_history(
    conn: sqlite3.Connection,
    retailer: str,
    product_id: str,
    limit: int = 30,
) -> list[dict]:
    """Return the most recent price records for a product, newest first."""
    rows = conn.execute(
        """
        SELECT * FROM prices
        WHERE retailer = ? AND product_id = ?
        ORDER BY scraped_at DESC
        LIMIT ?
        """,
        (retailer, product_id, limit),
    ).fetchall()
    return [dict(r) for r in rows]


def lowest_price_ever(
    conn: sqlite3.Connection, retailer: str, product_id: str
) -> Optional[float]:
    """Return the lowest regular price ever recorded for a product."""
    row = conn.execute(
        "SELECT MIN(price) FROM prices WHERE retailer=? AND product_id=? AND price > 0",
        (retailer, product_id),
    ).fetchone()
    return row[0] if row else None


def find_active_deals(conn: sqlite3.Connection, min_savings_pct: float = 10.0) -> list[dict]:
    """
    Return the most recent price record for each product where
    sale_price < price and the discount is at least min_savings_pct%.
    Only considers records scraped in the last 24 hours.
    """
    rows = conn.execute(
        """
        SELECT p.*,
               ROUND((p.price - p.sale_price) / p.price * 100, 1) AS savings_pct
        FROM prices p
        INNER JOIN (
            SELECT retailer, product_id, MAX(scraped_at) AS latest
            FROM prices
            GROUP BY retailer, product_id
        ) latest_only
            ON p.retailer = latest_only.retailer
           AND p.product_id = latest_only.product_id
           AND p.scraped_at = latest_only.latest
        WHERE p.sale_price IS NOT NULL
          AND p.sale_price < p.price
          AND p.price > 0
          AND ROUND((p.price - p.sale_price) / p.price * 100, 1) >= ?
          AND p.scraped_at >= datetime('now', '-1 day')
        ORDER BY savings_pct DESC
        """,
        (min_savings_pct,),
    ).fetchall()
    return [dict(r) for r in rows]


def cheapest_per_retailer(
    conn: sqlite3.Connection, name_contains: str
) -> list[dict]:
    """
    For a product matching a name substring, return the cheapest current price
    per retailer (from records scraped in the last 24 hours).
    """
    rows = conn.execute(
        """
        SELECT p.*
        FROM prices p
        INNER JOIN (
            SELECT retailer, product_id, MAX(scraped_at) AS latest
            FROM prices
            WHERE LOWER(name) LIKE ?
            GROUP BY retailer, product_id
        ) latest_only
            ON p.retailer = latest_only.retailer
           AND p.product_id = latest_only.product_id
           AND p.scraped_at = latest_only.latest
        WHERE LOWER(p.name) LIKE ?
          AND p.scraped_at >= datetime('now', '-1 day')
        ORDER BY p.retailer, COALESCE(p.sale_price, p.price) ASC
        """,
        (f"%{name_contains.lower()}%", f"%{name_contains.lower()}%"),
    ).fetchall()

    # Return only the cheapest per retailer
    seen = set()
    results = []
    for row in rows:
        r = dict(row)
        if r["retailer"] not in seen:
            seen.add(r["retailer"])
            results.append(r)
    return results


def find_by_upc(conn: sqlite3.Connection, upc: str) -> list[dict]:
    """
    Return the most recent price record per retailer for a given UPC barcode.

    Enables exact cross-retailer price matching when multiple scrapers have
    populated the upc column (Kroger, Fresh Thyme search, Needler's, Giant Eagle).
    Results are ordered cheapest effective price first.
    """
    rows = conn.execute(
        """
        SELECT p.*
        FROM prices p
        INNER JOIN (
            SELECT retailer, product_id, MAX(scraped_at) AS latest
            FROM prices
            WHERE upc = ?
            GROUP BY retailer, product_id
        ) latest_only
            ON p.retailer = latest_only.retailer
           AND p.product_id = latest_only.product_id
           AND p.scraped_at = latest_only.latest
        WHERE p.upc = ?
        ORDER BY COALESCE(p.sale_price, p.price) ASC
        """,
        (upc, upc),
    ).fetchall()
    return [dict(r) for r in rows]
