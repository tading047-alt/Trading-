# =========================
# 🐍 BASE IMAGE
# =========================
FROM python:3.11-slim

# =========================
# 📁 WORKDIR
# =========================
WORKDIR /app

# =========================
# ⚙️ SYSTEM DEPENDENCIES
# =========================
RUN apt-get update && apt-get install -y \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# =========================
# 📦 COPY PROJECT
# =========================
COPY . /app

# =========================
# 📚 INSTALL PYTHON LIBS
# =========================
RUN pip install --no-cache-dir \
    ccxt \
    pandas \
    numpy \
    requests

# =========================
# 🚀 ENV VARIABLES (optional default)
# =========================
ENV PYTHONUNBUFFERED=1

# =========================
# ▶️ RUN BOT
# =========================
CMD ["python", "main.py"]
