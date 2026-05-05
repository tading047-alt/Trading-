# Dockerfile
FROM python:3.11-slim  # تغيير من 3.10 إلى 3.11

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py .
COPY credentials.json .

CMD ["python", "main.py"]
