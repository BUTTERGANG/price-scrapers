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
import os
import random
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

# Playwright's Chromium needs shared libraries that aren't in the default
# system paths on Replit.  We resolve them from the Nix store at import time
# so the browser can launch without manual LD_LIBRARY_PATH setup.
_CHROMIUM_NIX_LIB_PATHS = [
    "/nix/store/y3nxdc2x8hwivppzgx5hkrhacsh87l21-glib-2.84.3/lib",
    "/nix/store/2jsrwgic869zynqljiqa4g7dqzpwm2yd-nss-3.101.2/lib",
    "/nix/store/gpb87pb8s826aggy1s3f352alp40dkj8-nspr-4.36/lib",
    "/nix/store/si92b84j9mqr3zshc8l78b7liq98sldc-cups-2.4.11/lib",
    "/nix/store/231d6mmkylzr80pf30dbywa9x9aryjgy-dbus-1.14.10-lib/lib",
    "/nix/store/l0d83xf43lsyhzqziy0am1cidhkcxs9q-expat-2.7.1/lib",
    "/nix/store/xpszkfp1gaf8jfmcsll93xg0pb4c0rk7-libdrm-2.4.124/lib",
    "/nix/store/sisfq9wihyqqjzmrpik9b4xksifw97ha-libxkbcommon-1.8.1/lib",
    "/nix/store/cpwib3zazj49fm0y04y53w4xkbqsgrgm-mesa-25.0.7/lib",
    "/nix/store/24w3s75aa2lrvvxsybficn8y3zxd27kp-mesa-libgbm-25.1.0/lib",
    "/nix/store/802n2ppbgbsk6211wjkg6dcjmifdcfr6-pango-1.56.3/lib",
    "/nix/store/prjwp9nyczsza4kga6a2bcb3qz1mvxg7-cairo-1.18.2/lib",
    "/nix/store/yw5xqn8lqinrifm9ij80nrmf0i6fdcbx-alsa-lib-1.2.13/lib",
    "/nix/store/1nsvsrqp5zm96r9p3rrq3yhlyw8jiy91-libX11-1.8.12/lib",
    "/nix/store/4phl6z95v2i4525y0zpmi9v6ac0n4bx7-libXcomposite-0.4.6/lib",
    "/nix/store/h8143a07cf1vw41s49h0zahnq13zim94-libXdamage-1.1.6/lib",
    "/nix/store/0046rn5sgi6l38zl81bg2r02zlzxqqbc-libXext-1.3.6/lib",
    "/nix/store/94grp8dx897wmf0x3azpdbgzj3krz7v5-libXfixes-6.0.1/lib",
    "/nix/store/5fcbi2lycw2hz7rbn3nl5nrhhk2ki8dd-libXrandr-1.5.4/lib",
    "/nix/store/2y2hhlki6macaj9j1409q1j6i33l6igf-libxcb-1.17.0/lib",
    "/nix/store/qrij2csr7p6jsfa40d7h4ckzqg4wd5w2-at-spi2-core-2.56.2/lib",
    "/nix/store/5flwv7rri80114p8vlz7l8qf8z5i557h-systemd-minimal-libs-257.6/lib",
]

def _ensure_chromium_libs() -> None:
    """Add Nix library paths to LD_LIBRARY_PATH if they exist."""
    existing = os.environ.get("LD_LIBRARY_PATH", "")
    existing_set = set(existing.split(":")) if existing else set()
    new_paths = [p for p in _CHROMIUM_NIX_LIB_PATHS if p not in existing_set and os.path.isdir(p)]
    if new_paths:
        combined = ":".join(new_paths)
        os.environ["LD_LIBRARY_PATH"] = f"{combined}:{existing}" if existing else combined

_ensure_chromium_libs()

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
        from playwright_stealth import Stealth
        await Stealth().apply_stealth_async(page)
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
