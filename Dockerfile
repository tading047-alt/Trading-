# Dockerfile
FROM python:3.10-slim

# تثبيت أدوات الوقت
RUN apt-get update && apt-get install -y --no-install-recommends \
    ntpdate \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# مزامنة الوقت مع Google Servers
RUN ntpdate -u time.google.com

WORKDIR /app

# نسخ وتثبيت المتطلبات
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# نسخ الملفات
COPY main.py .
COPY credentials.json .

# تشغيل البرنامج
CMD ["python", "main.py"]
