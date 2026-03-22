"""HTTP utilities: retry logic, jitter delays, and TLS-fingerprint-safe sessions.

curl_cffi impersonates a real Chrome TLS handshake (JA3/JA4 fingerprint),
which is required to bypass Akamai, PerimeterX, and Cloudflare bot detection.
Plain `requests` is fingerprinted and blocked by these systems.

Install: pip install curl-cffi
"""
import logging
import random
import time
from typing import Optional

logger = logging.getLogger(__name__)

# Browsers to rotate through for curl_cffi impersonation.
# safari17_0 is required for Walmart (Chrome TLS fingerprints now blocked
# by Walmart's PerimeterX stack as of early 2026 — Safari bypasses it).
_IMPERSONATE_OPTIONS = [
    "safari17_0",
    "safari16_5",
    "chrome120",
    "chrome116",
]


def jitter_sleep(base_seconds: float, variance: float = 0.4) -> None:
    """Sleep for base_seconds ± variance*base_seconds. Avoids fixed-interval bot fingerprinting."""
    low = base_seconds * (1 - variance)
    high = base_seconds * (1 + variance)
    duration = random.uniform(low, high)
    logger.debug(f"Sleeping {duration:.1f}s")
    time.sleep(duration)


def make_curl_session(proxy: Optional[str] = None):
    """
    Return a curl_cffi Session that impersonates Chrome.
    Handles TLS fingerprinting (JA3/JA4), HTTP/2, and header order.

    Args:
        proxy: optional proxy URL, e.g. "http://user:pass@host:port"
    """
    try:
        from curl_cffi import requests as curl_requests
    except ImportError:
        raise RuntimeError("Install curl_cffi: pip install curl-cffi")

    impersonate = random.choice(_IMPERSONATE_OPTIONS)
    session = curl_requests.Session(impersonate=impersonate)

    if proxy:
        session.proxies = {"http": proxy, "https": proxy}

    # Realistic base headers — sec-ch-ua and sec-fetch-* headers are
    # checked by Akamai/PerimeterX; their absence is a bot signal.
    session.headers.update(
        {
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
            "sec-ch-ua": '"Chromium";v="120", "Google Chrome";v="120", "Not-A.Brand";v="99"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"macOS"',
            "sec-fetch-dest": "document",
            "sec-fetch-mode": "navigate",
            "sec-fetch-site": "none",
            "sec-fetch-user": "?1",
            "upgrade-insecure-requests": "1",
        }
    )
    return session


def request_with_retry(
    session,
    method: str,
    url: str,
    *,
    max_retries: int = 4,
    base_delay: float = 5.0,
    backoff_factor: float = 2.0,
    retry_on: tuple = (429, 500, 502, 503, 504),
    **kwargs,
):
    """
    Make an HTTP request with exponential backoff + jitter on transient errors.

    - 429 (rate limited): backs off and retries
    - 403 (forbidden / bot detected): raises immediately — retrying won't help
    - 5xx server errors: backs off and retries
    - Network errors: backs off and retries

    Args:
        session: a requests.Session or curl_cffi Session
        method: "GET", "POST", etc.
        url: target URL
        max_retries: number of retry attempts after initial failure
        base_delay: seconds to wait before first retry
        backoff_factor: multiply delay by this on each retry
        retry_on: HTTP status codes that trigger a retry
        **kwargs: passed through to session.request()
    """
    delay = base_delay
    last_exc = None

    for attempt in range(max_retries + 1):
        try:
            resp = session.request(method, url, **kwargs)

            if resp.status_code == 403:
                logger.error(
                    f"[{url}] 403 Forbidden — bot detection triggered. "
                    "Consider switching to Playwright or a proxy."
                )
                resp.raise_for_status()  # raise immediately, no retry

            if resp.status_code in retry_on:
                retry_after = int(resp.headers.get("Retry-After", delay))
                wait = max(retry_after, delay)
                logger.warning(
                    f"[{url}] HTTP {resp.status_code} on attempt {attempt + 1}. "
                    f"Retrying in {wait:.1f}s…"
                )
                jitter_sleep(wait)
                delay *= backoff_factor
                continue

            return resp

        except Exception as exc:
            last_exc = exc
            if attempt < max_retries:
                logger.warning(
                    f"[{url}] Request error on attempt {attempt + 1}: {exc}. "
                    f"Retrying in {delay:.1f}s…"
                )
                jitter_sleep(delay)
                delay *= backoff_factor
            else:
                logger.error(f"[{url}] All {max_retries + 1} attempts failed.")
                raise

    raise RuntimeError(f"Exhausted retries for {url}") from last_exc
