"""
Tuya Operation Log API Example
Edit START_DATETIME and END_DATETIME below to set your query window.
"""
# --- Editable time window ---
START_DATETIME = "2026-02-23 17:30:58"  # Start datetime (YYYY-MM-DD HH:MM:SS)
END_DATETIME = "2026-02-24 17:54:58"    # End datetime (YYYY-MM-DD HH:MM:SS)

# --- Tuya API config ---
CLIENT_ID = "m7ku7veymhfcjrh43fs7"
SECRET = "e33551ec57e344169499964c82b1d18b"
DEVICE_ID = "bf3541ea3d395603b9nxrr"
REGION = "EU"
BASE_URLS = {
    "US": "https://openapi.tuyaus.com",
    "CN": "https://openapi.tuyacn.com",
    "EU": "https://openapi.tuyaeu.com"
}
BASE_URL = BASE_URLS.get(REGION, "https://openapi.tuyaeu.com")

# All imports at top
import time
import uuid
import hmac
import hashlib
import requests
from datetime import datetime

def get_access_token():
    """Get Tuya API access token."""
    t = str(int(time.time() * 1000))
    nonce = str(uuid.uuid4())
    path = "/v1.0/token?grant_type=1"
    content_sha256 = hashlib.sha256(b"").hexdigest()
    string_to_sign = f"GET\n{content_sha256}\n\n{path}"
    final_string = CLIENT_ID + t + nonce + string_to_sign
    sign = hmac.new(SECRET.encode(), final_string.encode(), hashlib.sha256).hexdigest().upper()
    headers = {
        "client_id": CLIENT_ID,
        "sign": sign,
        "t": t,
        "sign_method": "HMAC-SHA256",
        "nonce": nonce,
    }
    url = f"{BASE_URL}{path}"
    response = requests.get(url, headers=headers)
    data = response.json()
    return data["result"]["access_token"] if data.get("success") else None

def to_millis(dt_str):
    """Convert datetime string to milliseconds since epoch."""
    return int(datetime.strptime(dt_str, "%Y-%m-%d %H:%M:%S").timestamp() * 1000)

def get_operation_logs(access_token, device_id, type_str, start_ms, end_ms, size=20, query_type=1):
    """Query operation logs for a device and print them in a readable table."""
    t = str(int(time.time() * 1000))
    nonce = str(uuid.uuid4())
    path = f"/v2.0/cloud/thing/{device_id}/logs"
    params = {
        "type": type_str,
        "start_time": start_ms,
        "end_time": end_ms,
        "query_type": query_type,
        "size": size
    }
    sorted_query = "&".join(f"{k}={v}" for k, v in sorted(params.items()))
    content_sha256 = hashlib.sha256(b"").hexdigest()
    string_to_sign = f"GET\n{content_sha256}\n\n{path}?{sorted_query}"
    final_string = CLIENT_ID + access_token + t + nonce + string_to_sign
    sign = hmac.new(SECRET.encode(), final_string.encode(), hashlib.sha256).hexdigest().upper()
    headers = {
        "client_id": CLIENT_ID,
        "sign": sign,
        "t": t,
        "sign_method": "HMAC-SHA256",
        "nonce": nonce,
        "access_token": access_token
    }
    url = f"{BASE_URL}{path}?{sorted_query}"
    resp = requests.get(url, headers=headers)
    try:
        data = resp.json()
        logs = data.get('result', {}).get('logs', [])
        if not logs:
            print("No logs found.")
            return
        print(f"{'Time':<20} {'Code':<18} {'Value':<10} {'EventID':<7} {'From':<5} {'Status':<6}")
        print("-"*70)
        for log in logs:
            ts = log.get('event_time')
            dt = datetime.fromtimestamp(ts/1000).strftime('%Y-%m-%d %H:%M:%S') if ts else ''
            code = log.get('code', '')
            value = log.get('value', '')
            event_id = log.get('event_id', '')
            event_from = log.get('event_from', '')
            status = log.get('status', '')
            print(f"{dt:<20} {code:<18} {value:<10} {event_id!s:<7} {event_from!s:<5} {status!s:<6}")
    except Exception:
        print(resp.text)

if __name__ == "__main__":
    # Get access token
    token = get_access_token()
    if not token:
        print("Failed to get access token.")
        exit(1)

    # Convert editable datetimes to ms
    start_ms = to_millis(START_DATETIME)
    end_ms = to_millis(END_DATETIME)

    # Query all operation log types
    get_operation_logs(token, DEVICE_ID, "1,2,3,4,5,6,7,8,9,10", start_ms, end_ms, size=20)