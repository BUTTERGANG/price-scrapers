"""Walmart PerimeterX solver — adapted from snacsnoc/grocery-app for Walmart US.

This is a cleaned-up adaptation of the grocery-app's walmart_px.py for Walmart.com (US).
The US version uses firstPartyEnabled=true so the collector is proxied through walmart.com.

Key differences from the Canadian version:
  - appId: PXu6b0qd2S (vs PXnp9B16Cq)
  - Collector proxied through www.walmart.com/px/{appId}/xhr
  - Preso API returns 200 with block HTML instead of 412 JSON
"""
import json, base64, random, re, time, uuid as uuid_lib
from urllib.parse import quote, urlencode
from datetime import datetime

# Path hack for the grocery-app utils - we embed the needed function directly
# to avoid cross-project import issues
PX_TAG = "v6.7.9"
UA_CHROME = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36"


# ── Embedded generate_pc implementation from grocery-app/utils/px_utils.py ──

def _L(key: str) -> list:
    """Convert string to word array (like the JS function L)."""
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


def _O(t, n):
    """32-bit add."""
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


def _j(t, n):
    """32-bit rotate left."""
    t = t & 0xFFFFFFFF
    result = ((t << n) | (t >> (32 - n))) & 0xFFFFFFFF
    if result >= 0x80000000:
        result -= 0x100000000
    return result


def _N(t, n, e, r, o, i):
    return _O(_j(_O(_O(n, t), _O(r, i)), o), e)


def _P(t, n, e, r, o, i, a):
    c = n & e | ~n & r
    return _N(c, t, n, o, i, a)


def _R(t, n, e, r, o, i, a):
    abc = n & r | e & ~r
    return _N(abc, t, n, o, i, a)


def _X(t, n, e, r, o, i, a):
    return _N(n ^ e ^ r, t, n, o, i, a)


def _F(t, n, e, r, o, i, a):
    return _N(e ^ (n | ~r), t, n, o, i, a)


def _G(t):
    e = ""
    for n in range(0, 32 * len(t), 8):
        e += chr((t[n >> 5] >> (n % 32)) & 0xFF)
    return e


