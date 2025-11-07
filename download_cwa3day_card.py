#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import time
import logging
import requests
import base64
import json
from datetime import datetime

# ============== 共同設定 ==============
PAGE_URL = "https://www.cwa.gov.tw/V8/C/"
BASE_URL = "https://www.cwa.gov.tw"
DOWNLOAD_DIR = "weather_cards"
LOG_DIR = "logs"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}

os.makedirs(DOWNLOAD_DIR, exist_ok=True)
os.makedirs(LOG_DIR, exist_ok=True)

log_filename = os.path.join(LOG_DIR, datetime.now().strftime("cwa_%Y%m%d.log"))
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(log_filename, encoding="utf-8"),
        logging.StreamHandler()
    ]
)
log = logging.getLogger(__name__)

# ===== Google Drive 相依 =====
from google.oauth2.service_account import Credentials as SA_Credentials
from google.oauth2.credentials import Credentials as UserCredentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google.auth.transport.requests import Request as AuthRequest

_SCOPES = ["https://www.googleapis.com/auth/drive"]  # 或用 drive.file
_DRIVE_SVC = None
_AUTH_MODE = None  # "oauth" | "sa"
_SA_EMAIL = None

def _drive_client():
    """優先使用 OAuth token；沒有就回退 Service Account。"""
    global _DRIVE_SVC, _AUTH_MODE, _SA_EMAIL
    if _DRIVE_SVC:
        return _DRIVE_SVC

    # === 1) 優先：OAuth（我的雲端硬碟） ===
    b64_token = os.getenv("GDRIVE_OAUTH_TOKEN_B64")
    if b64_token:
        try:
            raw = base64.b64decode(b64_token).decode("utf-8")
            info = json.loads(raw)
            creds = UserCredentials.from_authorized_user_info(info, scopes=_SCOPES)
            # 若 token 過期，線上自動 refresh
            if not creds.valid and creds.refresh_token:
                creds.refresh(AuthRequest())
            _DRIVE_SVC = build("drive", "v3", credentials=creds, cache_discovery=False)
            _AUTH_MODE = "oauth"
            log.info("Google Drive 認證模式：OAuth（我的雲端硬碟）")
            return _DRIVE_SVC
        except Exception as e:
            log.error(f"初始化 OAuth 憑證失敗，將回退 Service Account：{e}")

    # === 2) 回退：Service Account（適合 Shared Drive） ===
    b64_sa = os.getenv("GDRIVE_SA_JSON_B64")
    if b64_sa:
        try:
            raw = base64.b64decode(b64_sa).decode("utf-8")
            info = json.loads(raw)
            creds = SA_Credentials.from_service_account_info(info, scopes=_SCOPES)
            _SA_EMAIL = info.get("client_email")
            _DRIVE_SVC = build("drive", "v3", credentials=creds, cache_discovery=False)
            _AUTH_MODE = "sa"
            log.info(f"Google Drive 認證模式：Service Account（{_SA_EMAIL}）")
            return _DRIVE_SVC
        except Exception as e:
            log.error(f"初始化 Service Account 失敗：{e}")

    log.warning("未提供任何 Google Drive 憑證（GDRIVE_OAUTH_TOKEN_B64 / GDRIVE_SA_JSON_B64）。")
    return None

def drive_file_exists(service, folder_id, filename):
    """查詢資料夾下是否已有同名檔案。共用參數對 My Drive/Shared Drive 皆可。"""
    try:
        q = f"name = '{filename}' and '{folder_id}' in parents and trashed = false"
        resp = service.files().list(
            q=q,
            fields="files(id, name)",
            pageSize=1,
            includeItemsFromAllDrives=True,
            supportsAllDrives=True,
            corpora="allDrives"
        ).execute()
        files = resp.get("files", [])
        return files[0] if files else None
    except Exception as e:
        log.warning(f"查詢 Drive 檔案失敗：{e}")
        return None

