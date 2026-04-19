FROM python:3.10-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# سطر للتشخيص: يعرض محتويات المجلد أثناء البناء
RUN ls -la /app

CMD ["python", "/app/main.py"]
