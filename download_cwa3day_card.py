#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import time
import logging
import requests
from datetime import datetime

# ============== 基本設定 ==============
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
    handlers=[logging.FileHandler(log_filename, encoding="utf-8"),
              logging.StreamHandler()]
)
log = logging.getLogger(__name__)

# ============== Telegram 設定 ==============
TG_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TG_CHAT_IDS = [c.strip() for c in os.getenv("TELEGRAM_CHAT_ID", "").split(",") if c.strip()]

def tg_send_photo(file_path, caption=None, parse_mode=None):
    """
    先用 sendPhoto（Telegram 會當作圖片貼文顯示）；
    若因大小/格式失敗，再改 sendDocument 當檔案傳。
    """
    if not TG_TOKEN or not TG_CHAT_IDS:
        log.warning("未設定 TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID，略過推播")
        return False

    api_base = f"https://api.telegram.org/bot{TG_TOKEN}"
    ok_any = False
    for chat_id in TG_CHAT_IDS:
        # 1) sendPhoto
        try:
            with open(file_path, "rb") as f:
                files = {"photo": (os.path.basename(file_path), f, "image/png")}
                data = {"chat_id": chat_id}
                if caption:
                    data["caption"] = caption
                if parse_mode:
                    data["parse_mode"] = parse_mode
                r = requests.post(f"{api_base}/sendPhoto", data=data, files=files, timeout=30)
            if r.ok and r.json().get("ok"):
                log.info(f"sendPhoto 成功 → chat {chat_id}")
                ok_any = True
                continue
            else:
                log.warning(f"sendPhoto 失敗 → chat {chat_id}，嘗試 sendDocument；resp={r.text}")
        except Exception as e:
            log.warning(f"sendPhoto 例外 → chat {chat_id}：{e}；改用 sendDocument")

        # 2) 後援：sendDocument
        try:
            with open(file_path, "rb") as f:
                files = {"document": (os.path.basename(file_path), f, "application/octet-stream")}
                data = {"chat_id": chat_id}
                if caption:
                    data["caption"] = caption
                r = requests.post(f"{api_base}/sendDocument", data=data, files=files, timeout=60)
            if r.ok and r.json().get("ok"):
                log.info(f"sendDocument 成功 → chat {chat_id}")
                ok_any = True
            else:
                log.error(f"sendDocument 仍失敗 → chat {chat_id}；resp={r.text}")
        except Exception as e:
            log.error(f"sendDocument 例外 → chat {chat_id}：{e}")
    return ok_any

# ============== 下載工具 ==============
def download_image(img_url, filename):
    path = os.path.join(DOWNLOAD_DIR, filename)
    if os.path.exists(path):
        log.info(f"檔案已存在: {filename}")
        return path, False
    log.info(f"下載圖片: {img_url}")
    for _ in range(3):
        try:
            r = requests.get(img_url, headers=HEADERS, timeout=20)
            r.raise_for_status()
            with open(path, "wb") as f:
                f.write(r.content)
            log.info(f"下載成功: {filename} ({len(r.content):,} bytes)")
            return path, True
        except Exception as e:
            log.warning(f"下載重試中: {e}")
            time.sleep(2)
    log.error("下載失敗")
    return None, False

# ============== Selenium 抓圖 ==============
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
            drv = webdriver.Chrome(service=service, options=options)
            log.info(f"使用內建 chromedriver: {driver_bin}")
            return drv
        except Exception as e:
            log.warning(f"內建 chromedriver 失敗：{e}")

    drv = webdriver.Chrome(options=options)
    log.info("使用系統 Chrome 成功啟動")
    return drv

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
        imgs = WebDriverWait(driver, 25).until(
            EC.presence_of_all_elements_located(
                (By.CSS_SELECTOR, ".weather-AD img[src*='WT_L']")
            )
        )

        img = imgs[0]
        src = img.get_attribute("src") or ""
        full_url = src if src.startswith("http") else BASE_URL + src
        filename = full_url.split("/")[-1].split("?")[0]

        saved_path, is_new = download_image(full_url, filename)
        if saved_path and is_new:
            # 推送到 Telegram（標題帶上時間與檔名）
            caption = f"CWA 天氣小卡\n時間：{datetime.now():%Y-%m-%d %H:%M:%S}"
            tg_send_photo(saved_path, caption=caption)
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