def upload_to_drive(filepath):
    """
    上傳到 Google Drive 指定資料夾：
    - OAuth：可上傳到『我的雲端硬碟』資料夾
    - SA：建議用 Shared Drive（否則會遇到 storageQuotaExceeded）
    """
    folder_id = os.getenv("GDRIVE_FOLDER_ID")
    if not folder_id:
        log.warning("未設定 GDRIVE_FOLDER_ID，略過上傳至 Google Drive")
        return None

    svc = _drive_client()
    if not svc:
        return None

    # 如果是 SA，而且 folder 在 My Drive，會遇到 quota 問題；這裡僅提醒，不阻擋
    if _AUTH_MODE == "sa":
        log.info("（提醒）目前使用 Service Account，請確保目標資料夾位於 Shared Drive。")

    filename = os.path.basename(filepath)
    exists = drive_file_exists(svc, folder_id, filename)
    if exists:
        log.info(f"Drive 已存在：{filename}（id={exists['id']}）")
        return exists

    try:
        media = MediaFileUpload(filepath, mimetype="image/png", resumable=False)
        meta = {"name": filename, "parents": [folder_id]}
        file = svc.files().create(
            body=meta,
            media_body=media,
            fields="id, webViewLink, webContentLink",
            supportsAllDrives=True
        ).execute()
        log.info(f"上傳至 Drive 成功：{filename}（id={file['id']}）")
        log.info(f"webViewLink: {file.get('webViewLink')}")
        log.info(f"webContentLink: {file.get('webContentLink')}")
        return file
    except Exception as e:
        log.error(f"上傳至 Drive 失敗：{e}")
        return None

# ===== 下載工具：回傳 (path, is_new) =====
def download_image(img_url, filename):
    filepath = os.path.join(DOWNLOAD_DIR, filename)
    if os.path.exists(filepath):
        log.info(f"檔案已存在: {filename}")
        return filepath, False
    log.info(f"下載圖片: {img_url}")
    for _ in range(3):
        try:
            r = requests.get(img_url, headers=HEADERS, timeout=20)
            r.raise_for_status()
            with open(filepath, "wb") as f:
                f.write(r.content)
            log.info(f"下載成功: {filename} ({len(r.content):,} bytes)")
            return filepath, True
        except Exception as e:
            log.warning(f"下載重試中: {e}")
            time.sleep(2)
    log.error("下載失敗")
    return None, False

# ===== Selenium：抓 .weather-AD 裡的 WT_L =====
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

def init_driver():
    log.info("正在初始化 Chrome WebDriver...")
    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")
    ua = HEADERS.get("User-Agent")
    if ua:
        options.add_argument(f"--user-agent={ua}")

    chrome_bin = os.getenv("GOOGLE_CHROME_BIN", "/usr/bin/chromium")
    if os.path.exists(chrome_bin):
        options.binary_location = chrome_bin

    driver_bin = os.getenv("CHROMEDRIVER_PATH", "/usr/bin/chromedriver")
    if os.path.exists(driver_bin):
        try:
            service = Service(executable_path=driver_bin)
            driver = webdriver.Chrome(service=service, options=options)
            log.info(f"使用內建 chromedriver: {driver_bin}")
            return driver
        except Exception as e:
            log.warning(f"內建 chromedriver 失敗：{e}")

    driver = webdriver.Chrome(options=options)
    log.info("使用系統 Chrome 成功啟動")
    return driver

def parse_weather_ad_card():
    driver = None
    try:
        driver = init_driver()
        log.info(f"載入網頁: {PAGE_URL}")
        driver.get(PAGE_URL)

        log.info("等待 .weather-AD 載入...")
        WebDriverWait(driver, 25).until(
            EC.presence_of_element_located((By.CLASS_NAME, "weather-AD"))
        )

        log.info("等待 WT_L 圖片出現...")
        img_elements = WebDriverWait(driver, 25).until(
            EC.presence_of_all_elements_located(
                (By.CSS_SELECTOR, ".weather-AD img[src*='WT_L']")
            )
        )

        img = img_elements[0]
        src = img.get_attribute("src") or ""
        full_url = src if src.startswith("http") else BASE_URL + src
        filename = full_url.split("/")[-1].split("?")[0]

        saved_path, is_new = download_image(full_url, filename)
        if saved_path and is_new:
            upload_to_drive(saved_path)
        return saved_path

    except Exception as e:
        log.error(f"錯誤: {e}", exc_info=True)
        if driver:
            driver.save_screenshot(os.path.join(LOG_DIR, "error.png"))
        return None
    finally:
        if driver:
            driver.quit()

