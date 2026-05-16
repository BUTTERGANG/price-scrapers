"""Data quality validation for scraped price records.

Runs after each scraper call, before DB insert. Designed to catch silent
breakage — structural site changes and parse errors that return bad data
without raising an exception.

Rules:
  DROP  — records that cannot be stored meaningfully (no name, HTML garbage)
  DEDUP — duplicate product_id within the same run (keep first occurrence)
  WARN  — anomalies logged but record is kept for inspection

BOGO / zero-price awareness:
  price=0 is valid for BOGO, "% off", and multi-buy deals where the retailer
  API returns the deal description without a resolved dollar price.
  A record is considered to have deal context if any of these fields is
  non-empty: deal_text, sale_story, pre_price_text.
  Only flag price=0 when ALL deal fields are absent.
"""
import logging
import re
from typing import Optional

logger = logging.getLogger(__name__)

# Records with price above this are flagged as likely parse errors.
# GFS bulk items can be $100–$200; $500 gives comfortable headroom.
_PRICE_MAX = 500.0

# Matches HTML tags and common HTML entities
_HTML_RE = re.compile(r"<[^>]+>|&(?:amp|lt|gt|quot|apos|nbsp);", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _has_deal_context(record: dict) -> bool:
    """Return True if the record has any deal text explaining a zero/absent price."""
    fields = ("deal_text", "sale_story", "pre_price_text")
    return any((record.get(f) or "").strip() for f in fields)


def _is_html_garbage(text: str) -> bool:
    """Return True if the text appears to be unparsed HTML markup."""
    return bool(_HTML_RE.search(text))


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def validate_results(
    results: list[dict],
    retailer: str,
) -> tuple[list[dict], list[str]]:
    """Validate a list of price records from one scraper run.

    Returns:
        (valid_records, issues)

        valid_records — records that passed all hard filters (drop/dedup);
                        anomaly warnings are noted in issues but the record
                        is still included.
        issues        — human-readable warning strings for every problem found.
    """
    valid: list[dict] = []
    issues: list[str] = []
    seen_ids: dict[str, str] = {}  # product_id → first-seen name

    for r in results:
        name = (r.get("name") or "").strip()
        price = r.get("price") or 0.0
        sale_price = r.get("sale_price")
        pid = str(r.get("product_id") or "")

        # ------------------------------------------------------------------
        # Hard drops — record cannot be saved meaningfully
        # ------------------------------------------------------------------

        if not name:
            issues.append(
                f"[{retailer}] DROP: empty name (product_id={pid!r})"
            )
            continue

        if _is_html_garbage(name):
            issues.append(
                f"[{retailer}] DROP: HTML in name — likely broken parser: {name[:80]!r}"
            )
            continue

        # ------------------------------------------------------------------
        # Deduplication — keep only the first occurrence per product_id
        # ------------------------------------------------------------------

        if pid:
            if pid in seen_ids:
                issues.append(
                    f"[{retailer}] DEDUP: product_id {pid!r} seen twice "
                    f"({name!r} duplicates {seen_ids[pid]!r}) — skipping second"
                )
                continue
            seen_ids[pid] = name

        # ------------------------------------------------------------------
        # Soft warnings — record is kept but the issue is logged
        # ------------------------------------------------------------------

        if price < 0:
            issues.append(
                f"[{retailer}] WARN: negative price ${price:.2f} for {name!r}"
            )

        elif price == 0 and not _has_deal_context(r):
            issues.append(
                f"[{retailer}] WARN: price=$0 with no deal text for {name!r} "
                f"(product_id={pid!r}) — possible parse error"
            )

        if price > _PRICE_MAX:
            issues.append(
                f"[{retailer}] WARN: unusually high price ${price:.2f} "
                f"for {name!r} — verify this isn't a parse artifact"
            )

        if (
            sale_price is not None
            and price > 0
            and sale_price >= price
        ):
            issues.append(
                f"[{retailer}] WARN: sale_price (${sale_price:.2f}) >= "
                f"regular price (${price:.2f}) for {name!r} — won't show as a deal"
            )

        valid.append(r)

    return valid, issues


def check_count_drop(
    retailer: str,
    new_count: int,
    last_count: Optional[int],
    threshold: float = 0.5,
) -> Optional[str]:
    """Return a warning string if the item count dropped more than *threshold*
    fraction compared to the last successful run, else None.

    Args:
        retailer:   Retailer name for the warning message.
        new_count:  Number of records returned in this run.
        last_count: records_saved from the last successful run (None = no history).
        threshold:  Fraction below which a drop triggers a warning (default 0.5 = 50%).
    """
    if last_count is None:
        return None
    if new_count < last_count * threshold:
        pct = round(100.0 * new_count / last_count)
        return (
            f"[{retailer}] WARN: item count dropped from {last_count} → {new_count} "
            f"({pct}% of last run) — possible parser breakage or site change"
        )
    return None
