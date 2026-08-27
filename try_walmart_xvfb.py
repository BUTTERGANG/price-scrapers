"""Try Walmart with Playwright + Xvfb (virtual display, non-headless mode)."""
import json, asyncio, os
from playwright.async_api import async_playwright

BYPASS_JS = """
Object.defineProperty(navigator, 'webdriver', { get: () => false });
Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
window.chrome = { runtime: {} };
"""

async def try_walmart_xvfb():
    async with async_playwright() as p:
        # Launch in non-headless mode (will render on Xvfb)
        browser = await p.chromium.launch(
            headless=False,  # Xvfb provides the display
            args=[
                '--no-sandbox',
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
        )
        
        page = await ctx.new_page()
        await page.add_init_script(BYPASS_JS)
        
        print("Navigating to Walmart (non-headless via Xvfb)...")
        
        try:
            await page.goto('https://www.walmart.com/search?q=milk', wait_until='domcontentloaded', timeout=30000)
            await page.wait_for_timeout(3000)
            
            title = await page.title()
            body = await page.content()
            has_products = '__NEXT_DATA__' in body
            has_blocked = 'Robot or human' in body
            print(f"Initial: Title='{title}', Products={has_products}, Blocked={has_blocked}")
            
            if has_blocked and not has_products:
                print("Blocked. Waiting 30s for PerimeterX to resolve...")
                for i in range(6):
                    await page.wait_for_timeout(5000)
                    body = await page.content()
                    has_products = '__NEXT_DATA__' in body
                    has_blocked = 'Robot or human' in body
                    print(f"  +{(i+1)*5}s: Products={has_products}, Blocked={has_blocked}")
                    if has_products:
                        break
            
            cookies = await ctx.cookies()
            cookie_dict = {c['name']: c['value'] for c in cookies}
            
            result = {
                'title': title,
                'has_products': has_products,
                'has_blocked': has_blocked,
                'cookie_names': list(cookie_dict.keys()),
                'has_px_valid': '_px2' in cookie_dict or '_pxff' in cookie_dict,
            }
            
            if has_products:
                script = await page.query_selector('script#__NEXT_DATA__')
                if script:
                    text = await script.inner_text()
                    data = json.loads(text)
                    items = (data.get('props',{}).get('pageProps',{}).get('initialData',{}).get('searchResult',{}).get('itemStacks',[]))
                    products = []
                    for stack in items:
                        for item in stack.get('items',[])[:5]:
                            products.append({'name': item.get('name',''), 'price': item.get('price','')})
                    result['products'] = products
                    print(f"\nProducts: {len(products)}")
                    for p in products[:3]:
                        print(f"  ${p['price']} - {p['name'][:50]}")
            
        except Exception as e:
            print(f"Error: {e}")
            result = {'error': str(e)}
        
        await browser.close()
        return result

result = asyncio.run(try_walmart_xvfb())
print(f"\n=== RESULT ===")
print(json.dumps(result, indent=2, default=str))
