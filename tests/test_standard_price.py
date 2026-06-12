"""Tests for standard unit price computation."""
import unittest

from utils.unit_price import normalize_unit_price, compute_standard_unit_price


class TestStandardPrice(unittest.TestCase):
    """Test that standard prices are computed correctly from normalized records."""

    def _make_record(self, name, price, unit=None, unit_price=None, department=""):
        """Build a record and run normalize_unit_price to set canonical fields."""
        record = {
            "name": name,
            "price": price,
            "unit": unit,
            "unit_price": unit_price,
            "department": department,
        }
        normalize_unit_price(record)
        return record

    def _make_record_raw(self, name, price, unit_price_normalized, unit_canonical, department=""):
        """Build a record with pre-set canonical fields (bypasses normalize_unit_price)."""
        return {
            "name": name,
            "price": price,
            "unit_price_normalized": unit_price_normalized,
            "unit_canonical": unit_canonical,
            "department": department,
        }

    # --- Integration tests: normalize → standard ---

    def test_milk_per_gallon(self):
        """Milk priced per gallon should stay per gallon."""
        record = self._make_record("Whole Milk 1 gal", 3.99, unit="1 gal", unit_price=3.99)
        result = compute_standard_unit_price(record)
        self.assertIsNotNone(result)
        self.assertEqual(result["standard_unit"], "per_gal")
        self.assertAlmostEqual(result["standard_price"], 3.99, places=2)

    def test_milk_half_gallon(self):
        """Milk priced per half-gallon should convert to per-gallon."""
        record = self._make_record("Whole Milk 1/2 gal", 2.49, unit="0.5 gal", unit_price=2.49)
        result = compute_standard_unit_price(record)
        self.assertIsNotNone(result)
        self.assertEqual(result["standard_unit"], "per_gal")
        self.assertAlmostEqual(result["standard_price"], 4.98, places=2)

    def test_eggs_per_dozen(self):
        """Eggs priced per dozen should stay per dozen."""
        record = self._make_record("Large Eggs 12 ct", 3.49, unit="12 ct", unit_price=3.49)
        result = compute_standard_unit_price(record)
        self.assertIsNotNone(result)
        self.assertEqual(result["standard_unit"], "per_dozen")
        self.assertAlmostEqual(result["standard_price"], 3.49, places=2)

    def test_cereal_per_lb(self):
        """Cereal: $4.99 for 12 oz → $6.65 per lb."""
        record = self._make_record("Cheerios Cereal 12 oz", 4.99, unit="12 oz", unit_price=4.99)
        result = compute_standard_unit_price(record)
        self.assertIsNotNone(result)
        self.assertEqual(result["standard_unit"], "per_lb")
        # 4.99 / 12 oz = 0.4158/oz → * 16 = 6.65/lb
        self.assertAlmostEqual(result["standard_price"], 6.65, places=2)

    def test_yogurt_per_32oz(self):
        """Yogurt: $5.99 for 32 fl oz → $5.99 per 32 oz."""
        record = self._make_record("Greek Yogurt 32 fl oz", 5.99, unit="32 fl oz", unit_price=5.99)
        result = compute_standard_unit_price(record)
        self.assertIsNotNone(result)
        self.assertEqual(result["standard_unit"], "per_32oz")
        self.assertAlmostEqual(result["standard_price"], 5.99, places=2)

    def test_no_unit_info(self):
        """Record with no unit info should return None."""
        record = self._make_record("Mystery Item", 2.99)
        result = compute_standard_unit_price(record)
        self.assertIsNone(result)

    def test_bananas_per_lb(self):
        """Bananas priced per lb should stay per lb."""
        record = self._make_record("Organic Bananas", 0.79, unit="lb", unit_price=0.79)
        result = compute_standard_unit_price(record)
        self.assertIsNotNone(result)
        self.assertEqual(result["standard_unit"], "per_lb")
        self.assertAlmostEqual(result["standard_price"], 0.79, places=2)

    def test_olive_oil_per_gal(self):
        """Olive oil priced per gallon should stay per gallon."""
        record = self._make_record("Extra Virgin Olive Oil 1 gal", 12.99, unit="1 gal", unit_price=12.99)
        result = compute_standard_unit_price(record)
        self.assertIsNotNone(result)
        self.assertEqual(result["standard_unit"], "per_gal")
        self.assertAlmostEqual(result["standard_price"], 12.99, places=2)

    def test_ground_beef_per_lb(self):
        """Ground beef priced per lb should stay per lb."""
        record = self._make_record("Ground Beef 80/20 1 lb", 5.99, unit="1 lb", unit_price=5.99)
        result = compute_standard_unit_price(record)
        self.assertIsNotNone(result)
        self.assertEqual(result["standard_unit"], "per_lb")
        self.assertAlmostEqual(result["standard_price"], 5.99, places=2)

    def test_cheese_per_lb(self):
        """Cheese: $3.49 for 8 oz → $6.98 per lb."""
        record = self._make_record("Sharp Cheddar Cheese 8 oz", 3.49, unit="8 oz", unit_price=3.49)
        result = compute_standard_unit_price(record)
        self.assertIsNotNone(result)
        self.assertEqual(result["standard_unit"], "per_lb")
        # 3.49 / 8 oz = 0.43625/oz → * 16 = 6.98/lb
        self.assertAlmostEqual(result["standard_price"], 6.98, places=2)

    def test_display_name(self):
        """Standard price result should include display_name."""
        record = self._make_record("Whole Milk 1 gal", 3.99, unit="1 gal", unit_price=3.99)
        result = compute_standard_unit_price(record)
        self.assertIsNotNone(result)
        self.assertEqual(result["display_name"], "per gallon")

    # --- Unit tests: compute_standard_unit_price in isolation ---

    def test_incompatible_conversion_returns_none(self):
        """per_ct → per_gal should return None (no conversion path)."""
        record = self._make_record_raw(
            "Bottled Water", 1.00,
            unit_price_normalized=0.05, unit_canonical="per_ct",
        )
        result = compute_standard_unit_price(record)
        # Water category resolves to per_gal, but per_ct → per_gal has no conversion
        self.assertIsNone(result)

    def test_missing_normalized_price_returns_none(self):
        """Record with no unit_price_normalized should return None."""
        record = self._make_record_raw(
            "Whole Milk 1 gal", 3.99,
            unit_price_normalized=None, unit_canonical="per_fl_oz",
        )
        result = compute_standard_unit_price(record)
        self.assertIsNone(result)

    def test_missing_canonical_returns_none(self):
        """Record with no unit_canonical should return None."""
        record = self._make_record_raw(
            "Whole Milk 1 gal", 3.99,
            unit_price_normalized=0.031, unit_canonical=None,
        )
        result = compute_standard_unit_price(record)
        self.assertIsNone(result)

    def test_per_fl_oz_to_per_gal(self):
        """0.03125/fl_oz × 128 = $4.00/gal."""
        record = self._make_record_raw(
            "Store Brand Whole Milk 1 gal", 4.00,
            unit_price_normalized=0.03125, unit_canonical="per_fl_oz",
            department="Dairy",
        )
        result = compute_standard_unit_price(record)
        self.assertIsNotNone(result)
        self.assertEqual(result["standard_unit"], "per_gal")
        self.assertAlmostEqual(result["standard_price"], 4.00, places=2)

    def test_per_oz_to_per_lb(self):
        """0.25/oz × 16 = $4.00/lb."""
        record = self._make_store_brand_cereal_raw()
        result = compute_standard_unit_price(record)
        self.assertIsNotNone(result)
        self.assertEqual(result["standard_unit"], "per_lb")
        self.assertAlmostEqual(result["standard_price"], 4.00, places=2)

    def test_per_ct_to_per_dozen(self):
        """0.25/ct × 12 = $3.00/dozen."""
        record = self._make_record_raw(
            "Store Brand Eggs 12 ct", 3.00,
            unit_price_normalized=0.25, unit_canonical="per_ct",
            department="Dairy",
        )
        result = compute_standard_unit_price(record)
        self.assertIsNotNone(result)
        self.assertEqual(result["standard_unit"], "per_dozen")
        self.assertAlmostEqual(result["standard_price"], 3.00, places=2)

    def _make_store_brand_cereal_raw(self):
        return self._make_record_raw(
            "Store Brand Cereal 16 oz", 4.00,
            unit_price_normalized=0.25, unit_canonical="per_oz",
        )


if __name__ == "__main__":
    unittest.main()
