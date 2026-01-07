from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (
    TimeoutException,
    NoSuchElementException,
    StaleElementReferenceException,
    ElementClickInterceptedException,
    ElementNotInteractableException,
)
import requests
import urllib3
import time
from datetime import datetime, timedelta, timezone
import pytz  # pip install pytz if needed
from config import BASE_URL, ACCESS_TOKEN, TARGET_HOSTNAME, TARGET_DATE
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# === Construct magic login link ===
magic_link = f"https://www.cv-prod-euwest-2.arista.io/api/v1/oauth?invitation={ACCESS_TOKEN}"

#Generate Active for target date
def generate_active_for_target_date_local(target_date_str=None):
    """
    Returns 'active' timestamp in milliseconds for the target date's 00:00:00
    in local timezone (Africa/Lagos, UTC+1)
    
    Args:
        target_date_str: Date string in format "M/D/YYYY". If None, uses TARGET_DATE from config
    """
    if target_date_str is None:
        target_date_str = TARGET_DATE
        
    local_tz = pytz.timezone("Africa/Lagos")
    
    # Parse the target date string in format "M/D/YYYY"
    target_date = datetime.strptime(target_date_str, "%m/%d/%Y")
    
    # Localize to timezone without adding extra hours
    target_date_local = local_tz.localize(target_date)
    
    # Convert to UTC timestamp in milliseconds
    active_ts = int(target_date_local.timestamp() * 1000)
    return active_ts


# Time range constants (used in each URL)
ACTIVE = generate_active_for_target_date_local()
FROM_OFFSET = 1000
TO_OFFSET = 86400000

# API headers
headers = {
    "Authorization": f"Bearer {ACCESS_TOKEN}",
    "Accept": "application/json",
    "Content-Type": "application/json",
}
# Use a requests.Session to reuse connections and headers for inventory/API calls
session = requests.Session()
session.headers.update(headers)


# Fetch inventory
def get_inventory():
    resp = session.get(f"{BASE_URL}/inventory/devices", verify=False)
    resp.raise_for_status()
    return resp.json()

# Get device serial
def get_device_serial(devices, hostname):
    device = next((d for d in devices if d["hostname"] == hostname), None)
    if not device:
        raise Exception(f"Device {hostname} not found")
    return device["serialNumber"]


# Fast targeted finder: try efficient, explicit selectors first to avoid scanning the entire DOM
def find_export_button_fast(driver):
    """Fast-path search using explicit, targeted XPath expressions.

    Returns an element if it looks like an export/download control, otherwise None.
    """
    xpaths = [
        # Buttons that contain export/download text
        "//button[contains(translate(text(),'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'export')]",
        "//button[contains(translate(@aria-label,'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'export')]",
        "//button[contains(translate(text(),'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'download')]",
        # Any element with a data-testid or class indicating export/download
        "//*[@data-testid and contains(translate(@data-testid,'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'export')]",
        "//*[contains(translate(@class,'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'export') and (self::button or @role='button' or self::a)]",
        "//*[contains(translate(@class,'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'download') and (self::button or @role='button' or self::a)]",
    ]

    for xp in xpaths:
        try:
            el = driver.find_element(By.XPATH, xp)
            if el.is_displayed():
                return el
        except Exception:
            continue

    return None


# Helper: attempt to locate an export button (handles stale reads)
def locate_export_button(driver):
    """Find a clickable export control.

    Looks for visible <button>, <a>, and elements with role='button' that
    either contain the words 'export'/'download'/'csv' in text/attributes,
    or contain an icon (SVG/<i>/<span>) that indicates a downward arrow /
    download action.
    """
    try:
        elems = driver.find_elements(By.XPATH, "//button | //a | //*[@role='button']")
    except StaleElementReferenceException:
        return None

    for e in elems:
        try:
            if not e.is_displayed():
                continue

            # Quick text + attribute check
            txt = (e.text or "").strip()
            attrs = " ".join(
                filter(None, [
                    e.get_attribute("aria-label"),
                    e.get_attribute("title"),
                    e.get_attribute("id"),
                    e.get_attribute("value"),
                    e.get_attribute("data-testid"),
                    e.get_attribute("data-qa"),
                    e.get_attribute("class"),
                ])
            )
            hay = (txt + " " + (attrs or "")).lower()
            if any(k in hay for k in ("export", "download", "csv")):
                return e

            # Check for icon descendants (SVG / <i> / <span>) that look like a download arrow
            try:
                svgs = e.find_elements(By.XPATH, ".//svg")
                for svg in svgs:
                    svg_attrs = " ".join(
                        filter(None, [
                            svg.get_attribute("aria-label"),
                            svg.get_attribute("title"),
                            svg.get_attribute("class"),
                            svg.get_attribute("id"),
                            svg.get_attribute("data-icon"),
                        ])
                    ).lower()
                    svg_html = (svg.get_attribute("outerHTML") or "").lower()
                    if any(k in svg_attrs for k in ("download", "export", "arrow", "down", "chev", "caret")) or any(
                        k in svg_html for k in ("download", "arrow", "down", "chevron", "caret", "fa-download", "bi-download")
                    ):
                        return e

                icons = e.find_elements(By.XPATH, ".//i | .//span")
                for ic in icons:
                    ic_attrs = " ".join(
                        filter(None, [
                            ic.get_attribute("class"),
                            ic.get_attribute("aria-label"),
                            ic.get_attribute("title"),
                            ic.text,
                        ])
                    ).lower()
                    if any(k in ic_attrs for k in ("download", "export", "arrow-down", "fa-download", "bi-download", "download-icon", "icon-download", "chevron-down", "arrow")):
                        return e
            except StaleElementReferenceException:
                # child became stale; skip this element and allow caller to retry
                continue

        except StaleElementReferenceException:
            # element became stale; skip it and allow caller to retry
            continue

    return None


