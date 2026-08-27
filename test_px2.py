"""Test PX solver — extract challenge from block page, solve, and verify."""
import sys, json, uuid as uuid_lib, time, re, base64
from urllib.parse import quote, urlencode
from datetime import datetime
sys.path.insert(0, '.')
from curl_cffi import requests as curl_requests
from utils.px_solver import (
    _encrypt_payload, _generate_pc, FINGERPRINT_CONSTANTS,
    _xor_encode, _parse_px3_cookie, PX_TAG, UA_CHROME
)

session = curl_requests.Session(impersonate='safari17_0')
session.headers.update({
    'User-Agent': UA_CHROME,
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.9',
})

# Step 1: Get block page
print("=== Step 1: Get block page ===")
r = session.get('https://www.walmart.com/search?q=milk', impersonate='safari17_0', timeout=20)
print(f"Status: {r.status_code}, Blocked: {'Robot or human' in r.text}")

# Extract PX params from HTML
html = r.text
px_app_id = re.search(r"window\._pxAppId\s*=\s*'([^']+)'", html)
if px_app_id:
    print(f"PX App ID: {px_app_id.group(1)}")

# The PX data object embedded in the page
px_data_match = re.search(r"window\._PXETnJ2Y5H\s*=\s*({.*?});", html, re.DOTALL)
if px_data_match:
    px_data = json.loads(px_data_match.group(1))
    print(f"PX data keys: {list(px_data.keys())}")
    for k, v in px_data.items():
        print(f"  {k}: {str(v)[:80]}")

# Step 2: Generate PX2 and send to collector
print("\n=== Step 2: Generate PX2 fingerprint ===")
px_uuid = str(uuid_lib.uuid4())
st = int(time.time() * 1000)
uid = str(uuid_lib.uuid4())
vid = str(uuid_lib.uuid4())
sid = str(uuid_lib.uuid4())
cts = str(uuid_lib.uuid4())

fingerprint_1_raw = json.dumps([{
    "t": "PX2",
    "d": {
        "PX96": "https://www.walmart.com",
        "PX63": "Win32",
        "PX191": 0,
        "PX850": 0,
        "PX851": 500,
        "PX1008": 3600,
        "PX1055": st,
        "PX1056": st + 25,
        "PX1038": px_uuid,
        "PX371": False,
    }
}], separators=(",", ":"))

pc_key = f"{px_uuid}:{PX_TAG}:{221}"
pc_val = _generate_pc(pc_key, fingerprint_1_raw)

payload_data = {
    "payload": _encrypt_payload(fingerprint_1_raw),
    "appId": px_app_id.group(1) if px_app_id else 'PXu6b0qd2S',
    "tag": PX_TAG,
    "uuid": px_uuid,
    "ft": 221,
    "seq": 0,
    "en": "NTA",
    "pc": pc_val,
    "sid": sid,
    "vid": vid,
    "cts": cts,
    "rsc": 1,
}

collector_url = "https://www.walmart.com/px/PXu6b0qd2S/xhr"
print(f"POST to collector: {collector_url}")

resp1 = session.post(
    collector_url,
    data=urlencode(payload_data, safe="="),
    headers={
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "*/*",
        "Origin": "https://www.walmart.com",
        "Referer": "https://www.walmart.com/",
    },
    impersonate="safari17_0",
    timeout=20,
)
print(f"PX2 collector response: {resp1.status_code}")
if resp1.status_code == 200:
    try:
        data1 = resp1.json()
        print(f"  do: {str(data1.get('do',''))[:150]}")
        px3_cookie = _parse_px3_cookie(data1)
        if px3_cookie:
            print(f"  ✓ PX cookie obtained directly from PX2!")
            print(f"  Cookie: {px3_cookie[:30]}...")
        else:
            print(f"  No cookie in PX2 response, need PX3")
    except Exception as e:
        print(f"  Non-JSON response: {resp1.text[:200]}")
else:
    print(f"  Response: {resp1.text[:200]}")

