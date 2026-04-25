# استخدام نسخة بايثون كاملة لتجنب نقص الاعتماديات
FROM python:3.10-slim

# إعداد المجلد الرئيسي
WORKDIR /app

# تثبيت أدوات البناء الضرورية (GCC و C++)
RUN apt-get update && apt-get install -y \
    build-essential \
    gcc \
    python3-dev \
    && rm -rf /var/lib/apt/lists/*

# تحديث pip
RUN pip install --no-cache-dir --upgrade pip

# نسخ وتثبيت المكتبات
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# نسخ باقي ملفات المشروع
COPY . .

# تشغيل البوت
CMD ["python", "main.py"]
