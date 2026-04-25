# استخدام نسخة بايثون حديثة تدعم pandas 3.0 والمكتبات الأخرى
FROM python:3.11-slim

WORKDIR /app

# تثبيت الأدوات الضرورية لبناء المكتبات
RUN apt-get update && apt-get install -y \
    build-essential \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# تحديث pip لأحدث نسخة
RUN pip install --no-cache-dir --upgrade pip

# نسخ ملف المتطلبات
COPY requirements.txt .

# تثبيت المكتبات مع تحديد نسخ متوافقة
RUN pip install --no-cache-dir -r requirements.txt

# نسخ باقي الملفات
COPY . .

CMD ["python", "main.py"]
