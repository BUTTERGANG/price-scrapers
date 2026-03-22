# Grocery Price Scrapers

Automated price collection for grocery retailers near **Broad Ripple, Indianapolis (ZIP 46220)**. Prices are stored in a SQLite database enabling trend tracking, sale detection, and cross-retailer comparison.

---

## Covered Stores

| Retailer | Store ID | Address | Status | Method |
|---|---|---|---|---|
| Kroger | `01400441` | 2629 E 65th St, Indianapolis 46220 | **Working** | Official public OAuth2 API |
| Kroger Weekly Ad | `02100959` / `02100998` | — | **Working** | DACS public API (no credentials) |
| Walmart | `2787` | 7325 N Keystone Ave, Indianapolis 46240 | **Working** | `curl_cffi` (safari17_0) + `__NEXT_DATA__` HTML parsing |
| Fresh Thyme | `rsid=208` | 6301 N College Ave, Indianapolis 46220 | **Working** | HTML parsing (search) + Flipp REST API (circular) |
| Meijer | `290` | 5550 N Keystone Ave, Indianapolis 46220 | **Working** | `curl_cffi` + AEM JSON API + Flipp REST API (circular) |
| Costco | `346` | 6110 E 86th St, Indianapolis 46250 | **Working** | Playwright stealth → intercept `search.costco.com` ⚠️ online prices only |
| Target | `2391` | Indianapolis area | **Working** | Plain `requests` + `api.target.com` weekly ads API |
| The Fresh Market | `56` / `247` | Carmel, IN (both) | **Working** | `curl_cffi` + `__NEXT_DATA__` JSON parsing |
| Aldi | `444-086` | 1440 E. 86th St, Indianapolis 46240 | **Working** | Plain `requests` + Flipp REST API |
| Whole Foods | `10378` | "Eighty-Sixth St.", Indianapolis | **Working** | `curl_cffi` + `__NEXT_DATA__` JSON (Amazon Next.js SSR) |
| Harvest Market | `17` | 2140 E 116th St, Carmel, IN 46032 | **Working** | Plain `requests` + Webstop SSR HTML (department pages) |
| Giant Eagle | `6550` | 11505 N Illinois St, Carmel IN 46032 | **Working** | `curl_cffi` + GraphQL API (`core.shop.gianteagle.com`) |
| GFS Store | `1905` | 9540 Masters Rd, Indianapolis, IN 46250 | **Working** | Plain `requests` + WordPress SSR HTML (ad tabs + department catalog) |
| Needler's Fresh Market | `1000-6062` | Lockerbie, Indianapolis, IN | **Working** | Plain `requests` + storebyweb.com REST API (product search) |
| Needler's Circular | store `929` | Lockerbie, Indianapolis, IN | **Working** | Vision-based circular parsing via Claude AI (requires `ANTHROPIC_API_KEY`) |

> **The Fresh Market note:** Both Indiana locations (146th St and Rangeline Rd) are in Carmel, IN — a suburb north of Indianapolis. Both share the same national deal board (~27 items/week).
>
> **Harvest Market note:** Niemann Harvest Market is a regional grocer. All locations share a single weekly circular. Store `17` = Carmel, IN (nearest to Broad Ripple).
>
> **GFS Store note:** Gordon Food Service Store is a foodservice/wholesale retailer. Items sold in bulk (cases, 10 lb boxes, gallon jugs). The "Fishers" URL slug maps to a store physically at 9540 Masters Rd, Indianapolis 46250.
>
> **Costco note:** In-warehouse shelf prices are not published online. Costco's API returns online/delivery prices only.

---

## Project Structure

```
PRICE_SCRAPERS/
├── scrapers/
│   ├── base.py               # Abstract base class — shared interface & error handling
│   ├── kroger.py             # Kroger — official OAuth2 API + DACS weekly circular
│   ├── walmart.py            # Walmart — curl_cffi (safari17_0) + __NEXT_DATA__ parsing
│   ├── meijer.py             # Meijer — AEM JSON endpoints + Flipp circular
│   ├── fresh_thyme.py        # Fresh Thyme — server-rendered HTML + Flipp circular
│   ├── costco.py             # Costco — Playwright intercept of search API
│   ├── target.py             # Target — api.target.com weekly ads API
│   ├── fresh_market.py       # The Fresh Market — __NEXT_DATA__ weekly features
│   ├── aldi.py               # Aldi — Flipp REST API
│   ├── whole_foods.py        # Whole Foods — Amazon Next.js SSR, __NEXT_DATA__ parsing
│   ├── harvest_market.py     # Harvest Market — Webstop SSR HTML, department pages
│   ├── gfs.py                # GFS Store — WordPress SSR HTML, ad tabs + department catalog
│   ├── giant_eagle.py        # Giant Eagle — Apollo GraphQL API, cursor pagination
│   ├── needlers.py           # Needler's — storebyweb.com REST API (product search)
│   └── needlers_circular.py  # Needler's — vision-based circular parsing via Claude AI
├── utils/
│   ├── http.py               # TLS-fingerprint-safe sessions, retry/backoff, jitter
│   ├── browser.py            # Playwright stealth browser for Costco
│   ├── db.py                 # SQLite price history database
│   ├── unit_price.py         # Unit price normalization ($/oz, $/lb, $/fl_oz, $/ct)
│   ├── validate.py           # Data quality validation (before DB insert)
│   └── compare.py            # In-memory price comparison helpers (current run)
├── scripts/
│   ├── find_stores.py        # Find Kroger/Meijer store IDs near a ZIP
│   └── query_prices.py       # Query the SQLite price database from the CLI
├── config/
│   ├── stores.json           # Store IDs and addresses
│   └── items.json            # Search queries (grocery items to track)
├── data/
│   ├── raw/                  # Raw API/HTML responses, one subdir per retailer
│   └── prices.db             # SQLite price history database
├── main.py                   # CLI entry point
├── runner.py                 # Scraper orchestration (serial + parallel)
├── telegram_bot.py           # Telegram bot interface (/price, /deals, /compare, /ask)
├── smoke_test.py             # Quick live smoke test
├── requirements.txt
└── .env.example
```

---

## Setup

### 1. Install dependencies

```bash
pip install -r requirements.txt
playwright install chromium   # only needed for Costco
```

