FROM python:3.9-slim

WORKDIR /app

# تثبيت المكتبات
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# نسخ الكود
COPY . .

# إنشاء المجلدات للتأكد (سيتم ربطها لاحقاً بالـ Volumes)
RUN mkdir -p data output

CMD ["python", "main.py"]
