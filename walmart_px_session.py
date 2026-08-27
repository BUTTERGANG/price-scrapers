"""Dual-layer PerimeterX session manager for Walmart.com.

Walmart uses two PX (HUMAN) deployments:
  Layer 1: PXu6b0qd2S — entry / homepage challenge
  Layer 2: PXUArm9B04 — search endpoint challenge

This module solves both layers and manages cookies/auth headers for a
curl_cffi session to use for actual scraping.
"""
import json, re, uuid as uuid_lib, time
from urllib.parse import urlencode

from grocery_app_walmart_px import WalmartPXGenerator, get_cloud_collector_url, _parse_px3_cookie


# ── Walmart PX app IDs ──
PX_LAYER1_APP_ID = "PXu6b0qd2S"
PX_LAYER2_APP_ID = "PXUArm9B04"

# Fixed for this PX version on Walmart
PX_FT = 221


class WalmartPxSession:
    """Manages dual-layer PerimeterX solving for Walmart.com.
    
    Usage:
        px = WalmartPxSession()
        if px.solve():
            # Use px.get_headers() and px.get_cookies() on requests
            session = curl_requests.Session(impersonate='safari17_0')
            session.headers.update(px.get_headers())
            for name, value in px.get_cookies().items():
                session.cookies.set(name, value, domain='.walmart.com')
            resp = session.get('https://www.walmart.com/search?q=milk', ...)
    """

    def __init__(self):
        import tls_client
        self.tls = tls_client.Session(
            client_identifier="chrome_127",
            random_tls_extension_order=True,
        )
        self.tls.headers = {
            'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'accept-language': 'en-US,en;q=0.9',
            'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                          'AppleWebKit/537.36 (KHTML, like Gecko) '
                          'Chrome/127.0.0.0 Safari/537.36',
        }

        # Solved cookie state
        self._layer1_cookie: str | None = None
        self._layer2_cookie: str | None = None
        self._vid: str = str(uuid_lib.uuid4())  # Shared VID across layers
        self._sid: str = str(uuid_lib.uuid4())
        self._cts: str = str(uuid_lib.uuid4())
        self._uuid: str = str(uuid_lib.uuid4())
        self._solved = False

    def _make_solver(self, app_id: str) -> WalmartPXGenerator:
        """Create a WalmartPXGenerator for the given app ID."""
        return WalmartPXGenerator(
            app_id=app_id,
            ft=PX_FT,
            collector_uri=get_cloud_collector_url(app_id),
            host="https://www.walmart.com",
            sid=self._sid,
            vid=self._vid,
            cts=self._cts,
        )

    def solve(self) -> bool:
        """Solve both PX layers.
        
        Returns True if both layers were solved successfully.
        After success, use get_headers() and get_cookies() for requests.
        """
        # Layer 1: Entry/trigger challenge
        print("[px] Solving Layer 1 (PXu6b0qd2S)...")
        solver1 = self._make_solver(PX_LAYER1_APP_ID)
        solver1.px_uuid = str(uuid_lib.uuid4())

        layer1_ok = solver1.solve(self.tls)
        if not layer1_ok:
            print("[px] ✗ Layer 1 failed")
            return False

        self._layer1_cookie = solver1.px_cookie
        print(f"[px] ✓ Layer 1 solved")

        # Set Layer 1 cookie so Layer 2 trigger works
        self.tls.cookies.set("_px3", self._layer1_cookie, domain=".walmart.com")
        self.tls.cookies.set("_pxvid", self._vid, domain=".walmart.com")

        # Trigger Layer 2 by hitting the search endpoint
        print("[px] Triggering Layer 2 (PXUArm9B04)...")
        trigger_headers = {
            **self._get_base_headers(),
            "X-Px-Authorization": f"3:{self._layer1_cookie}",
            "X-Px-Vid": self._vid,
            "X-Px-Uuid": str(uuid_lib.uuid4()),
        }

        r = self.tls.get(
            "https://www.walmart.com/search/api/preso",
            params={"query": "milk", "store": "2787"},
            headers=trigger_headers,
        )

        # If we get 200 with data, no Layer 2 needed!
        if r.status_code == 200 and "__NEXT_DATA__" not in r.text and "Robot" not in r.text:
            print("[px] No Layer 2 challenge — Layer 1 was sufficient!")
            self._solved = True
            return True

        if r.status_code != 412:
            print(f"[px] Layer 2 trigger: unexpected {r.status_code}, trying anyway")

        # Layer 2: Solve search challenge
        print("[px] Solving Layer 2 (PXUArm9B04)...")
        solver2 = self._make_solver(PX_LAYER2_APP_ID)
        solver2.px_uuid = str(uuid_lib.uuid4())

        layer2_ok = solver2.solve(self.tls)
        if not layer2_ok:
            print("[px] ✗ Layer 2 failed")
            return False

        self._layer2_cookie = solver2.px_cookie
        print("[px] ✓ Both layers solved!")
        self._solved = True

        return True

    def get_headers(self) -> dict:
        """Get HTTP headers for Walmart requests with PX auth."""
        headers = self._get_base_headers()

        if self._layer1_cookie:
            headers["X-Px-Authorization"] = f"3:{self._layer1_cookie}"
        if self._layer2_cookie:
            headers["X-Px-Wall"] = f"3:{self._layer2_cookie}"

        headers["X-Px-Vid"] = self._vid
        headers["X-Px-Uuid"] = self._uuid
        return headers

    def get_cookies(self) -> dict:
        """Get cookies dict to set on a session."""
        cookies = {}
        if self._layer1_cookie:
            cookies["_px3"] = self._layer1_cookie
        if self._layer2_cookie:
            cookies["_px3"] = self._layer2_cookie  # Same cookie name, last write wins
        cookies["_pxvid"] = self._vid
        return cookies

    def is_solved(self) -> bool:
        return self._solved

    def _get_base_headers(self) -> dict:
        """Standard browser headers for Walmart."""
        return {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/127.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": "https://www.walmart.com/",
        }
