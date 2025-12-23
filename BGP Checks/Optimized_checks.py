#!/usr/bin/env python3
import requests
from datetime import datetime, timedelta, timezone
import csv
import os

# === Parameters ===
prefix = "102.217.0.0/22"
my_asn = "329001"
glo_asn = "37148"        # GLO
dolphin_asn = "37613"    # Dolphin

# Month range
first_day_str = "2025-09-01"
last_day_str  = "2025-09-30"

first_day = datetime.fromisoformat(first_day_str).replace(tzinfo=timezone.utc)
last_day  = datetime.fromisoformat(last_day_str).replace(tzinfo=timezone.utc)
current_day = first_day

bgplay_url = "https://stat.ripe.net/data/bgplay/data.json"

# Directory to save CSV
csv_dir = r"C:\Users\SuleimanAbdulsalam\OneDrive - Kasi, Inc\Routes Check 2025"
os.makedirs(csv_dir, exist_ok=True)

# Prepare CSV file path for the whole month
csv_filename = os.path.join(csv_dir, f"data_{first_day_str}_to_{last_day_str}.csv")
with open(csv_filename, mode="w", newline="") as csvfile:
    writer = csv.writer(csvfile)
    writer.writerow(["Date", "GLO_upstream", "Dolphin_upstream"])

    # Loop over each day
    while current_day.date() <= last_day.date():
        day_start = current_day.replace(hour=0, minute=0, second=0)
        day_end   = current_day.replace(hour=23, minute=59, second=59)

        # Fetch BGPlay data for the day, all collectors
        params = {
            "resource": prefix,
            "starttime": day_start.isoformat(),
            "endtime": day_end.isoformat(),
            "unix_timestamps": "true",
            "collectors": ""  # empty = all collectors
        }
        resp = requests.get(bgplay_url, params=params)
        resp.raise_for_status()
        data = resp.json().get("data", {})

        initial_state = data.get("initial_state", []) or []
        events = sorted(data.get("events", []) or [], key=lambda e: int(float(e.get("timestamp", 0))))

        # Build optimized timestamps list: start-of-day + event timestamps +/- buffer
        event_ts_set = set()
        for ev in events:
            ev_ts = int(float(ev.get("timestamp", 0)))
            if ev_ts <= int(day_end.timestamp()):
                # add buffer timestamps around each event
                event_ts_set.update({ev_ts-1, ev_ts, ev_ts+1})
        timestamps = sorted({int(day_start.timestamp())} | event_ts_set)

        # Flags to track if GLO/Dolphin appear this day
        glo_yes = False
        dolphin_yes = False

        for ts in timestamps:
            # Rebuild active paths from scratch at this timestamp
            active_paths = [[str(x) for x in st.get("path") or st.get("as_path") or []]
                            for st in initial_state if st.get("path") or st.get("as_path")]

            # Apply all events up to current timestamp
            for ev in events:
                ev_ts = int(float(ev.get("timestamp", 0)))
                if ev_ts > ts:
                    break
                typ = str(ev.get("type", "")).lower()
                path = [str(x) for x in ev.get("path") or ev.get("as_path") or []]
                if not path:
                    continue
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

            # Stop checking further timestamps if both already yes
            if glo_yes and dolphin_yes:
                break

        # Write result to CSV
        writer.writerow([current_day.strftime('%Y-%m-%d'),
                         "Yes" if glo_yes else "No",
                         "Yes" if dolphin_yes else "No"])

        # Print result to console
        print(f"{current_day.strftime('%Y-%m-%d')} | GLO upstream: {'Yes' if glo_yes else 'No'} | Dolphin upstream: {'Yes' if dolphin_yes else 'No'}")

        # Move to next day
        current_day += timedelta(days=1)