# ============== 主程式 ==============
if __name__ == "__main__":
    start = time.time()
    log.info("開始抓取報天氣圖卡")
    saved = parse_weather_ad_card()
    elapsed = time.time() - start
    if saved:
        print("\n下載成功！")
        print(f"   檔案: {saved}")
        print(f"   耗時: {elapsed:.2f} 秒")
    else:
        print("\n下載失敗！請查看 logs/ 資料夾")





quit()

#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import time
import logging
import requests
import base64
import json
from datetime import datetime

# ============== 共同設定 ==============
PAGE_URL = "https://www.cwa.gov.tw/V8/C/"
BASE_URL = "https://www.cwa.gov.tw"
DOWNLOAD_DIR = "weather_cards"
LOG_DIR = "logs"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}

os.makedirs(DOWNLOAD_DIR, exist_ok=True)
os.makedirs(LOG_DIR, exist_ok=True)

log_filename = os.path.join(LOG_DIR, datetime.now().strftime("cwa_%Y%m%d.log"))
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(log_filename, encoding="utf-8"),
        logging.StreamHandler()
    ]
)
log = logging.getLogger(__name__)
# =====================================

# ===== Google Drive 相依 =====
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

_SCOPES = ["https://www.googleapis.com/auth/drive"]
_DRIVE_SVC = None
_SA_EMAIL = None
_IS_SHARED_DRIVE = None  # 會在首次使用時檢查

def _drive_client():
    global _DRIVE_SVC, _SA_EMAIL
    if _DRIVE_SVC:
        return _DRIVE_SVC

    b64 = os.getenv("GDRIVE_SA_JSON_B64")
    if not b64:
        log.warning("未設定 GDRIVE_SA_JSON_B64，略過上傳至 Google Drive")
        return None

    try:
        raw = base64.b64decode(b64).decode("utf-8")
        info = json.loads(raw)
        creds = Credentials.from_service_account_info(info, scopes=_SCOPES)
        _SA_EMAIL = info.get("client_email")
        log.info(f"使用的 Service Account：{_SA_EMAIL}")
        _DRIVE_SVC = build("drive", "v3", credentials=creds, cache_discovery=False)
        return _DRIVE_SVC
    except Exception as e:
        log.error(f"初始化 Google Drive 失敗：{e}")
        return None

def _ensure_shared_drive_folder(service, folder_id):
    """
    確認 folder_id 是否位於「共享雲端硬碟」。
    是：回傳 True；否：回傳 False（並在 log 說明要改用 Shared Drive）。
    """
    global _IS_SHARED_DRIVE
    if _IS_SHARED_DRIVE is not None:
        return _IS_SHARED_DRIVE
    try:
        meta = service.files().get(
            fileId=folder_id,
            fields="id, name, driveId, parents",
            supportsAllDrives=True
        ).execute()
        if meta.get("driveId"):
            log.info(f"確認：目標資料夾位於 Shared Drive（driveId={meta['driveId']}）")
            _IS_SHARED_DRIVE = True
        else:
            log.error(
                "偵測到 GDRIVE_FOLDER_ID 指向『我的雲端硬碟』而非『共享雲端硬碟』：\n"
                "Service Account 沒有個人儲存空間，無法上傳。\n"
                "請改用 Shared Drive：建立 Shared Drive → 將 Service Account 加為成員 → "
                "在 Shared Drive 內建立資料夾並使用其 folder ID。"
            )
            _IS_SHARED_DRIVE = False
    except Exception as e:
        log.error(f"讀取資料夾資訊失敗，無法判斷是否 Shared Drive：{e}")
        _IS_SHARED_DRIVE = False
    return _IS_SHARED_DRIVE

