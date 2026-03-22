from .http import jitter_sleep, make_curl_session, request_with_retry
from .db import (
    get_conn,
    insert_many,
    start_run,
    finish_run,
    log_failed_query,
    get_failed_queries,
    last_successful_run,
    find_active_deals,
    cheapest_per_retailer,
    price_history,
    lowest_price_ever,
    find_by_upc,
)
from .compare import (
    compare_by_name,
    compare_by_unit_price,
    find_deals,
    best_price_per_retailer,
    print_unit_price_comparison,
)
from .unit_price import normalize_unit_price, parse_size, format_unit_price
from .validate import validate_results, check_count_drop

__all__ = [
    # HTTP
    "jitter_sleep",
    "make_curl_session",
    "request_with_retry",
    # Database
    "get_conn",
    "insert_many",
    "start_run",
    "finish_run",
    "log_failed_query",
    "get_failed_queries",
    "last_successful_run",
    "find_active_deals",
    "cheapest_per_retailer",
    "price_history",
    "lowest_price_ever",
    "find_by_upc",
    # In-memory comparison (for reporting on current-run results)
    "compare_by_name",
    "compare_by_unit_price",
    "find_deals",
    "best_price_per_retailer",
    "print_unit_price_comparison",
    # Unit price normalization
    "normalize_unit_price",
    "parse_size",
    "format_unit_price",
    # Data quality validation
    "validate_results",
    "check_count_drop",
]
