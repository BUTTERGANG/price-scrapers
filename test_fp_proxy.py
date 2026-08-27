"""Test solving PX through Walmart's first-party proxy endpoint."""
import sys, json, re, uuid as uuid_lib
from urllib.parse import urlencode
sys.path.insert(0, '.')
from grocery_app_walmart_px import WalmartPXGenerator, _parse_px3_cookie
import tls_client

session = tls_client.Session(client_identifier='chrome_127', random_tls_extension_order=True)

vid = str(uuid_lib.uuid4())
sid = str(uuid_lib.uuid4())
cts = str(uuid_lib.uuid4())

layer2_app = 'PXUArm9B04'
fp_url = "https://www.walmart.com/px/{}/xhr".format(layer2_app)

px2 = WalmartPXGenerator(
    app_id=layer2_app,
    ft=221,
    collector_uri=fp_url,
    host="https://www.walmart.com",
    sid=sid,
    vid=vid,
    cts=cts,
)
px2.px_uuid = str(uuid_lib.uuid4())

px_headers = {
    'accept': '*/*',
    'content-type': 'application/x-www-form-urlencoded',
    'origin': 'https://www.walmart.com',
    'referer': 'https://www.walmart.com/',
    'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36',
}
session.headers = px_headers

# PX2 via first-party proxy
initial_payload, raw_fp1, puid = px2.generate_initial_payload()
resp1 = session.post(fp_url, data=urlencode(initial_payload, safe="="))
print('FP proxy PX2: {}'.format(resp1.status_code))
print('Body: {}'.format(resp1.text[:300]))

if resp1.status_code == 200:
    d1 = resp1.json()
    do1 = str(d1.get("do", ""))
    print('do: {}'.format(do1[:150]))
    cookie = _parse_px3_cookie(d1)
    if cookie:
        print('Cookie in PX2! {}...'.format(cookie[:30]))
    else:
        print('No cookie, need PX3...')
        cp = px2.generate_challenge_payload(raw_fp1, do1, puid, seq=1)
        resp2 = session.post(fp_url, data=urlencode(cp, safe="="))
        print('FP proxy PX3: {}'.format(resp2.status_code))
        if resp2.status_code == 200:
            d2 = resp2.json()
            do2 = str(d2.get("do", ""))
            print('do: {}'.format(do2[:200]))
            cookie = _parse_px3_cookie(d2)
            if cookie:
                print('Cookie in PX3! {}...'.format(cookie[:30]))
            else:
                print('Full: {}'.format(json.dumps(d2, indent=2)[:300]))
        else:
            print('Body: {}'.format(resp2.text[:200]))
else:
    print('Body: {}'.format(resp1.text[:200]))
