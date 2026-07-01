"""Tests for utils/validate.py — the data quality gate before DB insert."""
from utils.validate import check_count_drop, validate_results


def _record(**overrides):
    base = {
        "retailer": "kroger",
        "product_id": "p1",
        "name": "Whole Milk 1 gal",
        "price": 3.99,
        "sale_price": None,
    }
    return {**base, **overrides}


class TestHardDrops:
    def test_empty_name_dropped(self):
        valid, issues = validate_results([_record(name="")], "kroger")
        assert valid == []
        assert any("DROP" in i and "empty name" in i for i in issues)

    def test_html_garbage_dropped(self):
        valid, issues = validate_results(
            [_record(name="<div class='price'>Milk</div>")], "kroger"
        )
        assert valid == []
        assert any("HTML" in i for i in issues)

    def test_clean_record_kept(self):
        valid, issues = validate_results([_record()], "kroger")
        assert len(valid) == 1
        assert issues == []


class TestDedup:
    def test_duplicate_product_id_keeps_first(self):
        records = [
            _record(name="Milk A"),
            _record(name="Milk B"),  # same product_id
        ]
        valid, issues = validate_results(records, "kroger")
        assert len(valid) == 1
        assert valid[0]["name"] == "Milk A"
        assert any("DEDUP" in i for i in issues)

    def test_distinct_product_ids_all_kept(self):
        records = [_record(), _record(product_id="p2", name="Eggs")]
        valid, _ = validate_results(records, "kroger")
        assert len(valid) == 2


class TestZeroPriceDrops:
    def test_zero_price_without_deal_context_is_dropped(self):
        # No usable price and no deal text — nothing a user can act on
        # (e.g. Target $0 catalog rows). These are dropped at the source.
        valid, issues = validate_results([_record(price=0)], "kroger")
        assert valid == []
        assert any("DROP" in i and "no usable price" in i for i in issues)

    def test_zero_regular_but_sale_price_set_is_kept(self):
        # A real sale price means there's a usable number even if price=0.
        valid, _ = validate_results([_record(price=0, sale_price=1.99)], "kroger")
        assert len(valid) == 1


class TestSoftWarnings:
    def test_zero_price_with_deal_text_is_fine(self):
        valid, issues = validate_results(
            [_record(price=0, deal_text="BOGO Free")], "kroger"
        )
        assert len(valid) == 1
        assert issues == []

    def test_unusually_high_price_warns(self):
        valid, issues = validate_results([_record(price=999.0)], "kroger")
        assert len(valid) == 1
        assert any("unusually high" in i for i in issues)

    def test_sale_price_not_below_regular_warns(self):
        valid, issues = validate_results(
            [_record(price=3.99, sale_price=4.99)], "kroger"
        )
        assert len(valid) == 1
        assert any("sale_price" in i for i in issues)


class TestCountDrop:
    def test_no_history_returns_none(self):
        assert check_count_drop("kroger", 10, None) is None

    def test_big_drop_warns(self):
        warning = check_count_drop("kroger", 10, 100)
        assert warning is not None
        assert "kroger" in warning

    def test_small_drop_ok(self):
        assert check_count_drop("kroger", 80, 100) is None
