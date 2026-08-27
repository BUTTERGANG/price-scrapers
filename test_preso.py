"""Try different approach: avoid the PX layer 1 by using a fresh session directly on preso."""
import sys, json, re, uuid as uuid_lib
from urllib.parse import urlencode
sys.path.insert(0, '.')
from grocery_app_walmart_px import WalmartPXGenerator, get_cloud_collector_url, _parse_px3_cookie
import tls_client

# Fresh session with minimal headers
session = tls_client.Session(client_identifier='chrome_127', random_tls_extension_order=True)
session.headers = {
    'accept': 'application/json',
    'accept-language': 'en-US,en;q=0.9',
    'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36',
}

# Try preso API directly - maybe without PX headers it works differently  
r = session.get('https://www.walmart.com/search/api/preso?query=milk&store=2787')
print(f'Preso (no PX headers): {r.status_code}')
print(f'Body: {r.text[:200]}')

# Try with PX identification headers
session.headers['X-Px-Vid'] = str(uuid_lib.uuid4())
session.headers['X-Px-Uuid'] = str(uuid_lib.uuid4())

r2 = session.get('https://www.walmart.com/search/api/preso?query=milk&store=2787')
print(f'Preso (with PX headers): {r2.status_code}')
print(f'Body: {r2.text[:200]}')

# Check what cookies we have
print(f'Cookies: {list(session.cookies.keys())}')
print(f'Cookie vals: {dict(session.cookies.get_dict())}')