def _U(t, n):
    """Message padding."""
    try:
        t[n >> 5] |= 128 << (n % 32)
    except IndexError:
        t.append(128)
    try:
        t[14 + ((n + 64) >> 9 << 4)] = n
    except IndexError:
        for _ab in range(14 + ((n + 64) >> 9 << 4) - len(t) + 1):
            t.append(0)
        t[14 + ((n + 64) >> 9 << 4)] = n
    c = 1732584193
    u = -271733879
    l = -1732584194
    f = 271733878
    for e in range(0, len(t), 16):
        r = c
        o = u
        i = l
        a = f
        c = _P(c, u, l, f, t[e], 7, -680876936)
        f = _P(f, c, u, l, t[e + 1], 12, -389564586)
        l = _P(l, f, c, u, t[e + 2], 17, 606105819)
        u = _P(u, l, f, c, t[e + 3], 22, -1044525330)
        c = _P(c, u, l, f, t[e + 4], 7, -176418897)
        f = _P(f, c, u, l, t[e + 5], 12, 1200080426)
        l = _P(l, f, c, u, t[e + 6], 17, -1473231341)
        u = _P(u, l, f, c, t[e + 7], 22, -45705983)
        c = _P(c, u, l, f, t[e + 8], 7, 1770035416)
        f = _P(f, c, u, l, t[e + 9], 12, -1958414417)
        l = _P(l, f, c, u, t[e + 10], 17, -42063)
        u = _P(u, l, f, c, t[e + 11], 22, -1990404162)
        c = _P(c, u, l, f, t[e + 12], 7, 1804603682)
        f = _P(f, c, u, l, t[e + 13], 12, -40341101)
        l = _P(l, f, c, u, t[e + 14], 17, -1502002290)
        try:
            u = _P(u, l, f, c, t[e + 15], 22, 1236535329)
        except IndexError:
            u = _P(u, l, f, c, None, 22, 1236535329)
        c = _R(c, u, l, f, t[e + 1], 5, -165796510)
        f = _R(f, c, u, l, t[e + 6], 9, -1069501632)
        l = _R(l, f, c, u, t[e + 11], 14, 643717713)
        u = _R(u, l, f, c, t[e], 20, -373897302)
        c = _R(c, u, l, f, t[e + 5], 5, -701558691)
        f = _R(f, c, u, l, t[e + 10], 9, 38016083)
        try:
            l = _R(l, f, c, u, t[e + 15], 14, -660478335)
        except IndexError:
            l = _R(l, f, c, u, None, 14, -660478335)
        u = _R(u, l, f, c, t[e + 4], 20, -405537848)
        c = _R(c, u, l, f, t[e + 9], 5, 568446438)
        f = _R(f, c, u, l, t[e + 14], 9, -1019803690)
        l = _R(l, f, c, u, t[e + 3], 14, -187363961)
        u = _R(u, l, f, c, t[e + 8], 20, 1163531501)
        c = _R(c, u, l, f, t[e + 13], 5, -1444681467)
        f = _R(f, c, u, l, t[e + 2], 9, -51403784)
        l = _R(l, f, c, u, t[e + 7], 14, 1735328473)
        u = _R(u, l, f, c, t[e + 12], 20, -1926607734)
        c = _X(c, u, l, f, t[e + 5], 4, -378558)
        f = _X(f, c, u, l, t[e + 8], 11, -2022574463)
        l = _X(l, f, c, u, t[e + 11], 16, 1839030562)
        u = _X(u, l, f, c, t[e + 14], 23, -35309556)
        c = _X(c, u, l, f, t[e + 1], 4, -1530992060)
        f = _X(f, c, u, l, t[e + 4], 11, 1272893353)
        l = _X(l, f, c, u, t[e + 7], 16, -155497632)
        u = _X(u, l, f, c, t[e + 10], 23, -1094730640)
        c = _X(c, u, l, f, t[e + 13], 4, 681279174)
        f = _X(f, c, u, l, t[e], 11, -358537222)
        l = _X(l, f, c, u, t[e + 3], 16, -722521979)
        u = _X(u, l, f, c, t[e + 6], 23, 76029189)
        c = _X(c, u, l, f, t[e + 9], 4, -640364487)
        f = _X(f, c, u, l, t[e + 12], 11, -421815835)
        try:
            l = _X(l, f, c, u, t[e + 15], 16, 530742520)
        except IndexError:
            l = _X(l, f, c, u, None, 16, 530742520)
        u = _X(u, l, f, c, t[e + 2], 23, -995338651)
        c = _F(c, u, l, f, t[e], 6, -198630844)
        f = _F(f, c, u, l, t[e + 7], 10, 1126891415)
        l = _F(l, f, c, u, t[e + 14], 15, -1416354905)
        u = _F(u, l, f, c, t[e + 5], 21, -57434055)
        c = _F(c, u, l, f, t[e + 12], 6, 1700485571)
        f = _F(f, c, u, l, t[e + 3], 10, -1894986606)
        l = _F(l, f, c, u, t[e + 10], 15, -1051523)
        u = _F(u, l, f, c, t[e + 1], 21, -2054922799)
        c = _F(c, u, l, f, t[e + 8], 6, 1873313359)
        try:
            f = _F(f, c, u, l, t[e + 15], 10, -30611744)
        except IndexError:
            f = _F(f, c, u, l, None, 10, -30611744)
        l = _F(l, f, c, u, t[e + 6], 15, -1560198380)
        u = _F(u, l, f, c, t[e + 13], 21, 1309151649)
        c = _F(c, u, l, f, t[e + 4], 6, -145523070)
        f = _F(f, c, u, l, t[e + 11], 10, -1120210379)
        l = _F(l, f, c, u, t[e + 2], 15, 718787259)
        u = _F(u, l, f, c, t[e + 9], 21, -343485551)
        c = _O(c, r)
        u = _O(u, o)
        l = _O(l, i)
        f = _O(f, a)
    return [c, u, l, f]


def _calculate_hash_from_xored_value(value: str) -> str:
    n = "0123456789abcdef"
    e = ""
    for o in range(len(value)):
        r = ord(value[o])
        e += n[(r >> 4) & 0xF] + n[r & 0xF]
    return e


def _hash_to_full_pc(hash_str: str) -> int:
    n = ""
    e = ""
    for r in range(len(hash_str)):
        o = ord(hash_str[r])
        if 48 <= o <= 57:
            n += hash_str[r]
        else:
            e += str(o % 10)
    return n + e