**requirements.txt:**
```
curl-cffi>=0.7.0           # TLS fingerprint impersonation — Walmart, Meijer, The Fresh Market, Whole Foods, Giant Eagle
parsel>=1.9.0              # HTML parsing — Fresh Thyme, GFS, Harvest Market
playwright>=1.43.0         # Headless browser — Costco only
playwright-stealth>=1.0.6  # Removes headless browser detection signals
requests>=2.31.0           # HTTP — Kroger, Fresh Thyme (Flipp), Meijer (Flipp), Target, Aldi
python-dotenv>=1.0.0       # Load .env for API keys
loguru>=0.7.0              # Structured logging
python-telegram-bot>=20.0  # Telegram bot interface
anthropic>=0.20.0          # Claude API — /ask command in Telegram bot + Needlers circular vision scraper
```

### 2. Configure environment variables

Copy `.env.example` to `.env`:

```bash
cp .env.example .env
```

```ini
# Kroger Developer API — register free at https://developer.kroger.com
KROGER_CLIENT_ID=your_client_id_here
KROGER_CLIENT_SECRET=your_client_secret_here

# Telegram bot — get token from @BotFather
TELEGRAM_BOT_TOKEN=your_telegram_bot_token_here

# Anthropic Claude API — enables /ask command in Telegram bot and Needlers circular vision scraper
ANTHROPIC_API_KEY=your_anthropic_api_key_here
```

All other scrapers require no API keys — credentials are public (Target, Flipp-based circulars) or embedded in page source (The Fresh Market, Giant Eagle).

### 3. Confirm store IDs

Store IDs are pre-configured in `config/stores.json`. To verify or find new ones programmatically:

```python
# Kroger — find locationId near a ZIP
from scrapers import KrogerScraper
stores = KrogerScraper.find_stores("46220", config)

# Meijer
from scrapers import MeijerScraper
stores = MeijerScraper.find_store_id(config={})

# Target
from scrapers import TargetScraper
stores = TargetScraper.find_store_id(zip_code="46220")

# Aldi
from scrapers.aldi import AldiScraper
stores = AldiScraper.find_store_id(zip_code="46220")

# Harvest Market
from scrapers.harvest_market import HarvestMarketScraper
stores = HarvestMarketScraper.find_store_id(zip_code="46032")

# Giant Eagle
from scrapers.giant_eagle import GiantEagleScraper
stores = GiantEagleScraper.find_store(zip_code="46032")
```

### 4. Run

```bash
# Run all retailers (4 parallel workers by default)
python main.py

# Run specific retailers
python main.py aldi target gfs walmart

# Serial execution (safer for debugging)
python main.py --workers 1

# List all available retailer names
python main.py --list
```

---

## Scripts

### Find/confirm store IDs

```bash
python scripts/find_stores.py
python scripts/find_stores.py --zip 46220 --radius 15
```

### Query saved prices and deals

```bash
python scripts/query_prices.py milk
python scripts/query_prices.py "chicken breast" --deals
python scripts/query_prices.py --deals --min-savings 15
python scripts/query_prices.py --runs
```

### Telegram bot

```bash
python telegram_bot.py
```

Bot commands: `/start`, `/stores`, `/scrape [store...]`, `/price <item>`, `/deals [min_pct]`, `/compare <item>`, `/ask <question>`

---

## Architecture

### BaseScraper (`scrapers/base.py`)

All retailer scrapers inherit from `BaseScraper` and implement three methods:

```python
def authenticate(self) -> None: ...                              # tokens / session warmup
def search_products(self, query: str) -> list[dict]: ...         # keyword search
def get_product_price(self, product_id: str) -> Optional[dict]: ...  # single item lookup
```

Most scrapers also implement `scrape_circular()` to pull the current weekly ad independently of the product search system.

`scrape_items(queries)` is the main orchestration method — calls `authenticate()` once, then loops with jittered delays. Error handling is asymmetric:

- **Rate-limit (429/503):** re-raised immediately — continuing worsens a ban
- **Parse/network errors:** logged, skipped, recorded in DB — one bad page doesn't abort the run
- **3+ consecutive failures:** circuit breaker trips → raises `CircuitOpenError`

### Normalized Price Record

Every scraper produces the same dict schema via `normalize_price()`:

```python
{
    "retailer":              "kroger",
    "store_id":              "01400441",
    "product_id":            "0001111060921",
    "upc":                   "0001111060921",   # barcode if available; else None
    "name":                  "Kroger Whole Milk, 1 Gallon",
    "brand":                 "Kroger",          # None if unknown
    "department":            "Dairy",           # None if unknown
    "price":                 3.99,              # shelf/regular price
    "sale_price":            2.99,              # current sale price if on sale; else None
    "unit":                  "1 gal",           # size/unit string from retailer
    "unit_price":            3.99,              # price per unit (retailer-provided)
    "unit_price_normalized": 0.0312,            # computed $/fl_oz
    "unit_canonical":        "per_fl_oz",       # normalized unit key
    "url":                   "https://www.kroger.com/p/...",
    "scraped_at":            "2026-03-21T14:23:01.123456",
    # retailer-specific extras in extra_json: deal_text, circle_offer, snap_eligible, etc.
}
```

**UPC coverage** — scrapers that populate the `upc` field:

| Retailer | UPC source |
|---|---|
| Kroger | `productId` — 13-digit UPC-A |
| Fresh Thyme | URL slug: `-id-{barcode}` |
| Giant Eagle | `sku` field |
| Meijer | `code` field |
| Needler's | `scanCode` field |

**Brand/department coverage** — scrapers that populate `brand` and/or `department`:

| Retailer | `brand` | `department` |
|---|---|---|
| Kroger | ✓ | — |
| Walmart | ✓ | — |
| Meijer | ✓ | — |
| Giant Eagle | ✓ | — |
| Needler's | ✓ | ✓ |
| Whole Foods | ✓ | — |
| GFS | ✓ | ✓ |
| Target | ✓ | — |
| Harvest Market | — | ✓ |
| The Fresh Market | — | ✓ |

---

## Retailer Details

### Kroger