def drive_file_exists(service, folder_id, filename):
    """查詢指定資料夾下是否已有同名檔案（支援共享雲端硬碟）"""
    try:
        q = (
            f"name = '{filename}' and "
            f"'{folder_id}' in parents and trashed = false"
        )
        resp = service.files().list(
            q=q,
            fields="files(id, name)",
            pageSize=1,
            includeItemsFromAllDrives=True,  # <== 這裡
            supportsAllDrives=True,          # <== 這裡
            corpora="allDrives"              # <== 建議加
        ).execute()
        files = resp.get("files", [])
        return files[0] if files else None
    except Exception as e:
        log.warning(f"查詢 Drive 檔案失敗：{e}")
        return None

def upload_to_drive(filepath):
    """
    將本地圖片上傳到指定的 Google Drive 資料夾；
    - 僅 Shared Drive 允許（Service Account 沒有個人配額）
    - 已存在則跳過
    """
    folder_id = os.getenv("GDRIVE_FOLDER_ID")
    if not folder_id:
        log.warning("未設定 GDRIVE_FOLDER_ID，略過上傳至 Google Drive")
        return None

    svc = _drive_client()
    if not svc:
        return None

    # 檢查目標資料夾是否在 Shared Drive
    if not _ensure_shared_drive_folder(svc, folder_id):
        log.error("因目標資料夾不在 Shared Drive，已跳過上傳（避免 403 storageQuotaExceeded）。")
        return None

    filename = os.path.basename(filepath)

    exists = drive_file_exists(svc, folder_id, filename)
    if exists:
        log.info(f"Drive 已存在：{filename}（id={exists['id']}）")
        return exists

    try:
        media = MediaFileUpload(filepath, mimetype="image/png", resumable=False)
        meta = {"name": filename, "parents": [folder_id]}
        file = svc.files().create(
            body=meta,
            media_body=media,
            fields="id, webViewLink, webContentLink",
            supportsAllDrives=True  # <== 這裡
        ).execute()

        log.info(f"上傳至 Drive 成功：{filename}（id={file['id']}）")
        log.info(f"webViewLink: {file.get('webViewLink')}")
        log.info(f"webContentLink: {file.get('webContentLink')}")
        return file
    except Exception as e:
        log.error(f"上傳至 Drive 失敗：{e}")
        return None


# ===== 下載工具：回傳 (path, is_new) =====
def download_image(img_url, filename):
    filepath = os.path.join(DOWNLOAD_DIR, filename)
    if os.path.exists(filepath):
        log.info(f"檔案已存在: {filename}")
        return filepath, False  # 不重複下載

    log.info(f"下載圖片: {img_url}")
    for _ in range(3):
        try:
            r = requests.get(img_url, headers=HEADERS, timeout=20)
            r.raise_for_status()
            with open(filepath, "wb") as f:
                f.write(r.content)
            log.info(f"下載成功: {filename} ({len(r.content):,} bytes)")
            return filepath, True
        except Exception as e:
            log.warning(f"下載重試中: {e}")
            time.sleep(2)

    log.error("下載失敗")
    return None, False

# ===== Selenium 抓圖流程 =====
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

def init_driver():
    """Docker 內優先用 /usr/bin/chromedriver + /usr/bin/chromium；本地自動尋找"""
    log.info("正在初始化 Chrome WebDriver...")
    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")
    ua = HEADERS.get("User-Agent")
    if ua:
        options.add_argument(f"--user-agent={ua}")

    chrome_bin = os.getenv("GOOGLE_CHROME_BIN", "/usr/bin/chromium")
    if os.path.exists(chrome_bin):
        options.binary_location = chrome_bin

    driver_bin = os.getenv("CHROMEDRIVER_PATH", "/usr/bin/chromedriver")
    if os.path.exists(driver_bin):
        try:
            service = Service(executable_path=driver_bin)
            driver = webdriver.Chrome(service=service, options=options)
            log.info(f"使用內建 chromedriver: {driver_bin}")
            return driver
        except Exception as e:
            log.warning(f"內建 chromedriver 失敗：{e}")

    # 最後退回系統自帶或 webdriver-manager（本地測試時）
    driver = webdriver.Chrome(options=options)
    log.info("使用系統 Chrome 成功啟動")
    return driver

