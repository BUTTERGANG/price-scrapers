"""Shared pytest fixtures."""
import sqlite3
import pytest


@pytest.fixture
def db_conn():
    """In-memory SQLite connection with schema applied. Isolated per test."""
    from utils.db import _ensure_schema
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    _ensure_schema(conn)
    yield conn
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
        "scraped_at": "2026-03-19T10:00:00",
        "brand": "Kroger",
        "category": "Dairy",
    }


@pytest.fixture
def sample_sale_price(sample_price):
    """A price record with an active sale."""
    return {**sample_price, "price": 4.99, "sale_price": 3.49, "product_id": "0001111041701"}
