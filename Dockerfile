# استخدام نسخة بايثون 3.11 مستقرة
FROM python:3.11-slim

WORKDIR /app

# تثبيت git بالإضافة إلى أدوات البناء
RUN apt-get update && apt-get install -y \
    build-essential \
    gcc \
    git \
    && rm -rf /var/lib/apt/lists/*

# تحديث pip
RUN pip install --no-cache-dir --upgrade pip

# نسخ ملف المتطلبات
COPY requirements.txt .

# تثبيت المكتبات
RUN pip install --no-cache-dir -r requirements.txt

# نسخ باقي ملفات المشروع
COPY . .

CMD ["python", "main.py"]