- **Method:** Official public REST API at `api.kroger.com/v1`
- **Auth:** OAuth2 Client Credentials (`product.compact` scope). Token auto-refreshes 60s before expiry.
- **Rate limit:** 10,000 calls/day. Pagination multiplies calls (~90 calls per full run). Counter in `KrogerScraper._calls_today` warns at 90%.
- **Key endpoints:**
  - `POST /connect/oauth2/token` — access token
  - `GET /locations?filter.zipCode.near=46220` — find `locationId`
  - `GET /products?filter.term={q}&filter.locationId={id}&filter.limit=50&filter.start={n}` — paginated search
- **Price fields:** `items[].price.regular`, `items[].price.promo` (null if no sale), `items[].price.expirationDate`
- **Register:** https://developer.kroger.com

#### Kroger Weekly Ad (DACS — no OAuth required)

The weekly circular is available via Kroger's DACS (Digital Ads & Coupons System) at `przone.net`. **No credentials needed** — uses a public `XApiKey`.

- **DACS base URL:** `https://oms-kroger-webapp-da-classic-api-prod.przone.net`
- **XApiKey:** `bqwwosbzrzcvffztxzyczieljzsahmkp`
- **Weekly ad store IDs:** `02100959` and `02100998` (different from the product API `locationId`)
  - Stored in `config/stores.json` under `kroger.weekly_ad_store_ids`
  - Format: 3-digit division code + 5-digit store number
- **Flow:**
  1. `GET https://api.kroger.com/digitalads/v1/circulars?...` → find circular with `circularType == "print"`, extract `eventId`
  2. `GET /api/dacs/{adId}?location={locationId}` → page list
  3. `GET /api/dacs/{adId}/pages/{eventPageId}?location={locationId}` → page contents with `mapConfig` JSON per item
  4. `GET /api/dacs/{adId}/offers/{offerVersionProductGroupId}?location={locationId}` → offer detail
- **~152 items/week** per store; deduplicated across pages by `offerVersionProductGroupId`
- **`pricingText` examples:** `"$3.99  With Card"`, `"$2.49  LB  With Card"`, `"BUY 1 GET 1 Of Equal or Lesser Value FREE  With Card"`

### Walmart

- **Method:** `__NEXT_DATA__` JSON blob embedded in every search/product page
- **TLS fingerprinting (2026):** Chrome TLS profiles are now fully blocked by Walmart's PerimeterX stack. `curl_cffi` must use `safari17_0` or `safari16_5` impersonation. `chrome*` profiles return a "Robot or human?" challenge page with no product data.
- **Session warmup:** Hits homepage first to receive Akamai validation cookies (`bm_sz`, `_abck`)
- **Store pricing:** Set via `assortment_store_id` cookie
- **Price schema (2026 changes):**
  - `priceInfo.currentPrice` is now often `None` — actual price is top-level `item["price"]` (float)
  - `priceInfo.unitPrice` changed from `{unitString, price}` dict to display string (e.g. `"5.4 ¢/fl oz"`)
  - `priceInfo.wasPrice` changed from dict to dollar string (e.g. `"$22.99"`) — indicates item is on sale; `wasPrice` = regular price, `item["price"]` = sale price
- **Store ID:** Find at walmart.com store finder → URL contains `storeId=XXXX`

### Meijer

- **Product search:** AEM JSON endpoint — no API key, just `Referer: https://www.meijer.com/` header
  - `GET /bin/meijer/product/search.json?query={q}&storeId=290&pageSize=24&currentPage=0`
  - `curl_cffi` required — Akamai blocks plain `requests`
- **Weekly circular:** Direct Flipp REST API (no Playwright)
  - Base: `https://api.flipp.com/flyerkit/v4.0/`
  - Token: `81771d0c149847a93bc30b8e5b65bffb` (extracted from clientlib-react JS bundle)
  - `GET /publications/meijer?access_token=TOKEN&locale=en-US&store_code=290`
    - Publications: "Weekly Ad" (~7 days), "Pullout GM" (GM supplement), "Super Sale" (flash 1–2 days)
  - `GET /publication/{pub_id}/products?display_type=all&locale=en-US&access_token=TOKEN`
    - ~330 items; filter `item_type==1` (products), skip `item_type==5` (section headers)
    - Fields: `price_text`, `pre_price_text` ("sale", "3/"), `post_price_text` ("lb", "ea"), `sale_story`
- **mPerks:** Personalized prices require a logged-in session. Base prices available without login.

### Fresh Thyme

- **Platform:** `ww2.freshthyme.com` — Fresh Thyme's own platform (mi9cloud), not Instacart
- **Product search:** Server-side rendered HTML — plain `requests` + `parsel`, no JS needed
  - `GET https://ww2.freshthyme.com/sm/planning/rsid/208/results?q={query}`
  - Product IDs from URL slug: `-id-{barcode}` at end of href (barcode = UPC)
  - CSS classes are styled-components hashes — use `[class*='ProductCardName']` etc.
- **Weekly circular:** Direct Flipp REST API (no Playwright)
  - Base: `https://dam.flippenterprise.net/flyerkit`
  - Token: `69a8b46e89fdcd76ead41634ec35ac69` (from `__PRELOADED_STATE__` JSON in page)
  - `GET /publications/freshthymemarket?store_code=208&languages[]=en&locale=en&access_token=TOKEN`
    - Publications: "Weekly Ad" (~7 days), "Monthly Ad" (~30 days) — use Weekly Ad
  - `GET /publication/{pub_id}/products?display_type=all&locale=en&access_token=TOKEN`
    - Filter `item_type==1`; BOGO items: `sale_story="BUY ONE GET ONE FREE"`, `price_text=""`
- **Store rsid:** `208` = Broad Ripple, 6301 N College Ave

### Costco

- **⚠️ Pricing caveat:** In-warehouse shelf prices are not published online. API returns online/delivery prices only.
- **Search API:** `https://search.costco.com/api/apps/www_costco_com/query/www_costco_com_search`
  - Params: `q=milk&whloc=346-wh&rows=24&start=0&locale=en-US&userLocation=IN`
  - Price fields: `item_location_pricing_listPrice`, `item_location_pricing_salePrice`
  - Items with `item_product_price_in_cart_only=1` have no visible price
- **Anti-bot:** Akamai — direct requests return 401. Requires Playwright stealth session.
- **Warehouse #346:** Castleton, 6110 E 86th St, Indianapolis 46250

### Target

