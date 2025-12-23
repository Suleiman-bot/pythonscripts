#!/usr/bin/env python3
import requests
from datetime import datetime, timezone

# === Parameters ===
prefix = "102.217.0.0/22"
my_asn = "329001"
glo_asn = "37148"        # GLO
dolphin_asn = "37613"    # Dolphin

# Hardcoded BGPlay range (must include your timestamp)
starttime = "2025-06-13T00:00:00"
endtime   = "2025-06-13T23:59:59"

# Timestamp to check
check_time_str = "2025-06-13 23:12:53"
check_time = datetime.fromisoformat(check_time_str).replace(tzinfo=timezone.utc)
check_ts = int(check_time.timestamp())

# Fetch BGPlay data
bgplay_url = "https://stat.ripe.net/data/bgplay/data.json"
params = {
    "resource": prefix,
    "starttime": starttime,
    "endtime": endtime,
    "unix_timestamps": "true"
}
resp = requests.get(bgplay_url, params=params)
resp.raise_for_status()
data = resp.json().get("data", {})

initial_state = data.get("initial_state", []) or []
events = sorted(data.get("events", []) or [], key=lambda e: int(float(e.get("timestamp", 0))))

# Build active paths from initial state
active_paths = []
for st in initial_state:
    path = st.get("path") or st.get("as_path") or []
    if isinstance(path, list) and path:
        active_paths.append([str(x) for x in path])

# Apply events up to the check timestamp
for ev in events:
    ts = int(float(ev.get("timestamp", 0)))
    if ts > check_ts:
        break
    typ = str(ev.get("type", "")).lower()
    path = ev.get("path") or ev.get("as_path") or []
    if isinstance(path, list) and path:
        path = [str(x) for x in path]
        if "announce" in typ or typ == "a":
            active_paths.append(path)
        elif "withdraw" in typ or typ == "w":
            try:
                active_paths.remove(path)
            except ValueError:
                pass

# Collect all active paths where my ASN is the origin
paths_with_my_asn = [p for p in active_paths if p and str(p[-1]) == my_asn]

# Check if at least one path has GLO or Dolphin upstream
glo_up = any(glo_asn in p[:-1] for p in paths_with_my_asn)
dolphin_up = any(dolphin_asn in p[:-1] for p in paths_with_my_asn)

# Print simplified result
print(f"GLO upstream: {'Yes' if glo_up else 'No'} | Dolphin upstream: {'Yes' if dolphin_up else 'No'}")
