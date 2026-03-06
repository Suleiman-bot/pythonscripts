# Backup copy of tuya-token.py before injecting additional debug prints
# Created automatically

import time
import uuid
import hashlib
import hmac
import requests
from datetime import datetime
from urllib.parse import urlencode

CLIENT_ID = "m7ku7veymhfcjrh43fs7"
SECRET = "e33551ec57e344169499964c82b1d18b"
DEVICE_ID = "bfe638589811b17c2axoef"
CODES = "doorcontact_state,battery_state"
START_DATETIME = "2026-02-24 14:30:58"
END_DATETIME = "2026-02-24 14:30:58"
SIZE = 50
REGION = "EU"
BASE_URLS = {"US": "https://openapi.tuyaus.com","CN": "https://openapi.tuyacn.com","EU": "https://openapi.tuyaeu.com"}
BASE_URL = BASE_URLS.get(REGION, "https://openapi.tuyaeu.com")

def get_access_token():
    t = str(int(time.time() * 1000))
    nonce = str(uuid.uuid4())
    request_path = "/v1.0/token?grant_type=1"
    content_sha256 = hashlib.sha256(b"").hexdigest()
    string_to_sign = f"GET\n{content_sha256}\n\n{request_path}"
    final_string = CLIENT_ID + t + nonce + string_to_sign
    sign = hmac.new(SECRET.encode(), final_string.encode(), hashlib.sha256).hexdigest().upper()
    headers = {"client_id": CLIENT_ID, "sign": sign, "t": t, "sign_method": "HMAC-SHA256", "nonce": nonce}
    url = f"{BASE_URL}{request_path}"
    response = requests.get(url, headers=headers)
    data = response.json()
    if data.get("success"):
        return data["result"]["access_token"]
    else:
        print("Error getting token:", data)
        return None

def to_millis(dt_str, fmt="%Y-%m-%d %H:%M:%S"):
    dt = datetime.strptime(dt_str, fmt)
    return int(dt.timestamp() * 1000)

# end of backup
