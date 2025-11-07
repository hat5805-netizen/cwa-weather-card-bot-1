from flask import Flask, request, jsonify
import subprocess
import threading
import time
import sys
from datetime import datetime

app = Flask(__name__)

# ===== 共享狀態（避免重複執行） =====
RUN_LOCK = threading.Lock()
IS_RUNNING = False
LAST_RUN = {
    "started_at": None,
    "ended_at": None,
    "duration_sec": None,
    "returncode": None,
    "stdout_tail": "",
    "stderr_tail": "",
}

# ===== 實際要跑的工作 =====
def _run_job():
    """執行下載腳本；更新 LAST_RUN 狀態。"""
    global IS_RUNNING, LAST_RUN
    start_ts = time.time()
    LAST_RUN["started_at"] = datetime.utcnow().isoformat() + "Z"
    LAST_RUN["ended_at"] = None
    LAST_RUN["duration_sec"] = None
    LAST_RUN["returncode"] = None
    LAST_RUN["stdout_tail"] = ""
    LAST_RUN["stderr_tail"] = ""

    try:
        # Python 路徑：優先使用目前解譯器
        py = sys.executable or "python"

        # 提高穩定性：-u 取消 stdout 緩衝
        result = subprocess.run(
            [py, "-u", "download_cwa3day_card.py"],
            capture_output=True,
            text=True,
            timeout=300,  # 最長 300 秒
        )
        LAST_RUN["returncode"] = result.returncode
        # 只保留尾端 2000 字以免太長
        LAST_RUN["stdout_tail"] = (result.stdout or "")[-2000:]
        LAST_RUN["stderr_tail"] = (result.stderr or "")[-2000:]
        print("腳本輸出:", LAST_RUN["stdout_tail"])
        if LAST_RUN["stderr_tail"]:
            print("腳本錯誤:", LAST_RUN["stderr_tail"])

    except Exception as e:
        LAST_RUN["returncode"] = -1
        LAST_RUN["stderr_tail"] = f"Exception: {e}"
        print("執行失敗:", e)

    finally:
        LAST_RUN["ended_at"] = datetime.utcnow().isoformat() + "Z"
        LAST_RUN["duration_sec"] = round(time.time() - start_ts, 3)
        IS_RUNNING = False
        try:
            RUN_LOCK.release()
        except RuntimeError:
            pass  # 已釋放

def run_script_sync():
    """同步執行（blocking），回傳結果 dict。"""
    acquired = RUN_LOCK.acquire(blocking=False)
    if not acquired:
        return {"status": "busy", "message": "A job is already running."}, 409

    global IS_RUNNING
    IS_RUNNING = True
    try:
        _run_job()
        status = "ok" if LAST_RUN["returncode"] == 0 else "error"
        http = 200 if status == "ok" else 500
        return {
            "status": status,
            "running": False,
            "last_run": LAST_RUN,
        }, http
    finally:
        # _run_job 內已釋放鎖，但保險再確保一次
        if RUN_LOCK.locked():
            RUN_LOCK.release()
        IS_RUNNING = False

def run_script_async():
    """非同步啟動（立即回 202）。"""
    acquired = RUN_LOCK.acquire(blocking=False)
    if not acquired:
        return {"status": "busy", "message": "A job is already running."}, 409

    global IS_RUNNING
    IS_RUNNING = True
    t = threading.Thread(target=_run_job, daemon=True)
    t.start()
    return {"status": "started", "running": True}, 202

# ===== 路由 =====
@app.route("/")
def home():
    return "CWA Weather Card Bot is running!"

@app.route("/status")
def status():
    return jsonify({
        "running": IS_RUNNING,
        "last_run": LAST_RUN
    })

@app.route("/run")
def run():
    """
    參數：
      - sync=1 或 mode=sync  → 同步（工作完成才回應）
      - mode=async           → 非同步（立即回應）
      - 其他/未帶參數         → 預設非同步
    """
    sync = (
        request.args.get("sync") == "1"
        or request.args.get("mode") == "sync"
        or request.args.get("force") == "1"  # 兼容你剛提的 force=1
    )
    if sync:
        payload, code = run_script_sync()
        return jsonify(payload), code
    else:
        payload, code = run_script_async()
        return jsonify(payload), code

if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", "8080"))
    app.run(host="0.0.0.0", port=port)



quit()
from flask import Flask
import subprocess
import threading

app = Flask(__name__)

def run_script():
    try:
        result = subprocess.run(
            ["python", "download_cwa3day_card.py"],
            capture_output=True, text=True, timeout=120
        )
        print("腳本輸出:", result.stdout)
        if result.stderr:
            print("腳本錯誤:", result.stderr)
        return result.stdout + result.stderr
    except Exception as e:
        print("執行失敗:", e)
        return str(e)

@app.route('/')
def home():
    return "CWA Weather Card Bot is running!"

@app.route('/run')
def run():
    thread = threading.Thread(target=run_script)
    thread.start()
    return "任務已啟動！正在下載天氣小卡... (請查看 Render Logs 確認結果)"

if __name__ == '__main__':
    import os
    port = int(os.environ.get('PORT', '8080'))
    app.run(host='0.0.0.0', port=port)
