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
import logging
import re
from typing import Optional

from utils.category_resolver import resolve_standard_unit

logger = logging.getLogger(__name__)

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
    "bottle", "bottles", "bag", "bags", "box", "boxes",
    "can", "cans", "jar", "jars", "tube", "tubes",
    "roll", "rolls", "bar", "bars", "bunch", "bunches",
    "head", "heads", "clove", "cloves", "slice", "slices",
    "sheet", "sheets", "pad", "pads",
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
      | bottles?
      | bags?
      | boxes?
      | cans?
      | jars?
      | tubes?
      | rolls?
      | bars?
      | bunches?
      | heads?
      | cloves?
      | slices?
      | sheets?
      | pads?
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

# Pattern for price-per-unit strings like "3.99/lb", "0.12/oz", "2.50/gal"
# These appear in formatted_price fields and unit_price strings.
_PRICE_PER_UNIT_RE = re.compile(
    r"""
    (?:^|[\s,(\/])                         # must follow start, space, or delimiter
    \/?\s*                                 # optional leading slash
    \d+(?:[.,]\d+)?                        # price amount (not captured)
    \s*/\s*                                # slash separator
    (?P<unit>
        fluid\s+ounce[s]?
      | fluid\s+oz\.?
      | fl\.?\s*oz\.?
      | milliliter[s]?
      | gallon[s]?
      | ounce[s]?
      | pound[s]?
      | quart[s]?
      | liter[s]?
      | kilogram[s]?
      | lb
      | lbs
      | oz
      | kg
      | ml
      | gal
      | qt
      | pt
      | g
      | l
      | ea
      | ct
    )
    (?=\s|[.,)\/]|$)                       # must be followed by delimiter or end
    """,
    re.IGNORECASE | re.VERBOSE,
)


def _parse_price_per_unit(text: str) -> Optional[tuple[float, str]]:
    """Extract (1.0, unit_key) from a price-per-unit string like '$3.99/lb'.

    Returns a (quantity, unit_key) tuple with qty=1.0, since the price-per-unit
    string already expresses the unit cost. The caller can then use the record's
    price directly with the unit.

    Examples:
        "$3.99/lb"  → (1.0, "lb")
        "0.12/oz"   → (1.0, "oz")
        "2.50/gal"  → (1.0, "gal")
    """
    if not text:
        return None
    # Strip leading $ for cleaner matching
    cleaned = re.sub(r"^\$", "", text.strip()).strip()
    m = _PRICE_PER_UNIT_RE.search(cleaned)
    if not m:
        return None
    unit_raw = _clean_unit(m.group("unit"))
    return 1.0, unit_raw


def _clean_unit(raw: str) -> str:
    """Lowercase, collapse whitespace, strip trailing punctuation."""
    return re.sub(r"\s+", " ", raw.strip().lower()).rstrip(".")


def pre_normalize_name(text: str) -> str:
    """Expand common size patterns into parse_size()-friendly form.

    Handles:
      - "12-Pack", "6-Pack" → "12 ct", "6 ct"
      - "16oz", "12ct" (no space) → "16 oz", "12 ct"
      - "1/2 gal" → "0.5 gal"
      - "3pk" → "3 pk"
    """
    if not text:
        return text

    # "12-Pack" / "6-Pack" → "12 ct" / "6 ct"
    text = re.sub(
        r"(\d+)\s*[-]?\s*(?:pack|pk)\b",
        r"\1 ct",
        text,
        flags=re.IGNORECASE,
    )

    # "16oz", "12ct", "2lb", "500ml" (digit immediately followed by unit, no space)
    text = re.sub(
        r"(\d+(?:\.\d+)?)\s*(oz|lb|lbs|g|kg|ml|l|gal|qt|pt|ct|ea|fl\.?\s*oz)\b",
        r"\1 \2",
        text,
        flags=re.IGNORECASE,
    )

    # "1 1/2 gal" → "1.5 gal" (mixed fraction: whole number + fraction)
    def _mixed_frac_replace(m):
        try:
            whole = float(m.group(1))
            num = float(m.group(2)) / float(m.group(3))
            return f"{whole + num:g} {m.group(4)}"
        except (ValueError, ZeroDivisionError):
            return m.group(0)

    text = re.sub(
        r"(\d+)\s+(\d+)/(\d+)\s*(oz|lb|lbs|g|kg|ml|l|gal|qt|pt|ct|fl\.?\s*oz)\b",
        _mixed_frac_replace,
        text,
        flags=re.IGNORECASE,
    )

    # "1/2 gal", "3/4 lb" → "0.5 gal", "0.75 lb"
    def _frac_replace(m):
        try:
            num = float(m.group(1)) / float(m.group(2))
            return f"{num:g} {m.group(3)}"
        except (ValueError, ZeroDivisionError):
            return m.group(0)

    text = re.sub(
        r"(\d+)/(\d+)\s*(oz|lb|lbs|g|kg|ml|l|gal|qt|pt|ct|fl\.?\s*oz)\b",
        _frac_replace,
        text,
        flags=re.IGNORECASE,
    )

    return text


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

    # Pre-normalize common patterns
    text = pre_normalize_name(text)

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
# Multi-size parsing for compound expressions
# ---------------------------------------------------------------------------