def parse_weather_ad_card():
    driver = None
    try:
        driver = init_driver()

        log.info(f"載入網頁: {PAGE_URL}")
        driver.get(PAGE_URL)

        log.info("等待 .weather-AD 載入...")
        WebDriverWait(driver, 25).until(
            EC.presence_of_element_located((By.CLASS_NAME, "weather-AD"))
        )

        log.info("等待 WT_L 圖片出現...")
        img_elements = WebDriverWait(driver, 25).until(
            EC.presence_of_all_elements_located(
                (By.CSS_SELECTOR, ".weather-AD img[src*='WT_L']")
            )
        )

        img = img_elements[0]
        src = img.get_attribute("src") or ""
        full_url = src if src.startswith("http") else BASE_URL + src
        filename = full_url.split("/")[-1].split("?")[0]

        # 下載（不重複），僅新檔才上傳 Drive
        saved_path, is_new = download_image(full_url, filename)
        if saved_path and is_new:
            upload_to_drive(saved_path)

        return saved_path

    except Exception as e:
        log.error(f"錯誤: {e}", exc_info=True)
        if driver:
            driver.save_screenshot(os.path.join(LOG_DIR, "error.png"))
        return None
    finally:
        if driver:
            driver.quit()

# ============== 主程式 ==============
if __name__ == "__main__":
    start = time.time()
    log.info("開始抓取報天氣圖卡")
    saved = parse_weather_ad_card()
    elapsed = time.time() - start

    if saved:
        print("\n下載成功！")
        print(f"   檔案: {saved}")
        print(f"   耗時: {elapsed:.2f} 秒")
    else:
        print("\n下載失敗！請查看 logs/ 資料夾")



quit()
#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import time
import logging
import requests
import base64
import json
from datetime import datetime

# ============== 共同設定 ==============
PAGE_URL = "https://www.cwa.gov.tw/V8/C/"
BASE_URL = "https://www.cwa.gov.tw"
DOWNLOAD_DIR = "weather_cards"
LOG_DIR = "logs"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}

os.makedirs(DOWNLOAD_DIR, exist_ok=True)
os.makedirs(LOG_DIR, exist_ok=True)

log_filename = os.path.join(LOG_DIR, datetime.now().strftime("cwa_%Y%m%d.log"))
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(log_filename, encoding="utf-8"),
        logging.StreamHandler()
    ]
)
log = logging.getLogger(__name__)
# =====================================

# ===== Google Drive 相依 =====
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

_SCOPES = ["https://www.googleapis.com/auth/drive.file"]
_DRIVE_SVC = None

def _drive_client():
    """以 Service Account 初始化 Drive client（使用 Base64 JSON 環境變數）"""
    global _DRIVE_SVC
    if _DRIVE_SVC:
        return _DRIVE_SVC

    b64 = os.getenv("GDRIVE_SA_JSON_B64")
    if not b64:
        log.warning("未設定 GDRIVE_SA_JSON_B64，略過上傳至 Google Drive")
        return None

    try:
        raw = base64.b64decode(b64).decode("utf-8")
        info = json.loads(raw)
        creds = Credentials.from_service_account_info(info, scopes=_SCOPES)
        _DRIVE_SVC = build("drive", "v3", credentials=creds, cache_discovery=False)
        return _DRIVE_SVC
    except Exception as e:
        log.error(f"初始化 Google Drive 失敗：{e}")
        return None

def drive_file_exists(service, folder_id, filename):
    """查詢指定資料夾下是否已有同名檔案"""
    try:
        q = f"name = '{filename}' and '{folder_id}' in parents and trashed = false"
        resp = service.files().list(q=q, fields="files(id, name)", pageSize=1).execute()
        files = resp.get("files", [])
        return files[0] if files else None
    except Exception as e:
        log.warning(f"查詢 Drive 檔案失敗：{e}")
        return None

