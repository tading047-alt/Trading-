FROM python:3.10-slim

WORKDIR /app

# نسخ وتثبيت المتطلبات
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# نسخ ملفات المشروع
COPY main.py .
COPY credentials.json .

# تشغيل البرنامج
CMD ["python", "main.py"]
