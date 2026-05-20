"""Tests for category-aware standard unit resolution."""
import unittest

from utils.category_resolver import resolve_standard_unit


class TestResolveStandardUnit(unittest.TestCase):
    """Test that product records are mapped to the correct standard unit."""

    def test_milk(self):
        result = resolve_standard_unit({"name": "Kroger Whole Milk 1 gal", "department": "Dairy"})
        self.assertIsNotNone(result)
        self.assertEqual(result["standard_unit"], "per_gal")
        self.assertEqual(result["display_name"], "per gallon")
        self.assertEqual(result["canonical_base"], "volume_liquid")

    def test_eggs(self):
        result = resolve_standard_unit({"name": "Grade A Large Eggs 18 ct", "department": "Dairy"})
        self.assertIsNotNone(result)
        self.assertEqual(result["standard_unit"], "per_dozen")
        self.assertEqual(result["display_name"], "per dozen")

    def test_cereal(self):
        result = resolve_standard_unit({"name": "Honey Nut Cereal 12 oz", "department": "Breakfast"})
        self.assertIsNotNone(result)
        self.assertEqual(result["standard_unit"], "per_lb")
        self.assertEqual(result["display_name"], "per pound")

    def test_pasta(self):
        result = resolve_standard_unit({"name": "Barilla Spaghetti 16 oz", "department": "Pasta"})
        self.assertIsNotNone(result)
        self.assertEqual(result["standard_unit"], "per_lb")

    def test_rice(self):
        result = resolve_standard_unit({"name": "Jasmine Rice 5 lb", "department": "Grains"})
        self.assertIsNotNone(result)
        self.assertEqual(result["standard_unit"], "per_lb")

    def test_ground_beef(self):
        result = resolve_standard_unit({"name": "Ground Beef 80/20 1 lb", "department": "Meat"})
        self.assertIsNotNone(result)
        self.assertEqual(result["standard_unit"], "per_lb")

    def test_cheese(self):
        result = resolve_standard_unit({"name": "Kraft Cheddar Cheese 8 oz", "department": "Dairy"})
        self.assertIsNotNone(result)
        self.assertEqual(result["standard_unit"], "per_lb")

    def test_yogurt(self):
        result = resolve_standard_unit({"name": "Chobani Greek Yogurt 32 oz", "department": "Dairy"})
        self.assertIsNotNone(result)
        self.assertEqual(result["standard_unit"], "per_32oz")
        self.assertEqual(result["display_name"], "per 32 oz")

    def test_butter(self):
        result = resolve_standard_unit({"name": "Land O Lakes Butter 1 lb", "department": "Dairy"})
        self.assertIsNotNone(result)
        self.assertEqual(result["standard_unit"], "per_lb")

    def test_bananas(self):
        result = resolve_standard_unit({"name": "Organic Bananas", "department": "Produce"})
        self.assertIsNotNone(result)
        self.assertEqual(result["standard_unit"], "per_lb")

    def test_apples(self):
        result = resolve_standard_unit({"name": "Gala Apples 3 lb bag", "department": "Produce"})
        self.assertIsNotNone(result)
        self.assertEqual(result["standard_unit"], "per_lb")

    def test_olive_oil(self):
        result = resolve_standard_unit({"name": "Bertolli Extra Virgin Olive Oil 16.9 oz", "department": "Cooking"})
        self.assertIsNotNone(result)
        self.assertEqual(result["standard_unit"], "per_gal")

    def test_juice(self):
        result = resolve_standard_unit({"name": "Tropicana Orange Juice 52 oz", "department": "Beverages"})
        self.assertIsNotNone(result)
        self.assertEqual(result["standard_unit"], "per_gal")

    def test_water(self):
        result = resolve_standard_unit({"name": "Spring Water 1 gal", "department": "Beverages"})
        self.assertIsNotNone(result)
        self.assertEqual(result["standard_unit"], "per_gal")

    def test_chips(self):
        result = resolve_standard_unit({"name": "Lay's Classic Chips 10 oz", "department": "Snacks"})
        self.assertIsNotNone(result)
        self.assertEqual(result["standard_unit"], "per_lb")

    def test_bread(self):
        result = resolve_standard_unit({"name": "Wonder Bread Classic 20 oz", "department": "Bakery"})
        self.assertIsNotNone(result)
        self.assertEqual(result["standard_unit"], "per_ct")
        self.assertEqual(result["display_name"], "per item")

    def test_coffee(self):
        result = resolve_standard_unit({"name": "Folgers Classic Coffee 29 oz", "department": "Beverages"})
        self.assertIsNotNone(result)
        self.assertEqual(result["standard_unit"], "per_lb")

    def test_beans(self):
        result = resolve_standard_unit({"name": "Bush's Best Black Beans 15 oz", "department": "Canned Goods"})
        self.assertIsNotNone(result)
        self.assertEqual(result["standard_unit"], "per_lb")

    def test_flour(self):
        result = resolve_standard_unit({"name": "King Arthur All-Purpose Flour 5 lb", "department": "Baking"})
        self.assertIsNotNone(result)
        self.assertEqual(result["standard_unit"], "per_lb")

    def test_onions(self):
        result = resolve_standard_unit({"name": "Yellow Onions 3 lb bag", "department": "Produce"})
        self.assertIsNotNone(result)
        self.assertEqual(result["standard_unit"], "per_lb")

    def test_potatoes(self):
        result = resolve_standard_unit({"name": "Russet Potatoes 5 lb", "department": "Produce"})
        self.assertIsNotNone(result)
        self.assertEqual(result["standard_unit"], "per_lb")

    def test_fallback_for_unknown(self):
        """Unknown products should get the fallback (per item)."""
        result = resolve_standard_unit({"name": "Random Widget XYZ", "department": "Misc"})
        self.assertIsNotNone(result)
        self.assertEqual(result["standard_unit"], "per_ct")
        self.assertEqual(result["display_name"], "per item")

    def test_empty_name(self):
        """Empty name should still return fallback."""
        result = resolve_standard_unit({"name": "", "department": ""})
        self.assertIsNotNone(result)
        self.assertEqual(result["standard_unit"], "per_ct")

    def test_none_name(self):
        """None name should still return fallback."""
        result = resolve_standard_unit({"name": None, "department": None})
        self.assertIsNotNone(result)
        self.assertEqual(result["standard_unit"], "per_ct")

    def test_category_from_extra_json(self):
        """Category field in extra_json should be used for matching."""
        result = resolve_standard_unit({
            "name": "Store Brand White Milk",
            "department": "Dairy",
            "extra_json": {"category": "milk"},
        })
        self.assertIsNotNone(result)
        self.assertEqual(result["standard_unit"], "per_gal")

    def test_category_string(self):
        """String category field should be used for matching."""
        result = resolve_standard_unit({
            "name": "Store Brand White Milk",
            "department": "Dairy",
            "category": "milk",
        })
        self.assertIsNotNone(result)
        self.assertEqual(result["standard_unit"], "per_gal")

    def test_half_and_half(self):
        """Half & half should match milk/cream category."""
        result = resolve_standard_unit({"name": "Organic Valley Half & Half 32 oz", "department": "Dairy"})
        self.assertIsNotNone(result)
        self.assertEqual(result["standard_unit"], "per_gal")

    def test_buttermilk(self):
        result = resolve_standard_unit({"name": "Low-Fat Buttermilk 1 qt", "department": "Dairy"})
        self.assertIsNotNone(result)
        self.assertEqual(result["standard_unit"], "per_gal")

    def test_whipping_cream(self):
        result = resolve_standard_unit({"name": "Heavy Whipping Cream 16 oz", "department": "Dairy"})
        self.assertIsNotNone(result)
        self.assertEqual(result["standard_unit"], "per_gal")

    def test_chicken_breast(self):
        result = resolve_standard_unit({"name": "Boneless Skinless Chicken Breast 1.5 lb", "department": "Meat"})
        self.assertIsNotNone(result)
        self.assertEqual(result["standard_unit"], "per_lb")

    def test_bacon(self):
        result = resolve_standard_unit({"name": "Hickory Smoked Bacon 16 oz", "department": "Meat"})
        self.assertIsNotNone(result)
        self.assertEqual(result["standard_unit"], "per_lb")

    def test_strawberries(self):
        result = resolve_standard_unit({"name": "Fresh Strawberries 1 lb", "department": "Produce"})
        self.assertIsNotNone(result)
        self.assertEqual(result["standard_unit"], "per_lb")

    def test_trail_mix(self):
        result = resolve_standard_unit({"name": "Planters Trail Mix 24 oz", "department": "Snacks"})
        self.assertIsNotNone(result)
        self.assertEqual(result["standard_unit"], "per_lb")


if __name__ == "__main__":
    unittest.main()
