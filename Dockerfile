# استخدام نسخة بيثون خفيفة
FROM python:3.9-slim

# تحديد مجلد العمل داخل الحاوية
WORKDIR /app

# نسخ ملف المتطلبات أولاً للاستفادة من الـ Cache
COPY requirements.txt .

# تثبيت المكتبات
RUN pip install --no-cache-dir -r requirements.txt

# نسخ باقي ملفات المشروع (الكود)
COPY . .

# إنشاء مجلد المخرجات (اختياري لأن الكود سينشئه، لكنه أفضل للتنظيم)
RUN mkdir -p output

# تشغيل السكريبت عند تشغيل الحاوية
CMD ["python", "main.py"]
