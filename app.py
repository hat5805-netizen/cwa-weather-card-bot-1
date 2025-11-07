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

#@app.route('/run')
#def run():
#    thread = threading.Thread(target=run_script)
#    thread.start()
#    return "任務已啟動！正在下載天氣小卡... (請查看 Render Logs 確認結果)"

@app.route("/run")
def run_task():
    try:
        from download_cwa3day_card import parse_weather_ad_card
        parse_weather_ad_card()
        return "OK", 200  # ✅ 避免輸出太多文字
    except Exception as e:
        return "ERR", 200  # ✅ 一樣不要輸出太大內容


if __name__ == '__main__':
    import os
    port = int(os.environ.get('PORT', '8080'))
    app.run(host='0.0.0.0', port=port)
