# 使用官方 Python（bookworm），可 apt 安裝 chromium
FROM python:3.11-slim

# 基本套件 + Chromium + Chromedriver +中文字型
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        chromium chromium-driver fonts-noto-cjk ca-certificates curl && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

COPY . /app

# Selenium 路徑
ENV GOOGLE_CHROME_BIN=/usr/bin/chromium
ENV CHROMEDRIVER_PATH=/usr/bin/chromedriver
ENV PYTHONUNBUFFERED=1

# ✅ 關鍵：把 worker 的 stdout/stderr 收進 gunicorn，並把 access/error log 打到 stdout
# - --capture-output：把 worker print()/stderr 轉到 error log
# - --access-logfile - / --error-logfile -：都往 stdout 輸出（Render 會收）
# - --log-level info：降低被吞 log 的機率
CMD ["bash","-lc","exec gunicorn app:app --bind 0.0.0.0:${PORT:-8080} --timeout 180 --workers 1 --capture-output --access-logfile - --error-logfile - --log-level info"]
