"""Try Walmart via Playwright — attempt PerimeterX challenge solving."""
import json, sys, asyncio
from playwright.async_api import async_playwright

async def try_walmart():
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=[
                '--disable-blink-features=AutomationControlled',
                '--no-sandbox',
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
        )
        
        page = await ctx.new_page()
        
        # Monitor for both success signals and block signals
        result = {'status': 'unknown', 'cookies': [], 'title': '', 'has_products': False}
        
        try:
            print("Navigating to Walmart...")
            resp = await page.goto(
                'https://www.walmart.com/search?q=milk',
                wait_until='domcontentloaded',
                timeout=30000
            )
            print(f"Initial status: {resp.status if resp else 'None'}")
            
            # Wait a bit for JS to execute
            await page.wait_for_timeout(5000)
            
            title = await page.title()
            result['title'] = title
            print(f"Title: {title}")
            
            # Check page content
            body = await page.content()
            has_blocked = 'Robot or human' in body
            has_next_data = '__NEXT_DATA__' in body
            has_challenge = 'PerimeterX' in body or 'blocked' in body.lower()
            
            print(f"  Robot/human: {has_blocked}")
            print(f"  __NEXT_DATA__: {has_next_data}")
            print(f"  Challenge detected: {has_challenge}")
            
            # Try waiting longer for PerimeterX to resolve
            if has_blocked or has_challenge:
                print("PerimeterX challenge detected. Waiting 15s for resolution...")
                await page.wait_for_timeout(15000)
                
                title2 = await page.title()
                body2 = await page.content()
                has_next_data2 = '__NEXT_DATA__' in body2
                print(f"After wait - Title: {title2}, __NEXT_DATA__: {has_next_data2}")
                
                if has_next_data2:
                    result['has_products'] = True
                    # Extract __NEXT_DATA__
                    script = await page.query_selector('script#__NEXT_DATA__')
                    if script:
                        text = await script.inner_text()
                        data = json.loads(text)
                        result['next_data'] = data.get('props', {}).get('pageProps', {}).get('initialData', {})
            
            # Get cookies
            cookies = await ctx.cookies()
            result['cookies'] = {c['name']: c['value'] for c in cookies}
            print(f"Cookies: {list(result['cookies'].keys())}")
            
        except Exception as e:
            print(f"Error: {e}")
            result['error'] = str(e)
        
        await browser.close()
        return result

result = asyncio.run(try_walmart())
print("\n=== RESULT ===")
print(json.dumps({k: v for k, v in result.items() if k != 'next_data'}, indent=2, default=str))
