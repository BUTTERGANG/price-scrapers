"""Test dual-layer PX solver for Walmart."""
import sys
sys.path.insert(0, '.')
from walmart_px_session import WalmartPxSession

print("=== Testing dual-layer PX solver ===\n")

px = WalmartPxSession()
success = px.solve()

print(f"\nSolver success: {success}")
if success:
    print(f"Headers: {list(px.get_headers().keys())}")
    print(f"Cookies: {list(px.get_cookies().keys())}")
    
    # Try a curl_cffi search
    from curl_cffi import requests as curl_requests
    session = curl_requests.Session(impersonate='safari17_0')
    session.headers.update(px.get_headers())
    for name, value in px.get_cookies().items():
        session.cookies.set(name, value, domain='.walmart.com')
    
    r = session.get(
        'https://www.walmart.com/search?q=milk&store=2787',
        impersonate='safari17_0',
        timeout=25,
    )
    print(f"\nSearch: {r.status_code}")
    has_data = '__NEXT_DATA__' in r.text
    has_blocked = 'Robot or human' in r.text
    print(f"__NEXT_DATA__: {has_data}")
    print(f"Blocked: {has_blocked}")
    
    if has_data:
        m = __import__('re').search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', r.text, __import__('re').DOTALL)
        if m:
            data = __import__('json').loads(m.group(1))
            stacks = data.get('props',{}).get('pageProps',{}).get('initialData',{}).get('searchResult',{}).get('itemStacks',[])
            for stack in stacks:
                for item in stack.get('items',[])[:5]:
                    print(f"  ${item.get('price','?')} - {item.get('name','?')[:50]}")
    elif has_blocked:
        print(f"Body: {r.text[:200]}")
    else:
        print(f"Body: {r.text[:200]}")
else:
    print("Failed to solve PerimeterX for Walmart")
