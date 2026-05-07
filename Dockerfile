# استخدام نسخة خفيفة من بايثون
FROM python:3.9-slim

# ضبط مجلد العمل داخل الحاوية
WORKDIR /app

# نسخ ملف المكتبات أولاً (للاستفادة من الـ Caching)
COPY requirements.txt .

# تثبيت المكتبات
RUN pip install --no-cache-dir -r requirements.txt

# نسخ كود البوت (افترضنا أن اسم ملف الكود هو bot.py)
COPY bot.py .

# أمر تشغيل البوت
CMD ["python", "main.py"]