def upload_to_drive(filepath):
    """將本地圖片上傳到指定的 Google Drive 資料夾；已存在則跳過"""
    folder_id = os.getenv("GDRIVE_FOLDER_ID")
    if not folder_id:
        log.warning("未設定 GDRIVE_FOLDER_ID，略過上傳至 Google Drive")
        return None

    svc = _drive_client()
    if not svc:
        return None

    filename = os.path.basename(filepath)

    exists = drive_file_exists(svc, folder_id, filename)
    if exists:
        log.info(f"Drive 已存在：{filename}（id={exists['id']}）")
        return exists

    try:
        media = MediaFileUpload(filepath, mimetype="image/png", resumable=False)
        meta = {"name": filename, "parents": [folder_id]}
        file = svc.files().create(body=meta, media_body=media,
                                  fields="id, webViewLink, webContentLink").execute()
        log.info(f"上傳至 Drive 成功：{filename}（id={file['id']}）")
        log.info(f"webViewLink: {file.get('webViewLink')}")
        log.info(f"webContentLink: {file.get('webContentLink')}")
        return file
    except Exception as e:
        log.error(f"上傳至 Drive 失敗：{e}")
        return None

# ===== 下載工具：回傳 (path, is_new) =====
def download_image(img_url, filename):
    filepath = os.path.join(DOWNLOAD_DIR, filename)
    if os.path.exists(filepath):
        log.info(f"檔案已存在: {filename}")
        return filepath, False  # 不重複下載

    log.info(f"下載圖片: {img_url}")
    for _ in range(3):
        try:
            r = requests.get(img_url, headers=HEADERS, timeout=20)
            r.raise_for_status()
            with open(filepath, "wb") as f:
                f.write(r.content)
            log.info(f"下載成功: {filename} ({len(r.content):,} bytes)")
            return filepath, True
        except Exception as e:
            log.warning(f"下載重試中: {e}")
            time.sleep(2)

    log.error("下載失敗")
    return None, False

# ===== 你的 Selenium 抓圖流程（保留原邏輯）=====
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

def init_driver():
    """Docker 內優先用 /usr/bin/chromedriver + /usr/bin/chromium"""
    log.info("正在初始化 Chrome WebDriver...")
    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")
    ua = HEADERS.get("User-Agent")
    if ua:
        options.add_argument(f"--user-agent={ua}")

    chrome_bin = os.getenv("GOOGLE_CHROME_BIN", "/usr/bin/chromium")
    if os.path.exists(chrome_bin):
        options.binary_location = chrome_bin

    driver_bin = os.getenv("CHROMEDRIVER_PATH", "/usr/bin/chromedriver")
    if os.path.exists(driver_bin):
        try:
            service = Service(executable_path=driver_bin)
            driver = webdriver.Chrome(service=service, options=options)
            log.info(f"使用內建 chromedriver: {driver_bin}")
            return driver
        except Exception as e:
            log.warning(f"內建 chromedriver 失敗：{e}")

    # 最後退回系統自動尋找（本地測試用）
    driver = webdriver.Chrome(options=options)
    log.info("使用系統 Chrome 成功啟動")
    return driver

def parse_weather_ad_card():
    driver = None
    try:
        driver = init_driver()

        log.info(f"載入網頁: {PAGE_URL}")
        driver.get(PAGE_URL)

        log.info("等待 .weather-AD 載入...")
        WebDriverWait(driver, 25).until(
            EC.presence_of_element_located((By.CLASS_NAME, "weather-AD"))
        )

        log.info("等待 WT_L 圖片出現...")
        img_elements = WebDriverWait(driver, 25).until(
            EC.presence_of_all_elements_located(
                (By.CSS_SELECTOR, ".weather-AD img[src*='WT_L']")
            )
        )

        img = img_elements[0]
        src = img.get_attribute("src") or ""
        full_url = src if src.startswith("http") else BASE_URL + src
        filename = full_url.split("/")[-1].split("?")[0]

        # 下載（不重複），僅新檔才上傳 Drive
        saved_path, is_new = download_image(full_url, filename)
        if saved_path and is_new:
            upload_to_drive(saved_path)

        return saved_path

    except Exception as e:
        log.error(f"錯誤: {e}", exc_info=True)
        if driver:
            driver.save_screenshot(os.path.join(LOG_DIR, "error.png"))
        return None
    finally:
        if driver:
            driver.quit()

