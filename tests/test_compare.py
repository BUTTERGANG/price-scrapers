"""Tests for utils/compare.py — in-memory price comparison helpers."""
from utils.compare import compare_by_name, find_deals, best_price_per_retailer


RECORDS = [
    {"retailer": "kroger",     "name": "Kroger Whole Milk 1 gal",   "price": 3.99, "sale_price": None},
    {"retailer": "kroger",     "name": "Kroger 2% Milk 1 gal",      "price": 3.49, "sale_price": None},
    {"retailer": "walmart",    "name": "Great Value Whole Milk",     "price": 3.28, "sale_price": None},
    {"retailer": "fresh_thyme","name": "Fresh Thyme Organic Milk",   "price": 4.99, "sale_price": 3.99},
    {"retailer": "meijer",     "name": "Meijer Eggs Large 12ct",     "price": 2.99, "sale_price": 1.99},
]


class TestCompareByName:
    def test_filters_by_substring(self):
        results = compare_by_name(RECORDS, "milk")
        names = [r["name"] for r in results]
        assert all("milk" in n.lower() for n in names)
        assert "Meijer Eggs Large 12ct" not in names

    def test_case_insensitive(self):
        results = compare_by_name(RECORDS, "MILK")
        assert len(results) == 4

    def test_sorted_by_price_ascending(self):
        results = compare_by_name(RECORDS, "milk")
        prices = [r["price"] for r in results]
        assert prices == sorted(prices)

    def test_no_match_returns_empty(self):
        assert compare_by_name(RECORDS, "lobster") == []


class TestFindDeals:
    def test_returns_only_sale_items(self):
        deals = find_deals(RECORDS)
        assert all(d["sale_price"] is not None for d in deals)
        assert all(d["sale_price"] < d["price"] for d in deals)

    def test_sorted_by_savings_descending(self):
        deals = find_deals(RECORDS)
        savings = [d["savings"] for d in deals]
        assert savings == sorted(savings, reverse=True)

    def test_savings_field_added(self):
        deals = find_deals(RECORDS)
        for d in deals:
            assert "savings" in d
            assert d["savings"] == round(d["price"] - d["sale_price"], 2)

    def test_no_deals_returns_empty(self):
        no_sale = [r for r in RECORDS if r["sale_price"] is None]
        assert find_deals(no_sale) == []


class TestBestPricePerRetailer:
    def test_returns_one_per_retailer(self):
        best = best_price_per_retailer(RECORDS, "milk")
        retailers = list(best.keys())
        assert len(retailers) == len(set(retailers))

    def test_returns_cheapest_for_each(self):
        best = best_price_per_retailer(RECORDS, "milk")
        # Kroger has two milk entries; cheapest is $3.49
        assert best["kroger"]["price"] == 3.49

    def test_no_match_returns_empty_dict(self):
        assert best_price_per_retailer(RECORDS, "lobster") == {}
