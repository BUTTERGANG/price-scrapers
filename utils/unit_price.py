"""Unit price normalization.

Converts any item's price into a standardized per-unit cost so items from
different retailers and package sizes can be compared directly.

Adds two fields to every price record:
    unit_price_normalized  — numeric cost per canonical unit (float, or None)
    unit_canonical         — the canonical unit string (or None)

Canonical units:
    "per_fl_oz"  — liquids: milk, juice, broth, oil, wine, etc.
    "per_oz"     — dry/packaged goods: cereal, pasta, chips, canned goods
    "per_lb"     — by-weight items where the shelf price IS already $/lb
    "per_ct"     — countable items: eggs, rolls, bars, bottles sold by unit

Usage:
    from utils.unit_price import normalize_unit_price

    record = {"name": "Whole Milk", "price": 3.99, "unit": "1 gal", ...}
    normalize_unit_price(record)
    # → record["unit_price_normalized"] == 0.031172
    # → record["unit_canonical"]        == "per_fl_oz"
"""
import re
from typing import Optional

# ---------------------------------------------------------------------------
# Conversion tables
# All values = how many canonical units per one of this unit.
# ---------------------------------------------------------------------------

# Dry/solid weights → ounces
_WEIGHT_TO_OZ: dict[str, float] = {
    "oz":         1.0,
    "ounce":      1.0,
    "ounces":     1.0,
    "lb":         16.0,
    "lbs":        16.0,
    "pound":      16.0,
    "pounds":     16.0,
    "g":          0.035274,
    "gram":       0.035274,
    "grams":      0.035274,
    "kg":         35.274,
    "kilogram":   35.274,
    "kilograms":  35.274,
}

# Volumes → fluid ounces
_VOLUME_TO_FL_OZ: dict[str, float] = {
    "fl oz":          1.0,
    "fl. oz":         1.0,
    "fl. oz.":        1.0,
    "fl oz.":         1.0,
    "fl_oz":          1.0,
    "floz":           1.0,
    "fluid oz":       1.0,
    "fluid ounce":    1.0,
    "fluid ounces":   1.0,
    "cup":            8.0,
    "cups":           8.0,
    "pt":             16.0,
    "pint":           16.0,
    "pints":          16.0,
    "qt":             32.0,
    "quart":          32.0,
    "quarts":         32.0,
    "gal":            128.0,
    "gallon":         128.0,
    "gallons":        128.0,
    "l":              33.814,
    "liter":          33.814,
    "liters":         33.814,
    "litre":          33.814,
    "litres":         33.814,
    "ml":             0.033814,
    "milliliter":     0.033814,
    "milliliters":    0.033814,
    "millilitre":     0.033814,
    "millilitres":    0.033814,
}

# Count / each units
_COUNT_UNITS = frozenset({
    "ea", "each", "ct", "count", "pk", "pack", "packs",
    "piece", "pieces", "item", "items", "unit", "units",
})

# Bare weight units (no quantity) → price is already $/unit
_BARE_WEIGHT_LB = frozenset({"lb", "lbs", "pound", "pounds"})
_BARE_WEIGHT_OZ = frozenset({"oz", "ounce", "ounces"})

# Name keywords that indicate a liquid product.
# Used to disambiguate "oz" → per_fl_oz vs per_oz.
_LIQUID_KEYWORDS = frozenset({
    "milk", "juice", "water", "soda", "drink", "beverage", "broth", "stock",
    "wine", "beer", "ale", "cider", "lemonade", "tea", "coffee", "cream",
    "oil", "vinegar", "syrup", "sauce", "ketchup", "mustard", "dressing",
    "soup", "bleach", "detergent", "shampoo", "conditioner", "lotion",
    "cleaner", "spray", "rinse", "mouthwash", "smoothie", "kombucha",
    "sparkling", "tonic", "seltzer", "sparkling water",
})