- **Method:** Proprietary `api.target.com` weekly ads API — no Playwright, no auth, no bot detection
- **API keys** (public, embedded in `window.__CONFIG__` on the weekly ad page):
  - Weekly Ad key: `9ba599525edd204c560a2182ae1cbfaa3eeddca5`
  - Redsky key: `9f36aeafbe60771e321a7cc95a78140772ab3e96`
- **Step 1 — current promotion:**
  - `GET https://api.target.com/weekly_ads/v1/store_promotions?key=KEY&store_id=2391`
  - `promotion_id` format: `"2391-YYYYMMDD"` (date = ad start Sunday)
- **Step 2 — hotspot deals:**
  - `GET https://api.target.com/weekly_ads/v1/promotions/{promotion_id}?key=KEY`
  - Returns ~176 deal hotspots: `title`, `price`, `reg_price`, `tcin`, `offer_id`, `listing_id`, `circle_offer`
- **Step 3 — per-SKU prices (optional):**
  - `GET https://redsky.target.com/redsky_aggregations/v1/weeklyad/get_marketing_id_search_v1`
  - Use `fetch_sku_details=True` in `scrape_circular()` — adds ~176 extra API calls
- **Price formats:** `"$14.99"`, `"$3.99/lb"`, `"5/$25"`, `"2 for $5"`, `"BOGO 50% off"`, `"10% off"`
- **Target Circle:** Many deals require Circle membership (free). `circle_offer=True` in extra fields.

### Aldi

- **Platform:** Nuxt.js + Spryker e-commerce backend; weekly circular via Flipp
- **No Playwright, no auth, no bot detection** — plain `requests` works
- **Store ID format:** `"444-NNN"` (Spryker service-point IDs) — NOT the URL slug (`f252`)
- **Store locator:**
  - `GET https://api.aldi.us/v2/service-points?addressZipcode=46220&serviceType=pickup&limit=10&includeNearbyServicePoints=true`
  - Nearby stores:
    | Store Code | Address | Distance from Broad Ripple |
    |---|---|---|
    | `444-075` | 5235 N. Keystone Ave, Indianapolis 46220 | 3.7 mi |
    | `444-088` | 5151 E. 82nd St, Indianapolis 46250 | 1.9 mi |
    | `444-086` | 1440 E. 86th St, Indianapolis 46240 | 4.4 mi (configured) |
- **Weekly circular:** Flipp REST API
  - Token: `29d9bfdcf546dc601c10c64ed1e932f5` (from Nuxt JS bundle, `LeafletSnippet` component)
  - `GET /publications/aldi?store_code=444-086&languages[]=en&locale=en&access_token=TOKEN`
  - `GET /publication/{pub_id}/products?display_type=all&locale=en&access_token=TOKEN`
    - ~109 items per week; nearly all have a numeric `price_text`
    - Extra fields: `pre_price_text` (`"PRICE DROPS"`), `post_price_text` (unit), `categories`, `description` (size), `original_price`

### The Fresh Market

- **Platform:** Next.js + Contentful CMS (SSG/ISR) — all deal data in `__NEXT_DATA__` on page load
- **No separate API, no Playwright, no auth needed** — `curl_cffi` used for safety
- **Fetch:** `GET https://www.thefreshmarket.com/features/weekly-features`
- **Parse:** `<script id="__NEXT_DATA__">` → `props.pageProps.weeklySpecialsContent`
  - Dict of boards keyed by name (e.g. `weekly-specials-board-national`)
  - Each board: `applicableStoresCollection.items` + `specialItemsCollection.items`
- **Deal fields:** `specialItemName`, `specialMarketingPrice` (`"$3.99 lb"`, `"3/$5"`, `"Buy 1 Get 1 50% Off"`), `specialMarketingSavings`, `product.sku`, `product.description`, `product.department`
- **Indiana stores** (all on national board, same ~27 deals/week):
  | Store # | Address | Notes |
  |---|---|---|
  | `56` | 2490 E 146th St, Carmel IN 46033 | "146th" location |
  | `247` | 1392 S Rangeline Rd, Carmel IN 46032 | "Rangeline" location |
  | `92` | 5415 N College Ave, Indianapolis IN 46220 | Broad Ripple |

### Harvest Market

- **Platform:** Webstop (`www2.goharvestmarket.com` / `www3.goharvestmarket.com`), retailer ID `3328`
- **No Playwright, no auth, no bot detection** — plain `requests` works
- **Step 1 — set store (authenticate):**
  - `GET https://www3.goharvestmarket.com/retailers/3328/stores/{store_id}/choose_store?filter=circulars&url=.../circulars/`
  - Sets session cookies `3328_store_id` and `3328_store_number`; redirects to current circular URL
- **Step 2 — fetch 9 department pages:**
  - `GET https://www2.goharvestmarket.com/circulars/department/{dept}/`
  - Departments: `Bakery`, `Beer_and_Wine`, `Dairy`, `Deli`, `Fresh_Meat`, `Frozen`, `Grocery`, `Produce`, `Seafood`
- **Item fields:** `.circular-item-title`, `.circular-item-description`, `.price-prefix`, `.price-dollars`, `.price-cents`, `.price-suffix`
- **~76 items/week** across all 9 departments; one circular shared across all Harvest Market locations
- **Store ID `17`** = 2140 E 116th St, Carmel, IN 46032

### Whole Foods

- **Platform:** Amazon-owned Next.js SSP — all promotions in `__NEXT_DATA__` on first page load
- **No Playwright, no auth** — `curl_cffi` used for Amazon CDN safety
- **Fetch:** `GET https://www.wholefoodsmarket.com/sales-flyer?store-id=10378`
- **Parse:** `<script id="__NEXT_DATA__">` → `props.pageProps.promotions` (~59 items/week)
- **Promotion fields:**
  | Field | Example | Notes |
  |---|---|---|
  | `productName` | `"Strawberries, 16 oz"` | Name + size combined |
  | `originBrandName` | `"Organic"`, `"365 by WFM"` | Brand/origin label |
  | `regularPrice` | `"$4.99"`, `"$3.49/lb"` | Shelf price string |
  | `salePrice` | `"$3.66 ea"`, `"11% off"` | Dollar amount or deal text |
  | `primePrice` | `"$3.99 ea"`, `"20% off"`, `"Buy 1, Get 1 Free"` | Amazon Prime exclusive |
  | `itemType` | `"NSF"` or `"PMD"` | NSF = sale; PMD = Prime-exclusive deal |
  | `asinsList` | `["B07NRSXJH6"]` | Amazon ASINs |
