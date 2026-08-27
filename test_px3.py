"""Full PX solve attempt with TLS client — full flow: redirect → solve → search."""
import sys, json, uuid as uuid_lib, time, re, base64
from urllib.parse import quote, urlencode
from datetime import datetime

sys.path.insert(0, '.')
from grocery_app_walmart_px import WalmartPXGenerator
import tls_client

# ── Set up tls_client session ──
session = tls_client.Session(client_identifier='chrome_127', random_tls_extension_order=True)
session.headers = {
    'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'accept-language': 'en-US,en;q=0.9',
    'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36',
}

# ── Step 1: Get blocked with redirect that has UUID and VID ──
print("=== Step 1: Get PX challenge parameters ===")
r = session.get('https://www.walmart.com/search?q=milk&store=2787')
print(f"Search: {r.status_code}")

# If we got redirected, extract params from Location
if r.status_code in (301, 302, 303, 307, 308):
    loc = r.headers.get('location', '')
    print(f"Redirect to: {loc}")
    # Parse UUID and VID from redirect URL
    uuid_match = re.search(r'uuid=([^&]+)', loc)
    vid_match = re.search(r'vid=([^&]+)', loc)
    px_uuid = uuid_match.group(1) if uuid_match else str(uuid_lib.uuid4())
    px_vid = vid_match.group(1) if vid_match else str(uuid_lib.uuid4())
    print(f"PX UUID: {px_uuid}")
    print(f"PX VID: {px_vid}")
    
    # Follow the redirect to get the block page HTML
    r2 = session.get(f'https://www.walmart.com{loc}')
    print(f"Block page: {r2.status_code}")
    app_id_match = re.search(r"window\._pxAppId\s*=\s*'([^']+)'", r2.text)
    px_app_id = app_id_match.group(1) if app_id_match else 'PXu6b0qd2S'
    print(f"PX App ID: {px_app_id}")
else:
    # Already on block page
    print("Direct block page")
    app_id_match = re.search(r"window\._pxAppId\s*=\s*'([^']+)'", r.text)
    px_app_id = app_id_match.group(1) if app_id_match else 'PXu6b0qd2S'
    print(f"PX App ID: {px_app_id}")
    px_uuid = str(uuid_lib.uuid4())
    px_vid = str(uuid_lib.uuid4())

# ── Step 2: Initialize PX generator ──
px_sid = str(uuid_lib.uuid4())
px_cts = str(uuid_lib.uuid4())

px = WalmartPXGenerator(
    app_id=px_app_id,
    ft=221,
    collector_uri=f"https://www.walmart.com/px/{px_app_id}/xhr",
    host="https://www.walmart.com",
    sid=px_sid,
    vid=px_vid,
    cts=px_cts,
)
px.px_uuid = px_uuid

# ── Step 3: Send PX2 to collector ──
print("\n=== Step 2: PX2 to collector ===")
initial_payload, raw_fp1, px_uuid = px.generate_initial_payload()

resp1 = session.post(
    px.collector_uri,
    data=urlencode(initial_payload, safe="="),
)
print(f"Collector response: {resp1.status_code}")
resp1_json = resp1.json()
print(f"do (first 150 chars): {str(resp1_json.get('do',''))[:150]}")

# Check for cookie in PX2 response
cookie = px.extract_cookie_from_response(resp1_json)
if cookie:
    print(f"✓ Got cookie from PX2! {cookie[:30]}...")
    px.px_cookie = cookie
else:
    print("No cookie yet, need PX3 challenge response...")
    
    # ── Step 4: Generate PX3 from challenge ──
    try:
        do_str = str(resp1_json.get("do", ""))
        
        # Generate challenge payload
        challenge_payload = px.generate_challenge_payload(
            raw_fp1, do_str, px_uuid, seq=1
        )
        
        resp2 = session.post(
            px.collector_uri,
            data=urlencode(challenge_payload, safe="="),
        )
        print(f"PX3 collector response: {resp2.status_code}")
        resp2_json = resp2.json()
        print(f"do (first 200 chars): {str(resp2_json.get('do',''))[:200]}")
        
        cookie = px.extract_cookie_from_response(resp2_json)
        if cookie:
            print(f"✓ Got cookie from PX3! {cookie[:30]}...")
            px.px_cookie = cookie
        else:
            print("✗ Still no cookie")
            print(f"Full response: {json.dumps(resp2_json, indent=2)[:300]}")
    except Exception as e:
        print(f"Error in PX3: {e}")
        import traceback
        traceback.print_exc()

# ── Step 5: Try search with solved cookie ──
if px.px_cookie:
    print("\n=== Step 3: Search with solved PX cookie ===")
    # Apply cookie on session
    session.cookies.set("_px3", px.px_cookie, domain=".walmart.com")
    
    auth_headers = px._get_auth_headers()
    auth_headers['accept'] = 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8'
    
    r3 = session.get(
        "https://www.walmart.com/search",
        params={"q": "milk", "store": "2787"},
        headers=auth_headers,
    )
    print(f"Final search: {r3.status_code}")
    has_data = '__NEXT_DATA__' in r3.text
    has_blocked = 'Robot or human' in r3.text
    print(f"__NEXT_DATA__: {has_data}, Blocked: {has_blocked}")
    
    if has_data:
        m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', r3.text, re.DOTALL)
        if m:
            data = json.loads(m.group(1))
            stacks = data.get('props',{}).get('pageProps',{}).get('initialData',{}).get('searchResult',{}).get('itemStacks',[])
            for stack in stacks:
                for item in stack.get('items',[])[:3]:
                    print(f"  ${item.get('price','?')} - {item.get('name','?')[:50]}")
    elif has_blocked:
        print("Still blocked after PX solve")
        print(f"Body preview: {r3.text[:200]}")
