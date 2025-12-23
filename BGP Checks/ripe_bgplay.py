from datetime import datetime, timezone
from selenium import webdriver
import date_range_input as dri  # Import your date range

# --- CONFIG ---
IP_RANGE = "102.217.0.0/22"
PROFILE_DIR = r"C:\Users\SuleimanAbdulsalam\AppData\Local\Microsoft\Edge\User Data\SeleniumProfile"
PROFILE_NAME = "Default"

# --- Load start/end from date_range_input.py ---
start_date = datetime.strptime(dri.START_DATE, "%Y-%m-%d").replace(tzinfo=timezone.utc)
end_date = datetime.strptime(dri.END_DATE, "%Y-%m-%d").replace(tzinfo=timezone.utc)

# --- Convert to UNIX timestamps (seconds) ---
start_ts = int(start_date.timestamp())
end_ts = int(end_date.timestamp())

# --- Build URL ---
url = f"https://stat.ripe.net/bgplay/{IP_RANGE}#starttime={start_ts}&endtime={end_ts}"

# --- Open in Edge with profile ---
options = webdriver.EdgeOptions()
options.add_argument("--start-maximized")
options.add_argument(fr"--user-data-dir={PROFILE_DIR}")
options.add_argument(f"profile-directory={PROFILE_NAME}")

# 👇 This line makes the browser stay open
options.add_experimental_option("detach", True)

driver = webdriver.Edge(options=options)
driver.get(url)

print("✅ Opened:", url)
