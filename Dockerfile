FROM python:3.10-slim

WORKDIR /app

# نسخ ملف المتطلبات وتثبيته
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# نسخ باقي الملفات
COPY . .

# تشغيل البوت (الملف اسمه main.py)

CMD ["python", "/app/main.py"]