# Click export and wait for modal/close; returns True if we believe export triggered
def click_export_and_handle_modal(driver, wait, click_retries=2, fast_mode=True):
    """Click the export control and return quickly if possible.

    fast_mode=True will return immediately after a short confirmation sleep
    (non-blocking export), which reduces per-URL latency significantly.
    """
    small_wait = WebDriverWait(driver, 3)

    for attempt in range(click_retries):
        try:
            # Prefer fast targeted finder via a short local wait, then fallback
            try:
                export_btn = small_wait.until(lambda d: find_export_button_fast(d) or locate_export_button(d) or False)
            except TimeoutException:
                # fallback to quick find without waiting (non-blocking)
                export_btn = find_export_button_fast(driver) or locate_export_button(driver)

            if not export_btn:
                return False

            try:
                try:
                    export_btn.click()
                except (ElementClickInterceptedException, ElementNotInteractableException):
                    # Try scrolling into view and clicking again, then fallback to JS click
                    try:
                        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", export_btn)
                        # smaller pause after scroll
                        time.sleep(0.1)
                        export_btn.click()
                    except Exception:
                        try:
                            driver.execute_script("arguments[0].click();", export_btn)
                        except Exception:
                            # give up this attempt and retry
                            time.sleep(0.3)
                            continue
            except StaleElementReferenceException:
                # element became stale between locating & clicking; retry
                time.sleep(0.3)
                continue

            # If in fast mode, return immediately after a short confirmation sleep so
            # we can move to the next URL without waiting for modal teardown.
            if fast_mode:
                time.sleep(0.15)
                return True

            # Full mode: Wait for Close button or page readyState like before
            try:
                close_btn = WebDriverWait(driver, 4).until(
                    EC.element_to_be_clickable(
                        (
                            By.XPATH,
                            "//button[contains(translate(text(),'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'close')]",
                        )
                    )
                )
                try:
                    close_btn.click()
                except StaleElementReferenceException:
                    pass
                try:
                    WebDriverWait(driver, 1).until(EC.staleness_of(close_btn))
                except Exception:
                    pass
            except TimeoutException:
                try:
                    WebDriverWait(driver, 1).until(lambda d: d.execute_script("return document.readyState") == "complete")
                except TimeoutException:
                    pass

            return True

        except (TimeoutException, StaleElementReferenceException):
            # retry loop on timeouts or stale elements
            time.sleep(0.4)
            continue

    return False


