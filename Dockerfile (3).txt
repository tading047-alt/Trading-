FROM python:3.11-slim

WORKDIR /app

# Copier et installer les dépendances
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copier le script Python
COPY main.py .

# Lancer le bot
CMD ["python", "main.py"]
