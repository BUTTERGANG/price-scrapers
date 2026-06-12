"""Tests for utils/db.py — database operations."""
import pytest
from utils.db import (
    insert_price,
    insert_many,
    price_history,
    lowest_price_ever,
    find_active_deals,
    cheapest_per_retailer,
    start_run,
    finish_run,
    log_failed_query,
    get_failed_queries,
    last_successful_run,
)


def _fetch_one(conn, sql, params=()):
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchone()


class TestInsert:
    def test_insert_price_returns_row_id(self, db_conn, sample_price):
        row_id = insert_price(db_conn, sample_price)
        assert isinstance(row_id, int)
        assert row_id > 0

    def test_insert_many_returns_count(self, db_conn, sample_price, sample_sale_price):
        count = insert_many(db_conn, [sample_price, sample_sale_price])
        assert count == 2

    def test_insert_extra_fields_serialized(self, db_conn, sample_price):
        # brand is a real column; unknown fields like snap_eligible go to extra_json
        record = {**sample_price, "brand": "Kroger", "snap_eligible": True}
        insert_price(db_conn, record)
        row = _fetch_one(db_conn, "SELECT brand, extra_json FROM prices LIMIT 1")
        import json
        assert row["brand"] == "Kroger"
        extra = json.loads(row["extra_json"])
        assert extra.get("snap_eligible") is True
        assert extra.get("category") == "Dairy"


class TestPriceHistory:
    def test_returns_records_newest_first(self, db_conn, sample_price):
        r1 = {**sample_price, "scraped_at": "2026-03-18T10:00:00", "price": 3.99}
        r2 = {**sample_price, "scraped_at": "2026-03-19T10:00:00", "price": 4.29}
        insert_many(db_conn, [r1, r2])
        history = price_history(db_conn, "kroger", sample_price["product_id"])
        assert history[0]["price"] == 4.29
        assert history[1]["price"] == 3.99

    def test_lowest_price_ever(self, db_conn, sample_price):
        r1 = {**sample_price, "scraped_at": "2026-03-18T10:00:00", "price": 3.49}
        r2 = {**sample_price, "scraped_at": "2026-03-19T10:00:00", "price": 3.99}
        insert_many(db_conn, [r1, r2])
        low = lowest_price_ever(db_conn, "kroger", sample_price["product_id"])
        assert low == 3.49


class TestDeals:
    def test_find_active_deals_returns_sale_items(self, db_conn, sample_sale_price):
        insert_price(db_conn, sample_sale_price)
        deals = find_active_deals(db_conn, min_savings_pct=0)
        assert len(deals) == 1
        assert deals[0]["savings_pct"] > 0

    def test_find_active_deals_filters_by_min_savings(self, db_conn, sample_sale_price):
        insert_price(db_conn, sample_sale_price)
        # sale saves ~30%, so 50% threshold should return nothing
        deals = find_active_deals(db_conn, min_savings_pct=50)
        assert deals == []

    def test_no_sale_not_in_deals(self, db_conn, sample_price):
        insert_price(db_conn, sample_price)
        deals = find_active_deals(db_conn, min_savings_pct=0)
        assert deals == []


class TestCheapestPerRetailer:
    def test_returns_cheapest_match(self, db_conn, sample_price):
        expensive = {**sample_price, "price": 5.99, "product_id": "0001111041702"}
        insert_many(db_conn, [sample_price, expensive])
        results = cheapest_per_retailer(db_conn, "milk")
        assert len(results) == 1
        assert results[0]["price"] == 3.99

    def test_one_result_per_retailer(self, db_conn, sample_price):
        walmart = {**sample_price, "retailer": "walmart", "store_id": "2787", "price": 3.49}
        insert_many(db_conn, [sample_price, walmart])
        results = cheapest_per_retailer(db_conn, "milk")
        retailers = {r["retailer"] for r in results}
        assert retailers == {"kroger", "walmart"}


class TestRunLogging:
    def test_start_and_finish_run(self, db_conn):
        run_id = start_run(db_conn, "kroger", "01400441", queries_total=15)
        assert run_id > 0

        finish_run(db_conn, run_id, queries_ok=14, queries_failed=1, records_saved=210)
        row = _fetch_one(db_conn, "SELECT * FROM runs WHERE id=%s", (run_id,))
        assert row["status"] == "partial"
        assert row["queries_ok"] == 14
        assert row["records_saved"] == 210
        assert row["finished_at"] is not None

    def test_finish_run_success(self, db_conn):
        run_id = start_run(db_conn, "kroger", "01400441", queries_total=15)
        finish_run(db_conn, run_id, queries_ok=15, queries_failed=0, records_saved=300)
        row = _fetch_one(db_conn, "SELECT status FROM runs WHERE id=%s", (run_id,))
        assert row["status"] == "success"

    def test_finish_run_failed(self, db_conn):
        run_id = start_run(db_conn, "walmart", "2787", queries_total=15)
        finish_run(db_conn, run_id, queries_ok=0, queries_failed=0, records_saved=0, error="403 Forbidden")
        row = _fetch_one(db_conn, "SELECT status, error FROM runs WHERE id=%s", (run_id,))
        assert row["status"] == "failed"
        assert "403" in row["error"]

    def test_log_and_retrieve_failed_queries(self, db_conn):
        run_id = start_run(db_conn, "meijer", "290", queries_total=5)
        log_failed_query(db_conn, run_id, "meijer", "chicken breast", ValueError("parse error"))
        log_failed_query(db_conn, run_id, "meijer", "eggs", ConnectionError("timeout"))

        failed = get_failed_queries(db_conn, "meijer", run_id=run_id)
        assert set(failed) == {"chicken breast", "eggs"}

    def test_last_successful_run(self, db_conn):
        run_id = start_run(db_conn, "fresh_thyme", "104", queries_total=10)
        finish_run(db_conn, run_id, queries_ok=10, queries_failed=0, records_saved=150)
        result = last_successful_run(db_conn, "fresh_thyme")
        assert result is not None
        assert result["retailer"] == "fresh_thyme"
        assert result["records_saved"] == 150
