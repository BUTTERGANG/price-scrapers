"""Shared pytest fixtures."""
import os
import uuid
from datetime import datetime, timezone

import pytest


@pytest.fixture
def db_conn():
    """PostgreSQL connection with the schema applied in a disposable,
    randomly-named schema. Isolated per test; dropped on teardown."""
    dsn = os.environ.get("NEONDB1") or os.environ.get("DATABASE_URL")
    if not dsn:
        pytest.skip("No PostgreSQL connection string (NEONDB1/DATABASE_URL)")

    import psycopg2
    import psycopg2.extras
    from utils.db import _ensure_schema

    schema = f"test_{uuid.uuid4().hex[:12]}"
    conn = psycopg2.connect(dsn, cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        with conn.cursor() as cur:
            cur.execute(f'CREATE SCHEMA "{schema}"')
            cur.execute(f'SET search_path TO "{schema}"')
        conn.commit()
        _ensure_schema(conn)
        yield conn
    finally:
        try:
            conn.rollback()
            with conn.cursor() as cur:
                cur.execute(f'DROP SCHEMA "{schema}" CASCADE')
                # Reset before releasing: Neon's transaction-mode pooler reuses
                # server sessions, so a lingering search_path would leak to
                # other clients.
                cur.execute('SET search_path TO public')
            conn.commit()
        finally:
            conn.close()


@pytest.fixture
def sample_price():
    """A single normalized price record for use in DB and comparison tests."""
    return {
        "retailer": "kroger",
        "store_id": "01400441",
        "product_id": "0001111041700",
        "name": "Kroger 2% Reduced Fat Milk",
        "price": 3.99,
        "sale_price": None,
        "unit": "1 gal",
        "unit_price": 3.99,
        "url": "https://www.kroger.com/p/kroger-2-reduced-fat-milk/0001111041700",
        # Recent timestamp so freshness-windowed queries (e.g. find_active_deals)
        # see the record as current.
        "scraped_at": datetime.now(timezone.utc).isoformat(),
        "brand": "Kroger",
        "category": "Dairy",
    }


@pytest.fixture
def sample_sale_price(sample_price):
    """A price record with an active sale."""
    return {**sample_price, "price": 4.99, "sale_price": 3.49, "product_id": "0001111041701"}
