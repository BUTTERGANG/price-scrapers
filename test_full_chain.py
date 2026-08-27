"""Complete Walmart scraper with dual PX and full cookie chain."""
import sys, json, re, uuid as uuid_lib
from urllib.parse import urlencode
sys.path.insert(0, '.')
from grocery_app_walmart_px import WalmartPXGenerator, get_cloud_collector_url, _parse_px3_cookie
import tls_client

# Create tls session
session = tls_client.Session(client_identifier='chrome_127', random_tls_extension_order=True)
session.headers = {
    'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'accept-language': 'en-US,en;q=0.9',
    'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36',
}

vid = str(uuid_lib.uuid4())
sid = str(uuid_lib.uuid4())
cts = str(uuid_lib.uuid4())

# Step 1: Get blocked - capture all initial cookies
print("=== Step 1: Initial block ===")
r = session.get('https://www.walmart.com/search?q=milk&store=2787', allow_redirects=True)
initial_cookies = session.cookies.get_dict()
print('Initial cookies: {}'.format(list(initial_cookies.keys())))
print('URL: {}'.format(r.url))

# Step 2: Solve Layer 1 (without follow-redirect)
print("\n=== Step 2: Solve Layer 1 ===")
# Use a fresh request without following redirects
r_no_redirect = session.get('https://www.walmart.com/search?q=milk&store=2787', allow_redirects=False)
print('No-redirect status: {}'.format(r_no_redirect.status_code))

px1 = WalmartPXGenerator(
    app_id='PXu6b0qd2S', ft=221,
    collector_uri=get_cloud_collector_url('PXu6b0qd2S'),
    host="https://www.walmart.com", sid=sid, vid=vid, cts=cts,
)
px1.px_uuid = str(uuid_lib.uuid4())
ok1 = px1.solve(session)
print('Layer 1 solved: {}, cookie: {}'.format(ok1, str(px1.px_cookie)[:30] if px1.px_cookie else 'None'))

if ok1:
    # Set PX cookie
    session.cookies.set("_px3", px1.px_cookie, domain=".walmart.com")
    
    # Step 3: Retry search with Layer 1 cookie + all initial cookies
    print("\n=== Step 3: Retry search ===")
    r2 = session.get(
        'https://www.walmart.com/search',
        params={'q': 'milk', 'store': '2787'},
        headers={
            'X-Px-Authorization': '3:{}'.format(px1.px_cookie),
            'X-Px-Vid': vid,
            'X-Px-Uuid': str(uuid_lib.uuid4()),
        },
    )
    print('Status: {}'.format(r2.status_code))
    
    if r2.status_code == 200:
        has_data = '__NEXT_DATA__' in r2.text
        print('Has data: {}'.format(has_data))
        if has_data:
            m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', r2.text, re.DOTALL)
            if m:
                data = json.loads(m.group(1))
                stacks = data.get('props',{}).get('pageProps',{}).get('initialData',{}).get('searchResult',{}).get('itemStacks',[])
                for stack in stacks:
                    for item in stack.get('items',[])[:3]:
                        print('  ${} - {}'.format(item.get('price','?'), item.get('name','?')[:50]))
        else:
            print('Body: {}'.format(r2.text[:200]))
    elif r2.status_code == 412:
        data2 = r2.json()
        print('Challenge from: {}'.format(data2.get('appId')))
        
        if data2.get('appId') == 'PXUArm9B04':
            print("\n=== Step 4: Solve Layer 2 ===")
            px2 = WalmartPXGenerator(
                app_id='PXUArm9B04', ft=221,
                collector_uri=get_cloud_collector_url('PXUArm9B04'),
                host="https://www.walmart.com", sid=sid, vid=vid, cts=cts,
            )
            px2.px_uuid = str(uuid_lib.uuid4())
            ok2 = px2.solve(session)
            print('Layer 2 solved: {}, cookie: {}'.format(ok2, str(px2.px_cookie)[:30] if px2.px_cookie else 'None'))
            
            if ok2:
                session.cookies.set("_px3", px2.px_cookie, domain=".walmart.com")
                
                print("\n=== Step 5: Retry with both layers ===")
                r3 = session.get(
                    'https://www.walmart.com/search',
                    params={'q': 'milk', 'store': '2787'},
                    headers={
                        'X-Px-Authorization': '3:{}'.format(px2.px_cookie),
                        'X-Px-Vid': vid,
                        'X-Px-Uuid': str(uuid_lib.uuid4()),
                    },
                )
                print('Status: {}'.format(r3.status_code))
                has_data3 = '__NEXT_DATA__' in r3.text
                print('Has data: {}'.format(has_data3))
                if has_data3:
                    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', r3.text, re.DOTALL)
                    if m:
                        data3 = json.loads(m.group(1))
                        stacks3 = data3.get('props',{}).get('pageProps',{}).get('initialData',{}).get('searchResult',{}).get('itemStacks',[])
                        for stack in stacks3:
                            for item in stack.get('items',[])[:5]:
                                print('  ${} - {}'.format(item.get('price','?'), item.get('name','?')[:50]))
                elif r3.status_code == 412:
                    print('Still 412: {}'.format(r3.text[:200]))
                else:
                    print('Body: {}'.format(r3.text[:200]))
