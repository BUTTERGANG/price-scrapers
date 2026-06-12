"""Base scraper class all retailer scrapers inherit from."""
import json
import logging
import re
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path
from typing import Optional

from utils.http import jitter_sleep
from utils.unit_price import normalize_unit_price, compute_standard_unit_price

logger = logging.getLogger(__name__)

# HTTP status codes that mean we're rate-limited — back off, don't keep hammering
_RATE_LIMIT_CODES = {429, 503}


class ScraperError(Exception):
    """Raised when a scraper fails in a way that should stop the run."""


class CircuitOpenError(ScraperError):
    """Raised when too many consecutive query failures trip the circuit breaker."""


class BaseScraper(ABC):
    """Common interface for all grocery price scrapers."""

    retailer: str = ""  # Set by subclass, e.g. "kroger"

    def __init__(self, store_id: str, config: dict):
        self.store_id = store_id
        self.config = config
        self.raw_dir = Path("data/raw") / self.retailer
        self.prices_dir = Path("data/prices")
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        self.prices_dir.mkdir(parents=True, exist_ok=True)
        self.request_delay: float = config.get("request_delay_seconds", 10.0)
        # Circuit breaker: stop the run after this many consecutive failures.
        # Prevents burning through all queries when bot-detected or site is down.
        self._circuit_breaker_threshold: int = config.get("circuit_breaker_threshold", 3)

    @abstractmethod
    def authenticate(self) -> None:
        """Obtain/refresh auth tokens or session state."""

    @abstractmethod
    def search_products(self, query: str) -> list[dict]:
        """Search for products by keyword. Returns list of normalized price dicts."""

    @abstractmethod
    def get_product_price(self, product_id: str) -> Optional[dict]:
        """Fetch current price for a single product. Returns price dict or None."""

    def scrape_items(
        self,
        queries: list[str],
        db_conn=None,
        run_id: Optional[int] = None,
    ) -> tuple[list[dict], list[str]]:
        """
        Scrape prices for a list of search queries.

        Returns:
            (results, failed_queries) — results is a flat list of price records;
            failed_queries lists every query that raised an error.

        Error handling:
        - Rate-limit (429/503): stop immediately — continuing makes bans worse.
        - 3+ consecutive failures: circuit breaker trips, raises CircuitOpenError.
          Prevents burning all queries when bot-detected or site is down.
        - Empty results: warn after 3+ consecutive zero-result queries —
          bot challenges return a CAPTCHA page, not an error, so this catches
          silent failures that would otherwise look like success.
        - Parse/network errors: log, record in DB if run_id provided, continue.
        - save_raw errors: non-fatal warning — losing a debug file should never
          abort a run that already has good data.
        """
        self.authenticate()
        results: list[dict] = []
        failed: list[str] = []
        consecutive_errors = 0
        consecutive_empty = 0

        for i, query in enumerate(queries):
            try:
                products = self.search_products(query)

                # Empty result detection — a bot challenge page returns HTML
                # with no product data, so search_products returns [] without
                # raising. Flag it if this keeps happening.
                if not products:
                    consecutive_empty += 1
                    if consecutive_empty >= 3:
                        logger.warning(
                            f"[{self.retailer}] {consecutive_empty} consecutive empty results. "
                            "Possible bot detection or broken parser — check raw/ output."
                        )
                else:
                    consecutive_empty = 0

                results.extend(products)
                consecutive_errors = 0
                logger.info(f"[{self.retailer}] '{query}' → {len(products)} results")

            except Exception as exc:
                status = getattr(getattr(exc, "response", None), "status_code", None)

                if status in _RATE_LIMIT_CODES:
                    logger.error(
                        f"[{self.retailer}] Rate limited (HTTP {status}) on '{query}'. "
                        "Stopping scrape to avoid ban."
                    )
                    failed.append(query)
                    if db_conn and run_id:
                        from utils.db import log_failed_query
                        log_failed_query(db_conn, run_id, self.retailer, query, exc)
                    raise

                failed.append(query)
                consecutive_errors += 1
                logger.error(
                    f"[{self.retailer}] Error on '{query}' "
                    f"(consecutive: {consecutive_errors}): {exc}"
                )

                if db_conn and run_id:
                    from utils.db import log_failed_query
                    log_failed_query(db_conn, run_id, self.retailer, query, exc)

                if consecutive_errors >= self._circuit_breaker_threshold:
                    raise CircuitOpenError(
                        f"[{self.retailer}] Circuit breaker tripped after "
                        f"{consecutive_errors} consecutive failures. "
                        f"Last error: {exc}"
                    )

            if i < len(queries) - 1:
                jitter_sleep(self.request_delay)

        return results, failed

    def save_raw(self, data: dict | list, label: str) -> Optional[Path]:
        """
        Save raw API/HTML response to data/raw/{retailer}/{label}_{timestamp}.json.
        Non-fatal: logs a warning on failure rather than crashing the scraper.
        Losing a debug file should never abort a run that has good price data.
        """
        try:
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            path = self.raw_dir / f"{label}_{ts}.json"
            path.write_text(json.dumps(data, indent=2))
            logger.debug(f"Saved raw data → {path}")
            return path
        except Exception as exc:
            logger.warning(f"[{self.retailer}] Could not save raw data '{label}': {exc}")
            return None

    @staticmethod
    def _standardize_unit_field(raw_unit: Optional[str], name: str = "") -> Optional[str]:
        """Convert a retailer-specific unit string to a standardized form.

        Normalizes the wildly different unit strings from different retailers
        into a small set of consistent forms that parse_size() handles well.

        Standard forms:
          Size strings: "1 gal", "16 oz", "12 ct", "2 lb"  (quantity + unit)
          Bare units:   "lb", "oz", "ct", "ea"              (price is per-unit)
          None:         no unit info available

        Handles:
          "Each", "EA" → "ea"
          "Per 1-Lb. Pkg." → "1 lb"
          "Per 16-oz. Pkg." → "16 oz"
          "$3.49/lb" → "lb"
          "5.4 ¢/fl oz" → "fl oz"
          "1 gal", "16 oz" → pass through
        """
        if not raw_unit:
            return None

        unit = raw_unit.strip()
        unit = re.sub(r"\s+", " ", unit)

        # "Each", "EA", "Per Each" → "ea"
        if re.match(r"^(?:each|ea|per\s+each)$", unit, re.IGNORECASE):
            return "ea"

        # "Per 1-Lb. Pkg." or "Per 16-oz. Pkg." → extract size
        m = re.match(
            r"per\s+(\d+(?:\.\d+)?)\s*[-]?\s*(lb|oz|g|kg|ml|l|gal|qt|pt|ct|pk|pack|ea)\b",
            unit,
            re.IGNORECASE,
        )
        if m:
            qty = m.group(1)
            u = m.group(2).lower()
            unit_map = {
                "lb": "lb", "oz": "oz", "g": "g", "kg": "kg",
                "ml": "ml", "l": "l", "gal": "gal", "qt": "qt",
                "pt": "pt", "ct": "ct", "pk": "ct", "pack": "ct", "ea": "ea",
            }
            return f"{qty} {unit_map.get(u, u)}"

        # "$3.49/lb" or "3.49/lb" → "lb"
        m = re.match(
            r"\$?\d+\.?\d*\s*/\s*(lb|oz|g|kg|ml|l|gal|qt|pt|ct|fl\.?\s*oz|ea)\b",
            unit,
            re.IGNORECASE,
        )
        if m:
            return m.group(1).lower()

        # "5.4 ¢/fl oz" or "5.4 cents/fl oz" → "fl oz"
        m = re.match(r"[\d.]+\s*(?:¢|cents?)\s*/\s*(.*)", unit, re.IGNORECASE)
        if m:
            return m.group(1).strip().lower()

        # Bare uppercase abbreviations: "LB", "OZ", "CT", "EA", "GAL"
        bare_map = {
            "lb": "lb", "lbs": "lb", "oz": "oz", "ct": "ct", "ea": "ea",
            "gal": "gal", "pk": "ct", "pack": "ct",
        }
        unit_lower = unit.lower()
        if unit_lower in bare_map:
            return bare_map[unit_lower]

        # If it already looks like a size string (starts with a number), pass through
        if re.match(r"^\d", unit):
            return unit

        return unit if unit else None

    def normalize_price(
        self,
        product_id: str,
        name: str,
        price: float,
        unit: Optional[str] = None,
        unit_price: Optional[float] = None,
        url: Optional[str] = None,
        upc: Optional[str] = None,
        extra: Optional[dict] = None,
    ) -> dict:
        """Return a standardized price record used across all scrapers."""
        record = {
            "retailer": self.retailer,
            "store_id": self.store_id,
            "product_id": product_id,
            "upc": upc,
            "name": name,
            "price": price,
            "unit": self._standardize_unit_field(unit, name),
            "unit_price": unit_price,
            "url": url,
            "scraped_at": datetime.now().isoformat(),
            **(extra or {}),
        }
        normalize_unit_price(record)

        # Compute category-aware standard unit price (e.g., $/gallon for milk)
        std_result = compute_standard_unit_price(record)
        if std_result:
            record["standard_price"] = std_result["standard_price"]
            record["standard_unit"] = std_result["standard_unit"]
            record["standard_unit_display"] = std_result["display_name"]

        return record
