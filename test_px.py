"""Test the PerimeterX solver against Walmart.com."""
import sys, json, time
sys.path.insert(0, '.')
from curl_cffi import requests as curl_requests
from utils.px_solver import solve_px_for_walmart

# Create a curl_cffi session
session = curl_requests.Session(impersonate='safari17_0')
session.headers.update({
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.9',
})

# Warm up first
print("Warming up session...")
r = session.get('https://www.walmart.com/', impersonate='safari17_0', timeout=20)
print(f"Warm-up: {r.status_code}, cookies={list(session.cookies.keys())}")

# Try solving
print("\nSolving PerimeterX...")
result = solve_px_for_walmart(session)

if result:
    print(f"\nPX Solver result:")
    print(f"  Already valid: {result.get('already_valid', False)}")
    print(f"  _px3 cookie: {str(result.get('px3_cookie', ''))[:30]}...")
    print(f"  Auth header: {str(result.get('auth_header', ''))[:30]}...")
    
    if result.get('px3_cookie'):
        # Set the cookie and try a real request
        session.cookies.set('_px3', result['px3_cookie'], domain='.walmart.com')
        session.headers['X-Px-Authorization'] = result['auth_header']
        
        print("\nTrying search with PX cookie...")
        r2 = session.get(
            'https://www.walmart.com/search?q=milk&store=2787',
            impersonate='safari17_0',
            timeout=25
        )
        has_data = '__NEXT_DATA__' in r2.text
        has_blocked = 'Robot or human' in r2.text
        print(f"Search: {r2.status_code}, __NEXT_DATA__={has_data}, Blocked={has_blocked}")
        
        if has_data:
            import re
            m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', r2.text, re.DOTALL)
            if m:
                data = json.loads(m.group(1))
                stacks = data.get('props',{}).get('pageProps',{}).get('initialData',{}).get('searchResult',{}).get('itemStacks',[])
                for stack in stacks:
                    for item in stack.get('items',[])[:3]:
                        print(f"  ${item.get('price','?')} - {item.get('name','?')[:50]}")
    elif result.get('already_valid'):
        print("\nSession was already valid, no PX solving needed!")
else:
    print("\nFailed to solve PerimeterX")
    print("Session cookies:", list(session.cookies.keys()))