- **Prices are national** — identical across all WFM stores for a given week
- **Store ID `10378`** = "Eighty-Sixth St.", Indianapolis

### Giant Eagle

- **Platform:** React SPA + Apollo GraphQL (Hatched Labs). Static S3/CloudFront shell.
- **GraphQL endpoint:** `POST https://core.shop.gianteagle.com/api/v2`
- **No auth required** — public queries work without login. `curl_cffi` used for TLS safety.
- **Required headers:** `X-HL-APP: grocery`, `X-HL-CLIENT: web`, `X-HL-REFERRER: https://www.gianteagle.com/`, `content-type: application/json;charset=utf-8`
- **Store identifiers:**
  - `storeCode` — numeric string (e.g. `"6550"`), used in `GetProducts` queries
  - `storeSlug` — URL slug (e.g. `"carmel-bridges"`), used in `CircularsQuery`
- **Circular flow:**
  1. `CircularsQuery($storeSlug)` → current circular `id`, `displayDates`, `pdfUrl`
  2. `GetProducts(filters: {circular: true}, store: {storeCode: "6550"})` → ~178 sale items, cursor-paginated (24/page)
- **Product fields:** `name`, `brand`, `sku` (UPC), `price` (plain numeric string e.g. `"5.97"`), `comparedPrice`, `displayPricePerUnit` (e.g. `"$2.49/lb"`, `"12¢/oz"`), `rewardPromos[]`
- **`rewardPromos` fields:** `name`, `rewardType` (`"BOGO"`, `"PCT_OFF"`, `"FIXED_OFF"`), `buyQuantity`, `getQuantity`, `rewardAmount`

### GFS Store

- **Platform:** WordPress custom theme (`gfsstore.com`). Fully SSR HTML. No API keys, no auth, no bot detection.
- **No Playwright, no `curl_cffi`** — plain `requests` + `parsel`
- **Authentication (store selection required):**
  - All ad pages redirect to `/locations/?no-store-selected=true` until a store cookie is set
  - `authenticate()` hits `GET https://gfsstore.com/en-us/?dsr_id={mp_number}` which sets `wp-MyStore`, `wp-MyStoreID`, and `MyStoreID` session cookies
  - `mp_number = "MP153"` for the Indianapolis/Fishers store (from `data-mp_number` on map markers)
- **Two data sources:**

  **1. Weekly Ad tabs** (sale prices) — `scrape_circular()`
  | Ad Tab | URL | Approx. Items | Validity |
  |---|---|---|---|
  | Weekly Deals | `/en-us/ads/weekly-deals/` | ~35 | ~2 weeks |
  | In-Store Features | `/en-us/ads/in-store-features/` | ~25 | ~6 weeks |

  **2. Department catalog** (regular shelf prices) — `scrape_department()` / `scrape_all_departments()`
  - 12 departments: `Produce`, `Meat+%26+Seafood`, `Deli`, `Dairy`, `Frozen+Foods`, `Pantry`, `International`, `Beverages`, `Disposables`, `Cleaning+Supplies`, `Kitchenware`, `Cooking+Fuels`

- **Product box** (`.product-box`) fields: `data-name`, `data-brand`, `data-department`, `.product-box-price`, `.product-box-per`, `.product-image-overlay` (size badge), `.product-box__sale` (on-sale flag)
- **Store identification:**
  - `store_id = "1905"` — from `var autocomplete = {"store_id": "1905"}` in page JS
  - `mp_number = "MP153"` — required for `authenticate()` store cookie selection
- **Store details:** 9540 Masters Rd, Indianapolis IN 46250 | 317-845-0712 | Mon–Sat 7am–7pm, Sun 9am–6pm

### Needler's Fresh Market

#### Product Search (`scrapers/needlers.py`)

- **Platform:** storebyweb.com REST API (React SPA backend)
- **No auth, no bot detection** — plain `requests`
- **Product search:** `POST /s/{store_id}/api/b/` with `{"pn": 1, "ps": 100, "q": "milk"}`
- **Full catalog:** Same endpoint without `"q"`, paginated — Indianapolis store has ~22,000+ items
- **Price interpretation:** `actualPrice / actualPriceDivider` for multi-unit deals (e.g. 2/$5: price=5.0, divider=2); weight-based items use `weightProfile.abbrv`
- **UPC:** `scanCode` field
- **Store:** `1000-6062` (store number `929`), Lockerbie, Indianapolis IN

#### Weekly Circular — Vision-Based (`scrapers/needlers_circular.py`)

The Needlers weekly ad serves scanned JPEG flyer images. The circular scraper uses Claude AI vision to extract item data.

- **Flow:**
  1. Fetch `https://www2.needlersfreshmarket.com/WeeklyAd/Store/929/` — extract circular code from navigation links
  2. Download JPEG page images from `core-graphics.grocerywebsite.com`
  3. Send each image to **claude-haiku-4-5** with a structured extraction prompt
  4. Claude returns JSON: `[{"name": "...", "price": 0.0, "unit": "lb|ea|oz", "deal_text": "2/$5|BOGO", "size": "...", "brand": "..."}]`
- **Requires:** `ANTHROPIC_API_KEY` environment variable
- **Store:** `929` = Lockerbie, Indianapolis IN

---

## Flipp Weekly Circular System

**Fresh Thyme, Aldi, and Meijer** all use Flipp's SFML system for their weekly circulars:

| Retailer | Flipp Host | Token | Retailer Slug | Store Code |
|---|---|---|---|---|
| Fresh Thyme | `dam.flippenterprise.net/flyerkit` | `69a8b46e89fdcd76ead41634ec35ac69` | `freshthymemarket` | `208` |
| Aldi | `dam.flippenterprise.net/flyerkit` | `29d9bfdcf546dc601c10c64ed1e932f5` | `aldi` | `444-086` |
| Meijer | `api.flipp.com/flyerkit/v4.0` | `81771d0c149847a93bc30b8e5b65bffb` | `meijer` | `290` |

