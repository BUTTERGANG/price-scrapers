"""Walmart PerimeterX (HUMAN) solver — generates _px3 cookies without a browser.

Reverse-engineered from Pr0t0ns/PerimeterX-Solver and snacsnoc/grocery-app.
Adapted for Walmart.com (US) which uses firstPartyEnabled=true (PX proxied through
walmart.com itself).

Flow:
  1. Make a blocked request → get 412 with PX challenge parameters
  2. Extract appId, uuid, vid, collector URI from the response
  3. Generate PX2 fingerprint → POST to collector → get challenge data
  4. Generate PX3 fingerprint (challenge response) → POST to collector → get _px3 cookie
  5. Use _px3 in subsequent requests via X-Px-Authorization header + Cookie
"""
import json
import base64
import random
import re
import time
import uuid as uuid_lib
from datetime import datetime
from urllib.parse import quote, urlencode


# ── Constants (extracted from the PX init.js for Walmart US) ──

# Walmart.com PX app id
PX_APP_ID = "PXu6b0qd2S"
PX_TAG = "v6.7.9"

# These are extracted from the PX challenge response on Walmart US
# We extract them dynamically, but fall back to these defaults from the init.js
FINGERPRINT_CONSTANTS = {
    "PX1033": "49e5084e",
    "PX1019": "1530fd3",
    "PX1020": "57b9b686",
    "PX1021": "180dd7e3",
    "PX1022": "6a90378d",
}

# Browser fingerprint constants for a "real" browser
UA_CHROME = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36"


# ── PX crypto helpers (MD5-like HMAC with XOR obfuscation) ──

