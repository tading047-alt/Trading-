FROM python:3.10-slim

WORKDIR /app

# نسخ ملف المتطلبات وتثبيت المكتبات
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# نسخ باقي الملفات (بما فيها ملف main)
COPY . .

# تشغيل البوت باستخدام اسم الملف الصحيح (main وليس main.py)
CMD ["python", "main"]
