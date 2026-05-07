FROM python:3.11-slim

WORKDIR /app

# تثبيت اعتمادات النظام (اختياري - للحصول على أداء أفضل)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# نسخ وتثبيت مكتبات Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# نسخ ملفات المشروع
COPY main.py .
COPY .env .

# إنشاء مجلد للتسجيلات (logs)
RUN mkdir -p /app/logs

# تعيين متغيرات البيئة
ENV PYTHONUNBUFFERED=1
ENV TZ=UTC

# تشغيل البوت
CMD ["python", "main.py"]
