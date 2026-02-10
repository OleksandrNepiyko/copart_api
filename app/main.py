
import re
from pathlib import Path
import json
import requests
import time
from requests_html import HTMLSession
import os
from datetime import datetime
from seleniumbase import SB
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading
import random

from fastapi import FastAPI
from typing import Optional

tech_json_path = Path('app/tech_json')
res_json_path = Path('app/res_json')
SESSION = requests.Session()
POST_COUNT = 0
POST_LIMITER = 1000  # Number of POST requests before refreshing
#session (it includes pages and photos requests, so one full page = 1 page reques + 20 photos requests = 21 POST requests per full page)

SESSION_LOCK = threading.RLock()

PROXY_HOST = "109.236.80.2"
PROXY_PORT = "15259"
PROXY_USER = None
PROXY_PASS = None

if PROXY_USER and PROXY_PASS:
    PROXY_STRING = f"{PROXY_USER}:{PROXY_PASS}@{PROXY_HOST}:{PROXY_PORT}"
else:
    PROXY_STRING = f"{PROXY_HOST}:{PROXY_PORT}"

# Global Session Object
# This acts as the "bridge" between the token extractor and safe_post.
SESSION = requests.Session()

app = FastAPI()

def save_error(error_obj):
    #if an error occurs it should be saved here (only problems in automatic part of the program will be saved)
    error_obj['time_of_errror'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(tech_json_path / 'errors.json', 'a', encoding='utf-8') as f:
        json.dump(error_obj, f, indent=2, ensure_ascii=False)
        f.write(',\n')

def kill_chrome_processes():
    """Force kill stuck chrome/driver processes to prevent port errors on Windows."""
    if os.name == 'nt':
        try:
            os.system("taskkill /f /im chrome.exe >nul 2>&1")
            os.system("taskkill /f /im chromedriver.exe >nul 2>&1")
        except:
            pass

def get_copart_session_data(headless=False):
    """
    Launches a browser (UC mode), bypasses Cloudflare/CAPTCHA,
    and returns a dictionary of cookies and headers.
    """
    kill_chrome_processes()

    my_proxy = "109.236.80.2:15259"

    # Base structure for the result
    data = {
        "cookies": {},
        "headers": {
            "User-Agent": "",
            "X-XSRF-TOKEN": "",
            "X-Requested-With": "XMLHttpRequest", # Critical for Copart POST requests
            "Content-Type": "application/json;charset=UTF-8"
        }
    }

    # uc=True is mandatory for Cloudflare bypass
    # with SB(uc=True, incognito=True, test=True, headless=headless) as sb:

    with SB(uc=True, incognito=True, headless=headless, proxy=PROXY_STRING) as sb:
    # with SB(uc=True, incognito=True, headless=headless) as sb:
        try:
            sb.open("https://www.copart.com/vehicleFinder")

            # --- Smart Wait Logic ---
            # Loops for up to 60s to ensure page is fully loaded and CAPTCHA is solved
            page_loaded = False
            for _ in range(60):
                # Check for success indicators (URL or Element)
                if "vehicle" in sb.get_current_url().lower() and \
                   (sb.is_element_visible('#serverSideDataTable') or sb.is_element_visible('.inner-wrap')):
                    page_loaded = True
                    break

                # Auto-solve Cloudflare checkbox if visible
                if sb.is_element_visible('iframe[src*="cloudflare"]'):
                    sb.uc_gui_click_captcha()

                time.sleep(1)

            if not page_loaded:
                raise TimeoutError("Copart page failed to load (Cloudflare or Timeout).")

            time.sleep(2) # Stabilization time for final cookies

            # --- Data Extraction ---
            # 1. User Agent
            data["headers"]["User-Agent"] = sb.get_user_agent()

            # 2. Cookies (via CDP for completeness)
            cookies_data = sb.cdp.get_all_cookies()
            cookie_dict = {}
            xsrf_token = None

            for cookie in cookies_data:
                # Handle SeleniumBase object vs dict differences
                if isinstance(cookie, dict):
                    name = cookie.get('name', '')
                    value = cookie.get('value', '')
                else:
                    name = getattr(cookie, 'name', '')
                    value = getattr(cookie, 'value', '')

                if name:
                    cookie_dict[name] = value
                    # Capture XSRF token if found in cookies
                    if 'xsrf' in name.lower() or 'csrf' in name.lower():
                        xsrf_token = value

            data["cookies"] = cookie_dict

            # 3. XSRF Token (Check Cookies -> then LocalStorage)
            if xsrf_token:
                data["headers"]["X-XSRF-TOKEN"] = xsrf_token
            else:
                try:
                    ls = sb.execute_script("return window.localStorage;")
                    for k, v in ls.items():
                        if 'xsrf' in k.lower():
                            data["headers"]["X-XSRF-TOKEN"] = v
                            break
                except: pass

            return data

        except Exception as e:
            print(f"Error fetching Copart session data: {e}")
            save_error({
                'error_type': f"get_copart_session_data() Exception: {e}"
            })
            return None

def refresh_copart_session(headless=False):
    """
    Helper function to update the global SESSION object with a strict timeout.
    """
    print("taking cookies and headers")
    global SESSION

    # Внутрішня функція для запуску в окремому потоці
    def _get_session_task():
        return get_copart_session_data(headless=headless)

    session_retry_counter = 0
    session_data = None

    while not session_data:
        # Логіка сну (як у вашому коді), але пропускаємо сон для першої спроби (counter=0)
        if session_retry_counter > 0:
            sleep_time = 120 if session_retry_counter <= 3 else 300
            print(f"Waiting {sleep_time}s before retry...")
            time.sleep(sleep_time)

        session_retry_counter += 1
        print(f"Attempt to take cookies and headers #{session_retry_counter}")

        # Гарантовано вбиваємо процеси перед стартом, щоб мати чистий стан
        kill_chrome_processes()

        executor = ThreadPoolExecutor(max_workers=1)
        future = executor.submit(_get_session_task)

        try:
            session_data = future.result(timeout=60)
            executor.shutdown(wait=True)

        except TimeoutError:
            print(f"TIMEOUT: get_copart_session_data took longer than 60s.")

            # 1. Спочатку вбиваємо Chrome, щоб спробувати "розморозити" потік
            kill_chrome_processes()

            # Кажемо екзекутору закритися, але НЕ ЧЕКАТИ завершення потоку
            # Це дозволяє головному циклу while продовжити роботу негайно
            executor.shutdown(wait=False)

            session_data = None

        except Exception as e:
            print(f"Error executing session update: {e}")
            executor.shutdown(wait=False) # На випадок інших помилок теж не чекаємо
            session_data = None

    # Якщо ми вийшли з циклу, значить session_data отримано
    if session_data:
        print("session refreshed successfully")
        # Оновлюємо глобальну сесію під замком, якщо потрібно (хоча ви викликаєте це в одному потоці)
        with SESSION_LOCK:
            # === ГОЛОВНА ЗМІНА ТУТ ===
            # Ми викидаємо старий об'єкт SESSION на смітник і створюємо чистий.
            # Це вбиває всі старі завислі TCP-пули.
            SESSION = requests.Session()

            proxies = {
                "http": f"http://{PROXY_STRING}",
                "https": f"http://{PROXY_STRING}",
            }
            SESSION.proxies.update(proxies)

            SESSION.headers.update(session_data['headers'])
            SESSION.cookies.update(session_data['cookies'])
        return True

    return False

def safe_get(url, **kwargs):
    global POST_COUNT
    global POST_LIMITER

    if 'timeout' not in kwargs:
        kwargs['timeout'] = 30

    # Використовуємо той самий лічильник, що і для POST, щоб освіжати сесію
    with SESSION_LOCK:
        if POST_COUNT >= POST_LIMITER:
            print(f"[SafeGet] Limit {POST_LIMITER} reached. Refreshing session...")
            if not refresh_copart_session():
                raise RuntimeError("Failed to refresh session.")
            POST_COUNT = 0
        POST_COUNT += 1

    for attempt in range(5):
        try:
            response = SESSION.get(url, **kwargs)

            # --- Аналіз відповіді ---
            content_type = response.headers.get("Content-Type", "")
            # Успіх: 200 ОК і це JSON
            if response.status_code == 200 and "application/json" in content_type:
                return response

            # Якщо 404 - це означає лот не знайдено (видалений). Це НЕ помилка сесії.
            if response.status_code == 404:
                print(f"[SafeGet] 404 Not Found for {url} (Lot might be removed)")
                return response # Повертаємо як є, обробимо зовні

            # М'який блок (200 OK, але HTML)
            is_soft_block = (response.status_code == 200 and "application/json" not in content_type)

            # Помилки, що вимагають оновлення сесії
            if response.status_code in [403, 429, 503] or is_soft_block:
                reason = "Soft Block (HTML)" if is_soft_block else f"Status {response.status_code}"
                print(f"[SafeGet] Issue: {reason}. Attempt {attempt+1}/5. Refreshing...")

                with SESSION_LOCK:
                    time.sleep(random.uniform(2, 4))
                    refresh_copart_session()
                    POST_COUNT = 0
                continue

        except requests.exceptions.ConnectionError:
            print(f"[SafeGet] Connection error, retry {attempt+1}/5")
            time.sleep(5)
        except Exception as e:
             print(f"[SafeGet] Request error: {e}")
             with SESSION_LOCK:
                 refresh_copart_session()

    print("[SafeGet] Failed after 5 retries.")
    dummy = requests.Response()
    dummy.status_code = 500
    dummy._content = b"{}"
    return dummy

def safe_post(url, **kwargs):
    global POST_COUNT
    global POST_LIMITER

    if 'timeout' not in kwargs:
        kwargs['timeout'] = 30

    # 1. Перевірка лічильника (стандартна процедура)
    with SESSION_LOCK:
        if POST_COUNT >= POST_LIMITER:
            print(f"[SafePost] Limit {POST_LIMITER} reached. Refreshing session...")
            if not refresh_copart_session():
                raise RuntimeError("Failed to refresh session.")
            POST_COUNT = 0
        POST_COUNT += 1

    # 2. Виконуємо запит з логікою "Refresh on Error"
    for attempt in range(5):
        try:
            # print(f"[SafePost] Sending request (Attempt {attempt+1})...")
            response = SESSION.post(url, **kwargs)
            # print(f"[SafePost] Received response: {response.status_code}")

            # Якщо успіх (200) - перевіряємо, чи це дійсно JSON, а не сторінка блокування Cloudflare
            content_type = response.headers.get("Content-Type", "")
            is_soft_block = (response.status_code == 200 and "application/json" not in content_type)

            if response.status_code == 200 and not is_soft_block:
                return response
                 # Якщо це не JSON, можливо нас блокують, але поки повернемо як є.
                # (Але якщо це Cloudflare, наступний код впаде, тому див. нижче)
                # return response

            # Якщо помилка 403 (Forbidden) або 429 (Too Many Requests) або 503
            if response.status_code in [403, 429, 503] or is_soft_block:
                print(f"[SafePost] Got status {response.status_code}. Attempt {attempt+1}/5. Forcing Refresh...")

                # Блокуємо, щоб інші потоки почекали
                with SESSION_LOCK:
                    # Додаємо невелику затримку, щоб не спамити браузерами
                    time.sleep(2)
                    refresh_copart_session()
                    # Скидаємо лічильник, бо ми щойно оновились
                    POST_COUNT = 0
                continue # Йдемо на наступну ітерацію циклу (повторний запит)

        except requests.exceptions.ConnectionError:
            print(f"[SafePost] Connection error, retry {attempt+1}/5")
            time.sleep(5)
        except Exception as e:
             print(f"[SafePost] Request error: {e}")
             # Якщо сталася дивна помилка, теж спробуємо оновитись на всяк випадок
             with SESSION_LOCK:
                 refresh_copart_session()

    # Якщо після 5 спроб і оновлень нічого не вийшло
    print("[SafePost] Failed after 5 retries.")
    # Повертаємо dummy об'єкт з кодом 500, щоб програма не крашилась, а просто пропускала лот
    dummy = requests.Response()
    dummy.status_code = 500
    dummy._content = b"{}"
    return dummy

def fetch_build_sheet(lot_number, lot_hash):
    """
    Helper function to fetch build sheet data using lotHash.
    """
    url = "https://www.copart.com/public/data/lot/build-sheet"
    payload = {
        "lotId": int(lot_number),
        "lotHash": lot_hash
    }

    # Використовуємо safe_post, який вже має логіку повторів і оновлення сесії
    try:
        r = safe_post(url, json=payload, timeout=20)
        if r.status_code == 200:
            try:
                return r.json()
            except json.JSONDecodeError:
                return None
        elif r.status_code == 404:
             # Build sheet not found - it's normal for some lots
            return None
        else:
            print(f"[BuildSheet] Error {r.status_code} for lot {lot_number}")
            return None
    except Exception as e:
        print(f"[BuildSheet] Exception for lot {lot_number}: {e}")
        return None


@app.get("/test")
def test_endpoint():
    with open(res_json_path / "63137155.json", "r", encoding="utf-8") as f:
        data = json.load(f)
        return data
    return {"error": "Test file not found or something went wrong."}

@app.get("/lot/{number}")
def get_lot_details(number: int):

    url = f"https://www.copart.com/public/data/lotdetails/solr/{number}"

    r = safe_get(url, timeout = 30)

    if r.status_code != 200:
        print(f"Error {r.status_code} for lot {number}")
        return

    try:
        data = r.json()

        #for build-sheet
        lot_data_obj = data.get('data', {}).get('lotDetails', {})
        if not lot_data_obj:
             lot_data_obj = data.get('data', {}) # fallback

        lot_hash = lot_data_obj.get('lh')
        if not lot_hash:
            lot_hash = data.get('lh')

        if lot_hash:
            build_sheet_data = fetch_build_sheet(number, lot_hash)
            if build_sheet_data:
                data['build_sheet'] = build_sheet_data
            else:
                print(f"Error. get_lot_details build-sheet returned None")
                save_error({
                    'error_type': f"Error. get_lot_details build-sheet returned None"
                })

        res_json_path.mkdir(exist_ok=True)
        with open(res_json_path / f"{number}.json", "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        return data

    except Exception as e:
        # Якщо ми тут, значить safe_post повернув 200 OK, але це НЕ JSON.
        # Це 100% блок від Cloudflare. Треба оновлюватись.
        print(f"JSON Error for lot {number} : {e} (Likely soft-block). Triggering refresh...")
        with SESSION_LOCK:
            # Перевіряємо, може хтось вже оновив поки ми спали
            refresh_copart_session()

# if __name__ == "__main__":
#     get_lot_details(63137155)