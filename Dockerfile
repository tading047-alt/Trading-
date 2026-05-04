# Dockerfile - نسخة محدثة بدون ntpdate
FROM python:3.10-slim

# تثبيت أدوات الوقت المتاحة
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    tzdata \
    && rm -rf /var/lib/apt/lists/*

# تعيين المنطقة الزمنية (اختياري - غيرها حسب موقعك)
ENV TZ=Africa/Tunis
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

WORKDIR /app

# نسخ وتثبيت المتطلبات
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# نسخ الملفات
COPY main.py .
COPY credentials.json .

# تشغيل البرنامج
CMD ["python", "main.py"]
