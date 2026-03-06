import time
import uuid
import hmac
import hashlib
import requests

# Tuya API credentials
client_id = "m7ku7veymhfcjrh43fs7"
secret = "e33551ec57e344169499964c82b1d18b"       # AppSecret
grant_type = 1                     # usually 1 = client_credentials

# Step 1: Generate timestamp and nonce
t = str(int(time.time() * 1000))  # timestamp in ms
nonce = str(uuid.uuid4())         # random UUID

# Step 2: Prepare Token API request path
request_path = f"/v1.0/token?grant_type={grant_type}"

# Step 3: Content-SHA256 for empty body
content_sha256 = hashlib.sha256(b"").hexdigest()

# Step 4: Build stringToSign
string_to_sign = f"GET\n{content_sha256}\n\n{request_path}"

# Step 5: Build final string for HMAC (Token API)
final_string = client_id + t + nonce + string_to_sign

# Step 6: Calculate HMAC-SHA256 signature and uppercase it
sign = hmac.new(secret.encode(), final_string.encode(), hashlib.sha256).hexdigest().upper()

# Step 7: Prepare headers for API request
headers = {
    "client_id": client_id,
    "sign": sign,
    "t": t,
    "sign_method": "HMAC-SHA256",
    "nonce": nonce,
}

# Step 8: Make the GET request to Tuya Token API
url = f"https://openapi.tuyaus.com{request_path}"  # Change domain if your region differs

response = requests.get(url, headers=headers)
data = response.json()

if response.status_code == 200 and "result" in data:
    access_token = data["result"]["access_token"]
    expire_time = data["result"]["expire_time"]
    print(f"Access Token: {access_token}")
    print(f"Expires in: {expire_time} seconds")
else:
    print("Failed to get token:", data)
