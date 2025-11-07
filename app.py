# app.py
from flask import Flask, request, Response, abort
import subprocess, threading, os, time, glob

app = Flask(__name__)

SCRIPT = ["python", "download_cwa3day_card.py"]
TIMEOUT_SEC = int(os.getenv("RUN_TIMEOUT_SEC", "180"))  # 可用環境變數覆蓋

def run_script_sync():
    """
    同步執行：把 stdout/err 一併收集並「同時」印到 Render log，
    回傳（文字）給呼叫端 + 讓你在 Render Logs 看得到。
    """
    print(">>> [SYNC] start running script", flush=True)
    try:
        # 直接用 Popen 邊讀邊印，避免一次性塞爆記憶體、也能即時看到 log
        proc = subprocess.Popen(
            SCRIPT,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        lines = []
        start = time.time()
        while True:
            if proc.poll() is not None:
                # 把剩下的 buffer 讀完
                rest = proc.stdout.read()
                if rest:
                    print(rest, end="", flush=True)
                    lines.append(rest)
                break
            line = proc.stdout.readline()
            if line:
                print(line, end="", flush=True)
                lines.append(line)
            # 超時保護
            if time.time() - start > TIMEOUT_SEC:
                proc.kill()
                lines.append(f"\n[ERROR] Timeout after {TIMEOUT_SEC}s, process killed.\n")
                print(lines[-1], end="", flush=True)
                break

        rc = proc.returncode if proc.returncode is not None else -1
        print(f">>> [SYNC] end (returncode={rc})", flush=True)
        return rc, "".join(lines)
    except Exception as e:
        msg = f"[SYNC] exception: {e}\n"
        print(msg, flush=True)
        return -1, msg

def run_script_async():
    """
    背景執行：啟一條 daemon thread，log 一樣會打到 Render。
    """
    def _target():
        print(">>> [ASYNC] thread start", flush=True)
        try:
            res = subprocess.run(SCRIPT, capture_output=True, text=True, timeout=TIMEOUT_SEC)
            if res.stdout:
                print(res.stdout, end="", flush=True)
            if res.stderr:
                print(res.stderr, end="", flush=True)
            print(f">>> [ASYNC] done (returncode={res.returncode})", flush=True)
        except Exception as e:
            print(f"[ASYNC] exception: {e}", flush=True)

    th = threading.Thread(target=_target, daemon=True)
    th.start()

@app.route("/")
def home():
    return "CWA Weather Card Bot is running!"

@app.route("/run")
def run():
    sync = str(request.args.get("sync", "0")).lower() in ("1", "true", "yes")
    if sync:
        rc, out = run_script_sync()
        # 以純文字回傳完整執行結果，便於 GAS 抓 body 確認
        return Response(out, mimetype="text/plain")
    else:
        run_script_async()
        return "任務已啟動（背景）！請查看 Render Logs。"

@app.route("/logs")
def tail_logs():
    """
    方便直接用瀏覽器看最近 log。預設 n=200 行；會讀取 logs/ 下最晚的檔。
    """
    n = int(request.args.get("n", "200"))
    log_dir = "logs"
    files = sorted(glob.glob(os.path.join(log_dir, "*.log")))
    if not files:
        return "no log files", 404
    latest = files[-1]
    try:
        with open(latest, "r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()
        tail = "".join(lines[-n:])
        return Response(tail, mimetype="text/plain")
    except Exception as e:
        return abort(500, f"read log error: {e}")

if __name__ == "__main__":
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
