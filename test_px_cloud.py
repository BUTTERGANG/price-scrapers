"""Test PX solver with cloud collector URL (not first-party proxy)."""
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

# ── Step 1: Get blocked ──
print("=== Step 1: Getting blocked ===")
r = session.get('https://www.walmart.com/search?q=milk&store=2787')
print(f"Status: {r.status_code}")
uuid_match = re.search(r'uuid=([^&]+)', r.headers.get('location',''))
vid_match = re.search(r'vid=([^&]+)', r.headers.get('location',''))
px_uuid = uuid_match.group(1) if uuid_match else str(uuid_lib.uuid4())
px_vid = vid_match.group(1) if vid_match else str(uuid_lib.uuid4())
px_sid = str(uuid_lib.uuid4())
px_cts = str(uuid_lib.uuid4())

print(f"UUID: {px_uuid}, VID: {px_vid}")

# ── Step 2: Initialize PX with CLOUD collector URL ──
px = WalmartPXGenerator(
    app_id="PXu6b0qd2S",
    ft=221,
    collector_uri="https://collector-PXu6b0qd2S.px-cloud.net/api/v2/collector",
    host="https://www.walmart.com",
    sid=px_sid,
    vid=px_vid,
    cts=px_cts,
)
px.px_uuid = px_uuid

# ── Step 3: PX2 to cloud collector ──
print("\n=== Step 2: PX2 to cloud collector ===")
initial_payload, raw_fp1, px_uuid2 = px.generate_initial_payload()

# Add proper headers for cross-site collector
collector_headers = {
    'accept': '*/*',
    'accept-language': 'en-US,en;q=0.9',
    'content-type': 'application/x-www-form-urlencoded',
    'origin': 'https://www.walmart.com',
    'referer': 'https://www.walmart.com/',
    'sec-ch-ua': '"Not)A;Brand";v="99", "Google Chrome";v="127", "Chromium";v="127"',
    'sec-ch-ua-mobile': '?0',
    'sec-ch-ua-platform': '"Windows"',
    'sec-fetch-dest': 'empty',
    'sec-fetch-mode': 'cors',
    'sec-fetch-site': 'cross-site',
    'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36',
}

resp1 = session.post(
    px.collector_uri,
    data=urlencode(initial_payload, safe="="),
    headers=collector_headers,
)
print(f"Cloud collector PX2: {resp1.status_code}")
if resp1.status_code == 200:
    resp1_json = resp1.json()
    print(f"do (first 150): {str(resp1_json.get('do',''))[:150]}")
    cookie = px.extract_cookie_from_response(resp1_json)
    if cookie:
        print(f"✓ Cookie from PX2! {cookie[:40]}...")
        px.px_cookie = cookie
    else:
        print("Need PX3...")
        
        do_str = str(resp1_json.get("do", ""))
        challenge_payload = px.generate_challenge_payload(raw_fp1, do_str, px_uuid2, seq=1)
        
        resp2 = session.post(
            px.collector_uri,
            data=urlencode(challenge_payload, safe="="),
            headers=collector_headers,
        )
        print(f"Cloud collector PX3: {resp2.status_code}")
        if resp2.status_code == 200:
            resp2_json = resp2.json()
            print(f"do (first 200): {str(resp2_json.get('do',''))[:200]}")
            cookie = px.extract_cookie_from_response(resp2_json)
            if cookie:
                print(f"✓ Cookie from PX3! {cookie[:40]}...")
                px.px_cookie = cookie
            else:
                print(f"Full: {json.dumps(resp2_json, indent=2)[:300]}")
        else:
            print(f"PX3 error: {resp2.text[:200]}")
else:
    print(f"Collector error: {resp1.text[:200]}")

# ── Step 4: Try search with cookie ──
if px.px_cookie:
    print("\n=== Step 3: Search with PX cookie ===")
    session.cookies.set("_px3", px.px_cookie, domain=".walmart.com")
    session.cookies.set("_pxvid", px_vid, domain=".walmart.com")
    
    auth_headers = {
        'X-Px-Authorization': f"3:{px.px_cookie}",
        'X-Px-Vid': px_vid,
        'X-Px-Uuid': px_uuid,
        'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'accept-language': 'en-US,en;q=0.9',
        'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36',
    }
    
    r3 = session.get(
        "https://www.walmart.com/search",
        params={"q": "milk", "store": "2787"},
        headers=auth_headers,
    )
    print(f"Search: {r3.status_code}")
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
        print("Still blocked")
        print(f"Body: {r3.text[:200]}")
else:
    print("No cookie obtained, can't proceed")