# ---------------------------------------------------------------------------
# Size string regex
# ---------------------------------------------------------------------------
# Matches patterns like "1 gal", "16 OZ", "10 POUNDS", "64 fl oz", "12 ct"
# Long/multi-word alternatives (fl oz, fluid ounces, etc.) are listed first
# so they match before shorter overlapping ones (oz, l, g).

_SIZE_RE = re.compile(
    r"""
    (?:^|[\s,(\/])                         # must follow start, space, or delimiter
    (?P<qty>\d+(?:[.,]\d+)?)               # quantity: "16", "1.5", "1,5"
    \s*
    (?P<unit>
        fluid\s+ounce[s]?                  # fluid ounces
      | fluid\s+oz\.?                      # fluid oz
      | fl\.?\s*oz\.?(?:\s*s)?             # fl oz, fl. oz., fl. oz.s
      | milliliter[s]?                     # milliliters
      | millilitre[s]?
      | kilogram[s]?
      | gallon[s]?                         # gallons
      | ounce[s]?                          # ounces (before oz)
      | pound[s]?                          # pounds (before lb)
      | quart[s]?
      | liter[s]?
      | litre[s]?
      | piece[s]?
      | packs?
      | unit[s]?
      | count
      | each
      | cups?
      | pint[s]?
      | gram[s]?
      | oz\.?\b                            # oz (abbrev)
      | lbs?\b                             # lb, lbs
      | kg\b
      | ml\b
      | ct\b
      | ea\b
      | pk\b
      | qt\b
      | pt\b
      | gal\b
      | g\b                               # grams — after longer matches
      | l\b                               # liters — last (very short)
    )
    (?=\s|[.,)\/]|$)                       # must be followed by delimiter or end
    """,
    re.IGNORECASE | re.VERBOSE,
)


def _clean_unit(raw: str) -> str:
    """Lowercase, collapse whitespace, strip trailing punctuation."""
    return re.sub(r"\s+", " ", raw.strip().lower()).rstrip(".")


def parse_size(text: str) -> Optional[tuple[float, str]]:
    """Extract (quantity, unit_key) from a size or product name string.

    Returns None if no recognizable size+unit pattern is found.

    Examples:
        "1 gal"            → (1.0, "gal")
        "16 OZ"            → (16.0, "oz")
        "10 POUNDS"        → (10.0, "pounds")
        "Per 1-Lb. Pkg."   → (1.0, "lb")
        "12 ct"            → (12.0, "ct")
        "64 fl oz"         → (64.0, "fl oz")
        "Whole Milk 1 gal" → (1.0, "gal")
        "LB" (no digits)   → None
    """
    if not text:
        return None

    # Normalize digit-hyphen-letter (e.g. "1-Lb" → "1 Lb")
    text = re.sub(r"(\d)-([A-Za-z])", r"\1 \2", text)
    # Expand written fractions before the regex (e.g. "Half Gallon" → "0.5 Gallon")
    text = re.sub(r"\bhalf\b", "0.5", text, flags=re.IGNORECASE)
    text = re.sub(r"\bquarter\b", "0.25", text, flags=re.IGNORECASE)

    m = _SIZE_RE.search(text)
    if not m:
        return None

    qty_str = m.group("qty").replace(",", ".")
    unit_raw = _clean_unit(m.group("unit"))

    try:
        qty = float(qty_str)
    except ValueError:
        return None

    if qty <= 0:
        return None

    return qty, unit_raw


# ---------------------------------------------------------------------------
# Unit price computation
# ---------------------------------------------------------------------------

def _is_liquid(name: str) -> bool:
    name_lower = name.lower()
    return any(kw in name_lower for kw in _LIQUID_KEYWORDS)


