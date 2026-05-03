FROM python:3.11-slim

WORKDIR /app

# Installer les dépendances système (dont sqlite3)
RUN apt-get update && apt-get install -y \
    build-essential \
    gcc \
    git \
    sqlite3 \
    libsqlite3-dev \
    && rm -rf /var/lib/apt/lists/*

# Copier et installer les dépendances Python
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip
RUN pip install --no-cache-dir -r requirements.txt

# Copier le code de l'application
COPY . .

# Commande par défaut (à adapter selon votre besoin)
CMD ["python", "main.py"]
