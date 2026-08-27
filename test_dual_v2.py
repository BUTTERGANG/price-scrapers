"""Dual PX solver - follow redirects properly."""
import sys, json, re, uuid as uuid_lib, time
from urllib.parse import urlencode
sys.path.insert(0, '.')
sys.path.insert(0, '/home/alex/code/price-scrapers')
from grocery_app_walmart_px import WalmartPXGenerator, get_cloud_collector_url, _parse_px3_cookie, generate_pc

import tls_client

session = tls_client.Session(client_identifier='chrome_127', random_tls_extension_order=True)
session.headers = {
    'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'accept-language': 'en-US,en;q=0.9',
    'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36',
}

px_app_id = "PXu6b0qd2S"
vid = str(uuid_lib.uuid4())
sid = str(uuid_lib.uuid4())
cts = str(uuid_lib.uuid4())

# Step 1: Make a request, follow redirect to block page
print("=== Step 1: Getting block page ===")
r = session.get('https://www.walmart.com/search?q=milk&store=2787', allow_redirects=True)
print(f"Final status: {r.status_code}")
print(f"Final URL: {r.url}")
print(f"Blocked: {'Robot or human' in r.text}")
print(f"Cookies after: {list(session.cookies.keys())}")

# Step 2: Solve Layer 1 with the block page
print("\n=== Step 2: Solve Layer 1 ===")
px1 = WalmartPXGenerator(
    app_id=px_app_id,
    ft=221,
    collector_uri=get_cloud_collector_url(px_app_id),
    host="https://www.walmart.com",
    sid=sid,
    vid=vid,
    cts=cts,
)
px1.px_uuid = str(uuid_lib.uuid4())
ok1 = px1.solve(session)
print(f"Layer 1 solved: {ok1}, cookie: {str(px1.px_cookie)[:30] if px1.px_cookie else 'None'}")

if ok1:
    # Set cookie
    session.cookies.set("_px3", px1.px_cookie, domain=".walmart.com")
    
    # Step 3: Now retry search with Layer 1 cookie solved
    print("\n=== Step 3: Retry search with Layer 1 cookie ===")
    r2 = session.get(
        'https://www.walmart.com/search',
        params={'q': 'milk', 'store': '2787'},
        headers={
            'X-Px-Authorization': f"3:{px1.px_cookie}",
            'X-Px-Vid': vid,
            'X-Px-Uuid': str(uuid_lib.uuid4()),
        },
    )
    print(f"Status: {r2.status_code}")
    print(f"Headers: {dict(r2.headers)}")
    
    if r2.status_code == 200:
        has_data = '__NEXT_DATA__' in r2.text
        has_blocked = 'Robot or human' in r2.text
        print(f"__NEXT_DATA__: {has_data}, Blocked: {has_blocked}")
        if has_data:
            m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', r2.text, re.DOTALL)
            if m:
                data = json.loads(m.group(1))
                stacks = data.get('props',{}).get('pageProps',{}).get('initialData',{}).get('searchResult',{}).get('itemStacks',[])
                for stack in stacks:
                    for item in stack.get('items',[])[:3]:
                        print(f"  ${item.get('price','?')} - {item.get('name','?')[:50]}")
        elif has_blocked:
            print(f"Block page: {r2.text[:200]}")
        else:
            print(f"Response: {r2.text[:200]}")
    elif r2.status_code == 412:
        data2 = r2.json()
        print(f"412 - PX challenge from: {data2.get('appId')}")
        
        # Step 4: Solve Layer 2
        if data2.get('appId') == 'PXUArm9B04':
            print("\n=== Step 4: Solve Layer 2 ===")
            px2 = WalmartPXGenerator(
                app_id='PXUArm9B04',
                ft=221,
                collector_uri=get_cloud_collector_url('PXUArm9B04'),
                host="https://www.walmart.com",
                sid=sid,
                vid=vid,
                cts=cts,
            )
            px2.px_uuid = str(uuid_lib.uuid4())
            ok2 = px2.solve(session)
            print(f"Layer 2 solved: {ok2}, cookie: {str(px2.px_cookie)[:30] if px2.px_cookie else 'None'}")
            
            if ok2:
                session.cookies.set("_px3", px2.px_cookie, domain=".walmart.com")
                
                # Step 5: Retry
                print("\n=== Step 5: Retry with both layers ===")
                r3 = session.get(
                    'https://www.walmart.com/search',
                    params={'q': 'milk', 'store': '2787'},
                    headers={
                        'X-Px-Authorization': f"3:{px2.px_cookie}",
                        'X-Px-Vid': vid,
                        'X-Px-Uuid': str(uuid_lib.uuid4()),
                    },
                )
                print(f"Status: {r3.status_code}")
                has_data3 = '__NEXT_DATA__' in r3.text
                has_blocked3 = 'Robot or human' in r3.text
                print(f"__NEXT_DATA__: {has_data3}, Blocked: {has_blocked3}")
                
                if has_data3:
                    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', r3.text, re.DOTALL)
                    if m:
                        data3 = json.loads(m.group(1))
                        stacks3 = data3.get('props',{}).get('pageProps',{}).get('initialData',{}).get('searchResult',{}).get('itemStacks',[])
                        for stack in stacks3:
                            for item in stack.get('items',[])[:3]:
                                print(f"  ${item.get('price','?')} - {item.get('name','?')[:50]}")
                elif r3.status_code == 412:
                    print(f"Still 412: {r3.text[:200]}")
                else:
                    print(f"Response: {r3.text[:200]}")
