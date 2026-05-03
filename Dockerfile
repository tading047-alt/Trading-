FROM python:3.9-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
# إنشاء المجلدات لضمان الصلاحيات
RUN mkdir -p /app/data /app/output
CMD ["python", "main.py"]
