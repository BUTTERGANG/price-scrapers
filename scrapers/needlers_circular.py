"""Needler's Fresh Market weekly circular scraper — vision-based image parsing.

==============================================================================
ARCHITECTURE OVERVIEW
==============================================================================

Needlers' weekly ad at www2.needlersfreshmarket.com is a scanned flyer served
as JPEG images. There is no structured data for unauthenticated users.
This scraper:

  1. Fetches the WeeklyAd store page to extract the current circular code
     and number of pages from the embedded image URLs.

  2. Downloads each flyer page JPEG from core-graphics.grocerywebsite.com.

  3. Sends each image to Claude (claude-haiku-4-5) with a structured prompt
     requesting a JSON list of deals. Claude reads prices, product names,
     deal types (multi-unit, BOGO, percent-off) directly from the image.

  4. Returns normalized price records compatible with the rest of the project.

CIRCULAR CODE FORMAT
----------------------------------------------------------------------
  260319_FE_NFM  →  date=2026-03-19, store_code=FE_NFM
  Image URL pattern:
    https://core-graphics.grocerywebsite.com/G_WeeklyAd_core/FIMG/
      {code}/{code}_Base_1_Page_{N}_Zone_3.jpg

CLAUDE PROMPT
----------------------------------------------------------------------
Sends each image as base64 with a system prompt asking for JSON output:
  [{"name": "...", "price": 0.0, "unit": "lb|ea|oz|null",
    "deal_text": "2/$5|BOGO|10 for $10|null", "size": "...", "brand": "..."}]

REQUIREMENTS
----------------------------------------------------------------------
  pip install requests anthropic
  ANTHROPIC_API_KEY must be set in environment.

STORE IDs (Webstop)
----------------------------------------------------------------------
  929  Indianapolis (Lockerbie), 320 N. New Jersey St
"""
import base64
import json
import logging
import os
import re
from typing import Optional

import requests
import anthropic

from .base import BaseScraper

logger = logging.getLogger(__name__)

BASE_URL = "https://www2.needlersfreshmarket.com"
GRAPHICS_URL = "https://core-graphics.grocerywebsite.com/G_WeeklyAd_core/FIMG"
CLAUDE_MODEL = "claude-sonnet-4-6"
MAX_TOKENS = 8192

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

_EXTRACT_PROMPT = """\
This is a page from a grocery store weekly circular.

Extract every distinct sale deal visible on this page.
Return ONLY a JSON array — no explanation, no markdown fences, just the raw JSON.

Each element must have these exact keys:
  "name"      — product name as printed (string)
  "brand"     — brand name if visible, else null
  "size"      — package size if visible (e.g. "16 OZ", "1 LB", "6 PK"), else null
  "price"     — the numeric sale price as a float (e.g. 6.99, 1.0, 5.0)
  "unit"      — selling unit if shown: "lb", "ea", or null
  "deal_text" — the exact deal text from the circular badge/logo, else null

HOW DEAL BADGES WORK ON THIS CIRCULAR:
- Each deal is shown as a circular logo/badge with the deal text printed inside it.
- One badge can apply to a GROUP of products listed near it. In that case, give
  every product in the group the same deal_text from that badge.
- Read the badge text EXACTLY and carefully — "Buy 3 Get 2 Free" and
  "Buy 2 Get 3 Free" are different deals. Do not confuse them.
- A product with its own separate badge uses THAT badge, not a nearby group badge.

PRICING RULES:
- "10 for $10" badge: price=1.0, deal_text="10 for $10".
- "Buy N Get M Free" badges: price=0.0 (no dollar amount), deal_text as printed.
- "2 for $6" badge: price=6.0, deal_text="2 for $6" (do NOT divide the price).
- "2 for $5" badge: price=5.0, deal_text="2 for $5" (do NOT divide).
- "$X.XX/lb" badge: price=X.XX, unit="lb".
- Plain "$X.XX" badge: price=X.XX, unit=null.
- null for any field not visible on the page.
- Omit store headers, addresses, website URLs, and non-product text.
- Include EVERY product you can read that has a deal badge.
"""


