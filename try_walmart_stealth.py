"""Try Walmart with Playwright + stealth — more sophisticated bypass."""
import json, sys, asyncio
from playwright.async_api import async_playwright

BYPASS_JS = """
// Override the webdriver property
Object.defineProperty(navigator, 'webdriver', { get: () => false });
// Override permissions
const originalQuery = navigator.permissions.query;
navigator.permissions.query = (parameters) => (
  parameters.name === 'notifications' ?
    Promise.resolve({state: 'prompt', onchange: null}) :
    originalQuery(parameters)
);
// Override plugins/plugins array
Object.defineProperty(navigator, 'plugins', {
  get: () => [1, 2, 3, 4, 5],
});
Object.defineProperty(navigator, 'languages', {
  get: () => ['en-US', 'en'],
});
// Override chrome runtime
window.chrome = { runtime: {} };
"""

async def try_walmart_stealth():
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=[
                '--disable-blink-features=AutomationControlled',
                '--no-sandbox',
                '--disable-web-security',
                '--disable-features=IsolateOrigins,site-per-process',
                '--disable-setuid-sandbox',
                '--disable-dev-shm-usage',
            ]
        )
        
        ctx = await browser.new_context(
            user_agent=(
                'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
                'AppleWebKit/605.1.15 (KHTML, like Gecko) '
                'Version/17.0 Safari/605.1.15'
            ),
            viewport={'width': 1280, 'height': 800},
            locale='en-US',
            timezone_id='America/New_York',
            # Don't set any extra HTTP headers that automated tools add
            extra_http_headers={},
        )
        
        page = await ctx.new_page()
        
        # Inject stealth scripts before navigation
        await page.add_init_script(BYPASS_JS)
        
        print("Navigating to Walmart search...")
        
        try:
            # Navigate and wait for either products to load or challenge to complete
            await page.goto(
                'https://www.walmart.com/search?q=milk',
                wait_until='domcontentloaded',
                timeout=30000
            )
            
            # Wait a bit
            await page.wait_for_timeout(3000)
            
            title = await page.title()
            print(f"Title: {title}")
            
            body = await page.content()
            has_products = '__NEXT_DATA__' in body
            has_blocked = 'Robot or human' in body
            print(f"__NEXT_DATA__: {has_products}, Blocked: {has_blocked}")
            
            # If blocked, try waiting for the challenge to auto-resolve 
            # (some PerimeterX deployments pass automatically after a few seconds)
            if has_blocked and not has_products:
                print("PerimeterX detected. Waiting up to 30s for auto-resolve...")
                for i in range(6):
                    await page.wait_for_timeout(5000)
                    body = await page.content()
                    has_products = '__NEXT_DATA__' in body
                    has_blocked = 'Robot or human' in body
                    print(f"  After { (i+1)*5 }s: __NEXT_DATA__={has_products}, Blocked={has_blocked}")
                    if has_products:
                        break
            
            # Get all cookies
            cookies = await ctx.cookies()
            cookie_dict = {c['name']: c['value'] for c in cookies}
            print(f"\nCookies: {list(cookie_dict.keys())}")
            
            result = {
                'title': title,
                'has_products': has_products,
                'has_blocked': has_blocked,
                'cookies': cookie_dict,
            }
            
            # Extract products if available
            if has_products:
                script = await page.query_selector('script#__NEXT_DATA__')
                if script:
                    text = await script.inner_text()
                    data = json.loads(text)
                    items = (data.get('props',{})
                            .get('pageProps',{})
                            .get('initialData',{})
                            .get('searchResult',{})
                            .get('itemStacks',[]))
                    products = []
                    for stack in items:
                        for item in stack.get('items',[])[:5]:
                            products.append({
                                'name': item.get('name',''),
                                'price': item.get('price',''),
                            })
                    result['products'] = products
                    print(f"\nProducts found: {len(products)}")
                    for p in products:
                        print(f"  ${p['price']} - {p['name'][:50]}")
            
        except Exception as e:
            print(f"Error: {e}")
            result = {'error': str(e)}
        
        await browser.close()
        return result

result = asyncio.run(try_walmart_stealth())
print("\n=== FINAL ===")
print(json.dumps({k: v for k, v in result.items() if k != 'cookies'}, indent=2, default=str))
# Print just cookie names
if 'cookies' in result:
    print(f"Cookie count: {len(result['cookies'])}")