# Matches "6 x 16 oz", "12 - 16 oz", "24 @ 12 fl oz"
_MULTI_SIZE_RE = re.compile(
    r"""
    (?P<count>\d+(?:\.\d+)?)                    # pack count: "6", "12"
    \s*(?:x|×|-|@)\s*                            # separator
    (?P<qty>\d+(?:\.\d+)?)                        # per-item qty: "16", "12"
    \s*
    (?P<unit>
        fluid\s+ounce[s]?
      | fluid\s+oz\.?
      | fl\.?\s*oz\.?
      | ounce[s]?
      | pound[s]?
      | gallon[s]?
      | quart[s]?
      | pint[s]?
      | liter[s]?
      | litre[s]?
      | milliliter[s]?
      | kilogram[s]?
      | gram[s]?
      | oz\.?\b
      | lbs?\b
      | gal\b
      | qt\b
      | pt\b
      | l\b
      | ml\b
      | kg\b
      | g\b
    )
    """,
    re.IGNORECASE | re.VERBOSE,
)


def parse_size_multi(text: str) -> Optional[tuple[float, str]]:
    """Extract total quantity from compound size expressions.

    For multi-pack items like "Coca-Cola 12-Pack 12 fl oz", returns the
    total volume (144 fl oz). For count-only expressions like "6 - 16 oz",
    returns the total weight/volume.

    Returns None if no compound pattern is found.

    Examples:
        "6 x 16 oz"    → (96.0, "oz")
        "12 - 12 fl oz" → (144.0, "fl oz")
        "24 @ 16.9 fl oz" → (405.6, "fl oz")
    """
    if not text:
        return None

    text = pre_normalize_name(text)
    m = _MULTI_SIZE_RE.search(text)
    if not m:
        return None

    try:
        count = float(m.group("count"))
        qty = float(m.group("qty"))
    except ValueError:
        return None

    if count <= 0 or qty <= 0:
        return None

    unit_raw = _clean_unit(m.group("unit"))
    total = count * qty

    return total, unit_raw


# ---------------------------------------------------------------------------
# Category-aware standard unit price
# ---------------------------------------------------------------------------

# Conversion factors: (from_canonical, to_standard) -> multiplier
_STANDARD_CONVERSIONS = {
    # Volume: fl_oz → larger units
    ("per_fl_oz", "per_gal"): 128.0,
    ("per_fl_oz", "per_32oz"): 32.0,
    ("per_fl_oz", "per_fl_oz"): 1.0,
    # Weight: oz ↔ lb
    ("per_oz", "per_lb"): 16.0,
    ("per_oz", "per_oz"): 1.0,
    ("per_lb", "per_lb"): 1.0,
    ("per_lb", "per_oz"): 1 / 16.0,
    # Count: ct → dozen
    ("per_ct", "per_dozen"): 12.0,
    ("per_ct", "per_ct"): 1.0,
    # Cross-type: count items sold by weight (e.g., bananas priced per ct but standard is per_lb)
    # These require item weight; without it we can't convert. Omitted intentionally.
}


def compute_standard_unit_price(record: dict) -> Optional[dict]:
    """Compute price per standard unit for category-aware comparison.

    Uses the existing unit_price_normalized + unit_canonical fields and
    converts to the category-appropriate standard unit.

    Returns:
        dict with keys: standard_price, standard_unit, display_name, canonical_base
        or None if conversion is not possible.

    Example:
        record = {"name": "Whole Milk 1 gal", "unit_price_normalized": 0.031172,
                  "unit_canonical": "per_fl_oz"}
        compute_standard_unit_price(record)
        → {"standard_price": 3.99, "standard_unit": "per_gal",
           "display_name": "per gallon", "canonical_base": "volume_liquid"}
    """
    norm = record.get("unit_price_normalized")
    canon = record.get("unit_canonical")

    if norm is None or canon is None:
        return None

    category_info = resolve_standard_unit(record)
    if category_info is None:
        return None

    standard_unit = category_info["standard_unit"]
    key = (canon, standard_unit)
    multiplier = _STANDARD_CONVERSIONS.get(key)

    if multiplier is None:
        logger.debug(
            "No conversion from %s to %s for %r",
            canon, standard_unit, record.get("name"),
        )
        return None

    return {
        "standard_price": round(norm * multiplier, 4),
        "standard_unit": standard_unit,
        "display_name": category_info["display_name"],
        "canonical_base": category_info["canonical_base"],
    }


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


