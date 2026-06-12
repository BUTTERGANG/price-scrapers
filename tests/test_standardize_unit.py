"""Tests for BaseScraper._standardize_unit_field()."""
import unittest

from scrapers.base import BaseScraper


class TestStandardizeUnitField(unittest.TestCase):
    """Test that retailer-specific unit strings are normalized correctly."""

    def test_each(self):
        self.assertEqual(BaseScraper._standardize_unit_field("Each"), "ea")
        self.assertEqual(BaseScraper._standardize_unit_field("each"), "ea")
        self.assertEqual(BaseScraper._standardize_unit_field("EACH"), "ea")

    def test_ea(self):
        self.assertEqual(BaseScraper._standardize_unit_field("EA"), "ea")
        self.assertEqual(BaseScraper._standardize_unit_field("ea"), "ea")

    def test_per_each(self):
        self.assertEqual(BaseScraper._standardize_unit_field("Per Each"), "ea")

    def test_per_pkg(self):
        self.assertEqual(BaseScraper._standardize_unit_field("Per 1-Lb. Pkg."), "1 lb")
        self.assertEqual(BaseScraper._standardize_unit_field("Per 16-oz. Pkg."), "16 oz")
        self.assertEqual(BaseScraper._standardize_unit_field("Per 12-ct. Pkg."), "12 ct")

    def test_price_per_unit(self):
        self.assertEqual(BaseScraper._standardize_unit_field("$3.49/lb"), "lb")
        self.assertEqual(BaseScraper._standardize_unit_field("3.49/lb"), "lb")
        self.assertEqual(BaseScraper._standardize_unit_field("$0.25/oz"), "oz")
        self.assertEqual(BaseScraper._standardize_unit_field("$1.99/ea"), "ea")

    def test_cents_per_unit(self):
        self.assertEqual(BaseScraper._standardize_unit_field("5.4 ¢/fl oz"), "fl oz")
        self.assertEqual(BaseScraper._standardize_unit_field("5.4 cents/fl oz"), "fl oz")

    def test_bare_abbreviations(self):
        self.assertEqual(BaseScraper._standardize_unit_field("LB"), "lb")
        self.assertEqual(BaseScraper._standardize_unit_field("OZ"), "oz")
        self.assertEqual(BaseScraper._standardize_unit_field("CT"), "ct")
        self.assertEqual(BaseScraper._standardize_unit_field("GAL"), "gal")
        self.assertEqual(BaseScraper._standardize_unit_field("lbs"), "lb")
        self.assertEqual(BaseScraper._standardize_unit_field("pk"), "ct")
        self.assertEqual(BaseScraper._standardize_unit_field("pack"), "ct")

    def test_size_string_passthrough(self):
        self.assertEqual(BaseScraper._standardize_unit_field("1 gal"), "1 gal")
        self.assertEqual(BaseScraper._standardize_unit_field("16 oz"), "16 oz")
        self.assertEqual(BaseScraper._standardize_unit_field("2 lb"), "2 lb")
        self.assertEqual(BaseScraper._standardize_unit_field("12 ct"), "12 ct")

    def test_none_input(self):
        self.assertIsNone(BaseScraper._standardize_unit_field(None))

    def test_empty_string(self):
        self.assertIsNone(BaseScraper._standardize_unit_field(""))

    def test_whitespace_only(self):
        self.assertIsNone(BaseScraper._standardize_unit_field("   "))

    def test_unknown_unit(self):
        """Unknown units that don't match any pattern are returned as-is."""
        result = BaseScraper._standardize_unit_field("foobar")
        self.assertEqual(result, "foobar")

    def test_extra_whitespace(self):
        self.assertEqual(BaseScraper._standardize_unit_field("  EA  "), "ea")
        self.assertEqual(BaseScraper._standardize_unit_field("  1 gal  "), "1 gal")


if __name__ == "__main__":
    unittest.main()