# Step 3: PX3
if resp1.status_code == 200 and not _parse_px3_cookie(resp1.json()):
    print("\n=== Step 3: Generate PX3 challenge response ===")
    try:
        do_str = str(data1.get("do", ""))
        sts_val = int(do_str.split("sts|")[1].split("',")[0])
        cls_val = do_str.split("cls|")[1].split("',")[0]
        drc_val = int(do_str.split("drc|")[1].split("',")[0])
        wcs_val = do_str.split("wcs|")[1].split("',")[0]
        cs_val = do_str.split("cs|")[1].split("',")[0]
        
        now = datetime.now()
        formatted_date = now.strftime('%a %b %d %Y %H:%M:%S GMT-0400 (Eastern Daylight Time)')
        
        key_dynamic = _xor_encode(cls_val, sts_val % 10 + 2)
        val_dynamic = _xor_encode(cls_val, sts_val % 10 + 1)
        
        fingerprint_2_raw = json.dumps([{
            "t": "PX3",
            "d": {
                "PX234": False, "PX235": False, "PX151": False, "PX239": False,
                "PX240": False, "PX152": False, "PX153": False, "PX314": False,
                "PX192": False, "PX196": False, "PX207": False, "PX251": False,
                "PX982": sts_val, "PX983": cls_val,
                key_dynamic: val_dynamic,
                "PX985": drc_val,
                "PX1033": FINGERPRINT_CONSTANTS["PX1033"],
                "PX1019": FINGERPRINT_CONSTANTS["PX1019"],
                "PX1020": FINGERPRINT_CONSTANTS["PX1020"],
                "PX1021": FINGERPRINT_CONSTANTS["PX1021"],
                "PX1022": FINGERPRINT_CONSTANTS["PX1022"],
                "PX1035": True, "PX1139": False, "PX1025": False,
                "PX359": _generate_pc(UA_CHROME, px_uuid, False),
                "PX943": wcs_val,
                "PX357": _generate_pc(UA_CHROME, vid, False),
                "PX358": _generate_pc(UA_CHROME, sid, False),
                "PX229": 24, "PX230": 24,
                "PX91": 1280, "PX92": 800, "PX269": 1280, "PX270": 752,
                "PX93": "1280X800", "PX185": 665, "PX186": 252, "PX187": 0,
                "PX188": 0, "PX95": True, "PX400": 1441, "PX404": "109|66|66|70|80",
                "PX90": ["loadTimes", "csi", "app"],
                "PX190": "", "PX552": "false", "PX399": "false",
                "PX549": 1, "PX411": 1, "PX405": True, "PX547": True,
                "PX134": True, "PX89": True, "PX170": 5,
                "PX85": ["PDF Viewer", "Chrome PDF Viewer", "Chromium PDF Viewer", "Microsoft Edge PDF Viewer", "WebKit built-in PDF"],
                "PX1179": True, "PX1180": True,
                "PX59": UA_CHROME, "PX61": "en-US", "PX313": ["en-US", "en"],
                "PX63": "Win32", "PX86": True, "PX154": 420, "PX1157": 8,
                "PX1173": 2, "PX133": True, "PX88": True, "PX169": 2,
                "PX62": "Gecko", "PX69": "20030107", "PX64": UA_CHROME,
                "PX65": "Netscape", "PX66": "Mozilla", "PX1144": True,
                "PX1152": 1.45, "PX1153": 100, "PX1154": False, "PX1155": "4g",
                "PX60": True, "PX87": True,
                "PX821": 4294705152, "PX822": 21869834, "PX823": 18631122,
                "PX147": False, "PX155": formatted_date,
                "PX236": False, "PX194": False, "PX195": True, "PX237": 10,
                "PX238": "missing", "PX208": "visible", "PX218": 0,
                "PX231": 752, "PX232": 1280, "PX254": False, "PX295": False,
                "PX268": False, "PX166": True, "PX138": False, "PX143": True,
                "PX1142": 8, "PX1143": 3, "PX1146": 0, "PX1147": 1,
                "PX714": "64556c77", "PX715": "",
                "PX724": "10207b2f", "PX725": "10207b2f", "PX729": "90e65465",
                "PX443": True, "PX466": True, "PX467": True, "PX468": True,
                "PX191": 0, "PX94": 6, "PX120": [], "PX141": False,
                "PX96": "https://www.walmart.com",
                "PX55": quote("https://www.walmart.com", safe=''),
                "PX34": "Error\n    at Oe (https://static.walmart.com/px/PXu6b0qd2S/init.js:3:10744)",
                "PX1065": 2,
                "PX850": 0, "PX851": 500,
                "PX1054": int(time.time()) * 1000,
                "PX1008": 3600, "PX1055": st, "PX1056": st + 25,
                "PX1038": px_uuid, "PX371": False,
            }
        }], separators=(",", ":")).replace("\\n", "\\\\n").replace(")\\n", ")\\\\\n").replace("r\\n", "r\\\\n").replace("Error\\n", "Error\\\\n")
        
        pc_val_2 = _generate_pc(pc_key, fingerprint_2_raw)
        
        payload_data_2 = {
            "payload": _encrypt_payload(fingerprint_2_raw),
            "appId": px_app_id.group(1) if px_app_id else 'PXu6b0qd2S',
            "tag": PX_TAG,
            "uuid": px_uuid,
            "ft": 221,
            "seq": 1,
            "en": "NTA",
            "cs": cs_val,
            "pc": pc_val_2,
            "sid": sid,
            "vid": vid,
            "cts": cts,
            "rsc": 2,
        }
        
        resp2 = session.post(
            collector_url,
            data=urlencode(payload_data_2, safe="="),
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "*/*",
                "Origin": "https://www.walmart.com",
                "Referer": "https://www.walmart.com/",
            },
            impersonate="safari17_0",
            timeout=20,
        )
        print(f"PX3 collector response: {resp2.status_code}")
        if resp2.status_code == 200:
            data2 = resp2.json()
            print(f"  do: {str(data2.get('do',''))[:200]}")
            px3_cookie = _parse_px3_cookie(data2)
            if px3_cookie:
                print(f"  ✓ PX cookie obtained!")
                print(f"  Cookie: {px3_cookie[:40]}...")
            else:
                print(f"  No cookie extracted")
                print(f"  Full response: {json.dumps(data2, indent=2)[:300]}")
        else:
            print(f"  Response: {resp2.text[:300]}")
    except Exception as e:
        print(f"  Error in PX3: {e}")
        import traceback
        traceback.print_exc()
