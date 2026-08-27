"""Test Walmart PX solver using TLS client (grocery-app approach adapted for US)."""
import sys, json, uuid as uuid_lib, time, re, base64, os
from urllib.parse import quote, urlencode
from datetime import datetime

sys.path.insert(0, '.')
from grocery_app_walmart_px import WalmartPXGenerator
import tls_client
session = tls_client.Session(client_identifier="chrome_127", random_tls_extension_order=True)
session.headers = {
    'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'accept-language': 'en-US,en;q=0.9',
    'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36',
}

# Generate UUIDs for PX
px_vid = str(uuid_lib.uuid4())
px_sid = str(uuid_lib.uuid4())
px_cts = str(uuid_lib.uuid4())
px_uuid = str(uuid_lib.uuid4())

# Initialize PX generator for Walmart US
px_generator = WalmartPXGenerator(
    app_id="PXu6b0qd2S",
    ft=221,
    collector_uri="https://www.walmart.com/px/PXu6b0qd2S/xhr",
    host="https://www.walmart.com",
    sid=px_sid,
    vid=px_vid,
    cts=px_cts,
)

# Store our px_uuid separately
px_generator.px_uuid = px_uuid

# Step 1: Try a request with PX headers
print("=== Step 1: Warm-up request ===")
# Add PX identification headers
px_generator._apply_px_headers(session.headers)

r = session.get("https://www.walmart.com/")
print(f"Warm-up: {r.status_code}")

# Apply PX cookies
cookies = {}
px_generator._apply_px_cookies(cookies)

# Try search with PX headers/cookies
print("\n=== Step 2: Search attempt ===")
r2 = session.get(
    "https://www.walmart.com/search",
    params={"q": "milk", "store": "2787"},
    headers={**session.headers, **px_generator._get_auth_headers()},
    cookies=cookies,
)
print(f"Search: {r2.status_code}")
has_data = '__NEXT_DATA__' in r2.text
has_blocked = 'Robot or human' in r2.text
print(f"  __NEXT_DATA__: {has_data}, Blocked: {has_blocked}")

if has_blocked and not has_data:
    print("\nBlocked. Checking for PX challenge...")
    # Check the preso API
    r3 = session.get(
        "https://www.walmart.com/search/api/preso",
        params={"query": "milk", "store": "2787"},
        headers={**session.headers, **px_generator._get_auth_headers()},
        cookies=cookies,
    )
    print(f"Preso API: {r3.status_code}")
    if r3.status_code == 412:
        print("Got 412 challenge!")
        challenge = r3.json()
        print(f"Challenge: {json.dumps(challenge, indent=2)[:500]}")
    else:
        print(f"Response: {r3.text[:300]}")
elif has_data:
    print("Already have data — no PX challenge needed!")
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', r2.text, re.DOTALL)
    if m:
        data = json.loads(m.group(1))
        stacks = data.get('props',{}).get('pageProps',{}).get('initialData',{}).get('searchResult',{}).get('itemStacks',[])
        for stack in stacks:
            for item in stack.get('items',[])[:3]:
                print(f"  ${item.get('price','?')} - {item.get('name','?')[:50]}")
