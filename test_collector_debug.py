"""Deep debug: inspect the raw PX collector response and cookies."""
import sys, json, uuid as uuid_lib
from urllib.parse import urlencode
sys.path.insert(0, '.')
from grocery_app_walmart_px import WalmartPXGenerator, get_cloud_collector_url, _parse_px3_cookie
import tls_client

session = tls_client.Session(client_identifier='chrome_127', random_tls_extension_order=True)
session.headers = {
    'accept': '*/*',
    'content-type': 'application/x-www-form-urlencoded',
    'origin': 'https://www.walmart.com',
    'referer': 'https://www.walmart.com/',
    'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36',
}

vid = str(uuid_lib.uuid4())
sid = str(uuid_lib.uuid4())
cts = str(uuid_lib.uuid4())

for app_id in ['PXu6b0qd2S', 'PXUArm9B04']:
    print('\n=== {} ==='.format(app_id))
    
    collector_url = get_cloud_collector_url(app_id)
    print('Collector: {}'.format(collector_url))
    
    px = WalmartPXGenerator(
        app_id=app_id, ft=221, collector_uri=collector_url,
        host="https://www.walmart.com", sid=sid, vid=vid, cts=cts,
    )
    px.px_uuid = str(uuid_lib.uuid4())
    
    # PX2
    payload, raw_fp1, puid = px.generate_initial_payload()
    r1 = session.post(collector_url, data=urlencode(payload, safe="="))
    print('PX2: {}'.format(r1.status_code))
    
    if r1.status_code == 200:
        d1 = r1.json()
        print('Response keys: {}'.format(list(d1.keys())))
        
        # Check for Set-Cookie header
        resp_headers = dict(r1.headers)
        if 'Set-Cookie' in resp_headers:
            print('Set-Cookie: {}'.format(resp_headers['Set-Cookie'][:200]))
        
        cookie = _parse_px3_cookie(d1)
        if cookie:
            print('Cookie value: {}'.format(cookie[:50]))
        else:
            print('No cookie in PX2')
            print('do: {}'.format(str(d1.get('do',''))[:200]))
            
            # PX3
            do_str = str(d1.get("do", ""))
            cp = px.generate_challenge_payload(raw_fp1, do_str, puid, seq=1)
            r2 = session.post(collector_url, data=urlencode(cp, safe="="))
            print('PX3: {}'.format(r2.status_code))
            
            if r2.status_code == 200:
                d2 = r2.json()
                resp_headers2 = dict(r2.headers)
                if 'Set-Cookie' in resp_headers2:
                    print('Set-Cookie: {}'.format(resp_headers2['Set-Cookie'][:200]))
                cookie = _parse_px3_cookie(d2)
                if cookie:
                    print('Cookie value: {}'.format(cookie[:50]))
                else:
                    print('No cookie in PX3 either')
                    print('do: {}'.format(str(d2.get('do',''))[:200]))
                    print('Full: {}'.format(json.dumps(d2, indent=2)[:500]))
            else:
                print('Body: {}'.format(r2.text[:200]))
    else:
        print('Body: {}'.format(r1.text[:200]))
