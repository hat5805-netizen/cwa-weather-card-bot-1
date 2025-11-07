from flask import Flask, request
import subprocess
import threading
import sys

app = Flask(__name__)

# -------------------------
# 執行主要的 Python 腳本
# -------------------------
def run_script():
    try:
        result = subprocess.run(
            ["python", "download_cwa3day_card.py"],
            capture_output=True,
            text=True,
            timeout=180
        )
        # --- 將 stdout/stderr 全部印出到 Render Logs ---
        print("腳本輸出:\n", result.stdout, flush=True)
        if result.stderr:
            print("腳本錯誤:\n", result.stderr, flush=True)

        return result.stdout + result.stderr

    except Exception as e:
        print("執行失敗:", e, flush=True)
        return str(e)


# -------------------------
# Render Health Check
# -------------------------
@app.route('/')
def home():
    return "CWA Weather Card Bot is running!"


# -------------------------
# 主要入口 `/run`
# sync=1 → 同步執行（會等待腳本跑完）
# 不帶 sync → 背景執行（適合 cron/GAS 喚醒）
# -------------------------
@app.route('/run')
def run():
    sync = request.args.get("sync", "0") == "1"

    if sync:
        print("[sync mode] 接收到同步執行請求", flush=True)
        output = run_script()
        # 回傳最後 2000 字，避免訊息太大
        return "✅ 同步執行完成\n\n" + output[-2000:]

    else:
        print("[async mode] 已啟動背景任務", flush=True)
        thread = threading.Thread(target=run_script, daemon=True)
        thread.start()
        return "任務已啟動！正在下載天氣小卡... (請查看 Render Logs 確認結果)"


# -------------------------
# 若直接本機啟動 Flask（Render 用不到）
# -------------------------
if __name__ == '__main__':
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
