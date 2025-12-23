#!/usr/bin/env python3
import requests
from datetime import datetime, timedelta, timezone

# === Parameters ===
prefix = "102.217.0.0/22"
my_asn = "329001"        # Your ASN
glo_asn = "37148"        # GLO
dolphin_asn = "37613"    # Dolphin

# Month range
first_day_str = "2025-09-01"
last_day_str  = "2025-09-30"

first_day = datetime.fromisoformat(first_day_str).replace(tzinfo=timezone.utc)
last_day  = datetime.fromisoformat(last_day_str).replace(tzinfo=timezone.utc)
current_day = first_day

# RIPEstat announced-prefixes API
announced_url = "https://stat.ripe.net/data/announced-prefixes/data.json"

while current_day.date() <= last_day.date():
    day_start = current_day.replace(hour=0, minute=0, second=0)
    day_end   = current_day.replace(hour=23, minute=59, second=59)
    
    start_iso = day_start.isoformat()
    end_iso   = day_end.isoformat()

    def get_announced_prefixes(asn):
        params = {
            "resource": str(asn),
            "starttime": start_iso,
            "endtime": end_iso
        }
        resp = requests.get(announced_url, params=params)
        resp.raise_for_status()
        data = resp.json().get("data", {})
        # Extract the "prefix" field from each dict
        prefixes = [p["prefix"] for p in data.get("prefixes", []) if "prefix" in p]
        return prefixes

    my_prefixes = get_announced_prefixes(my_asn)
    glo_prefixes = get_announced_prefixes(glo_asn)
    dolphin_prefixes = get_announced_prefixes(dolphin_asn)

    # Check if they are announcing your specific prefix
    my_yes = prefix in my_prefixes
    glo_yes = prefix in glo_prefixes
    dolphin_yes = prefix in dolphin_prefixes

    print(f"{current_day.strftime('%Y-%m-%d')}")
    print(f"  My ASN ({my_asn}) announces {len(my_prefixes)} prefixes: {', '.join(my_prefixes)}")
    print(f"  GLO ({glo_asn}) announces {len(glo_prefixes)} prefixes: {', '.join(glo_prefixes)}")
    print(f"  Dolphin ({dolphin_asn}) announces {len(dolphin_prefixes)} prefixes: {', '.join(dolphin_prefixes)}")
    print(f"  Is {prefix} announced? Me: {'Yes' if my_yes else 'No'}, GLO: {'Yes' if glo_yes else 'No'}, Dolphin: {'Yes' if dolphin_yes else 'No'}\n")

    current_day += timedelta(days=1)