# ============== 主程式 ==============
if __name__ == "__main__":
    start = time.time()
    log.info("開始抓取報天氣圖卡")
    saved = parse_weather_ad_card()
    elapsed = time.time() - start

    if saved:
        print("\n下載成功！")
        print(f"   檔案: {saved}")
        print(f"   耗時: {elapsed:.2f} 秒")
    else:
        print("\n下載失敗！請查看 logs/ 資料夾")


quit()
#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import time
import logging
import requests
from datetime import datetime

# ============== 共同設定 ==============
PAGE_URL = "https://www.cwa.gov.tw/V8/C/"
RADAR_PAGE_URL = "https://www.cwa.gov.tw/V8/C/W/OBM.Map.html"  # 含 WT_L*.png
BASE_URL = "https://www.cwa.gov.tw"

DOWNLOAD_DIR = "weather_cards"
LOG_DIR = "logs"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}

# 控制是否使用 Selenium：本地預設 True；Render 請在環境變數設 USE_SELENIUM=0
USE_SELENIUM = os.getenv("USE_SELENIUM", "1") not in ("0", "false", "False")

os.makedirs(DOWNLOAD_DIR, exist_ok=True)
os.makedirs(LOG_DIR, exist_ok=True)

log_filename = os.path.join(LOG_DIR, datetime.now().strftime("cwa_%Y%m%d.log"))
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(log_filename, encoding="utf-8"),
        logging.StreamHandler()
    ]
)
log = logging.getLogger(__name__)
# =====================================


def download_image(img_url, filename):
    filepath = os.path.join(DOWNLOAD_DIR, filename)
    if os.path.exists(filepath):
        log.info(f"檔案已存在: {filename}")
        return filepath
    log.info(f"下載圖片: {img_url}")
    for _ in range(3):
        try:
            r = requests.get(img_url, headers=HEADERS, timeout=20)
            r.raise_for_status()
            with open(filepath, "wb") as f:
                f.write(r.content)
            log.info(f"下載成功: {filename} ({len(r.content):,} bytes)")
            return filepath
        except Exception as e:
            log.warning(f"下載重試中: {e}")
            time.sleep(2)
    log.error("下載失敗")
    return None


# =========================================================
# A) Render 用：requests + BeautifulSoup（無瀏覽器）
# =========================================================
def parse_weather_ad_card_requests():
    from bs4 import BeautifulSoup
    from urllib.parse import urljoin

    def _pick_from_html(html, desc):
        soup = BeautifulSoup(html, "html.parser")
        imgs = soup.find_all("img")
        log.info(f"{desc} <img> 數量: {len(imgs)}")

        # 1) 優先 WT_L*.png（完整雷達圖）
        for img in imgs:
            src = (img.get("src") or "")
            if "WT_L" in src and src.lower().endswith(".png"):
                return urljoin(BASE_URL, src)

        # 2) 次選：首頁預覽圖
        for img in imgs:
            src = (img.get("src") or "")
            if "CV1_TW_1000_forPreview.png" in src:
                return urljoin(BASE_URL, src)

        return None

    try:
        log.info(f"requests 取得首頁: {PAGE_URL}")
        r = requests.get(PAGE_URL, headers=HEADERS, timeout=15)
        r.raise_for_status()
        url = _pick_from_html(r.text, "首頁")
        if url:
            return url
    except Exception as e:
        log.warning(f"首頁抓取失敗: {e}")

    try:
        log.info(f"requests 取得雷達專頁: {RADAR_PAGE_URL}")
        r = requests.get(RADAR_PAGE_URL, headers=HEADERS, timeout=15)
        r.raise_for_status()
        url = _pick_from_html(r.text, "雷達專頁")
        if url:
            return url
    except Exception as e:
        log.error(f"雷達專頁抓取失敗: {e}")

    return None