def _compute(
    price: float, qty: float, unit_key: str, name: str
) -> Optional[tuple[float, str]]:
    """Return (unit_price_normalized, unit_canonical) for a (qty, unit_key) pair.

    Returns None if the unit isn't recognized.
    """
    # Volume — unambiguous multi-word keys first
    if unit_key in _VOLUME_TO_FL_OZ:
        factor = _VOLUME_TO_FL_OZ[unit_key]
        return round(price / (qty * factor), 6), "per_fl_oz"

    # "oz" — disambiguate using product name
    if unit_key in ("oz", "ounce", "ounces"):
        canonical = "per_fl_oz" if _is_liquid(name) else "per_oz"
        return round(price / qty, 6), canonical

    # Dry weight
    if unit_key in _WEIGHT_TO_OZ:
        factor = _WEIGHT_TO_OZ[unit_key]
        return round(price / (qty * factor), 6), "per_oz"

    # Count
    if unit_key in _COUNT_UNITS:
        return round(price / qty, 6), "per_ct"

    return None


def normalize_unit_price(record: dict) -> dict:
    """Augment a normalized price record with unit_price_normalized and unit_canonical.

    The effective price used is sale_price if present, otherwise price.
    Modifies the record dict in-place and returns it for chaining.

    Logic:
      1. Try to parse a (quantity, unit) from the ``unit`` field.
      2. Fall back to parsing the product ``name`` for an embedded size.
      3. If a size was found, compute the normalized price.
      4. If no size but the unit field is a bare unit (lb, oz, ea, ct …),
         treat the price as already per-unit and set canonical accordingly.
    """
    price = record.get("sale_price") or record.get("price") or 0.0
    if not price or price <= 0:
        return record

    unit = (record.get("unit") or "").strip()
    name = (record.get("name") or "")

    # ------------------------------------------------------------------
    # Steps 1 & 2: parse size from unit field, then fall back to name
    # ------------------------------------------------------------------
    result = parse_size(unit) if unit else None
    if result is None and name:
        result = parse_size(name)

    if result is not None:
        qty, unit_key = result
        computed = _compute(price, qty, unit_key, name)
        if computed is not None:
            record["unit_price_normalized"], record["unit_canonical"] = computed
            return record

    # ------------------------------------------------------------------
    # Step 4: bare units — price IS already a per-unit price
    # ------------------------------------------------------------------
    unit_clean = _clean_unit(unit) if unit else ""

    if unit_clean in _BARE_WEIGHT_LB:
        # e.g. unit="lb" — price is $/lb (by-weight produce or meat)
        record["unit_price_normalized"] = round(price, 4)
        record["unit_canonical"] = "per_lb"

    elif unit_clean in _BARE_WEIGHT_OZ:
        # e.g. unit="oz" — price is $/oz (rare, but possible for bulk bins)
        canonical = "per_fl_oz" if _is_liquid(name) else "per_oz"
        record["unit_price_normalized"] = round(price, 4)
        record["unit_canonical"] = canonical

    elif unit_clean in _COUNT_UNITS:
        # e.g. unit="each", "ea" — price is $/each; try name for size first
        record["unit_price_normalized"] = round(price, 4)
        record["unit_canonical"] = "per_ct"

    return record


# ---------------------------------------------------------------------------
# Formatting helper
# ---------------------------------------------------------------------------

_CANONICAL_LABELS = {
    "per_fl_oz": "/fl oz",
    "per_oz":    "/oz",
    "per_lb":    "/lb",
    "per_ct":    "/ct",
}


def format_unit_price(record: dict) -> Optional[str]:
    """Return a human-readable unit price string, e.g. '$0.031/fl oz'.

    Returns None if the record has no normalized unit price.
    """
    norm = record.get("unit_price_normalized")
    canon = record.get("unit_canonical")
    if norm is None or canon is None:
        return None
    label = _CANONICAL_LABELS.get(canon, f"/{canon}")
    # Use 3 sig figs for sub-cent values, 2 decimal places otherwise
    if norm < 0.10:
        return f"${norm:.4f}{label}"
    return f"${norm:.2f}{label}"