def _byte_to_words(key: str) -> list:
    """Convert a string to a list of 32-bit words."""
    n = None
    e = []
    for i in range(len(key) >> 2):
        e.append(0)
    n = 0
    for n in range(0, 8 * len(key), 8):
        try:
            e[n >> 5] |= (255 & ord(key[n // 8])) << (n % 32)
        except IndexError:
            e.append(0)
            e[n >> 5] |= (255 & ord(key[n // 8])) << (n % 32)
    return e


def _add32(t, n):
    """32-bit integer addition with wrapping."""
    if t is None:
        return n
    t = t & 0xFFFFFFFF
    n = n & 0xFFFFFFFF
    e = (t & 0xFFFF) + (n & 0xFFFF)
    upper = ((t >> 16) + (n >> 16) + (e >> 16)) & 0xFFFF
    result = (upper << 16) | (e & 0xFFFF)
    if result >= 0x80000000:
        result -= 0x100000000
    return result


def _rotl(t, n):
    """32-bit rotate left."""
    t = t & 0xFFFFFFFF
    result = ((t << n) | (t >> (32 - n))) & 0xFFFFFFFF
    if result >= 0x80000000:
        result -= 0x100000000
    return result


def _ff(a, b, c, d, x, s, ac):
    return _add32(_rotl(_add32(_add32(a, b), _add32(c, d)), s), ac)


def _gg(a, b, c, d, x, s, ac):
    return _ff((b & c) | (~b & d), a, b, c, x, s, ac)


def _hh(a, b, c, d, x, s, ac):
    return _ff(b ^ c ^ d, a, b, c, x, s, ac)


def _ii(a, b, c, d, x, s, ac):
    return _ff(c ^ (b | ~d), a, b, c, x, s, ac)


def _md5_round(t):
    """The MD5 round function (modified from original MD5)."""
    c = 1732584193
    u = -271733879
    l = -1732584194
    f = 271733878
    for e in range(0, len(t), 16):
        r = c
        o = u
        i = l
        a = f
        c = _gg(c, u, l, f, t[e], 7, -680876936)
        f = _gg(f, c, u, l, t[e + 1], 12, -389564586)
        l = _gg(l, f, c, u, t[e + 2], 17, 606105819)
        u = _gg(u, l, f, c, t[e + 3], 22, -1044525330)
        c = _gg(c, u, l, f, t[e + 4], 7, -176418897)
        f = _gg(f, c, u, l, t[e + 5], 12, 1200080426)
        l = _gg(l, f, c, u, t[e + 6], 17, -1473231341)
        u = _gg(u, l, f, c, t[e + 7], 22, -45705983)
        c = _gg(c, u, l, f, t[e + 8], 7, 1770035416)
        f = _gg(f, c, u, l, t[e + 9], 12, -1958414417)
        l = _gg(l, f, c, u, t[e + 10], 17, -42063)
        u = _gg(u, l, f, c, t[e + 11], 22, -1990404162)
        c = _gg(c, u, l, f, t[e + 12], 7, 1804603682)
        f = _gg(f, c, u, l, t[e + 13], 12, -40341101)
        l = _gg(l, f, c, u, t[e + 14], 17, -1502002290)
        try:
            u = _gg(u, l, f, c, t[e + 15], 22, 1236535329)
        except IndexError:
            u = _gg(u, l, f, c, None, 22, 1236535329)
        c = _hh(c, u, l, f, t[e + 1], 5, -165796510)
        f = _hh(f, c, u, l, t[e + 6], 9, -1069501632)
        l = _hh(l, f, c, u, t[e + 11], 14, 643717713)
        u = _hh(u, l, f, c, t[e], 20, -373897302)
        c = _hh(c, u, l, f, t[e + 5], 5, -701558691)
        f = _hh(f, c, u, l, t[e + 10], 9, 38016083)
        try:
            l = _hh(l, f, c, u, t[e + 15], 14, -660478335)
        except IndexError:
            l = _hh(l, f, c, u, None, 14, -660478335)
        u = _hh(u, l, f, c, t[e + 4], 20, -405537848)
        c = _hh(c, u, l, f, t[e + 9], 5, 568446438)
        f = _hh(f, c, u, l, t[e + 14], 9, -1019803690)
        l = _hh(l, f, c, u, t[e + 3], 14, -187363961)
        u = _hh(u, l, f, c, t[e + 8], 20, 1163531501)
        c = _hh(c, u, l, f, t[e + 13], 5, -1444681467)
        f = _hh(f, c, u, l, t[e + 2], 9, -51403784)
        l = _hh(l, f, c, u, t[e + 7], 14, 1735328473)
        u = _hh(u, l, f, c, t[e + 12], 20, -1926607734)
        c = _ii(c, u, l, f, t[e + 5], 4, -378558)
        f = _ii(f, c, u, l, t[e + 8], 11, -2022574463)
        l = _ii(l, f, c, u, t[e + 11], 16, 1839030562)
        u = _ii(u, l, f, c, t[e + 14], 23, -35309556)
        c = _ii(c, u, l, f, t[e + 1], 4, -1530992060)
        f = _ii(f, c, u, l, t[e + 4], 11, 1272893353)
        l = _ii(l, f, c, u, t[e + 7], 16, -155497632)
        u = _ii(u, l, f, c, t[e + 10], 23, -1094730640)
        c = _ii(c, u, l, f, t[e + 13], 4, 681279174)
        f = _ii(f, c, u, l, t[e], 11, -358537222)
        l = _ii(l, f, c, u, t[e + 3], 16, -722521979)
        u = _ii(u, l, f, c, t[e + 6], 23, 76029189)
        c = _ii(c, u, l, f, t[e + 9], 4, -640364487)
        f = _ii(f, c, u, l, t[e + 12], 11, -421815835)
        try:
            l = _ii(l, f, c, u, t[e + 15], 16, 530742520)
        except IndexError:
            l = _ii(l, f, c, u, None, 16, 530742520)
        u = _ii(u, l, f, c, t[e + 2], 23, -995338651)
        c = _ii(c, u, l, f, t[e], 6, -198630844)
        f = _ii(f, c, u, l, t[e + 7], 10, 1126891415)
        l = _ii(l, f, c, u, t[e + 14], 15, -1416354905)
        u = _ii(u, l, f, c, t[e + 5], 21, -57434055)
        c = _ii(c, u, l, f, t[e + 12], 6, 1700485571)
        f = _ii(f, c, u, l, t[e + 3], 10, -1894986606)
        l = _ii(l, f, c, u, t[e + 10], 15, -1051523)
        u = _ii(u, l, f, c, t[e + 1], 21, -2054922799)
        c = _ii(c, u, l, f, t[e + 8], 6, 1873313359)
        try:
            f = _ii(f, c, u, l, t[e + 15], 10, -30611744)
        except IndexError:
            f = _ii(f, c, u, l, None, 10, -30611744)
        l = _ii(l, f, c, u, t[e + 6], 15, -1560198380)
        u = _ii(u, l, f, c, t[e + 13], 21, 1309151649)
        c = _ii(c, u, l, f, t[e + 4], 6, -145523070)
        f = _ii(f, c, u, l, t[e + 11], 10, -1120210379)
        l = _ii(l, f, c, u, t[e + 2], 15, 718787259)
        u = _ii(u, l, f, c, t[e + 9], 21, -343485551)
        c = _add32(c, r)
        u = _add32(u, o)
        l = _add32(l, i)
        f = _add32(f, a)
    return [c, u, l, f]


def _words_to_bytes(t):
    """Convert list of 32-bit words back to a string."""
    e = ""
    for n in range(0, 32 * len(t), 8):
        e += chr((t[n >> 5] >> (n % 32)) & 0xFF)
    return e


def _pad_message(t, n):
    """MD5-style message padding."""
    try:
        t[n >> 5] |= 128 << (n % 32)
    except IndexError:
        t.append(128)
    try:
        t[14 + ((n + 64) >> 9 << 4)] = n
    except IndexError:
        for _extra in range(14 + ((n + 64) >> 9 << 4) - len(t) + 1):
            t.append(0)
        t[14 + ((n + 64) >> 9 << 4)] = n
    return t


def _generate_pc(key: str, fingerprint: str, pc_generation: bool = True) -> str:
    """Generate the PC (proof-of-computation) value that PX requires.
    
    This is essentially HMAC-MD5 with obfuscated constants.
    
    Args:
        key: The HMAC key (uuid:tag:ft format)
        fingerprint: The fingerprint string to compute over
        pc_generation: If True, returns the compressed PC (every other digit).
                       If False, returns the raw hex hash.
    """
    r = _byte_to_words(key)
    o = []
    i = []
    for _ in range(15):
        o.append(0)
        i.append(0)
    o.append(None)
    i.append(None)
    if len(r) > 16:
        r = _md5_round(_pad_message(r, 8 * len(key)))
    for e in range(16):
        try:
            o[e] = 909522486 ^ r[e]
        except IndexError:
            o[e] = 909522486
        try:
            i[e] = 1549556828 ^ r[e]
        except IndexError:
            i[e] = 1549556828
    for val in _byte_to_words(fingerprint):
        o.append(val)
    a = _md5_round(_pad_message(o, 512 + 8 * len(fingerprint)))
    for int_val in a:
        i.append(int_val)
    v = _words_to_bytes(_md5_round(_pad_message(i, 640)))
    
    # Convert to hex string
    n = "0123456789abcdef"
    hex_str = ""
    for o in range(len(v)):
        r = ord(v[o])
        hex_str += n[(r >> 4) & 0xF] + n[r & 0xF]
    
    if not pc_generation:
        return hex_str
    
    # Extract digits for compression
    n = ""
    e2 = ""
    for r in range(len(hex_str)):
        o = ord(hex_str[r])
        if 48 <= o <= 57:
            n += hex_str[r]
        else:
            e2 += str(o % 10)
    result = n + e2
    
    # Take every other digit
    compressed = ""
    for i in range(0, len(result), 2):
        compressed += result[i]
    return compressed


def _xor_encode(t, e=50):
    """XOR encode a string with a key."""
    output = ""
    for i in range(len(t)):
        output += chr(ord(t[i]) ^ e)
    return output


def _encrypt_payload(payload: str) -> str:
    """Encrypt a payload for sending to PX collector.
    
    XOR + URL-decode + base64 encode.
    """
    url_encoded = quote(payload, safe='')
    decoded = re.sub(r'%([0-9A-F]{2})', lambda m: chr(int(m.group(1), 16)), url_encoded)
    return base64.b64encode(decoded.encode('utf-8')).decode('utf-8')


def _extract_px_params(resp_text: str) -> dict:
    """Extract PerimeterX challenge parameters from a block page response."""
    params = {}
    
    m = re.search(r"window\._pxAppId\s*=\s*'([^']+)'", resp_text)
    if m:
        params["app_id"] = m.group(1)
    
    m = re.search(r"window\._pxHostUrl\s*=\s*'([^']+)'", resp_text)
    if m:
        params["host_url"] = m.group(1)
    
    m = re.search(r"window\._pxJsClientSrc\s*=\s*'([^']+)'", resp_text)
    if m:
        params["js_client_src"] = m.group(1)
    
    m = re.search(r"window\._PXVID\s*=\s*'([^']*)'", resp_text)
    if m:
        params["vid"] = m.group(1)
    
    return params


def _extract_challenge_params_from_json(json_resp: dict) -> dict:
    """Extract challenge parameters from the JSON error response (412 from preso API)."""
    params = {}
    params["app_id"] = json_resp.get("appId", PX_APP_ID)
    params["uuid"] = json_resp.get("uuid", str(uuid_lib.uuid4()))
    params["vid"] = json_resp.get("vid", "")
    params["host_url"] = json_resp.get("hostUrl", f"/px/{PX_APP_ID}/xhr")
    # For firstPartyEnabled, the collector is at the same origin
    params["collector_url"] = json_resp.get("collectorUrl", 
        f"https://www.walmart.com/px/{PX_APP_ID}/xhr")
    params["first_party"] = json_resp.get("firstPartyEnabled", True)
    return params


def solve_px_for_walmart(session, headless: bool = False) -> dict:
    """Solve PerimeterX challenge for Walmart.com and return cookies + auth header.
    
    Args:
        session: A curl_cffi Session configured with Walmart impersonation.
        headless: Whether the session is headless (affects some fingerprint values).
    
    Returns:
        dict with 'px3_cookie' (str) and 'auth_header' (str) on success,
        or None if solving failed.
    """
    # Step 1: Make a request that will be blocked to get challenge parameters
    resp = session.get(
        "https://www.walmart.com/search/api/preso",
        params={"query": "milk", "store": "2787"},
        impersonate="safari17_0",
        timeout=20,
    )
    
    if resp.status_code != 412:
        # Not blocked — session may already be valid, try a search
        print(f"[px-solver] Unexpected status {resp.status_code}, trying search directly")
        r = session.get(
            "https://www.walmart.com/search",
            params={"q": "milk", "store": "2787"},
            impersonate="safari17_0",
            timeout=20,
        )
        if "__NEXT_DATA__" in r.text:
            return {"px3_cookie": None, "auth_header": None, "already_valid": True}
        return None
    
    # Parse challenge params
    challenge = resp.json()
    params = _extract_challenge_params_from_json(challenge)
    params["ft"] = 221  # Fixed for this PX version
    
    print(f"[px-solver] Challenge received: appId={params['app_id']}, uuid={params['uuid']}")
    
    # Step 2: Generate PX2 fingerprint and send to collector
    px_uuid = str(uuid_lib.uuid4())
    st = int(time.time() * 1000)
    sid = params.get("sid", str(uuid_lib.uuid4()))
    vid = params.get("vid", str(uuid_lib.uuid4()))
    cts = params.get("cts", str(uuid_lib.uuid4()))
    
    fingerprint_1_raw = json.dumps([{
        "t": "PX2",
        "d": {
            "PX96": "https://www.walmart.com",
            "PX63": "Win32",
            "PX191": 0,
            "PX850": 0,
            "PX851": random.randint(300, 700),
            "PX1008": 3600,
            "PX1055": st,
            "PX1056": st + random.randint(1, 50),
            "PX1038": px_uuid,
            "PX371": False,
        }
    }], separators=(",", ":"))
    
    pc_key = f"{px_uuid}:{PX_TAG}:{params['ft']}"
    pc_val = _generate_pc(pc_key, fingerprint_1_raw)
    
    payload_data = {
        "payload": _encrypt_payload(fingerprint_1_raw),
        "appId": params["app_id"],
        "tag": PX_TAG,
        "uuid": px_uuid,
        "ft": params["ft"],
        "seq": 0,
        "en": "NTA",
        "pc": pc_val,
        "sid": sid,
        "vid": vid,
        "rsc": 1,
    }
    
    # Add cts if present in challenge
    if cts:
        payload_data["cts"] = cts
    
    collector_url = f"https://www.walmart.com/px/{params['app_id']}/xhr"
    
    print(f"[px-solver] Sending PX2 to collector...")
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
    
    if resp1.status_code != 200:
        print(f"[px-solver] Collector returned {resp1.status_code}")
        return None
    
    try:
        resp1_data = resp1.json()
    except Exception:
        print(f"[px-solver] Collector returned non-JSON: {resp1.text[:200]}")
        return None
    
    # Check if PX2 already gave us the cookie (sometimes it does on first try)
    px3_cookie = _parse_px3_cookie(resp1_data)
    if px3_cookie:
        print(f"[px-solver] PX2 directly yielded cookie: {px3_cookie[:20]}...")
        return {
            "px3_cookie": px3_cookie,
            "auth_header": f"3:{px3_cookie}",
            "already_valid": False,
        }
    
    # Step 3: Generate PX3 fingerprint (challenge response) from PX2 response
    print(f"[px-solver] Generating PX3 challenge response...")
    
    # Parse the challenge data from resp1
    try:
        do_str = str(resp1_data.get("do", ""))
        sts_val = int(do_str.split("sts|")[1].split("',")[0])
        cls_val = do_str.split("cls|")[1].split("',")[0]
        drc_val = int(do_str.split("drc|")[1].split("',")[0])
        wcs_val = do_str.split("wcs|")[1].split("',")[0]
        cs_val = do_str.split("cs|")[1].split("',")[0]
    except (IndexError, ValueError, AttributeError) as e:
        print(f"[px-solver] Failed to parse PX2 response: {e}")
        print(f"[px-solver] Response: {resp1_data}")
        return None
    
    now = datetime.now()
    # US Eastern time (same as Indianapolis)
    try:
        import pytz
        tz = pytz.timezone('America/New_York')
        formatted_date = now.astimezone(tz).strftime('%a %b %d %Y %H:%M:%S GMT%z') + " (Eastern Daylight Time)"
    except ImportError:
        offset = -4 * 3600  # EDT
        formatted_date = now.strftime('%a %b %d %Y %H:%M:%S') + f" GMT{offset:+05d} (Eastern Daylight Time)"
    
    # The obfuscated key used in PX3
    key_dynamic = _xor_encode(cls_val, sts_val % 10 + 2)
    val_dynamic = _xor_encode(cls_val, sts_val % 10 + 1)
    
    fingerprint_2_raw = json.dumps([{
        "t": "PX3",
        "d": {
            "PX234": False, "PX235": False, "PX151": False, "PX239": False,
            "PX240": False, "PX152": False, "PX153": False, "PX314": False,
            "PX192": False, "PX196": False, "PX207": False, "PX251": False,
            "PX982": sts_val,
            "PX983": cls_val,
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
            "PX85": ["PDF Viewer", "Chrome PDF Viewer", "Chromium PDF Viewer",
                     "Microsoft Edge PDF Viewer", "WebKit built-in PDF"],
            "PX1179": True, "PX1180": True,
            "PX59": UA_CHROME,
            "PX61": "en-US", "PX313": ["en-US", "en"],
            "PX63": "Win32", "PX86": True, "PX154": 420, "PX1157": 8,
            "PX1173": 2, "PX133": True, "PX88": True, "PX169": 2,
            "PX62": "Gecko", "PX69": "20030107",
            "PX64": UA_CHROME,
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
            "PX850": 0, "PX851": random.randint(300, 700),
            "PX1054": int(time.time()) * 1000,
            "PX1008": 3600, "PX1055": st, "PX1056": st + random.randint(1, 50),
            "PX1038": px_uuid, "PX371": False,
        }
    }], separators=(",", ":")).replace("\\n", "\\\\n").replace(")\\n", ")\\\\\n").replace("r\\n", "r\\\\n").replace("Error\\n", "Error\\\\n")
    
    pc_val_2 = _generate_pc(pc_key, fingerprint_2_raw)
    
    payload_data_2 = {
        "payload": _encrypt_payload(fingerprint_2_raw),
        "appId": params["app_id"],
        "tag": PX_TAG,
        "uuid": px_uuid,
        "ft": params["ft"],
        "seq": 1,
        "en": "NTA",
        "cs": cs_val,
        "pc": pc_val_2,
        "sid": sid,
        "vid": vid,
        "cts": cts,
        "rsc": 2,
    }
    
    print(f"[px-solver] Sending PX3 to collector...")
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
    
    if resp2.status_code != 200:
        print(f"[px-solver] Collector returned {resp2.status_code}")
        return None
    
    try:
        resp2_data = resp2.json()
    except Exception:
        print(f"[px-solver] Collector returned non-JSON: {resp2.text[:200]}")
        return None
    
    # Step 4: Extract the _px3 cookie from the response
    px3_cookie = _parse_px3_cookie(resp2_data)
    if px3_cookie:
        print(f"[px-solver] PX challenge solved! Cookie obtained.")
        return {
            "px3_cookie": px3_cookie,
            "auth_header": f"3:{px3_cookie}",
            "already_valid": False,
        }
    
    print(f"[px-solver] Failed to extract _px3 cookie from response")
    print(f"[px-solver] Response: {resp2_data}")
    return None


def _parse_px3_cookie(response_data: dict) -> str:
    """Extract the _px3 cookie value from a PX collector response."""
    try:
        do_str = str(response_data.get("do", ""))
        # Format: "bake|_px3|330|COOKIE_VALUE|..."
        match = re.search(r"bake\|_px3\|330\|([^|]+)\|", do_str)
        if match:
            return match.group(1)
        # Other variations
        match = re.search(r"_px3\|(\d+)\|([^|]+)", do_str)
        if match:
            return match.group(2)
    except Exception:
        pass
    return None
