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