All use the same two-step flow: list publications → fetch items. All filter `item_type==1` for individual products.

---

## Anti-Bot Summary

| Technique | Applied To | Why |
|---|---|---|
| `curl_cffi` Safari TLS impersonation (`safari17_0`) | Walmart | Chrome TLS fingerprints fully blocked by PerimeterX as of early 2026; Safari bypasses it |
| `curl_cffi` Chrome TLS impersonation | Meijer (product search), The Fresh Market, Whole Foods, Giant Eagle | Akamai/Cloudflare/Amazon Varnish checks JA3/JA4 fingerprint; `requests` is blocked |
| `playwright-stealth` | Costco | Removes `navigator.webdriver`, adds chrome runtime/plugins |
| Homepage session warmup | Walmart | Akamai sets validation cookies (`bm_sz`, `_abck`) on first visit |
| `dsr_id` store cookie selection | GFS | All ad pages redirect to store selector unless `wp-MyStore` cookie is set via `/?dsr_id=MP153` |
| `jitter_sleep()` ±40% variance | All scrapers | Fixed-interval requests are a bot signal |
| `sec-ch-ua`, `sec-fetch-*` headers | `curl_cffi` sessions | Absent headers flag non-browser clients |
| `Referer` header required | Meijer | Returns 403 without it |
| Store cookie required | Harvest Market | Store must be selected via `choose_store` before fetching department pages |
| 403 raises immediately (no retry) | All scrapers | Retrying a blocked request makes bans worse |
| Proxy support | `make_curl_session`, `browser.py` | Optional; pass `proxy` in config dict |

---

## Database (`utils/db.py`)

The SQLite database at `data/prices.db` is append-only — every scrape adds new rows for price history tracking.

### Schema

```sql
CREATE TABLE prices (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    retailer              TEXT    NOT NULL,
    store_id              TEXT    NOT NULL,
    product_id            TEXT    NOT NULL,
    upc                   TEXT,               -- barcode (UPC-A or EAN-13); NULL if unavailable
    name                  TEXT    NOT NULL,
    brand                 TEXT,               -- brand name; NULL if unknown
    department            TEXT,               -- department/category; NULL if unknown
    price                 REAL,               -- regular/shelf price
    sale_price            REAL,               -- current sale price; NULL if not on sale
    unit                  TEXT,               -- size/unit string (e.g. "1 gal", "12 oz")
    unit_price            REAL,               -- retailer-provided price per unit
    unit_price_normalized REAL,               -- computed $/oz or $/lb (normalized)
    unit_canonical        TEXT,               -- normalized unit key (e.g. "per_fl_oz")
    url                   TEXT,
    extra_json            TEXT,               -- retailer-specific fields as JSON
    scraped_at            TEXT    NOT NULL    -- ISO 8601 timestamp
);

-- Fast lookup by UPC for cross-retailer price comparison
CREATE INDEX idx_prices_upc        ON prices (upc)        WHERE upc IS NOT NULL;
CREATE INDEX idx_prices_brand      ON prices (brand)      WHERE brand IS NOT NULL;
CREATE INDEX idx_prices_department ON prices (department) WHERE department IS NOT NULL;
CREATE INDEX idx_prices_lookup     ON prices (retailer, product_id, scraped_at);

CREATE TABLE runs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    retailer        TEXT    NOT NULL,
    store_id        TEXT    NOT NULL,
    status          TEXT    NOT NULL DEFAULT 'running',  -- 'running'|'success'|'partial'|'failed'
    queries_total   INTEGER NOT NULL DEFAULT 0,
    queries_ok      INTEGER NOT NULL DEFAULT 0,
    queries_failed  INTEGER NOT NULL DEFAULT 0,
    records_saved   INTEGER NOT NULL DEFAULT 0,
    error           TEXT,
    started_at      TEXT    NOT NULL,
    finished_at     TEXT
);

CREATE TABLE failed_queries (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id      INTEGER NOT NULL REFERENCES runs(id),
    retailer    TEXT    NOT NULL,
    query       TEXT    NOT NULL,
    error_type  TEXT,
    error_msg   TEXT,
    failed_at   TEXT    NOT NULL
);
```

### Key queries

```python
from utils import get_conn, find_active_deals, cheapest_per_retailer, price_history, find_by_upc

conn = get_conn()

# Active sales with at least 15% off (from last 24 hours)
deals = find_active_deals(conn, min_savings_pct=15.0)

# Cheapest milk across all retailers
best = cheapest_per_retailer(conn, "milk")

# Exact cross-retailer match by UPC barcode
matches = find_by_upc(conn, "0001111060921")  # returns cheapest-first per retailer

# Price history for a specific product
history = price_history(conn, retailer="kroger", product_id="0001111060921")
```

---

## Configuration Files

### `config/stores.json`

```json
{
  "location": { "neighborhood": "Broad Ripple", "zip": "46220" },
  "stores": {
    "kroger":       { "store_id": "01400441", "weekly_ad_store_ids": ["02100959", "02100998"], "address": "2629 E 65th St, Indianapolis 46220" },
    "walmart":      { "store_id": "2787",     "address": "7325 N Keystone Ave, Indianapolis 46240" },
    "meijer":       { "store_id": "290",      "address": "5550 N Keystone Ave, Indianapolis 46220" },
    "fresh_thyme":  { "store_id": "208",      "address": "6301 N College Ave, Indianapolis 46220" },
    "costco":       { "store_id": "346",      "address": "6110 E 86th St, Indianapolis 46250" },
    "target":       { "store_id": "2391",     "address": "Indianapolis area" },
    "fresh_market": {
      "store_ids": {
        "146th":     { "store_id": "56",  "address": "2490 E 146th St, Carmel IN 46033" },
        "rangeline": { "store_id": "247", "address": "1392 S Rangeline Rd, Carmel IN 46032" }
      }
    },
    "aldi":           { "store_id": "444-086", "address": "1440 E. 86th St, Indianapolis 46240" },
    "whole_foods":    { "store_id": "10378",   "address": "Eighty-Sixth St., Indianapolis" },
    "harvest_market": { "store_id": "17",      "address": "2140 E 116th St, Carmel, IN 46032" },
    "gfs":            { "store_id": "1905", "mp_number": "MP153", "slug": "fishers", "address": "9540 Masters Rd, Indianapolis, IN 46250" },
    "giant_eagle":    { "store_id": "6550", "store_slug": "carmel-bridges", "address": "11505 N Illinois St, Carmel IN 46032" },
    "needlers":       { "store_id": "1000-6062", "store_number": "929", "address": "Lockerbie, Indianapolis, IN" }
  }
}
```