# =========================================================
# B) 你原本的 Selenium 版（保留原狀）
# =========================================================
def init_driver():
    """初始化 Chrome：Docker(Chromium) 優先，其次本地系統，再退 webdriver-manager"""
    log.info("正在初始化 Chrome WebDriver...")
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.chrome.service import Service

    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--log-level=3")
    ua = HEADERS.get("User-Agent")
    if ua:
        options.add_argument(f"--user-agent={ua}")

    chrome_bin = os.getenv("GOOGLE_CHROME_BIN")
    if chrome_bin and os.path.exists(chrome_bin):
        options.binary_location = chrome_bin

    # 1) Docker 內建的 chromedriver
    driver_bin = os.getenv("CHROMEDRIVER_PATH", "/usr/bin/chromedriver")
    try:
        if os.path.exists(driver_bin):
            service = Service(executable_path=driver_bin)
            driver = webdriver.Chrome(service=service, options=options)
            log.info(f"使用內建 chromedriver: {driver_bin}")
            return driver
    except Exception as e:
        log.warning(f"內建 chromedriver 失敗：{e}")

    # 2) 本地系統自帶
    try:
        driver = webdriver.Chrome(options=options)
        log.info("使用系統 Chrome 成功啟動")
        return driver
    except Exception as e1:
        log.warning(f"系統 Chrome 失敗：{e1}")

    # 3) 退回 webdriver-manager（僅本地可能用到）
    try:
        from webdriver_manager.chrome import ChromeDriverManager
        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=options)
        log.info("使用 webdriver-manager 成功啟動")
        return driver
    except Exception as e2:
        log.error(f"webdriver-manager 也失敗：{e2}")
        return None



def parse_weather_ad_card():
    # 這是你原本 Selenium 的流程，不動
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.common.exceptions import TimeoutException

    driver = None
    try:
        driver = init_driver()
        if not driver:
            return None

        log.info(f"載入網頁: {PAGE_URL}")
        driver.get(PAGE_URL)

        log.info("等待 .weather-AD 載入...")
        WebDriverWait(driver, 20).until(
            EC.presence_of_element_located((By.CLASS_NAME, "weather-AD"))
        )

        log.info("等待 WT_L 圖片出現...")
        img_elements = WebDriverWait(driver, 20).until(
            EC.presence_of_all_elements_located(
                (By.CSS_SELECTOR, ".weather-AD img[src*='WT_L']")
            )
        )

        img = img_elements[0]
        src = img.get_attribute("src") or ""
        full_url = src if src.startswith("http") else BASE_URL + src
        filename = full_url.split("/")[-1].split("?")[0]
        return download_image(full_url, filename)

    except TimeoutException:
        log.error("等待超時")
        if driver:
            driver.save_screenshot(os.path.join(LOG_DIR, "timeout.png"))
    except Exception as e:
        log.error(f"錯誤: {e}", exc_info=True)
        if driver:
            driver.save_screenshot(os.path.join(LOG_DIR, "error.png"))
    finally:
        if driver:
            driver.quit()
    return None


# ================= 主程式 =================
if __name__ == "__main__":
    start = time.time()
    log.info("開始抓取報天氣圖卡")

    if USE_SELENIUM:
        log.info("模式：Selenium")
        saved = parse_weather_ad_card()  # 直接回傳已下載檔案路徑
    else:
        log.info("模式：requests（Render 推薦）")
        url = parse_weather_ad_card_requests()
        saved = None
        if url:
            filename = url.split("/")[-1].split("?")[0]
            saved = download_image(url, filename)

    elapsed = time.time() - start
    if saved:
        print("\n下載成功！")
        print(f"   檔案: {saved}")
        print(f"   耗時: {elapsed:.2f} 秒")
    else:
        print("\n下載失敗！請查看 logs/ 資料夾")
