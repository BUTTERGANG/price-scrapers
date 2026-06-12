"""Tests for unit_price helper functions: pre_normalize_name, parse_size_multi."""
import unittest

from utils.unit_price import pre_normalize_name, parse_size_multi, parse_size


class TestPreNormalizeName(unittest.TestCase):
    """Test that product name text is normalized before size parsing."""

    def test_pack_expansion(self):
        self.assertEqual(pre_normalize_name("Coca-Cola 12-Pack"), "Coca-Cola 12 ct")
        self.assertEqual(pre_normalize_name("6-Pack Bottled Water"), "6 ct Bottled Water")
        self.assertEqual(pre_normalize_name("12 pack soda"), "12 ct soda")

    def test_pk_expansion(self):
        self.assertEqual(pre_normalize_name("12pk Water"), "12 ct Water")
        self.assertEqual(pre_normalize_name("6 pk cans"), "6 ct cans")

    def test_no_space_unit(self):
        self.assertEqual(pre_normalize_name("Cheerios 12oz"), "Cheerios 12 oz")
        self.assertEqual(pre_normalize_name("Pasta 16oz"), "Pasta 16 oz")
        self.assertEqual(pre_normalize_name("Rice 2lb"), "Rice 2 lb")
        self.assertEqual(pre_normalize_name("Flour 5lb"), "Flour 5 lb")

    def test_fraction_conversion(self):
        self.assertEqual(pre_normalize_name("Milk 1/2 gal"), "Milk 0.5 gal")
        self.assertEqual(pre_normalize_name("Butter 3/4 lb"), "Butter 0.75 lb")
        self.assertEqual(pre_normalize_name("Oil 1/4 gal"), "Oil 0.25 gal")

    def test_mixed_fraction(self):
        self.assertEqual(pre_normalize_name("Ice Cream 1 1/2 gal"), "Ice Cream 1.5 gal")
        self.assertEqual(pre_normalize_name("Juice 2 1/4 qt"), "Juice 2.25 qt")

    def test_none_input(self):
        self.assertIsNone(pre_normalize_name(None))

    def test_empty_string(self):
        self.assertEqual(pre_normalize_name(""), "")

    def test_no_changes(self):
        self.assertEqual(pre_normalize_name("Whole Milk 1 gal"), "Whole Milk 1 gal")

    def test_decimal_quantity(self):
        # The no-space regex inserts a space but preserves the original case of the unit
        self.assertEqual(pre_normalize_name("Water 1.5L"), "Water 1.5 L")

    def test_fl_oz_no_space(self):
        self.assertEqual(pre_normalize_name("Coke 12fl oz"), "Coke 12 fl oz")


class TestParseSizeMulti(unittest.TestCase):
    """Test compound size expressions like '6 x 16 oz'."""

    def test_basic_multi(self):
        result = parse_size_multi("6 x 16 oz")
        self.assertEqual(result, (96.0, "oz"))

    def test_dash_separator(self):
        result = parse_size_multi("12 - 12 fl oz")
        self.assertEqual(result, (144.0, "fl oz"))

    def test_pack_notation(self):
        # "4 pack 16.9 fl oz" — parse_size_multi only handles "x" and "-" separators
        # "pack" is not a recognized multi-size pattern, so it returns None
        result = parse_size_multi("4 pack 16.9 fl oz")
        self.assertIsNone(result)

    def test_no_match(self):
        self.assertIsNone(parse_size_multi("16 oz"))
        self.assertIsNone(parse_size_multi("single bottle"))
        self.assertIsNone(parse_size_multi(""))

    def test_none_input(self):
        self.assertIsNone(parse_size_multi(None))


class TestParseSizeWithPreNormalization(unittest.TestCase):
    """Test that parse_size benefits from pre_normalize_name."""

    def test_pack_in_name(self):
        result = parse_size("Coca-Cola 12-Pack")
        self.assertIsNotNone(result)
        self.assertEqual(result[0], 12.0)
        self.assertEqual(result[1], "ct")

    def test_no_space_oz(self):
        result = parse_size("Cheerios 16oz")
        self.assertIsNotNone(result)
        self.assertEqual(result[0], 16.0)
        self.assertEqual(result[1], "oz")

    def test_half_gallon_fraction(self):
        result = parse_size("Milk 1/2 gal")
        self.assertIsNotNone(result)
        self.assertAlmostEqual(result[0], 0.5)
        self.assertEqual(result[1], "gal")

    def test_mixed_fraction(self):
        result = parse_size("Ice Cream 1 1/2 gal")
        self.assertIsNotNone(result)
        self.assertAlmostEqual(result[0], 1.5)
        self.assertEqual(result[1], "gal")


if __name__ == "__main__":
    unittest.main()