### `config/items.json`

Search queries run against every retailer that supports product search (Kroger, Walmart, Meijer, Fresh Thyme, Needler's):

```json
{
  "queries": ["milk", "eggs", "bread", "butter", "chicken breast", "orange juice", ...]
}
```

Target, The Fresh Market, Whole Foods, Aldi, Harvest Market, and GFS use circular/flyer mode — their `search_products()` methods filter the current circular rather than querying a live product catalog. Keyword queries are most effective for Kroger, Walmart, Meijer, Fresh Thyme, and Needler's.

---

## Usage Examples

```python
# Kroger — product search (requires OAuth credentials in .env)
from scrapers.kroger import KrogerScraper
scraper = KrogerScraper(store_id="01400441", config={
    "client_id": "...", "client_secret": "..."
})
results = scraper.search_products("milk")

# Kroger — weekly circular (no credentials needed)
scraper = KrogerScraper(store_id="02100959", config={})
circular = scraper.scrape_circular()
circular = scraper.scrape_circular(location_id="02100998")  # second store

# Meijer — weekly circular
from scrapers.meijer import MeijerScraper
scraper = MeijerScraper(store_id="290", config={})
deals = scraper.scrape_circular()            # Weekly Ad (default)
deals = scraper.scrape_circular("Super Sale")  # Flash sale items

# Target — weekly ad
from scrapers.target import TargetScraper
scraper = TargetScraper(store_id="2391", config={})
deals = scraper.scrape_circular()
deals = scraper.scrape_circular(fetch_sku_details=True)  # +176 API calls for per-SKU pricing

# The Fresh Market — weekly features
from scrapers.fresh_market import FreshMarketScraper, STORE_146TH, STORE_RANGELINE
scraper = FreshMarketScraper(store_id=STORE_146TH, config={})
deals = scraper.scrape_circular()   # ~27 deals, same for all Indiana stores

# Aldi — weekly circular
from scrapers.aldi import AldiScraper
scraper = AldiScraper(store_id="444-086", config={})
deals = scraper.scrape_circular()               # current week (~109 items)
deals = scraper.scrape_circular("In Store Ad")  # next week preview

# Whole Foods — weekly sales flyer
from scrapers.whole_foods import WholeFoodsScraper
scraper = WholeFoodsScraper(store_id="10378", config={})
deals = scraper.scrape_circular()  # ~59 promotions; includes NSF (sale) and PMD (Prime) deals

# Harvest Market — weekly circular (~76 items across 9 departments)
from scrapers.harvest_market import HarvestMarketScraper
scraper = HarvestMarketScraper(store_id="17", config={})
deals = scraper.scrape_circular()

# GFS Store — weekly ads + optional full department catalog
from scrapers.gfs import GFSScraper
scraper = GFSScraper(store_id="1905", config={"mp_number": "MP153"})
scraper.authenticate()                 # required — sets store cookie via dsr_id=MP153
deals = scraper.scrape_circular()      # ~59 items from both ad tabs, deduplicated
catalog = scraper.scrape_all_departments()  # full shelf catalog, 12 departments

# Giant Eagle — weekly circular via GraphQL (~178 sale items)
from scrapers.giant_eagle import GiantEagleScraper
scraper = GiantEagleScraper(store_id="6550", config={})
deals = scraper.scrape_circular()
results = scraper.search_products("chicken")   # full catalog search

# Needler's — product search
from scrapers.needlers import NeedlersScraper
scraper = NeedlersScraper(store_id="1000-6062")
results = scraper.search_products("milk")

# Needler's — vision-based weekly circular (requires ANTHROPIC_API_KEY)
from scrapers.needlers_circular import NeedlersCircularScraper
scraper = NeedlersCircularScraper(store_id="929")
deals = scraper.scrape_circular()  # downloads flyer images, extracts with Claude vision
```

---

## Adding a New Retailer

1. Create `scrapers/{retailer}.py` and subclass `BaseScraper`
2. Implement `authenticate()`, `search_products()`, and `get_product_price()`
3. Optionally implement `scrape_circular()` for weekly ad data
4. Use `self.normalize_price(...)` to return consistent records — pass `upc=`, `brand=`, `department=` when available
5. Use `make_curl_session()` from `utils/http.py` if bot protection is present
6. Use `run_intercept()` from `utils/browser.py` if JS rendering is required
7. Add store ID to `config/stores.json`
8. Export the class from `scrapers/__init__.py`
9. Register in `runner.py` `_build_registry()`

---

## Failure Handling

| Failure | Detection | Response |
|---|---|---|
| Rate limited (HTTP 429/503) | `request_with_retry` checks status | Exponential backoff + jitter, up to 4 retries. If still failing, raises and stops the retailer's run immediately. |
| Bot detected (HTTP 403) | `request_with_retry` checks status | Raises immediately, no retry. Log suggests switching to Playwright or a proxy. |
| Silent bot detection (CAPTCHA page) | Empty-result counter in `scrape_items` | After 3 consecutive empty results, logs a warning pointing at `data/raw/` for inspection. |
| Parse/extraction error | Exception in `search_products` | Logged, skipped, recorded in `failed_queries` table. Other queries continue. |
| 3+ consecutive query failures | Circuit breaker in `scrape_items` | Raises `CircuitOpenError` — stops this retailer. Other retailers still run. |
| Network error | `request_with_retry` exception handler | Retries with exponential backoff up to 4×. |
| Disk full / bad permissions | `save_raw` try/except | Non-fatal warning. Raw debug files are optional. |
| Top-level scraper crash | `_run_one()` in `runner.py` | Caught per-retailer. Others continue. Run marked `failed` in DB. |
| Item count drops >50% vs last run | `check_count_drop()` in `utils/validate.py` | Warning logged — possible structural site change. |
| Bad data (zero prices, HTML in names) | `validate_results()` in `utils/validate.py` | Invalid records dropped before DB insert; issues logged as warnings. |

---

## Pending Work

- [ ] Add `TELEGRAM_BOT_TOKEN` and `ANTHROPIC_API_KEY` to `.env.example`
- [ ] Add scheduled scrape runs (cron/launchd or APScheduler inside bot process)
- [ ] Add price alert subscriptions to Telegram bot (`/alert <item> <threshold>`)
- [ ] Confirm Target store #2391 exact address via `TargetScraper.find_store_id()`
- [ ] Meijer `code` field UPC — verify it is actually a standard UPC barcode (vs. an internal SKU)
- [ ] Replit deployment — disable Costco (no Playwright on free tier), wire up env vars

---

## Roadmap: Cross-Retailer Price Research

The scrapers collect prices per retailer, but research questions like *"which store has the cheapest chicken breast this week?"* require linking records across retailers.

### The three matching problems

| Level | Example | Use case |
|---|---|---|
| **Identical** | Tyson 3 lb chicken breast at Kroger vs. Walmart (same UPC) | Direct price comparison |
| **Equivalent** | Kroger-brand vs. Meijer-brand whole milk, 1 gal | "Cheapest option" comparison |
| **Category** | All 2% milk regardless of brand or size | Inflation tracking, market basket |

### Tier 1 — UPC exact matching ✅ Implemented

`upc` is now a first-class column. `find_by_upc(conn, upc)` returns the most recent price per retailer for a given barcode, ordered cheapest first. UPC data is populated by Kroger, Fresh Thyme, Giant Eagle, Needler's, and tentatively Meijer.

**Gap:** Store brands (Kroger brand, Meijer brand, Aldi own-label) have unique UPCs per retailer — they match within a retailer but not across retailers.

### Tier 2 — Structured attribute extraction (~30–40% coverage, medium effort)

Parse product names into structured attributes, then match on specs:

```
"Kroger 2% Reduced Fat Milk, 1 gal"
→ { brand: "Kroger", type: "milk", fat_pct: "2%", size: "1", unit: "gal" }

"Meijer 2% Milk 1 Gallon"
→ { brand: "Meijer", type: "milk", fat_pct: "2%", size: "1", unit: "gal" }
```

Products sharing `(type, size, unit)` are **equivalent**. A single Claude prompt handles 50–100 names at once. Attributes stored in a `product_attributes` table; matched on `(type, size, unit)` with brand intentionally excluded.

### Tier 3 — Embedding similarity for the long tail (~10–15% coverage)

For items that don't match on UPC or attributes (mixed packs, prepared foods, specialty items):

1. Embed product names with a small model (`all-MiniLM-L6-v2` or `text-embedding-3-small`)
2. Store embeddings in a `pgvector` column
3. Top-k nearest neighbors → Claude validates: *same product / equivalent / just similar-sounding*

### Recommended schema addition (for Tier 2+)

```sql
CREATE TABLE product_groups (
    id              BIGSERIAL PRIMARY KEY,
    canonical_name  TEXT    NOT NULL,
    category        TEXT,
    match_type      TEXT    NOT NULL,   -- 'upc_exact' | 'attribute' | 'embedding' | 'manual'
    upc_list        TEXT[],
    attributes      JSONB,             -- { type, size, unit, fat_pct, ... }
    embedding       vector(384),
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

ALTER TABLE prices ADD COLUMN group_id BIGINT REFERENCES product_groups(id);
```

---

## Future Feature Ideas

### 1. Shopping List Optimizer

Given a grocery list, find the optimal store assignment to minimize total cost.

```python
from optimizer import ShoppingListOptimizer
opt = ShoppingListOptimizer(conn)
result = opt.optimize(
    items=["whole milk 1gal", "eggs 12ct", "bread", "chicken breast"],
    max_stores=2,
)
```

Requires cross-retailer product groups (Tier 2+). For single-retailer comparison, `cheapest_per_retailer()` already handles it.

---

### 2. Sale Cycle Detection

Use price history to predict when items go on sale:

```python
{
  "item":           "Tyson Chicken Breast 3 lb",
  "retailer":       "kroger",
  "avg_sale_cycle": "every 3.1 weeks",
  "last_sale_date": "2026-03-08",
  "next_predicted": "2026-03-29",
  "avg_sale_price": "$7.49",
  "avg_regular":    "$10.99"
}
```

Requires 3–4 months of price history. Weekly batch job: `python scripts/detect_sale_cycles.py`.

---

### 3. Market Basket Inflation Tracker

Track a fixed set of staple items weekly for a local grocery inflation index:

```
=== Market Basket — Week of 2026-03-16 ===
Retailer          Basket Cost   vs. Last Week   vs. 3 Months Ago
────────────────  ──────────    ─────────────   ────────────────
Aldi              $28.41        +$0.22 (+0.8%)  +$1.15 (+4.2%)
Kroger            $34.19        -$0.81 (-2.3%)  +$2.41 (+7.6%)
Meijer            $33.82        +$0.44 (+1.3%)  +$3.10 (+10.1%)
Walmart           $29.17        -$0.12 (-0.4%)  +$0.89 (+3.1%)
```

Requires product groups for cross-retailer mapping.

---

### 4. Data Export

```bash
# Export current-week prices as CSV
python scripts/export.py --format csv --since 7d --output data/exports/

# Export full price history as Parquet (pandas-ready)
python scripts/export.py --format parquet --output data/exports/prices.parquet
```

---

### 5. Additional Retailers

| Retailer | Nearest Location | Approach | Priority |
|---|---|---|---|
| **Trader Joe's** | 5130 E 82nd St, Indianapolis 46250 | Static HTML + internal JSON or Instacart API | High |
| **Ruler Foods** | 5716 N Keystone Ave, Indianapolis 46220 | Kroger subsidiary — likely same `api.kroger.com` endpoint with a Ruler `locationId` | High |
| **Dollar General** | Multiple near 46220 | DG API or Instacart | Medium |
| **CVS / Walgreens** | Multiple near 46220 | CVS promotions API; Walgreens weekly ad | Medium |
| **Amazon Fresh** | Delivery only | Amazon product API (requires auth) | Low |

> **Ruler Foods note:** Kroger-owned deep-discount banner. Run `KrogerScraper.find_stores('46220', config)` and look for Ruler in the results — it likely uses the same product endpoint.
