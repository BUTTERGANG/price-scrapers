"""Test dual-layer PX with tls_client for the actual request."""
import sys, json, re
sys.path.insert(0, '.')
from walmart_px_session import WalmartPxSession

print("=== Testing dual-layer PX (tls_client search) ===\n")

px = WalmartPxSession()
success = px.solve()

if success:
    print("Now searching with tls_client (same session as solver)...")
    
    r = px.tls.get(
        "https://www.walmart.com/search",
        params={"q": "milk", "store": "2787"},
    )
    print(f"Search: {r.status_code}")
    has_data = '__NEXT_DATA__' in r.text
    has_blocked = 'Robot or human' in r.text
    print(f"__NEXT_DATA__: {has_data}, Blocked: {has_blocked}")
    
    if has_data:
        m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', r.text, re.DOTALL)
        if m:
            data = json.loads(m.group(1))
            stacks = data.get('props',{}).get('pageProps',{}).get('initialData',{}).get('searchResult',{}).get('itemStacks',[])
            for stack in stacks:
                for item in stack.get('items',[])[:5]:
                    print(f"  ${item.get('price','?')} - {item.get('name','?')[:50]}")
    elif has_blocked:
        print(f"Body: {r.text[:200]}")
    else:
        print(f"Non-blocked, non-data response:")
        # Check if it was a redirect or other
        if r.status_code in (301, 302, 307, 308):
            print(f"  Redirect to: {r.headers.get('location','')}")
        else:
            print(f"  Body: {r.text[:300]}")

    # Also try with explicit headers
    print("\n--- Retrying with explicit headers ---")
    r2 = px.tls.get(
        "https://www.walmart.com/search",
        params={"q": "milk", "store": "2787"},
        headers={
            **px.get_headers(),
            'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        },
    )
    print(f"Search: {r2.status_code}")
    has_data2 = '__NEXT_DATA__' in r2.text
    has_blocked2 = 'Robot or human' in r2.text
    print(f"__NEXT_DATA__: {has_data2}, Blocked: {has_blocked2}")
    if has_data2:
        m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', r2.text, re.DOTALL)
        if m:
            data2 = json.loads(m.group(1))
            stacks2 = data2.get('props',{}).get('pageProps',{}).get('initialData',{}).get('searchResult',{}).get('itemStacks',[])
            for stack in stacks2:
                for item in stack.get('items',[])[:5]:
                    print(f"  ${item.get('price','?')} - {item.get('name','?')[:50]}")
    elif has_blocked2:
        print(f"Body: {r2.text[:200]}")
    elif r2.status_code == 412:
        print(f"412 - Challenge response:")
        print(f"  {r2.text[:300]}")
