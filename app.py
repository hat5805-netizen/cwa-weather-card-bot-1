# app.py
from flask import Flask, jsonify, make_response, request
import subprocess
import threading
import os
import time
import json
import uuid
import re

app = Flask(__name__)

LAST_JSON = "/app/last_push.json"  # Render 容器內的檔案路徑，可自行調整
SCRIPT = ["python", "download_cwa3day_card.py"]
SCRIPT_TIMEOUT = 180  # 視需要調整

SEND_OK_PATTERNS = [
    r"sendPhoto\s*成功",           # 你日誌裡的關鍵字
    r"Telegram\s*OK",             # 預留：若未來換訊息
]

def _stdout_has_success(stdout: str) -> bool:
    for pat in SEND_OK_PATTERNS:
        if re.search(pat, stdout or "", re.IGNORECASE):
            return True
    return False

def _save_last(payload: dict) -> None:
    try:
        with open(LAST_JSON, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False)
    except Exception as e:
        app.logger.warning(f"[last] save failed: {e}")

def run_script_sync() -> dict:
    """
    同步執行下載+推播腳本，回傳執行結果 dict
    """
    run_id = uuid.uuid4().hex[:8]
    ts = int(time.time())

    try:
        # 帶上 RUN_ID（腳本用不到也沒關係）
        env = os.environ.copy()
        env["RUN_ID"] = run_id

        result = subprocess.run(
            SCRIPT,
            capture_output=True,
            text=True,
            timeout=SCRIPT_TIMEOUT,
            env=env
        )

        stdout = (result.stdout or "").strip()
        stderr = (result.stderr or "").strip()
        rc = result.returncode

        # 成功條件：腳本輸出含「sendPhoto 成功」；退路：rc==0 也視為成功
        tg_ok = _stdout_has_success(stdout) or (rc == 0)
        status = 200 if tg_ok else 502

        # 寫日誌
        if tg_ok:
            app.logger.info(f"[{run_id}] sendPhoto 成功 | rc={rc}")
        else:
            app.logger.error(f"[{run_id}] sendPhoto 失敗 | rc={rc} | stderr={stderr[:800]}")

        # 存最近一次結果
        payload = {
            "timestamp": ts,
            "run_id": run_id,
            "telegram_ok": tg_ok,
            "returncode": rc,
            "stdout_tail": stdout[-1200:],   # 留一段尾巴方便查
            "stderr_tail": stderr[-1200:]
        }
        _save_last(payload)

        return {"status": status, "body": payload}

    except subprocess.TimeoutExpired as e:
        msg = f"script timeout ({SCRIPT_TIMEOUT}s)"
        app.logger.error(f"[timeout] {msg}")
        payload = {
            "timestamp": int(time.time()),
            "run_id": "timeout",
            "telegram_ok": False,
            "error": msg
        }
        _save_last(payload)
        return {"status": 504, "body": payload}
    except Exception as e:
        msg = f"script exception: {e}"
        app.logger.exception(msg)
        payload = {
            "timestamp": int(time.time()),
            "run_id": "exception",
            "telegram_ok": False,
            "error": msg
        }
        _save_last(payload)
        return {"status": 502, "body": payload}

def run_script_async():
    # 舊邏輯：背景跑，讓瀏覽器立即回應
    try:
        result = subprocess.run(
            SCRIPT, capture_output=True, text=True, timeout=SCRIPT_TIMEOUT
        )
        stdout = (result.stdout or "").strip()
        stderr = (result.stderr or "").strip()
        tg_ok = _stdout_has_success(stdout) or (result.returncode == 0)
        payload = {
            "timestamp": int(time.time()),
            "run_id": uuid.uuid4().hex[:8],
            "telegram_ok": tg_ok,
            "returncode": result.returncode,
            "stdout_tail": stdout[-1200:],
            "stderr_tail": stderr[-1200:]
        }
        _save_last(payload)
        if tg_ok:
            app.logger.info("【async】sendPhoto 成功")
        else:
            app.logger.error(f"【async】sendPhoto 失敗 | stderr={stderr[:800]}")
    except Exception as e:
        app.logger.exception(f"【async】exception: {e}")
        _save_last({
            "timestamp": int(time.time()),
            "run_id": "async-exception",
            "telegram_ok": False,
            "error": str(e)
        })

@app.route("/")
def home():
    return "CWA Weather Card Bot is running!"

@app.route("/run")
def run():
    """
    - /run           -> 非同步（與你原本行為一致，立刻回覆）
    - /run?sync=1    -> 同步執行，依 TG 成敗回 200/502，給 cron-job 用
    """
    if request.args.get("sync") == "1":
        res = run_script_sync()
        return make_response(jsonify(res["body"]), res["status"])
    # 非同步
    thread = threading.Thread(target=run_script_async, daemon=True)
    thread.start()
    return make_response(
        "任務已啟動（非同步）！正在下載天氣小卡…（請查看 Render Logs 或 /last）",
        202
    )

@app.route("/last")
def last():
    try:
        with open(LAST_JSON, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        data = {"error": "no record yet"}
    return jsonify(data)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8080"))
    app.run(host="0.0.0.0", port=port)
