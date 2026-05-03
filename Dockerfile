FROM python:3.11-slim

WORKDIR /app

# Installer directement les packages sans requirements.txt
RUN pip install --no-cache-dir pandas openpyxl

COPY . .

CMD ["python", "main.py"]
