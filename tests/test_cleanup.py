"""Tests for cleanup_old_prices — destructive code deserves coverage."""
from datetime import datetime, timedelta, timezone

from utils.db import cleanup_old_prices, insert_many


def _record(product_id, scraped_at, price=2.99):
    return {
        "retailer": "kroger",
        "store_id": "s1",
        "product_id": product_id,
        "name": f"Item {product_id}",
        "price": price,
        "scraped_at": scraped_at,
    }


def _count_prices(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) AS cnt FROM prices")
        return cur.fetchone()["cnt"]


class TestCleanup:
    def test_recent_records_untouched(self, db_conn):
        now = datetime.now(timezone.utc)
        insert_many(db_conn, [
            _record("p1", now - timedelta(days=1)),
            _record("p1", now - timedelta(days=30)),
        ])
        result = cleanup_old_prices(db_conn, days_to_keep=90)
        assert result["deleted"] == 0
        assert _count_prices(db_conn) == 2

    def test_old_records_pruned_keeping_monthly_sample(self, db_conn):
        now = datetime.now(timezone.utc)
        # Three old records in the same calendar month for the same product:
        # the earliest is kept as the monthly sample, the other two deleted.
        base = (now - timedelta(days=200)).replace(day=10)
        insert_many(db_conn, [
            _record("p1", base),
            _record("p1", base + timedelta(days=2)),
            _record("p1", base + timedelta(days=4)),
            _record("p1", now - timedelta(days=1)),  # recent, untouched
        ])
        result = cleanup_old_prices(db_conn, days_to_keep=90)
        assert result["deleted"] == 2
        assert result["kept_monthly_samples"] == 1
        assert _count_prices(db_conn) == 2

    def test_separate_months_each_keep_a_sample(self, db_conn):
        now = datetime.now(timezone.utc)
        insert_many(db_conn, [
            _record("p1", (now - timedelta(days=200)).replace(day=5)),
            _record("p1", (now - timedelta(days=170)).replace(day=5)),
        ])
        result = cleanup_old_prices(db_conn, days_to_keep=90)
        assert result["deleted"] == 0
        assert _count_prices(db_conn) == 2
