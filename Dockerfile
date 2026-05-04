# Dockerfile
FROM python:3.10-slim

WORKDIR /app

# نسخ ملف المتطلبات
COPY requirements.txt .

# تثبيت المكتبات
RUN pip install --no-cache-dir -r requirements.txt

# نسخ ملفات المشروع
COPY main.py .
COPY credentials.json .

# تشغيل البرنامج
CMD ["python", "main.py"]
