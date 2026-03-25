# CVaaS Selenium Automation Scripts

Python scripts for automating data extraction from Arista CloudVision as a Service (CVaaS). Includes connectivity metrics, data usage, and device health monitoring.

## Setup (Quick)

### 1. Install Python Packages
```bash
pip install selenium requests pytz python-docx
```

### 2. Create config.py
```bash
copy config.py.example config.py
```
Then edit `config.py` with:
- `ACCESS_TOKEN` - Get JWT from CVaaS portal (F12 → Network tab → Authorization header)
- `TARGET_HOSTNAME` - Your device hostname
- `TARGET_DATE` - Date in format "M/D/YYYY"

### 3. Setup Edge Selenium Profile
Scripts use Edge browser with a dedicated Selenium profile to avoid conflicts with your normal Edge session.

**For Windows:**
```bash
# Profile path: C:\Users\[YourUsername]\AppData\Local\Microsoft\Edge\User Data\SeleniumProfile

# Update Device_Health.py, export.py, and export_headless.py:
# Replace "SuleimanAbdulsalam" with your Windows username in lines like:
# --user-data-dir=C:\Users\[YourUsername]\AppData\Local\Microsoft\Edge\User Data\SeleniumProfile
```

The profile will be auto-created on first run. This keeps Selenium sessions separate from your normal browsing.

### 4. Download WebDriver
- Edge: https://developer.microsoft.com/microsoft-edge/tools/webdriver/ (matches your Edge version)
- Or Chrome: https://chromedriver.chromium.org/ (if you prefer Chrome)
- Place in same folder as scripts or in system PATH

### 5. Run a Script
```bash
python export.py              # Connectivity metrics
python Data_Usage.py         # Traffic data
python Device_Health.py      # Device health
python api_test.py           # Test API connection
```

## Scripts Overview

| Script | Purpose | Output |
|--------|---------|--------|
| **export.py** | Extracts jitter, latency, packet loss from connectivity interfaces | CSV files, HTML/DOCX reports |
| **export_headless.py** | Same as export.py but runs without visible browser (for servers/automation) | CSV files, HTML/DOCX reports |
| **Data_Usage.py** | Extracts traffic flow data (inflow/outflow/total) for ISP links | CSV with traffic statistics |
| **Device_Health.py** | Monitors device CPU and memory usage across all devices | DOCX + CSV health summary |
| **connectivity-statistics.py** | Formatted table view of connectivity metrics with min/max values | Console table + CSV |
| **statistics.py** | Comprehensive statistics and aggregated reports | DOCX reports |
| **api_test.py** | Tests CVaaS API connectivity and device inventory | Console output |

## Getting Access Token

1. Log into CVaaS: https://www.cv-prod-euwest-2.arista.io
2. Press F12 → Network tab
3. Make any request (click buttons, navigate)
4. Find Authorization header: `Bearer eyJhbGc...`
5. Copy the token part after "Bearer"

## Troubleshooting

| Problem | Fix |
|---------|-----|
| `No module named 'selenium'` | Run: `pip install selenium requests pytz python-docx` |
| `No config.py` | `copy config.py.example config.py` and edit it |
| `WebDriver not found` | Download WebDriver, place in script folder or system PATH |
| `Unauthorized error` | Get fresh JWT token (expires every 24h) |
| `SeleniumProfile path not found` | Update username in script paths: `C:\Users\[YourUsername]\AppData\Local\Microsoft\Edge\User Data\SeleniumProfile` |

## Notes

- `config.py` is in .gitignore (keeps tokens secure)
- Outputs go to Downloads folder by default
- Selenium uses dedicated Edge profile to avoid interfering with normal browsing
- Test with `python api_test.py` first to verify credentials