# Main selenium flow
def export_via_gui(serial):
    print("🌐 Opening Selenium in headless Edge mode...")
    options = webdriver.EdgeOptions()

    # Headless mode
    options.add_argument("--headless=new")  # modern headless mode
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")  # needed for some UIs to render correctly

    # Optional: keep profile if you still need cookies/sessions
    options.add_argument(
        r"--user-data-dir=C:\Users\SuleimanAbdulsalam\AppData\Local\Microsoft\Edge\User Data\SeleniumProfile"
    )
    options.add_argument("profile-directory=Default")

    driver = webdriver.Edge(options=options)
    wait = WebDriverWait(driver, 30)

    # === Open CVaaS login with token ===
    print("Opening CVaaS login link...")
    driver.get(magic_link)

    # Wait for login/redirect or page to be ready
    try:
        wait.until(lambda d: d.current_url != magic_link or d.execute_script("return document.readyState") == "complete")
    except TimeoutException:
        pass
    print("Login complete, proceeding with metric URLs...")

    # URLs using the shared FROM_OFFSET/TO_OFFSET constants (8 URLs total: 4 for Ethernet1 + 4 for Ethernet2)
    urls = [
    # Ethernet1 Traffic Counter
    f"https://www.cv-prod-euwest-2.arista.io/cv/devices/ethernet-stats/JPE20050335?active={ACTIVE}&fromOffset={FROM_OFFSET}&toOffset={TO_OFFSET}&modal=true&modalParams=%7B%22datasetId%22%3A%22JPE20050335%22%2C%22metricKey%22%3A%22INTERFACE_IN_BITRATE%22%2C%22metricParams%22%3A%7B%22aggregationIntervalOverride%22%3A%221m%22%2C%22deviceId%22%3A%22JPE20050335%22%2C%22intf%22%3A%22Ethernet1%22%7D%7D&modalPanel=RAW_DATA&metric=jitter",
    f"https://www.cv-prod-euwest-2.arista.io/cv/devices/ethernet-stats/JPE20050335?active={ACTIVE}&fromOffset={FROM_OFFSET}&toOffset={TO_OFFSET}&modal=true&modalParams=%7B%22datasetId%22%3A%22JPE20050335%22%2C%22metricKey%22%3A%22INTERFACE_OUT_BITRATE%22%2C%22metricParams%22%3A%7B%22aggregationIntervalOverride%22%3A%221m%22%2C%22deviceId%22%3A%22JPE20050335%22%2C%22intf%22%3A%22Ethernet1%22%7D%7D&modalPanel=RAW_DATA&metric=jitter",
    f"https://www.cv-prod-euwest-2.arista.io/cv/devices/ethernet-stats/JPE20050335?active={ACTIVE}&fromOffset={FROM_OFFSET}&toOffset={TO_OFFSET}&modal=true&modalParams=%7B%22datasetId%22%3A%22JPE20050335%22%2C%22metricKey%22%3A%22INTERFACE_IN_UCAST_RATE%22%2C%22metricParams%22%3A%7B%22aggregationIntervalOverride%22%3A%221m%22%2C%22deviceId%22%3A%22JPE20050335%22%2C%22intf%22%3A%22Ethernet1%22%7D%7D&modalPanel=RAW_DATA&metric=jitter",
    f"https://www.cv-prod-euwest-2.arista.io/cv/devices/ethernet-stats/JPE20050335?active={ACTIVE}&fromOffset={FROM_OFFSET}&toOffset={TO_OFFSET}&modal=true&modalParams=%7B%22datasetId%22%3A%22JPE20050335%22%2C%22metricKey%22%3A%22INTERFACE_OUT_UCAST_RATE%22%2C%22metricParams%22%3A%7B%22aggregationIntervalOverride%22%3A%221m%22%2C%22deviceId%22%3A%22JPE20050335%22%2C%22intf%22%3A%22Ethernet1%22%7D%7D&modalPanel=RAW_DATA&metric=jitter",
    # Ethernet2 Traffic Counter
    f"https://www.cv-prod-euwest-2.arista.io/cv/devices/ethernet-stats/JPE20050335?active={ACTIVE}&fromOffset={FROM_OFFSET}&toOffset={TO_OFFSET}&modal=true&modalParams=%7B%22datasetId%22%3A%22JPE20050335%22%2C%22metricKey%22%3A%22INTERFACE_IN_BITRATE%22%2C%22metricParams%22%3A%7B%22aggregationIntervalOverride%22%3A%221m%22%2C%22deviceId%22%3A%22JPE20050335%22%2C%22intf%22%3A%22Ethernet2%22%7D%7D&modalPanel=RAW_DATA&metric=jitter",
    f"https://www.cv-prod-euwest-2.arista.io/cv/devices/ethernet-stats/JPE20050335?active={ACTIVE}&fromOffset={FROM_OFFSET}&toOffset={TO_OFFSET}&modal=true&modalParams=%7B%22datasetId%22%3A%22JPE20050335%22%2C%22metricKey%22%3A%22INTERFACE_OUT_BITRATE%22%2C%22metricParams%22%3A%7B%22aggregationIntervalOverride%22%3A%221m%22%2C%22deviceId%22%3A%22JPE20050335%22%2C%22intf%22%3A%22Ethernet2%22%7D%7D&modalPanel=RAW_DATA&metric=jitter",
    f"https://www.cv-prod-euwest-2.arista.io/cv/devices/ethernet-stats/JPE20050335?active={ACTIVE}&fromOffset={FROM_OFFSET}&toOffset={TO_OFFSET}&modal=true&modalParams=%7B%22datasetId%22%3A%22JPE20050335%22%2C%22metricKey%22%3A%22INTERFACE_IN_UCAST_RATE%22%2C%22metricParams%22%3A%7B%22aggregationIntervalOverride%22%3A%221m%22%2C%22deviceId%22%3A%22JPE20050335%22%2C%22intf%22%3A%22Ethernet2%22%7D%7D&modalPanel=RAW_DATA&metric=jitter",
    f"https://www.cv-prod-euwest-2.arista.io/cv/devices/ethernet-stats/JPE20050335?active={ACTIVE}&fromOffset={FROM_OFFSET}&toOffset={TO_OFFSET}&modal=true&modalParams=%7B%22datasetId%22%3A%22JPE20050335%22%2C%22metricKey%22%3A%22INTERFACE_OUT_UCAST_RATE%22%2C%22metricParams%22%3A%7B%22aggregationIntervalOverride%22%3A%221m%22%2C%22deviceId%22%3A%22JPE20050335%22%2C%22intf%22%3A%22Ethernet2%22%7D%7D&modalPanel=RAW_DATA&metric=jitter",
    # Ethernet3 Traffic Counter
    f"https://www.cv-prod-euwest-2.arista.io/cv/devices/ethernet-stats/JPE20050335?active={ACTIVE}&fromOffset={FROM_OFFSET}&toOffset={TO_OFFSET}&modal=true&modalParams=%7B%22datasetId%22%3A%22JPE20050335%22%2C%22metricKey%22%3A%22INTERFACE_IN_BITRATE%22%2C%22metricParams%22%3A%7B%22aggregationIntervalOverride%22%3A%221m%22%2C%22deviceId%22%3A%22JPE20050335%22%2C%22intf%22%3A%22Ethernet3%22%7D%7D&modalPanel=RAW_DATA&metric=jitter",
    f"https://www.cv-prod-euwest-2.arista.io/cv/devices/ethernet-stats/JPE20050335?active={ACTIVE}&fromOffset={FROM_OFFSET}&toOffset={TO_OFFSET}&modal=true&modalParams=%7B%22datasetId%22%3A%22JPE20050335%22%2C%22metricKey%22%3A%22INTERFACE_OUT_BITRATE%22%2C%22metricParams%22%3A%7B%22aggregationIntervalOverride%22%3A%221m%22%2C%22deviceId%22%3A%22JPE20050335%22%2C%22intf%22%3A%22Ethernet3%22%7D%7D&modalPanel=RAW_DATA&metric=jitter",
    f"https://www.cv-prod-euwest-2.arista.io/cv/devices/ethernet-stats/JPE20050335?active={ACTIVE}&fromOffset={FROM_OFFSET}&toOffset={TO_OFFSET}&modal=true&modalParams=%7B%22datasetId%22%3A%22JPE20050335%22%2C%22metricKey%22%3A%22INTERFACE_IN_UCAST_RATE%22%2C%22metricParams%22%3A%7B%22aggregationIntervalOverride%22%3A%221m%22%2C%22deviceId%22%3A%22JPE20050335%22%2C%22intf%22%3A%22Ethernet3%22%7D%7D&modalPanel=RAW_DATA&metric=jitter",
    f"https://www.cv-prod-euwest-2.arista.io/cv/devices/ethernet-stats/JPE20050335?active={ACTIVE}&fromOffset={FROM_OFFSET}&toOffset={TO_OFFSET}&modal=true&modalParams=%7B%22datasetId%22%3A%22JPE20050335%22%2C%22metricKey%22%3A%22INTERFACE_OUT_UCAST_RATE%22%2C%22metricParams%22%3A%7B%22aggregationIntervalOverride%22%3A%221m%22%2C%22deviceId%22%3A%22JPE20050335%22%2C%22intf%22%3A%22Ethernet3%22%7D%7D&modalPanel=RAW_DATA&metric=jitter",
       
    # Jitter metrics for Glo
    f"https://www.cv-prod-euwest-2.arista.io/cv/devices/connectivity?active={ACTIVE}&fromOffset={FROM_OFFSET}&toOffset={TO_OFFSET}&modal=true&modalParams=%7B%22alternativeTitle%22%3A%22Jitter+for+KASI-LOS5-R201-BG01+%28inet+%2F+Ethernet1%29+to+GLO_INT_to_AIRTEL_NIG%22%2C%22datasetId%22%3A%22JPE20050335%22%2C%22metricKey%22%3A%22JITTER_VRF%22%2C%22metricParams%22%3A%7B%22deviceId%22%3A%22JPE20050335%22%2C%22hostVrfIntf%22%3A%22Ethernet1%22%2C%22hostVrfPair%22%3A%7B%22hostName%22%3A%22GLO_INT_to_AIRTEL_NIG%22%2C%22vrfName%22%3A%22inet%22%7D%7D%7D&modalPanel=RAW_DATA&metric=jitter",
    f"https://www.cv-prod-euwest-2.arista.io/cv/devices/connectivity?active={ACTIVE}&fromOffset={FROM_OFFSET}&toOffset={TO_OFFSET}&modal=true&modalParams=%7B%22alternativeTitle%22%3A%22Jitter+for+KASI-LOS5-R201-BG01+%28inet+%2F+Ethernet1%29+to+GLO_INT_to_SEABON_ITA%22%2C%22datasetId%22%3A%22JPE20050335%22%2C%22metricKey%22%3A%22JITTER_VRF%22%2C%22metricParams%22%3A%7B%22deviceId%22%3A%22JPE20050335%22%2C%22hostVrfIntf%22%3A%22Ethernet1%22%2C%22hostVrfPair%22%3A%7B%22hostName%22%3A%22GLO_INT_to_SEABON_ITA%22%2C%22vrfName%22%3A%22inet%22%7D%7D%7D&modalPanel=RAW_DATA&metric=jitter",
    f"https://www.cv-prod-euwest-2.arista.io/cv/devices/connectivity?active={ACTIVE}&fromOffset={FROM_OFFSET}&toOffset={TO_OFFSET}&modal=true&modalParams=%7B%22alternativeTitle%22%3A%22Jitter+for+KASI-LOS5-R201-BG01+%28inet+%2F+Ethernet1%29+to+GLO_INT_to_TATA_East_US%22%2C%22datasetId%22%3A%22JPE20050335%22%2C%22metricKey%22%3A%22JITTER_VRF%22%2C%22metricParams%22%3A%7B%22deviceId%22%3A%22JPE20050335%22%2C%22hostVrfIntf%22%3A%22Ethernet1%22%2C%22hostVrfPair%22%3A%7B%22hostName%22%3A%22GLO_INT_to_TATA_East_US%22%2C%22vrfName%22%3A%22inet%22%7D%7D%7D&modalPanel=RAW_DATA&metric=jitter",
    f"https://www.cv-prod-euwest-2.arista.io/cv/devices/connectivity?active={ACTIVE}&fromOffset={FROM_OFFSET}&toOffset={TO_OFFSET}&modal=true&modalParams=%7B%22alternativeTitle%22%3A%22Jitter+for+KASI-LOS5-R201-BG01+%28inet+%2F+Ethernet1%29+to+GLO_INT_to_Hurri_West_US%22%2C%22datasetId%22%3A%22JPE20050335%22%2C%22metricKey%22%3A%22JITTER_VRF%22%2C%22metricParams%22%3A%7B%22deviceId%22%3A%22JPE20050335%22%2C%22hostVrfIntf%22%3A%22Ethernet1%22%2C%22hostVrfPair%22%3A%7B%22hostName%22%3A%22GLO_INT_to_Hurri_West_US%22%2C%22vrfName%22%3A%22inet%22%7D%7D%7D&modalPanel=RAW_DATA&metric=jitter",
    # Jitter metrics for Dol-Sec
    f"https://www.cv-prod-euwest-2.arista.io/cv/devices/connectivity?active={ACTIVE}&fromOffset={FROM_OFFSET}&toOffset={TO_OFFSET}&modal=true&modalParams=%7B%22alternativeTitle%22%3A%22Jitter+for+KASI-LOS5-R201-BG01+%28inet+%2F+Ethernet2%29+to+DOL_SEC_to_AIRTEL_NIG%22%2C%22datasetId%22%3A%22JPE20050335%22%2C%22metricKey%22%3A%22JITTER_VRF%22%2C%22metricParams%22%3A%7B%22deviceId%22%3A%22JPE20050335%22%2C%22hostVrfIntf%22%3A%22Ethernet2%22%2C%22hostVrfPair%22%3A%7B%22hostName%22%3A%22DOL_SEC_to_AIRTEL_NIG%22%2C%22vrfName%22%3A%22inet%22%7D%7D%7D&modalPanel=RAW_DATA&metric=jitter",
    f"https://www.cv-prod-euwest-2.arista.io/cv/devices/connectivity?active={ACTIVE}&fromOffset={FROM_OFFSET}&toOffset={TO_OFFSET}&modal=true&modalParams=%7B%22alternativeTitle%22%3A%22Jitter+for+KASI-LOS5-R201-BG01+%28inet+%2F+Ethernet2%29+to+DOL_SEC_to_SEABON_ITA%22%2C%22datasetId%22%3A%22JPE20050335%22%2C%22metricKey%22%3A%22JITTER_VRF%22%2C%22metricParams%22%3A%7B%22deviceId%22%3A%22JPE20050335%22%2C%22hostVrfIntf%22%3A%22Ethernet2%22%2C%22hostVrfPair%22%3A%7B%22hostName%22%3A%22DOL_SEC_to_SEABON_ITA%22%2C%22vrfName%22%3A%22inet%22%7D%7D%7D&modalPanel=RAW_DATA&metric=jitter",
    f"https://www.cv-prod-euwest-2.arista.io/cv/devices/connectivity?active={ACTIVE}&fromOffset={FROM_OFFSET}&toOffset={TO_OFFSET}&modal=true&modalParams=%7B%22alternativeTitle%22%3A%22Jitter+for+KASI-LOS5-R201-BG01+%28inet+%2F+Ethernet2%29+to+DOL_SEC_to_TATA_East_US%22%2C%22datasetId%22%3A%22JPE20050335%22%2C%22metricKey%22%3A%22JITTER_VRF%22%2C%22metricParams%22%3A%7B%22deviceId%22%3A%22JPE20050335%22%2C%22hostVrfIntf%22%3A%22Ethernet2%22%2C%22hostVrfPair%22%3A%7B%22hostName%22%3A%22DOL_SEC_to_TATA_East_US%22%2C%22vrfName%22%3A%22inet%22%7D%7D%7D&modalPanel=RAW_DATA&metric=jitter",
    f"https://www.cv-prod-euwest-2.arista.io/cv/devices/connectivity?active={ACTIVE}&fromOffset={FROM_OFFSET}&toOffset={TO_OFFSET}&modal=true&modalParams=%7B%22alternativeTitle%22%3A%22Jitter+for+KASI-LOS5-R201-BG01+%28inet+%2F+Ethernet2%29+to+DOL_SEC_to_Hurri_West_US%22%2C%22datasetId%22%3A%22JPE20050335%22%2C%22metricKey%22%3A%22JITTER_VRF%22%2C%22metricParams%22%3A%7B%22deviceId%22%3A%22JPE20050335%22%2C%22hostVrfIntf%22%3A%22Ethernet2%22%2C%22hostVrfPair%22%3A%7B%22hostName%22%3A%22DOL_SEC_to_Hurri_West_US%22%2C%22vrfName%22%3A%22inet%22%7D%7D%7D&modalPanel=RAW_DATA&metric=jitter",
    # Jitter metric for Dol-Pri
    f"https://www.cv-prod-euwest-2.arista.io/cv/devices/connectivity?active={ACTIVE}&fromOffset={FROM_OFFSET}&toOffset={TO_OFFSET}&modal=true&modalParams=%7B%22alternativeTitle%22%3A%22Jitter+for+KASI-LOS5-R201-BG01+%28inet+%2F+Ethernet3%29+to+DOL_PRI_to_AIRTEL_NIG%22%2C%22datasetId%22%3A%22JPE20050335%22%2C%22metricKey%22%3A%22JITTER_VRF%22%2C%22metricParams%22%3A%7B%22deviceId%22%3A%22JPE20050335%22%2C%22hostVrfIntf%22%3A%22Ethernet3%22%2C%22hostVrfPair%22%3A%7B%22hostName%22%3A%22DOL_PRI_to_AIRTEL_NIG%22%2C%22vrfName%22%3A%22inet%22%7D%7D%7D&modalPanel=RAW_DATA&metric=jitter",
    f"https://www.cv-prod-euwest-2.arista.io/cv/devices/connectivity?active={ACTIVE}&fromOffset={FROM_OFFSET}&toOffset={TO_OFFSET}&modal=true&modalParams=%7B%22alternativeTitle%22%3A%22Jitter+for+KASI-LOS5-R201-BG01+%28inet+%2F+Ethernet3%29+to+DOL_PRI_to_SEABON_ITA%22%2C%22datasetId%22%3A%22JPE20050335%22%2C%22metricKey%22%3A%22JITTER_VRF%22%2C%22metricParams%22%3A%7B%22deviceId%22%3A%22JPE20050335%22%2C%22hostVrfIntf%22%3A%22Ethernet3%22%2C%22hostVrfPair%22%3A%7B%22hostName%22%3A%22DOL_PRI_to_SEABON_ITA%22%2C%22vrfName%22%3A%22inet%22%7D%7D%7D&modalPanel=RAW_DATA&metric=jitter",
    f"https://www.cv-prod-euwest-2.arista.io/cv/devices/connectivity?active={ACTIVE}&fromOffset={FROM_OFFSET}&toOffset={TO_OFFSET}&modal=true&modalParams=%7B%22alternativeTitle%22%3A%22Jitter+for+KASI-LOS5-R201-BG01+%28inet+%2F+Ethernet3%29+to+DOL_PRI_to_TATA_East_US%22%2C%22datasetId%22%3A%22JPE20050335%22%2C%22metricKey%22%3A%22JITTER_VRF%22%2C%22metricParams%22%3A%7B%22deviceId%22%3A%22JPE20050335%22%2C%22hostVrfIntf%22%3A%22Ethernet3%22%2C%22hostVrfPair%22%3A%7B%22hostName%22%3A%22DOL_PRI_to_TATA_East_US%22%2C%22vrfName%22%3A%22inet%22%7D%7D%7D&modalPanel=RAW_DATA&metric=jitter",
    f"https://www.cv-prod-euwest-2.arista.io/cv/devices/connectivity?active={ACTIVE}&fromOffset={FROM_OFFSET}&toOffset={TO_OFFSET}&modal=true&modalParams=%7B%22alternativeTitle%22%3A%22Jitter+for+KASI-LOS5-R201-BG01+%28inet+%2F+Ethernet3%29+to+DOL_PRI_to_Hurri_West_US%22%2C%22datasetId%22%3A%22JPE20050335%22%2C%22metricKey%22%3A%22JITTER_VRF%22%2C%22metricParams%22%3A%7B%22deviceId%22%3A%22JPE20050335%22%2C%22hostVrfIntf%22%3A%22Ethernet3%22%2C%22hostVrfPair%22%3A%7B%22hostName%22%3A%22DOL_PRI_to_Hurri_West_US%22%2C%22vrfName%22%3A%22inet%22%7D%7D%7D&modalPanel=RAW_DATA&metric=jitter",
    
    # Latency metric for Glo
    f"https://www.cv-prod-euwest-2.arista.io/cv/devices/connectivity?active={ACTIVE}&fromOffset={FROM_OFFSET}&toOffset={TO_OFFSET}&modal=true&modalParams=%7B%22alternativeTitle%22%3A%22Latency+for+KASI-LOS5-R201-BG01+%28inet+%2F+Ethernet1%29+to+GLO_INT_to_AIRTEL_NIG%22%2C%22datasetId%22%3A%22JPE20050335%22%2C%22metricKey%22%3A%22LATENCY_VRF%22%2C%22metricParams%22%3A%7B%22deviceId%22%3A%22JPE20050335%22%2C%22hostVrfIntf%22%3A%22Ethernet1%22%2C%22hostVrfPair%22%3A%7B%22hostName%22%3A%22GLO_INT_to_AIRTEL_NIG%22%2C%22vrfName%22%3A%22inet%22%7D%7D%7D&modalPanel=RAW_DATA&metric=latency",
    f"https://www.cv-prod-euwest-2.arista.io/cv/devices/connectivity?active={ACTIVE}&fromOffset={FROM_OFFSET}&toOffset={TO_OFFSET}&modal=true&modalParams=%7B%22alternativeTitle%22%3A%22Latency+for+KASI-LOS5-R201-BG01+%28inet+%2F+Ethernet1%29+to+GLO_INT_to_SEABON_ITA%22%2C%22datasetId%22%3A%22JPE20050335%22%2C%22metricKey%22%3A%22LATENCY_VRF%22%2C%22metricParams%22%3A%7B%22deviceId%22%3A%22JPE20050335%22%2C%22hostVrfIntf%22%3A%22Ethernet1%22%2C%22hostVrfPair%22%3A%7B%22hostName%22%3A%22GLO_INT_to_SEABON_ITA%22%2C%22vrfName%22%3A%22inet%22%7D%7D%7D&modalPanel=RAW_DATA&metric=latency",
    f"https://www.cv-prod-euwest-2.arista.io/cv/devices/connectivity?active={ACTIVE}&fromOffset={FROM_OFFSET}&toOffset={TO_OFFSET}&modal=true&modalParams=%7B%22alternativeTitle%22%3A%22Latency+for+KASI-LOS5-R201-BG01+%28inet+%2F+Ethernet1%29+to+GLO_INT_to_TATA_East_US%22%2C%22datasetId%22%3A%22JPE20050335%22%2C%22metricKey%22%3A%22LATENCY_VRF%22%2C%22metricParams%22%3A%7B%22deviceId%22%3A%22JPE20050335%22%2C%22hostVrfIntf%22%3A%22Ethernet1%22%2C%22hostVrfPair%22%3A%7B%22hostName%22%3A%22GLO_INT_to_TATA_East_US%22%2C%22vrfName%22%3A%22inet%22%7D%7D%7D&modalPanel=RAW_DATA&metric=latency",
    f"https://www.cv-prod-euwest-2.arista.io/cv/devices/connectivity?active={ACTIVE}&fromOffset={FROM_OFFSET}&toOffset={TO_OFFSET}&modal=true&modalParams=%7B%22alternativeTitle%22%3A%22Latency+for+KASI-LOS5-R201-BG01+%28inet+%2F+Ethernet1%29+to+GLO_INT_to_Hurri_West_US%22%2C%22datasetId%22%3A%22JPE20050335%22%2C%22metricKey%22%3A%22LATENCY_VRF%22%2C%22metricParams%22%3A%7B%22deviceId%22%3A%22JPE20050335%22%2C%22hostVrfIntf%22%3A%22Ethernet1%22%2C%22hostVrfPair%22%3A%7B%22hostName%22%3A%22GLO_INT_to_Hurri_West_US%22%2C%22vrfName%22%3A%22inet%22%7D%7D%7D&modalPanel=RAW_DATA&metric=latency",
    # Latency metric for DOL_SEC
    f"https://www.cv-prod-euwest-2.arista.io/cv/devices/connectivity?active={ACTIVE}&fromOffset={FROM_OFFSET}&toOffset={TO_OFFSET}&modal=true&modalParams=%7B%22alternativeTitle%22%3A%22Latency+for+KASI-LOS5-R201-BG01+%28inet+%2F+Ethernet2%29+to+DOL_SEC_to_AIRTEL_NIG%22%2C%22datasetId%22%3A%22JPE20050335%22%2C%22metricKey%22%3A%22LATENCY_VRF%22%2C%22metricParams%22%3A%7B%22deviceId%22%3A%22JPE20050335%22%2C%22hostVrfIntf%22%3A%22Ethernet2%22%2C%22hostVrfPair%22%3A%7B%22hostName%22%3A%22DOL_SEC_to_AIRTEL_NIG%22%2C%22vrfName%22%3A%22inet%22%7D%7D%7D&modalPanel=RAW_DATA&metric=latency",
    f"https://www.cv-prod-euwest-2.arista.io/cv/devices/connectivity?active={ACTIVE}&fromOffset={FROM_OFFSET}&toOffset={TO_OFFSET}&modal=true&modalParams=%7B%22alternativeTitle%22%3A%22Latency+for+KASI-LOS5-R201-BG01+%28inet+%2F+Ethernet2%29+to+DOL_SEC_to_SEABON_ITA%22%2C%22datasetId%22%3A%22JPE20050335%22%2C%22metricKey%22%3A%22LATENCY_VRF%22%2C%22metricParams%22%3A%7B%22deviceId%22%3A%22JPE20050335%22%2C%22hostVrfIntf%22%3A%22Ethernet2%22%2C%22hostVrfPair%22%3A%7B%22hostName%22%3A%22DOL_SEC_to_SEABON_ITA%22%2C%22vrfName%22%3A%22inet%22%7D%7D%7D&modalPanel=RAW_DATA&metric=latency",
    f"https://www.cv-prod-euwest-2.arista.io/cv/devices/connectivity?active={ACTIVE}&fromOffset={FROM_OFFSET}&toOffset={TO_OFFSET}&modal=true&modalParams=%7B%22alternativeTitle%22%3A%22Latency+for+KASI-LOS5-R201-BG01+%28inet+%2F+Ethernet2%29+to+DOL_SEC_to_TATA_East_US%22%2C%22datasetId%22%3A%22JPE20050335%22%2C%22metricKey%22%3A%22LATENCY_VRF%22%2C%22metricParams%22%3A%7B%22deviceId%22%3A%22JPE20050335%22%2C%22hostVrfIntf%22%3A%22Ethernet2%22%2C%22hostVrfPair%22%3A%7B%22hostName%22%3A%22DOL_SEC_to_TATA_East_US%22%2C%22vrfName%22%3A%22inet%22%7D%7D%7D&modalPanel=RAW_DATA&metric=latency",
    f"https://www.cv-prod-euwest-2.arista.io/cv/devices/connectivity?active={ACTIVE}&fromOffset={FROM_OFFSET}&toOffset={TO_OFFSET}&modal=true&modalParams=%7B%22alternativeTitle%22%3A%22Latency+for+KASI-LOS5-R201-BG01+%28inet+%2F+Ethernet2%29+to+DOL_SEC_to_Hurri_West_US%22%2C%22datasetId%22%3A%22JPE20050335%22%2C%22metricKey%22%3A%22LATENCY_VRF%22%2C%22metricParams%22%3A%7B%22deviceId%22%3A%22JPE20050335%22%2C%22hostVrfIntf%22%3A%22Ethernet2%22%2C%22hostVrfPair%22%3A%7B%22hostName%22%3A%22DOL_SEC_to_Hurri_West_US%22%2C%22vrfName%22%3A%22inet%22%7D%7D%7D&modalPanel=RAW_DATA&metric=latency",
    # Latency metric for DOL_PRI
    f"https://www.cv-prod-euwest-2.arista.io/cv/devices/connectivity?active={ACTIVE}&fromOffset={FROM_OFFSET}&toOffset={TO_OFFSET}&modal=true&modalParams=%7B%22alternativeTitle%22%3A%22Latency+for+KASI-LOS5-R201-BG01+%28inet+%2F+Ethernet3%29+to+DOL_PRI_to_AIRTEL_NIG%22%2C%22datasetId%22%3A%22JPE20050335%22%2C%22metricKey%22%3A%22LATENCY_VRF%22%2C%22metricParams%22%3A%7B%22deviceId%22%3A%22JPE20050335%22%2C%22hostVrfIntf%22%3A%22Ethernet3%22%2C%22hostVrfPair%22%3A%7B%22hostName%22%3A%22DOL_PRI_to_AIRTEL_NIG%22%2C%22vrfName%22%3A%22inet%22%7D%7D%7D&modalPanel=RAW_DATA&metric=latency",
    f"https://www.cv-prod-euwest-2.arista.io/cv/devices/connectivity?active={ACTIVE}&fromOffset={FROM_OFFSET}&toOffset={TO_OFFSET}&modal=true&modalParams=%7B%22alternativeTitle%22%3A%22Latency+for+KASI-LOS5-R201-BG01+%28inet+%2F+Ethernet3%29+to+DOL_PRI_to_SEABON_ITA%22%2C%22datasetId%22%3A%22JPE20050335%22%2C%22metricKey%22%3A%22LATENCY_VRF%22%2C%22metricParams%22%3A%7B%22deviceId%22%3A%22JPE20050335%22%2C%22hostVrfIntf%22%3A%22Ethernet3%22%2C%22hostVrfPair%22%3A%7B%22hostName%22%3A%22DOL_PRI_to_SEABON_ITA%22%2C%22vrfName%22%3A%22inet%22%7D%7D%7D&modalPanel=RAW_DATA&metric=latency",
    f"https://www.cv-prod-euwest-2.arista.io/cv/devices/connectivity?active={ACTIVE}&fromOffset={FROM_OFFSET}&toOffset={TO_OFFSET}&modal=true&modalParams=%7B%22alternativeTitle%22%3A%22Latency+for+KASI-LOS5-R201-BG01+%28inet+%2F+Ethernet3%29+to+DOL_PRI_to_TATA_East_US%22%2C%22datasetId%22%3A%22JPE20050335%22%2C%22metricKey%22%3A%22LATENCY_VRF%22%2C%22metricParams%22%3A%7B%22deviceId%22%3A%22JPE20050335%22%2C%22hostVrfIntf%22%3A%22Ethernet3%22%2C%22hostVrfPair%22%3A%7B%22hostName%22%3A%22DOL_PRI_to_TATA_East_US%22%2C%22vrfName%22%3A%22inet%22%7D%7D%7D&modalPanel=RAW_DATA&metric=latency",
    f"https://www.cv-prod-euwest-2.arista.io/cv/devices/connectivity?active={ACTIVE}&fromOffset={FROM_OFFSET}&toOffset={TO_OFFSET}&modal=true&modalParams=%7B%22alternativeTitle%22%3A%22Latency+for+KASI-LOS5-R201-BG01+%28inet+%2F+Ethernet3%29+to+DOL_PRI_to_Hurri_West_US%22%2C%22datasetId%22%3A%22JPE20050335%22%2C%22metricKey%22%3A%22LATENCY_VRF%22%2C%22metricParams%22%3A%7B%22deviceId%22%3A%22JPE20050335%22%2C%22hostVrfIntf%22%3A%22Ethernet3%22%2C%22hostVrfPair%22%3A%7B%22hostName%22%3A%22DOL_PRI_to_Hurri_West_US%22%2C%22vrfName%22%3A%22inet%22%7D%7D%7D&modalPanel=RAW_DATA&metric=latency",

    # Packet Loss metric for GLO_INT
    f"https://www.cv-prod-euwest-2.arista.io/cv/devices/connectivity?active={ACTIVE}&fromOffset={FROM_OFFSET}&toOffset={TO_OFFSET}&modal=true&modalParams=%7B%22alternativeTitle%22%3A%22Packet+Loss+for+KASI-LOS5-R201-BG01+%28inet+%2F+Ethernet1%29+to+GLO_INT_to_AIRTEL_NIG%22%2C%22datasetId%22%3A%22JPE20050335%22%2C%22metricKey%22%3A%22PACKET_LOSS_VRF%22%2C%22metricParams%22%3A%7B%22deviceId%22%3A%22JPE20050335%22%2C%22hostVrfIntf%22%3A%22Ethernet1%22%2C%22hostVrfPair%22%3A%7B%22hostName%22%3A%22GLO_INT_to_AIRTEL_NIG%22%2C%22vrfName%22%3A%22inet%22%7D%7D%7D&modalPanel=RAW_DATA&metric=loss",
    f"https://www.cv-prod-euwest-2.arista.io/cv/devices/connectivity?active={ACTIVE}&fromOffset={FROM_OFFSET}&toOffset={TO_OFFSET}&modal=true&modalParams=%7B%22alternativeTitle%22%3A%22Packet+Loss+for+KASI-LOS5-R201-BG01+%28inet+%2F+Ethernet1%29+to+GLO_INT_to_SEABON_ITA%22%2C%22datasetId%22%3A%22JPE20050335%22%2C%22metricKey%22%3A%22PACKET_LOSS_VRF%22%2C%22metricParams%22%3A%7B%22deviceId%22%3A%22JPE20050335%22%2C%22hostVrfIntf%22%3A%22Ethernet1%22%2C%22hostVrfPair%22%3A%7B%22hostName%22%3A%22GLO_INT_to_SEABON_ITA%22%2C%22vrfName%22%3A%22inet%22%7D%7D%7D&modalPanel=RAW_DATA&metric=loss",
    f"https://www.cv-prod-euwest-2.arista.io/cv/devices/connectivity?active={ACTIVE}&fromOffset={FROM_OFFSET}&toOffset={TO_OFFSET}&modal=true&modalParams=%7B%22alternativeTitle%22%3A%22Packet+Loss+for+KASI-LOS5-R201-BG01+%28inet+%2F+Ethernet1%29+to+GLO_INT_to_TATA_East_US%22%2C%22datasetId%22%3A%22JPE20050335%22%2C%22metricKey%22%3A%22PACKET_LOSS_VRF%22%2C%22metricParams%22%3A%7B%22deviceId%22%3A%22JPE20050335%22%2C%22hostVrfIntf%22%3A%22Ethernet1%22%2C%22hostVrfPair%22%3A%7B%22hostName%22%3A%22GLO_INT_to_TATA_East_US%22%2C%22vrfName%22%3A%22inet%22%7D%7D%7D&modalPanel=RAW_DATA&metric=loss",
    f"https://www.cv-prod-euwest-2.arista.io/cv/devices/connectivity?active={ACTIVE}&fromOffset={FROM_OFFSET}&toOffset={TO_OFFSET}&modal=true&modalParams=%7B%22alternativeTitle%22%3A%22Packet+Loss+for+KASI-LOS5-R201-BG01+%28inet+%2F+Ethernet1%29+to+GLO_INT_to_Hurri_West_US%22%2C%22datasetId%22%3A%22JPE20050335%22%2C%22metricKey%22%3A%22PACKET_LOSS_VRF%22%2C%22metricParams%22%3A%7B%22deviceId%22%3A%22JPE20050335%22%2C%22hostVrfIntf%22%3A%22Ethernet1%22%2C%22hostVrfPair%22%3A%7B%22hostName%22%3A%22GLO_INT_to_Hurri_West_US%22%2C%22vrfName%22%3A%22inet%22%7D%7D%7D&modalPanel=RAW_DATA&metric=loss",
    # Packet Loss metric for DOL_SEC
    f"https://www.cv-prod-euwest-2.arista.io/cv/devices/connectivity?active={ACTIVE}&fromOffset={FROM_OFFSET}&toOffset={TO_OFFSET}&modal=true&modalParams=%7B%22alternativeTitle%22%3A%22Packet+Loss+for+KASI-LOS5-R201-BG01+%28inet+%2F+Ethernet2%29+to+DOL_SEC_to_AIRTEL_NIG%22%2C%22datasetId%22%3A%22JPE20050335%22%2C%22metricKey%22%3A%22PACKET_LOSS_VRF%22%2C%22metricParams%22%3A%7B%22deviceId%22%3A%22JPE20050335%22%2C%22hostVrfIntf%22%3A%22Ethernet2%22%2C%22hostVrfPair%22%3A%7B%22hostName%22%3A%22DOL_SEC_to_AIRTEL_NIG%22%2C%22vrfName%22%3A%22inet%22%7D%7D%7D&modalPanel=RAW_DATA&metric=loss",
    f"https://www.cv-prod-euwest-2.arista.io/cv/devices/connectivity?active={ACTIVE}&fromOffset={FROM_OFFSET}&toOffset={TO_OFFSET}&modal=true&modalParams=%7B%22alternativeTitle%22%3A%22Packet+Loss+for+KASI-LOS5-R201-BG01+%28inet+%2F+Ethernet2%29+to+DOL_SEC_to_SEABON_ITA%22%2C%22datasetId%22%3A%22JPE20050335%22%2C%22metricKey%22%3A%22PACKET_LOSS_VRF%22%2C%22metricParams%22%3A%7B%22deviceId%22%3A%22JPE20050335%22%2C%22hostVrfIntf%22%3A%22Ethernet2%22%2C%22hostVrfPair%22%3A%7B%22hostName%22%3A%22DOL_SEC_to_SEABON_ITA%22%2C%22vrfName%22%3A%22inet%22%7D%7D%7D&modalPanel=RAW_DATA&metric=loss",
    f"https://www.cv-prod-euwest-2.arista.io/cv/devices/connectivity?active={ACTIVE}&fromOffset={FROM_OFFSET}&toOffset={TO_OFFSET}&modal=true&modalParams=%7B%22alternativeTitle%22%3A%22Packet+Loss+for+KASI-LOS5-R201-BG01+%28inet+%2F+Ethernet2%29+to+DOL_SEC_to_TATA_East_US%22%2C%22datasetId%22%3A%22JPE20050335%22%2C%22metricKey%22%3A%22PACKET_LOSS_VRF%22%2C%22metricParams%22%3A%7B%22deviceId%22%3A%22JPE20050335%22%2C%22hostVrfIntf%22%3A%22Ethernet2%22%2C%22hostVrfPair%22%3A%7B%22hostName%22%3A%22DOL_SEC_to_TATA_East_US%22%2C%22vrfName%22%3A%22inet%22%7D%7D%7D&modalPanel=RAW_DATA&metric=loss",
    f"https://www.cv-prod-euwest-2.arista.io/cv/devices/connectivity?active={ACTIVE}&fromOffset={FROM_OFFSET}&toOffset={TO_OFFSET}&modal=true&modalParams=%7B%22alternativeTitle%22%3A%22Packet+Loss+for+KASI-LOS5-R201-BG01+%28inet+%2F+Ethernet2%29+to+DOL_SEC_to_Hurri_West_US%22%2C%22datasetId%22%3A%22JPE20050335%22%2C%22metricKey%22%3A%22PACKET_LOSS_VRF%22%2C%22metricParams%22%3A%7B%22deviceId%22%3A%22JPE20050335%22%2C%22hostVrfIntf%22%3A%22Ethernet2%22%2C%22hostVrfPair%22%3A%7B%22hostName%22%3A%22DOL_SEC_to_Hurri_West_US%22%2C%22vrfName%22%3A%22inet%22%7D%7D%7D&modalPanel=RAW_DATA&metric=loss",
    # Packet Loss metric for DOL_PRI
    f"https://www.cv-prod-euwest-2.arista.io/cv/devices/connectivity?active={ACTIVE}&fromOffset={FROM_OFFSET}&toOffset={TO_OFFSET}&modal=true&modalParams=%7B%22alternativeTitle%22%3A%22Packet+Loss+for+KASI-LOS5-R201-BG01+%28inet+%2F+Ethernet3%29+to+DOL_PRI_to_AIRTEL_NIG%22%2C%22datasetId%22%3A%22JPE20050335%22%2C%22metricKey%22%3A%22PACKET_LOSS_VRF%22%2C%22metricParams%22%3A%7B%22deviceId%22%3A%22JPE20050335%22%2C%22hostVrfIntf%22%3A%22Ethernet3%22%2C%22hostVrfPair%22%3A%7B%22hostName%22%3A%22DOL_PRI_to_AIRTEL_NIG%22%2C%22vrfName%22%3A%22inet%22%7D%7D%7D&modalPanel=RAW_DATA&metric=loss",
    f"https://www.cv-prod-euwest-2.arista.io/cv/devices/connectivity?active={ACTIVE}&fromOffset={FROM_OFFSET}&toOffset={TO_OFFSET}&modal=true&modalParams=%7B%22alternativeTitle%22%3A%22Packet+Loss+for+KASI-LOS5-R201-BG01+%28inet+%2F+Ethernet3%29+to+DOL_PRI_to_SEABON_ITA%22%2C%22datasetId%22%3A%22JPE20050335%22%2C%22metricKey%22%3A%22PACKET_LOSS_VRF%22%2C%22metricParams%22%3A%7B%22deviceId%22%3A%22JPE20050335%22%2C%22hostVrfIntf%22%3A%22Ethernet3%22%2C%22hostVrfPair%22%3A%7B%22hostName%22%3A%22DOL_PRI_to_SEABON_ITA%22%2C%22vrfName%22%3A%22inet%22%7D%7D%7D&modalPanel=RAW_DATA&metric=loss",
    f"https://www.cv-prod-euwest-2.arista.io/cv/devices/connectivity?active={ACTIVE}&fromOffset={FROM_OFFSET}&toOffset={TO_OFFSET}&modal=true&modalParams=%7B%22alternativeTitle%22%3A%22Packet+Loss+for+KASI-LOS5-R201-BG01+%28inet+%2F+Ethernet3%29+to+DOL_PRI_to_TATA_East_US%22%2C%22datasetId%22%3A%22JPE20050335%22%2C%22metricKey%22%3A%22PACKET_LOSS_VRF%22%2C%22metricParams%22%3A%7B%22deviceId%22%3A%22JPE20050335%22%2C%22hostVrfIntf%22%3A%22Ethernet3%22%2C%22hostVrfPair%22%3A%7B%22hostName%22%3A%22DOL_PRI_to_TATA_East_US%22%2C%22vrfName%22%3A%22inet%22%7D%7D%7D&modalPanel=RAW_DATA&metric=loss",
    f"https://www.cv-prod-euwest-2.arista.io/cv/devices/connectivity?active={ACTIVE}&fromOffset={FROM_OFFSET}&toOffset={TO_OFFSET}&modal=true&modalParams=%7B%22alternativeTitle%22%3A%22Packet+Loss+for+KASI-LOS5-R201-BG01+%28inet+%2F+Ethernet3%29+to+DOL_PRI_to_Hurri_West_US%22%2C%22datasetId%22%3A%22JPE20050335%22%2C%22metricKey%22%3A%22PACKET_LOSS_VRF%22%2C%22metricParams%22%3A%7B%22deviceId%22%3A%22JPE20050335%22%2C%22hostVrfIntf%22%3A%22Ethernet3%22%2C%22hostVrfPair%22%3A%7B%22hostName%22%3A%22DOL_PRI_to_Hurri_West_US%22%2C%22vrfName%22%3A%22inet%22%7D%7D%7D&modalPanel=RAW_DATA&metric=loss",

    ]

    wait = WebDriverWait(driver, 30)

    # Benchmarking: record per-URL elapsed times
    run_start = time.perf_counter()
    timings = []  # list of tuples (url, elapsed_seconds, succeeded)

    try:
        for url in urls:
            print(f"🔎 Opening URL: {url}")
            driver.get(url)

            # brief wait for the modal/UI to settle (prefer explicit wait for export control)
            try:
                WebDriverWait(driver, 1).until(lambda d: find_export_button_fast(d) is not None)
            except TimeoutException:
                pass

            start = time.perf_counter()
            # Use fast_mode to return quickly after click confirmation
            succeeded = click_export_and_handle_modal(driver, wait, fast_mode=True)
            elapsed = time.perf_counter() - start
            timings.append((url, elapsed, bool(succeeded)))

            if succeeded:
                print(f"✅ Export triggered for URL: {url} (took {elapsed:.2f}s)")
            else:
                print(f"❌ Failed to trigger Export for URL: {url} (took {elapsed:.2f}s)")

            # ensure the page finished processing before next URL (tiny wait)
            try:
                WebDriverWait(driver, 0.2).until(lambda d: d.execute_script("return document.readyState") == "complete")
            except TimeoutException:
                pass

    finally:
        # If the final export likely succeeded, wait briefly to let the download start/finish
        if timings and timings[-1][2]:
            print("⏳ Final export detected as successful; waiting 2s to allow download to start/finish...")
            time.sleep(2)
        driver.quit()
        run_total = time.perf_counter() - run_start
        # Print lightweight benchmark summary
        total_urls = len(timings)
        total_success = sum(1 for _, _, s in timings if s)
        print("\n📊 Export benchmark summary:")
        print(f" - Total URLs: {total_urls}, Succeeded: {total_success}, Failed: {total_urls - total_success}")
        print(f" - Total run time: {run_total:.2f}s, Avg per URL: {(run_total / total_urls) if total_urls else 0:.2f}s")
        for i, (u, t, s) in enumerate(timings, 1):
            short = (u if len(u) <= 80 else u[:77] + '...')
            print(f"   {i:02d}. {short} -> {t:.2f}s {'OK' if s else 'FAIL'})")


# Main
if __name__ == "__main__":
    print("🔎 Fetching inventory from CVaaS...")
    devices = get_inventory()
    serial = get_device_serial(devices, TARGET_HOSTNAME)
    print(f"✅ Found {TARGET_HOSTNAME} with serial {serial}")

    export_via_gui(serial)
