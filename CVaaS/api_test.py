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

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# === CONFIG ===
BASE_URL = "https://www.cv-prod-euwest-2.arista.io/cvpservice"
ACCESS_TOKEN = "eyJhbGciOiJFUzI1NiIsInR5cCI6IkpXVCJ9.eyJkaWQiOjY5NTkxNjIyNjczNTUxNTM3NDksImRzbiI6IlN1bGVpbWFuLkFiZHVsc2FsYW0iLCJkc3QiOiJ1c2VyIiwiZW1haWwiOiJzdWxlaW1hbi5hYmR1bHNhbGFtQGthc2ljbG91ZC5jb20iLCJleHAiOjE3NTgzMDAxMzksImlhdCI6MTc1ODIxMzc0MCwib2dpIjo2OTU5MTYyMjY3MzU1MDY5MjM2LCJvZ24iOiJrYXNpY2xvdWQiLCJzaWQiOiI4Yzg2OTU0NzQwNzRhMjlmM2JkMDAyZWVlNmFhOTc3ODhhMmViMWFkY2MxYTBiYWRkOGFkODRmYmY4OWM0YzM4LTZPY2xGdXRnR3hrMlk5a0g5bHdackNVeWhsRGRSNDVQakRmeEp5WHoifQ.MBGp7Pbgt98AJ5_LQrJDnCtGGTQvRVnTGq_vQ-9XJmLyYg9h9MMIs56CVwTvrdYOIMMEcSwwdJgZd_wOYsqjbQ"
TARGET_HOSTNAME = "KASI-LOS5-R201-BG01"

headers = {
    "Authorization": f"Bearer {ACCESS_TOKEN}",
    "Accept": "application/json",
    "Content-Type": "application/json"
}

def get_inventory():
    resp = requests.get(f"{BASE_URL}/inventory/devices", headers=headers, verify=False)
    resp.raise_for_status()
    return resp.json()

def get_device_serial(devices, hostname):
    device = next((d for d in devices if d["hostname"] == hostname), None)
    if not device:
        raise Exception(f"Device {hostname} not found")
    return device["serialNumber"]

def export_via_gui(serial):
    print("🌐 Opening Selenium with clean Edge profile...")
    options = webdriver.EdgeOptions()
    options.add_argument("--start-maximized")
    options.add_argument(r"--user-data-dir=C:\Users\SuleimanAbdulsalam\AppData\Local\Microsoft\Edge\User Data\SeleniumProfile")
    options.add_argument("profile-directory=Default")  # Default inside SeleniumProfile

    driver = webdriver.Edge(options=options)

    try:
        url = f"https://www.cv-prod-euwest-2.arista.io/cv/devices/ethernet-stats/{serial}?modal=true&modalParams=%7B%22datasetId%22%3A%22{serial}%22%2C%22metricKey%22%3A%22INTERFACE_IN_BITRATE%22%2C%22metricParams%22%3A%7B%22aggregationIntervalOverride%22%3A%22default%22%2C%22deviceId%22%3A%22{serial}%22%2C%22intf%22%3A%22Ethernet1%22%7D%7D&modalPanel=RAW_DATA"
        driver.get(url)

        wait = WebDriverWait(driver, 20)  # wait up to 20 seconds

        def find_export_button(d):
            return locate_export_button(d)

        def locate_export_button(driver):
            try:
                elems = driver.find_elements(By.XPATH, "//button | //a | //*[@role='button']")
            except StaleElementReferenceException:
                return False
            for e in elems:
                try:
                    if not e.is_displayed():
                        continue

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
                        continue

                except StaleElementReferenceException:
                    continue
            return False

        export_button = wait.until(lambda d: locate_export_button(d) or False)
        try:
            try:
                export_button.click()
            except (ElementClickInterceptedException, ElementNotInteractableException):
                try:
                    driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", export_button)
                    time.sleep(0.2)
                    export_button.click()
                except Exception:
                    driver.execute_script("arguments[0].click();", export_button)
        except Exception as e:
            print(f"❌ Failed to click Export button: {e}")
        else:
            print("✅ Export triggered, check Downloads folder")

        # Optional: wait a few seconds for download
        time.sleep(5)

    except TimeoutException:
        print("❌ Timed out waiting for Export button")
    except NoSuchElementException:
        print("❌ Export element not found on page")
    finally:
        driver.quit()

if __name__ == "__main__":
    print("🔎 Fetching inventory from CVaaS...")
    devices = get_inventory()
    serial = get_device_serial(devices, TARGET_HOSTNAME)
    print(f"✅ Found {TARGET_HOSTNAME} with serial {serial}")

    export_via_gui(serial)
