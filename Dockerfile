# 1. استخدام نسخة بايثون حديثة ومستقرة
FROM python:3.11-slim

# 2. تعيين مجلد العمل داخل الحاوية
WORKDIR /app

# 3. تثبيت أدوات النظام الضرورية (لتعامل بايثون مع الرسوم البيانية)
RUN apt-get update && apt-get install -y \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# 4. نسخ ملف المتطلبات وتثبيت المكتبات
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 5. نسخ جميع ملفات المشروع (main.py و credentials.json وغيرها)
COPY . .

# 6. الأمر المشغل للبوت
CMD ["python", "main.py"]
