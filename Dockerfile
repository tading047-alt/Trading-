FROM python:3.10-slim

WORKDIR /app

COPY requirements.txt .

# ✅ هنا - أكتب أوامر pip في Dockerfile
RUN pip uninstall -y python-telegram-bot || true
RUN pip install python-telegram-bot==13.7

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py .
COPY credentials.json .

CMD ["python", "main.py"]