def generate_pc(key: str, fingerprint: str, pc_generation: bool = True) -> str:
    """Generate the PC (proof-of-computation) value."""
    e = None
    r = _L(key)
    o = []
    i = []
    for _abcd in range(15):
        o.append(0)
        i.append(0)
    o.append(None)
    i.append(None)
    if len(r) > 16:
        r = _U(r, 8 * len(key))
    for e in range(16):
        try:
            o[e] = 909522486 ^ r[e]
        except IndexError:
            o[e] = 909522486
        try:
            i[e] = 1549556828 ^ r[e]
        except IndexError:
            i[e] = 1549556828
    for val in _L(fingerprint):
        o.append(val)
    a = _U(o, 512 + 8 * len(fingerprint))
    for int_val in a:
        i.append(int_val)
    v = _G(_U(i, 640))
    calculated_hash = _calculate_hash_from_xored_value(v)
    if not pc_generation:
        return calculated_hash
    r = _hash_to_full_pc(calculated_hash)
    o = ""
    for i in range(0, len(r), 2):
        o += r[i]
    return o


class WalmartPXGenerator:
    """PX cookie generator for Walmart.com (US first-party proxy mode)."""

    def __init__(self, app_id: str, ft: int, collector_uri: str, host: str, sid: str, vid: str, cts: str):
        self.base_url = host
        self.host = host
        self.app_id = app_id
        self.tag = PX_TAG
        self.ft = ft
        self.collector_uri = collector_uri
        self.sid = sid
        self.vid = vid
        self.cts = cts
        self.px_cookie = None
        self.px_uuid = None

    def _encode(self, payload: str, e: int = 50) -> str:
        """XOR encode a string."""
        output = ""
        for i in range(len(payload)):
            output += chr(ord(payload[i]) ^ e)
        return output

    def _encrypt(self, payload: str) -> str:
        """XOR → URL-escape → base64."""
        quoted = quote(payload)
        decoded = re.sub(r"%([0-9A-F]{2})", lambda m: chr(int(m.group(1), 16)), quoted)
        return base64.b64encode(decoded.encode()).decode()

    def _encrypt_payload(self, payload: str) -> str:
        return self._encrypt(self._encode(payload))

    def _generate_fingerprint_1(self, host: str, uuid: str, st: int):
        """Generate initial PX2 fingerprint."""
        return json.dumps(([{
            "t": "PX2",
            "d": {
                "PX96": host,
                "PX63": "Win32",
                "PX191": 0,
                "PX850": 0,
                "PX851": random.randint(300, 700),
                "PX1008": 3600,
                "PX1055": st,
                "PX1056": st + random.randint(1, 50),
                "PX1038": uuid,
                "PX371": False,
            }
        }]), separators=(",", ":"))

    def _generate_fingerprint_2(self, payload_1: list, response_do: str, vid: str, sid: str):
        """Generate challenge PX3 fingerprint from PX2 response."""
        payload_1_data = payload_1[0]["d"]
        response_data = str(response_do)

        def safe_split(data, key):
            return data.split(key)[1].split("',")[0]

        cls_val = safe_split(response_data, "cls|")
        sts_val = int(safe_split(response_data, "sts|"))
        drc_val = int(safe_split(response_data, "drc|"))
        wcs_val = safe_split(response_data, "wcs|")

        key_dynamic = f"{self._encode(cls_val, sts_val % 10 + 2)}"
        val_dynamic = f"{self._encode(cls_val, sts_val % 10 + 1)}"

        now = datetime.now()
        formatted_date = now.strftime('%a %b %d %Y %H:%M:%S GMT-0400 (Eastern Daylight Time)')

        fp = [{
            "t": "PX3",
            "d": {
                "PX234": False, "PX235": False, "PX151": False, "PX239": False,
                "PX240": False, "PX152": False, "PX153": False, "PX314": False,
                "PX192": False, "PX196": False, "PX207": False, "PX251": False,
                "PX982": sts_val,
                "PX983": cls_val,
                key_dynamic: val_dynamic,
                "PX985": drc_val,
                "PX1033": "49e5084e",
                "PX1019": "1530fd3",
                "PX1020": "57b9b686",
                "PX1021": "180dd7e3",
                "PX1022": "6a90378d",
                "PX1035": True, "PX1139": False, "PX1025": False,
                "PX359": f"{generate_pc(UA_CHROME, payload_1_data['PX1038'], False)}",
                "PX943": wcs_val,
                "PX357": f"{generate_pc(UA_CHROME, vid, False)}",
                "PX358": f"{generate_pc(UA_CHROME, sid, False)}",
                "PX229": 24, "PX230": 24,
                "PX91": 1280, "PX92": 800, "PX269": 1280, "PX270": 752,
                "PX93": "1280X800", "PX185": 665, "PX186": 252,
                "PX187": 0, "PX188": 0, "PX95": True, "PX400": 1441,
                "PX404": "109|66|66|70|80",
                "PX90": ["loadTimes", "csi", "app"],
                "PX190": "", "PX552": "false", "PX399": "false",
                "PX549": 1, "PX411": 1, "PX405": True, "PX547": True,
                "PX134": True, "PX89": True, "PX170": 5,
                "PX85": ["PDF Viewer", "Chrome PDF Viewer", "Chromium PDF Viewer",
                         "Microsoft Edge PDF Viewer", "WebKit built-in PDF"],
                "PX1179": True, "PX1180": True,
                "PX59": UA_CHROME,
                "PX61": "en-US", "PX313": ["en-US", "en"],
                "PX63": payload_1_data["PX63"],
                "PX86": True, "PX154": 420, "PX1157": 8, "PX1173": 2,
                "PX133": True, "PX88": True, "PX169": 2,
                "PX62": "Gecko", "PX69": "20030107",
                "PX64": UA_CHROME,
                "PX65": "Netscape", "PX66": "Mozilla", "PX1144": True,
                "PX1152": 1.45, "PX1153": 100, "PX1154": False, "PX1155": "4g",
                "PX60": True, "PX87": True,
                "PX821": 4294705152, "PX822": 21869834, "PX823": 18631122,
                "PX147": False, "PX155": formatted_date,
                "PX236": False, "PX194": False, "PX195": True,
                "PX237": 10, "PX238": "missing",
                "PX208": "visible", "PX218": 0,
                "PX231": 752, "PX232": 1280,
                "PX254": False, "PX295": False, "PX268": False,
                "PX166": True, "PX138": False, "PX143": True,
                "PX1142": 8, "PX1143": 3, "PX1146": 0, "PX1147": 1,
                "PX714": "64556c77", "PX715": "",
                "PX724": "10207b2f", "PX725": "10207b2f", "PX729": "90e65465",
                "PX443": True, "PX466": True, "PX467": True, "PX468": True,
                "PX191": payload_1_data["PX191"],
                "PX94": 6, "PX120": [], "PX141": False,
                "PX96": payload_1_data["PX96"],
                "PX55": quote(str(payload_1_data["PX96"]), safe=""),
                "PX34": "Error\n    at Oe (https://static.walmart.com/px/PXu6b0qd2S/init.js:3:10744)",
                "PX1065": 2,
                "PX850": payload_1_data["PX850"],
                "PX851": payload_1_data["PX851"],
                "PX1054": int(time.time()) * 1000,
                "PX1008": payload_1_data["PX1008"],
                "PX1055": payload_1_data["PX1055"],
                "PX1056": payload_1_data["PX1056"],
                "PX1038": payload_1_data["PX1038"],
                "PX371": payload_1_data["PX371"],
            }
        }]

        json_str = json.dumps(fp, separators=(",", ":"))
        return (json_str
                .replace("\\n", "\\\\n")
                .replace(")\\n", ")\\\\\n")
                .replace("r\\n", "r\\\\n")
                .replace("Error\\n", "Error\\\\n"))

    def generate_initial_payload(self):
        """Generate the initial PX2 collector payload."""
        px_uuid = str(uuid_lib.uuid4())
        current_time = int(time.time() * 1000)
        self.px_uuid = px_uuid

        raw_payload_str = self._generate_fingerprint_1(self.base_url, px_uuid, current_time)
        encrypted_payload = self._encrypt_payload(raw_payload_str)
        pc_key = f"{px_uuid}:{self.tag}:{self.ft}"

        data = {
            "payload": encrypted_payload,
            "appId": self.app_id,
            "tag": self.tag,
            "uuid": px_uuid,
            "ft": self.ft,
            "seq": 0,
            "en": "NTA",
            "pc": generate_pc(pc_key, raw_payload_str),
            "sid": self.sid,
            "vid": self.vid,
            "cts": self.cts,
            "rsc": 1,
        }
        return data, json.loads(raw_payload_str), px_uuid

    def generate_challenge_payload(self, raw_payload_1, response_do, px_uuid, seq=1):
        """Generate the PX3 challenge response payload."""
        if isinstance(raw_payload_1, str):
            payload_1_list = json.loads(raw_payload_1)
        else:
            payload_1_list = raw_payload_1

        fp2 = self._generate_fingerprint_2(payload_1_list, response_do, self.vid, self.sid)
        pc_key = f"{px_uuid}:{self.tag}:{self.ft}"

        try:
            cs_val = str(response_do).split("cs|")[1].split("',")[0]
        except (IndexError, AttributeError):
            cs_val = ""

        data = {
            "payload": self._encrypt_payload(fp2),
            "appId": self.app_id,
            "tag": self.tag,
            "uuid": px_uuid,
            "ft": self.ft,
            "seq": seq,
            "en": "NTA",
            "cs": cs_val,
            "pc": generate_pc(pc_key, fp2),
            "sid": self.sid,
            "vid": self.vid,
            "cts": self.cts,
            "rsc": seq + 1,
        }
        return data

    def _apply_px_headers(self, headers: dict):
        """Add PX identification headers to a request."""
        px_uuid = self.px_uuid or str(uuid_lib.uuid4())
        headers["X-Px-Vid"] = self.vid
        headers["X-Px-Uuid"] = px_uuid
        if self.px_cookie:
            headers["X-Px-Authorization"] = f"3:{self.px_cookie}"
        if not self.px_uuid:
            self.px_uuid = px_uuid

    def _apply_px_cookies(self, cookies: dict):
        """Set PX cookies on a cookie dict."""
        if self.px_cookie:
            cookies["_px3"] = self.px_cookie
        cookies["_pxvid"] = self.vid

    def _get_auth_headers(self) -> dict:
        """Get auth-only headers (no standard headers)."""
        h = {}
        if self.px_cookie:
            h["X-Px-Authorization"] = f"3:{self.px_cookie}"
        h["X-Px-Vid"] = self.vid
        h["X-Px-Uuid"] = self.px_uuid or str(uuid_lib.uuid4())
        return h

    def solve(self, session) -> bool:
        """Full solve flow: PX2 → PX3 → get _px3 cookie.
        
        Args:
            session: tls_client.Session or any session with .post()
            
        Returns:
            True if cookie was obtained, False otherwise.
        """
        initial_payload, raw_fp1, px_uuid = self.generate_initial_payload()
        
        collector_headers = {
            'accept': '*/*',
            'content-type': 'application/x-www-form-urlencoded',
            'origin': self.host,
            'referer': f'{self.host}/',
            'user-agent': UA_CHROME,
        }
        
        resp1 = session.post(self.collector_uri, data=urlencode(initial_payload, safe="="), headers=collector_headers)
        if resp1.status_code != 200:
            return False
        
        resp1_json = resp1.json()
        cookie = _parse_px3_cookie(resp1_json)
        if cookie:
            self.px_cookie = cookie
            return True
        
        do_str = str(resp1_json.get("do", ""))
        challenge_payload = self.generate_challenge_payload(raw_fp1, do_str, px_uuid, seq=1)
        
        resp2 = session.post(self.collector_uri, data=urlencode(challenge_payload, safe="="), headers=collector_headers)
        if resp2.status_code != 200:
            return False
        
        resp2_json = resp2.json()
        cookie = _parse_px3_cookie(resp2_json)
        if cookie:
            self.px_cookie = cookie
            return True
        
        return False


# ── Module-level helpers ──

def _parse_px3_cookie(response_data: dict) -> str | None:
    """Extract _px3 cookie value from a PX collector response."""
    try:
        do_str = str(response_data.get("do", ""))
        match = re.search(r"bake\|_px3\|330\|([^|]+)\|", do_str)
        if match:
            return match.group(1)
    except Exception:
        pass
    return None


def extract_px_challenge_params(html_or_json) -> dict:
    """Extract PX challenge parameters from either HTML block page or 412 JSON."""
    params = {}
    if isinstance(html_or_json, dict):
        params["app_id"] = html_or_json.get("appId", "")
        params["uuid"] = html_or_json.get("uuid", str(uuid_lib.uuid4()))
        params["vid"] = html_or_json.get("vid", "")
        params["first_party"] = html_or_json.get("firstPartyEnabled", True)
        return params
    m = re.search(r"window\._pxAppId\s*=\s*'([^']+)'", html_or_json)
    if m:
        params["app_id"] = m.group(1)
    return params


def get_cloud_collector_url(app_id: str) -> str:
    """Get the cloud collector URL for a given PX app ID."""
    return f"https://collector-{app_id}.px-cloud.net/api/v2/collector"
