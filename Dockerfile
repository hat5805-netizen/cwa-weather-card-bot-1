# 使用官方 Python（bookworm），可 apt 安裝 chromium
FROM python:3.11-slim

# 基本套件 + Chromium + Chromedriver +中文字型
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        chromium chromium-driver fonts-noto-cjk ca-certificates curl && \
    rm -rf /var/lib/apt/lists/*

# 工作目錄
WORKDIR /app

# 先安裝相依
COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

# 複製程式
COPY . /app

# 提供給 Selenium 的固定路徑
ENV GOOGLE_CHROME_BIN=/usr/bin/chromium
ENV CHROMEDRIVER_PATH=/usr/bin/chromedriver
ENV PYTHONUNBUFFERED=1

# Render 會提供 $PORT；gunicorn 維持單 worker 即可
CMD ["bash","-lc","exec gunicorn app:app --bind 0.0.0.0:${PORT:-8080} --timeout 180 --workers 1"]
