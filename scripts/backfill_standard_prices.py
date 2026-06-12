#!/usr/bin/env python3
"""
Backfill standard_price, standard_unit, standard_unit_display for existing DB records.

Processes rows in batches of 5000 where standard_price IS NULL.
For each row, re-runs the category resolution and standard unit price computation
that would normally happen during scraping.

Usage:
    python3 scripts/backfill_standard_prices.py          # backfill all
    python3 scripts/backfill_standard_prices.py --dry-run  # preview only
    python3 scripts/backfill_standard_prices.py --retailer kroger  # one retailer
"""
import argparse
import logging
import sys
import time
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from utils import (
    get_conn,
    release_conn,
    init_db,
)
from utils.unit_price import normalize_unit_price, compute_standard_unit_price

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)s  %(message)s")
logger = logging.getLogger(__name__)

BATCH_SIZE = 5000


def backfill(dry_run: bool = False, retailer_filter: str = None) -> dict:
    conn = get_conn()
    init_db()
    total_updated = 0
    total_scanned = 0
    batches = 0

    try:
        while True:
            # Fetch a batch of rows that need backfilling
            with conn.cursor() as cur:
                if retailer_filter:
                    cur.execute(
                        """
                        SELECT id, retailer, store_id, product_id, name, department,
                               price, unit, unit_price, unit_price_normalized, unit_canonical,
                               extra_json
                        FROM prices
                        WHERE standard_price IS NULL
                          AND retailer = %s
                        ORDER BY id
                        LIMIT %s
                        """,
                        (retailer_filter, BATCH_SIZE),
                    )
                else:
                    cur.execute(
                        """
                        SELECT id, retailer, store_id, product_id, name, department,
                               price, unit, unit_price, unit_price_normalized, unit_canonical,
                               extra_json
                        FROM prices
                        WHERE standard_price IS NULL
                        ORDER BY id
                        LIMIT %s
                        """,
                        (BATCH_SIZE,)
                    )
                rows = cur.fetchall()

            if not rows:
                break

            batches += 1
            batch_ids = []
            batch_updates = []

            for row in rows:
                total_scanned += 1
                record = {
                    "retailer": row["retailer"],
                    "store_id": row["store_id"],
                    "product_id": row["product_id"],
                    "name": row["name"] or "",
                    "department": row["department"],
                    "price": row["price"],
                    "unit": row["unit"],
                    "unit_price": row["unit_price"],
                    "unit_price_normalized": row["unit_price_normalized"],
                    "unit_canonical": row["unit_canonical"],
                    "extra_json": row["extra_json"],
                }

                # Re-run normalization to populate unit_price_normalized if missing
                normalize_unit_price(record)

                # Compute standard unit price
                std_result = compute_standard_unit_price(record)

                if std_result:
                    batch_ids.append(row["id"])
                    batch_updates.append((
                        std_result["standard_price"],
                        std_result["standard_unit"],
                        std_result["display_name"],
                        row["id"],
                    ))

            if batch_updates and not dry_run:
                with conn.cursor() as cur:
                    # Use executemany for efficiency
                    cur.executemany(
                        """
                        UPDATE prices
                        SET standard_price = %s,
                            standard_unit = %s,
                            standard_unit_display = %s
                        WHERE id = %s
                        """,
                        batch_updates,
                    )
                conn.commit()
                total_updated += len(batch_updates)
                logger.info(
                    f"Batch {batches}: updated {len(batch_updates)} of {len(rows)} rows "
                    f"(total updated: {total_updated})"
                )
            elif batch_updates and dry_run:
                total_updated += len(batch_updates)
                logger.info(
                    f"Batch {batches} [DRY RUN]: would update {len(batch_updates)} of {len(rows)} rows"
                )
            else:
                logger.info(f"Batch {batches}: no standard prices computable for {len(rows)} rows")

            # If we got fewer rows than batch size, we've processed all rows
            if len(rows) < BATCH_SIZE:
                break

            # Small delay to avoid hammering the DB
            time.sleep(0.1)

    except KeyboardInterrupt:
        logger.info("Interrupted — committing progress so far...")
        conn.commit()
    except Exception:
        logger.exception("Backfill failed")
        conn.rollback()
        raise
    finally:
        release_conn(conn)

    return {
        "total_scanned": total_scanned,
        "total_updated": total_updated,
        "batches": batches,
        "dry_run": dry_run,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Backfill standard prices for existing DB records")
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing")
    parser.add_argument("--retailer", type=str, default=None, help="Backfill only this retailer")
    args = parser.parse_args()

    logger.info(f"Starting backfill (dry_run={args.dry_run}, retailer={args.retailer or 'all'})")
    result = backfill(dry_run=args.dry_run, retailer_filter=args.retailer)
    logger.info(f"Backfill complete: {result}")
