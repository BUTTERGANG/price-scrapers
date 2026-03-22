"""Shared Playwright browser utilities for scrapers that need JS rendering.

Used by: FreshThymeScraper, CostcoScraper, and Walmart fallback.

Stealth configuration applied:
- navigator.webdriver removed (primary detection vector)
- Realistic viewport, locale, timezone, color scheme
- Chrome runtime object populated (missing in raw headless)
- Permissions granted to match real browser behavior
- User-agent matches the Chrome version being impersonated

Install:
    pip install playwright playwright-stealth
    playwright install chromium
"""
import asyncio
import logging
import random
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

# Match the Chrome version used in curl_cffi impersonation
_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

_VIEWPORTS = [
    {"width": 1440, "height": 900},
    {"width": 1920, "height": 1080},
    {"width": 1366, "height": 768},
    {"width": 1280, "height": 800},
]


async def _apply_stealth(page) -> None:
    """
    Patch the page's JS environment to remove headless browser signals.
    playwright-stealth handles most of this automatically; these are
    additional patches for properties it may miss.
    """
    try:
        from playwright_stealth import stealth_async
        await stealth_async(page)
    except ImportError:
        logger.warning(
            "playwright-stealth not installed. Bot detection risk is higher. "
            "Run: pip install playwright-stealth"
        )

    # Remove webdriver flag even if stealth didn't catch it
    await page.add_init_script(
        """
        Object.defineProperty(navigator, 'webdriver', { get: () => undefined });

        // Populate chrome runtime object — missing in headless Chromium
        window.chrome = {
            runtime: {},
            loadTimes: function(){},
            csi: function(){},
            app: {}
        };

        // Fake realistic plugin list (empty plugins = bot signal)
        Object.defineProperty(navigator, 'plugins', {
            get: () => [
                { name: 'Chrome PDF Plugin' },
                { name: 'Chrome PDF Viewer' },
                { name: 'Native Client' }
            ]
        });

        // Fake language list
        Object.defineProperty(navigator, 'languages', {
            get: () => ['en-US', 'en']
        });
        """
    )


async def fetch_with_intercept(
    url: str,
    intercept_url_pattern: str,
    on_response: Callable[[Any], Any],
    *,
    headless: bool = True,
    timeout_ms: int = 30_000,
    proxy: Optional[str] = None,
    wait_for_selector: Optional[str] = None,
) -> Optional[Any]:
    """
    Navigate to `url` in a stealthy Playwright browser, intercept any network
    response whose URL contains `intercept_url_pattern`, and call
    `on_response(json_data)`.

    Args:
        url: page to navigate to
        intercept_url_pattern: substring to match in XHR/fetch response URLs
        on_response: called with the parsed JSON body; its return value is returned
        headless: run without a visible browser window
        timeout_ms: navigation timeout in milliseconds
        proxy: optional proxy URL e.g. "http://user:pass@host:port"
        wait_for_selector: optional CSS selector to wait for before closing

    Returns:
        Whatever `on_response` returns, or None if no matching response was intercepted.
    """
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        raise RuntimeError(
            "Install playwright: pip install playwright && playwright install chromium"
        )

    result = None
    viewport = random.choice(_VIEWPORTS)
    proxy_config = {"server": proxy} if proxy else None

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=headless,
            proxy=proxy_config,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
            ],
        )

        context = await browser.new_context(
            viewport=viewport,
            user_agent=_USER_AGENT,
            locale="en-US",
            timezone_id="America/Indiana/Indianapolis",
            color_scheme="light",
            # Grant realistic permissions
            permissions=["geolocation", "notifications"],
        )

        page = await context.new_page()
        await _apply_stealth(page)

        async def handle_response(response):
            nonlocal result
            if intercept_url_pattern in response.url:
                try:
                    data = await response.json()
                    result = on_response(data)
                    logger.debug(f"Intercepted response from: {response.url}")
                except Exception as exc:
                    logger.warning(f"Failed to parse intercepted response from {response.url}: {exc}")

        page.on("response", handle_response)

        try:
            await page.goto(url, timeout=timeout_ms, wait_until="domcontentloaded")

            if wait_for_selector:
                await page.wait_for_selector(wait_for_selector, timeout=timeout_ms)
            else:
                # Wait for network to go quiet rather than a fixed sleep
                await page.wait_for_load_state("networkidle", timeout=timeout_ms)

        except Exception as exc:
            logger.error(f"Navigation error for {url}: {exc}")

        await browser.close()

    return result


async def fetch_page_html(
    url: str,
    *,
    headless: bool = True,
    timeout_ms: int = 30_000,
    proxy: Optional[str] = None,
    wait_for_selector: Optional[str] = None,
) -> str:
    """Return the fully-rendered HTML of a page after JS execution."""
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        raise RuntimeError(
            "Install playwright: pip install playwright && playwright install chromium"
        )

    viewport = random.choice(_VIEWPORTS)
    proxy_config = {"server": proxy} if proxy else None
    html = ""

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=headless,
            proxy=proxy_config,
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
        )
        context = await browser.new_context(
            viewport=viewport,
            user_agent=_USER_AGENT,
            locale="en-US",
            timezone_id="America/Indiana/Indianapolis",
        )
        page = await context.new_page()
        await _apply_stealth(page)

        await page.goto(url, timeout=timeout_ms, wait_until="domcontentloaded")

        if wait_for_selector:
            await page.wait_for_selector(wait_for_selector, timeout=timeout_ms)
        else:
            await page.wait_for_load_state("networkidle", timeout=timeout_ms)

        html = await page.content()
        await browser.close()

    return html


def run_intercept(
    url: str,
    pattern: str,
    on_response: Callable,
    **kwargs,
) -> Optional[Any]:
    """Synchronous wrapper around fetch_with_intercept."""
    return asyncio.run(fetch_with_intercept(url, pattern, on_response, **kwargs))


def run_fetch_html(url: str, **kwargs) -> str:
    """Synchronous wrapper around fetch_page_html."""
    return asyncio.run(fetch_page_html(url, **kwargs))
