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
import logging
import sys

from fastapi import FastAPI
from typing import Optional

log_dir = Path('app/logs')
log_dir.mkdir(parents=True, exist_ok=True)
log_file_path = log_dir / 'scraper.log'

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(log_file_path, encoding='utf-8'), # Запис у файл
        logging.StreamHandler(sys.stdout)                     # Вивід у консоль
    ]
)
logger = logging.getLogger("CopartScraper")
# ---------------------

tech_json_path = Path('app/tech_json')
res_json_path = Path('app/res_json')
tech_json_path.mkdir(parents=True, exist_ok=True)
res_json_path.mkdir(parents=True, exist_ok=True)
SESSION = requests.Session()
POST_COUNT = 0
POST_LIMITER = 1000  # Number of POST requests before refreshing
#session (it includes pages and photos requests, so one full page = 1 page reques + 20 photos requests = 21 POST requests per full page)

SESSION_LOCK = threading.RLock()

# Global Session Object
# This acts as the "bridge" between the token extractor and safe_post.
SESSION = requests.Session()

app = FastAPI()

SESSION_FILE = Path("app/session/copart_session.json")
SESSION_FILE.parent.mkdir(parents=True, exist_ok=True)

def save_session_to_file(headers, cookies):
    data = {
        "saved_at": datetime.now().isoformat(),
        "headers": headers,
        "cookies": cookies
    }
    with open(SESSION_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def load_session_from_file():
    if not SESSION_FILE.exists():
        return False

    try:
        with open(SESSION_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)

        headers = data.get("headers")
        cookies = data.get("cookies")

        if not headers or not cookies:
            return False

        global SESSION
        SESSION = requests.Session()
        SESSION.headers.update(headers)
        SESSION.cookies.update(cookies)

        return True

    except Exception:
        return False


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
    kill_chrome_processes()

    data = {
        "cookies": {},
        "headers": {
            "User-Agent": "",
            "X-XSRF-TOKEN": "",
            "X-Requested-With": "XMLHttpRequest",
            "Content-Type": "application/json;charset=UTF-8"
        }
    }

    with SB(uc=True, incognito=True, headless=headless, user_data_dir=None) as sb:
        try:
            sb.open("https://www.copart.com/vehicleFinder")

            MAX_RELOADS = 5
            reload_count = 0
            page_ready = False

            while reload_count < MAX_RELOADS and not page_ready:
                start = time.time()

                # Чекаємо до 5 секунд на стабілізацію
                while time.time() - start < 5:
                    if (
                        "vehicle" in sb.get_current_url().lower()
                        and (
                            sb.is_element_visible("#serverSideDataTable")
                            or sb.is_element_visible(".inner-wrap")
                        )
                    ):
                        page_ready = True
                        break

                    if sb.is_element_visible('iframe[src*="cloudflare"]'):
                        sb.uc_gui_click_captcha()

                    time.sleep(1)

                if page_ready:
                    break

                reload_count += 1
                wait_time = 10 if reload_count > 1 else 0
                logger.info(f"[Copart] Cookies not ready → reload #{reload_count}, wait {wait_time}s")

                time.sleep(wait_time)
                sb.refresh()

            if not page_ready:
                raise TimeoutError("Page loaded but cookies never stabilized")

            # Даємо сторінці фінальні 1–2 секунди
            time.sleep(2)

            # ===== ЗАБИРАЄМО USER AGENT =====
            data["headers"]["User-Agent"] = sb.get_user_agent()

            # ===== ЗАБИРАЄМО COOKIES =====
            cookies_data = sb.cdp.get_all_cookies()

            cookie_dict = {}
            xsrf_token = None

            for c in cookies_data:
                # Цей блок коду працює і з об'єктами, і зі словниками
                if isinstance(c, dict):
                    name = c.get("name")
                    value = c.get("value")
                else:
                    # Якщо це об'єкт Cookie, беремо атрибути напряму
                    name = getattr(c, "name", None)
                    value = getattr(c, "value", None)

                if not name:
                    continue

                # Зберігаємо в простий словник, який точно запишеться в JSON
                cookie_dict[name] = value

                if "xsrf" in name.lower() or "csrf" in name.lower():
                    xsrf_token = value

            if not cookie_dict:
                raise RuntimeError("No cookies found via CDP")

            if not xsrf_token:
                 # Іноді токен не в куках, а в заголовках, але Copart зазвичай тримає в XSRF-TOKEN куці
                 logger.warning("XSRF token missing in cookies collection.")
                 # Можна спробувати не падати, а повернути те що є, але POST запити можуть не пройти
                 # raise RuntimeError("Cookies fetched but XSRF token missing")

            data["cookies"] = cookie_dict
            if xsrf_token:
                data["headers"]["X-XSRF-TOKEN"] = xsrf_token

            return data

        except Exception as e:
            logger.error(f"[Copart] Session fetch failed: {e}")
            save_error({
                "error_type": f"get_copart_session_data error: {e}"
            })
            return None


def refresh_copart_session(headless=False):
    """
    Helper function to update the global SESSION object with a strict timeout.
    """
    logger.info("taking cookies and headers")
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
            logger.info(f"Waiting {sleep_time}s before retry...")
            time.sleep(sleep_time)

        session_retry_counter += 1
        logger.info(f"Attempt to take cookies and headers #{session_retry_counter}")

        # Гарантовано вбиваємо процеси перед стартом, щоб мати чистий стан
        kill_chrome_processes()

        executor = ThreadPoolExecutor(max_workers=1)
        future = executor.submit(_get_session_task)

        try:
            time.sleep(2)
            session_data = future.result(timeout=60)
            time.sleep(2) # Stabilization time after successful fetch
            executor.shutdown(wait=True)

        except TimeoutError:
            logger.error(f"TIMEOUT: get_copart_session_data took longer than 60s.")

            # 1. Спочатку вбиваємо Chrome, щоб спробувати "розморозити" потік
            kill_chrome_processes()

            # Кажемо екзекутору закритися, але НЕ ЧЕКАТИ завершення потоку
            # Це дозволяє головному циклу while продовжити роботу негайно
            executor.shutdown(wait=False)

            session_data = None

        except Exception as e:
            logger.error(f"Error executing session update: {e}")
            executor.shutdown(wait=False) # На випадок інших помилок теж не чекаємо
            session_data = None

    # Якщо ми вийшли з циклу, значить session_data отримано
    if session_data:
        logger.info("session refreshed successfully")
        # Оновлюємо глобальну сесію під замком, якщо потрібно (хоча ви викликаєте це в одному потоці)
        with SESSION_LOCK:
            # === ГОЛОВНА ЗМІНА ТУТ ===
            # Ми викидаємо старий об'єкт SESSION на смітник і створюємо чистий.
            # Це вбиває всі старі завислі TCP-пули.
            SESSION = requests.Session()

            SESSION.headers.update(session_data['headers'])
            SESSION.cookies.update(session_data['cookies'])
            time.sleep(2)
            save_session_to_file(
                session_data["headers"],
                session_data["cookies"]
            )
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
            logger.info(f"[SafeGet] Limit {POST_LIMITER} reached. Refreshing session...")
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
                logger.info(f"[SafeGet] 404 Not Found for {url} (Lot might be removed)")
                return response # Повертаємо як є, обробимо зовні

            # М'який блок (200 OK, але HTML)
            is_soft_block = (response.status_code == 200 and "application/json" not in content_type)

            # Помилки, що вимагають оновлення сесії
            if response.status_code in [403, 429, 503] or is_soft_block:
                reason = "Soft Block (HTML)" if is_soft_block else f"Status {response.status_code}"
                logger.warning(f"[SafeGet] Issue: {reason}. Attempt {attempt+1}/5. Refreshing...")

                with SESSION_LOCK:
                    time.sleep(random.uniform(2, 4))
                    refresh_copart_session()
                    POST_COUNT = 0
                continue

        except requests.exceptions.ConnectionError:
            logger.error(f"[SafeGet] Connection error, retry {attempt+1}/5")
            time.sleep(5)
        except Exception as e:
             logger.error(f"[SafeGet] Request error: {e}")
             with SESSION_LOCK:
                 refresh_copart_session()

    logger.error("[SafeGet] Failed after 5 retries.")
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
            logger.info(f"[SafePost] Limit {POST_LIMITER} reached. Refreshing session...")
            if not refresh_copart_session():
                raise RuntimeError("Failed to refresh session.")
            POST_COUNT = 0
        POST_COUNT += 1

    # 2. Виконуємо запит з логікою "Refresh on Error"
    for attempt in range(5):
        try:
            # logger.info(f"[SafePost] Sending request (Attempt {attempt+1})...")
            response = SESSION.post(url, **kwargs)
            # logger.info(f"[SafePost] Received response: {response.status_code}")

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
                logger.warning(f"[SafePost] Got status {response.status_code}. Attempt {attempt+1}/5. Forcing Refresh...")

                # Блокуємо, щоб інші потоки почекали
                with SESSION_LOCK:
                    # Додаємо невелику затримку, щоб не спамити браузерами
                    time.sleep(2)
                    refresh_copart_session()
                    # Скидаємо лічильник, бо ми щойно оновились
                    POST_COUNT = 0
                continue # Йдемо на наступну ітерацію циклу (повторний запит)

        except requests.exceptions.ConnectionError:
            logger.error(f"[SafePost] Connection error, retry {attempt+1}/5")
            time.sleep(5)
        except Exception as e:
             logger.error(f"[SafePost] Request error: {e}")
             # Якщо сталася дивна помилка, теж спробуємо оновитись на всяк випадок
             with SESSION_LOCK:
                 refresh_copart_session()

    # Якщо після 5 спроб і оновлень нічого не вийшло
    logger.error("[SafePost] Failed after 5 retries.")
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
            logger.error(f"[BuildSheet] Error {r.status_code} for lot {lot_number}")
            return None
    except Exception as e:
        logger.error(f"[BuildSheet] Exception for lot {lot_number}: {e}")
        return None


@app.get("/test")
def test_endpoint():
    with open(res_json_path / "63137155.json", "r", encoding="utf-8") as f:
        data = json.load(f)
        return data
    return {"error": "Test file not found or something went wrong."}

@app.get("/lot/{number}")
def get_lot_details(number: int):
    load_session_from_file()

    url = f"https://www.copart.com/public/data/lotdetails/solr/{number}"

    r = safe_get(url, timeout = 30)

    if r.status_code != 200:
        logger.error(f"Error {r.status_code} for lot {number}")
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
                logger.error(f"Error. get_lot_details build-sheet returned None")
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
        logger.error(f"JSON Error for lot {number} : {e} (Likely soft-block). Triggering refresh...")
        with SESSION_LOCK:
            # Перевіряємо, може хтось вже оновив поки ми спали
            refresh_copart_session()

# if __name__ == "__main__":
#     get_lot_details(63137155)