def _unit_key_to_canonical(unit_key: str, name: str) -> Optional[str]:
    """Map a unit_key to its canonical form for price-per-unit strings."""
    if unit_key in _VOLUME_TO_FL_OZ:
        return "per_fl_oz"
    if unit_key in ("oz", "ounce", "ounces"):
        return "per_fl_oz" if _is_liquid(name) else "per_oz"
    if unit_key in _WEIGHT_TO_OZ:
        # lb → per_lb, kg → per_lb (already per-weight), g → per_oz
        if unit_key in ("lb", "lbs", "pound", "pounds"):
            return "per_lb"
        if unit_key in ("kg", "kilogram", "kilograms"):
            return "per_lb"
        return "per_oz"
    if unit_key in _COUNT_UNITS:
        return "per_ct"
    return None


def normalize_unit_price(record: dict) -> dict:
    """Augment a normalized price record with unit_price_normalized and unit_canonical.

    The effective price used is sale_price if present, otherwise price.
    Modifies the record dict in-place and returns it for chaining.

    Logic:
      1. Try to parse a (quantity, unit) from the ``unit`` field.
      2. Fall back to parsing the product ``name`` for an embedded size.
      3. Fall back to parsing common extra fields (formatted_price, deal_text,
         unit_price string) for size info that scrapers store there.
      4. If a size was found, compute the normalized price.
      5. If no size but the unit field is a bare unit (lb, oz, ea, ct …),
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

    # ------------------------------------------------------------------
    # Step 2b: try multi-size parsing on the name for compound expressions
    # e.g. "Coca-Cola 12-Pack 12 fl oz" → (144.0, "fl oz")
    # ------------------------------------------------------------------
    if result is None and name:
        result = parse_size_multi(name)

    # ------------------------------------------------------------------
    # Step 3: fall back to extra fields that may contain size info
    # ------------------------------------------------------------------
    price_per_unit_key: Optional[str] = None
    if result is None:
        extra_fields = (
            record.get("formatted_price") or "",
            record.get("deal_text") or "",
            record.get("unit_price") or "",
            record.get("sale_unit_price") or "",
        )
        for field_val in extra_fields:
            field_str = str(field_val).strip()
            if not field_str:
                continue
            # Try standard size parsing (e.g. "1 gal", "16 oz")
            parsed = parse_size(field_str)
            if parsed is not None:
                result = parsed
                break
            # Try price-per-unit parsing (e.g. "$3.99/lb", "0.12/oz")
            # This means the price IS already per-unit, so we handle it below.
            ppu = _parse_price_per_unit(field_str)
            if ppu is not None:
                price_per_unit_key = ppu[1]  # unit_key
                break

    # ------------------------------------------------------------------
    # Step 3b: Kroger "sold_by" field — "unit" means countable, "weight" means by weight
    # If we still have no size but sold_by is "unit", treat as per-count
    # ------------------------------------------------------------------
    if result is None and price_per_unit_key is None:
        sold_by = str(record.get("sold_by") or "").strip().lower()
        if sold_by == "unit":
            record["unit_price_normalized"] = round(price, 4)
            record["unit_canonical"] = "per_ct"
            return record

    # ------------------------------------------------------------------
    # Step 4: compute normalized price
    # ------------------------------------------------------------------
    if result is not None:
        qty, unit_key = result
        computed = _compute(price, qty, unit_key, name)
        if computed is not None:
            record["unit_price_normalized"], record["unit_canonical"] = computed
            return record

    # ------------------------------------------------------------------
    # Step 4b: price-per-unit from extra fields — price is already per-unit
    # ------------------------------------------------------------------
    if price_per_unit_key is not None:
        canonical = _unit_key_to_canonical(price_per_unit_key, name)
        if canonical is not None:
            record["unit_price_normalized"] = round(price, 4)
            record["unit_canonical"] = canonical
            return record

    # ------------------------------------------------------------------
    # Step 5: bare units — price IS already a per-unit price
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

    if "unit_price_normalized" not in record:
        logger.debug(
            "unit_price normalization failed for %r (unit=%r, price=%s)",
            name, unit, price,
        )

    # ------------------------------------------------------------------
    # Step 6: compute category-aware standard unit price
    # ------------------------------------------------------------------
    std_result = compute_standard_unit_price(record)
    if std_result:
        record["standard_price"] = std_result["standard_price"]
        record["standard_unit"] = std_result["standard_unit"]
        record["standard_unit_display"] = std_result["display_name"]

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
