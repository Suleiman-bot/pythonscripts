#!/usr/bin/env python3
import requests
from datetime import datetime, timedelta, timezone

# === Parameters ===
prefix = "102.217.0.0/22"
my_asn = "329001"
glo_asn = "37148"        # GLO
dolphin_asn = "37613"    # Dolphin

# Month range
first_day_str = "2025-09-25"
last_day_str  = "2025-09-30"

first_day = datetime.fromisoformat(first_day_str).replace(tzinfo=timezone.utc)
last_day  = datetime.fromisoformat(last_day_str).replace(tzinfo=timezone.utc)
current_day = first_day

bgplay_url = "https://stat.ripe.net/data/bgplay/data.json"

# Loop over each day
while current_day.date() <= last_day.date():
    day_start = current_day.replace(hour=0, minute=0, second=0)
    day_end   = current_day.replace(hour=23, minute=59, second=59)
    
    # Fetch BGPlay data for this single day
    params = {
        "resource": prefix,
        "starttime": day_start.isoformat(),
        "endtime": day_end.isoformat(),
        "unix_timestamps": "true"
    }
    resp = requests.get(bgplay_url, params=params)
    resp.raise_for_status()
    data = resp.json().get("data", {})

    initial_state = data.get("initial_state", []) or []
    events = sorted(data.get("events", []) or [], key=lambda e: int(float(e.get("timestamp", 0))))

    # Flags to track if GLO/Dolphin appear this day
    glo_yes = False
    dolphin_yes = False

    # Iterate through every second in the day
    ts = int(day_start.timestamp())
    day_end_ts = int(day_end.timestamp())
    while ts <= day_end_ts:
        # Rebuild active_paths from scratch each second
        active_paths = []
        for st in initial_state:
            path = st.get("path") or st.get("as_path") or []
            if isinstance(path, list) and path:
                active_paths.append([str(x) for x in path])

        # Apply all events up to current timestamp
        for ev in events:
            ev_ts = int(float(ev.get("timestamp", 0)))
            if ev_ts > ts:
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

        # Filter paths where my ASN is the origin
        paths_with_my_asn = [p for p in active_paths if p and str(p[-1]) == my_asn]

        # Check if GLO/Dolphin appear in any path
        if any(str(glo_asn) in p[:-1] for p in paths_with_my_asn):
            glo_yes = True
        if any(str(dolphin_asn) in p[:-1] for p in paths_with_my_asn):
            dolphin_yes = True

        # If both already yes, stop checking further seconds for this day
        if glo_yes and dolphin_yes:
            break

        ts += 1  # move to next second

    # Print result for the day
    print(f"{current_day.strftime('%Y-%m-%d')} | GLO upstream: {'Yes' if glo_yes else 'No'} | Dolphin upstream: {'Yes' if dolphin_yes else 'No'}")

    # Move to next day
    current_day += timedelta(days=1)