class NeedlersCircularScraper(BaseScraper):
    """
    Vision-based scraper for Needler's weekly circular.
    Uses the Claude API to extract deal data from flyer images.

    Requires ANTHROPIC_API_KEY in environment.
    """

    retailer = "needlers_circular"

    def __init__(self, store_id: str, config: dict):
        """
        Args:
            store_id: Webstop store number string, e.g. "929" for Indianapolis.
        """
        super().__init__(store_id, config)
        self.session = requests.Session()
        self.session.headers.update(_HEADERS)
        api_key = (
            config.get("anthropic_api_key")
            or os.environ.get("ANTHROPIC_API_KEY")
            or os.environ.get("ANTHROPIC_AUTH_TOKEN")
        )
        if not api_key:
            raise ValueError(
                "No Anthropic API key found. Set ANTHROPIC_API_KEY or ANTHROPIC_AUTH_TOKEN."
            )
        kwargs: dict = {"api_key": api_key}
        base_url = config.get("anthropic_base_url") or os.environ.get("ANTHROPIC_BASE_URL")
        if base_url:
            kwargs["base_url"] = base_url
        self.claude = anthropic.Anthropic(**kwargs)

    def authenticate(self) -> None:
        """Set the Webstop store cookie by visiting the store page."""
        resp = self.session.get(
            f"{BASE_URL}/WeeklyAd/Store/{self.store_id}/",
            timeout=15,
            allow_redirects=True,
        )
        resp.raise_for_status()
        logger.info(
            f"[needlers_circular] Store cookie set for store {self.store_id}. "
            f"Cookie: {dict(self.session.cookies)}"
        )

    def _get_circular_info(self) -> tuple[str, int]:
        """
        Parse the WeeklyAd store page to extract the circular code and page count.
        Returns (circular_code, num_pages), e.g. ("260319_FE_NFM", 6).
        Raises ValueError if nothing is found.
        """
        resp = self.session.get(
            f"{BASE_URL}/WeeklyAd/Store/{self.store_id}/",
            timeout=15,
        )
        resp.raise_for_status()

        # Image URLs look like: /FIMG/260319_FE_NFM/260319_FE_NFM_Base_1_Page_3_Zone_3.jpg
        pattern = re.compile(
            r"/FIMG/([^/]+)/\1_Base_1_Page_(\d+)_Zone_\d+\.jpg"
        )
        matches = pattern.findall(resp.text)
        if not matches:
            raise ValueError(
                "Could not find circular image URLs in WeeklyAd page. "
                "The circular code or page structure may have changed."
            )

        circular_code = matches[0][0]
        num_pages = max(int(m[1]) for m in matches)
        logger.info(
            f"[needlers_circular] Circular code: {circular_code}, pages: {num_pages}"
        )
        return circular_code, num_pages

    def _download_page(self, circular_code: str, page: int) -> bytes:
        """Download a single flyer page image. Returns raw JPEG bytes."""
        url = (
            f"{GRAPHICS_URL}/{circular_code}/"
            f"{circular_code}_Base_1_Page_{page}_Zone_3.jpg"
        )
        resp = self.session.get(url, timeout=30)
        resp.raise_for_status()
        logger.debug(
            f"[needlers_circular] Downloaded page {page} "
            f"({len(resp.content):,} bytes)"
        )
        return resp.content

    def _extract_deals_from_image(self, image_bytes: bytes, page: int) -> list[dict]:
        """
        Send one flyer page image to Claude and parse the JSON response.
        Returns a list of raw deal dicts.
        """
        image_b64 = base64.standard_b64encode(image_bytes).decode()

        msg = self.claude.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=MAX_TOKENS,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/jpeg",
                                "data": image_b64,
                            },
                        },
                        {"type": "text", "text": _EXTRACT_PROMPT},
                    ],
                }
            ],
        )

        raw_text = msg.content[0].text.strip()

        # Strip any markdown fences if the model adds them
        raw_text = re.sub(r"^```(?:json)?\s*", "", raw_text)
        raw_text = re.sub(r"\s*```$", "", raw_text)
        # Normalize empty strings to null so json.loads gives None
        raw_text = re.sub(r'":\s*""', '": null', raw_text)

        try:
            deals = json.loads(raw_text)
        except json.JSONDecodeError as e:
            logger.error(
                f"[needlers_circular] JSON parse error on page {page}: {e}\n"
                f"Raw response: {raw_text[:300]}"
            )
            return []

        if not isinstance(deals, list):
            logger.warning(
                f"[needlers_circular] Expected list from Claude, got {type(deals)} on page {page}"
            )
            return []

        logger.info(
            f"[needlers_circular] Page {page}: extracted {len(deals)} deals "
            f"(tokens: {msg.usage.input_tokens}in/{msg.usage.output_tokens}out)"
        )
        return deals

    def scrape_circular(self) -> list[dict]:
        """
        Download all circular pages and extract deals via Claude vision.
        Returns a deduplicated list of normalized price records.
        """
        self.authenticate()
        circular_code, num_pages = self._get_circular_info()

        seen: set[str] = set()
        results: list[dict] = []
        all_raw: list[dict] = []

        for page in range(1, num_pages + 1):
            logger.info(
                f"[needlers_circular] Processing page {page}/{num_pages}..."
            )
            try:
                image_bytes = self._download_page(circular_code, page)
            except Exception as e:
                logger.error(f"[needlers_circular] Failed to download page {page}: {e}")
                continue

            deals = self._extract_deals_from_image(image_bytes, page)

            for deal in deals:
                name = (deal.get("name") or "").strip()
                if not name:
                    continue

                raw_price = deal.get("price")
                try:
                    price = float(raw_price) if raw_price is not None else 0.0
                except (TypeError, ValueError):
                    price = 0.0

                deal_text = deal.get("deal_text") or None
                unit = deal.get("unit") or None
                size = deal.get("size") or None
                brand = deal.get("brand") or None

                # Dedup by name+price (same item can appear across pages)
                dedup_key = f"{name.lower()}|{price}"
                if dedup_key in seen:
                    continue
                seen.add(dedup_key)

                raw_item = {
                    "page": page,
                    "circular_code": circular_code,
                    "name": name,
                    "brand": brand,
                    "size": size,
                    "price": price,
                    "unit": unit,
                    "deal_text": deal_text,
                }
                all_raw.append(raw_item)

                # Use name as product_id (no structured IDs in image mode)
                product_id = re.sub(r"\s+", "_", name.lower())

                results.append(
                    self.normalize_price(
                        product_id=product_id,
                        name=name,
                        price=price,
                        unit=unit,
                        url=f"{BASE_URL}/WeeklyAd/Store/{self.store_id}/",
                        extra={
                            "deal_text": deal_text,
                            "brand": brand,
                            "size": size,
                            "page": page,
                            "circular_code": circular_code,
                        },
                    )
                )

        self.save_raw(all_raw, f"circular_{circular_code}")
        logger.info(
            f"[needlers_circular] Done: {len(results)} unique deals from "
            f"{num_pages} pages."
        )
        return results

    def search_products(self, query: str) -> list[dict]:
        """Search the current circular by name."""
        query_lower = query.lower()
        return [
            r for r in self.scrape_circular()
            if query_lower in r["name"].lower()
        ]

    def get_product_price(self, product_id: str) -> Optional[dict]:
        for r in self.scrape_circular():
            if r["product_id"] == product_id:
                return r
        return None
