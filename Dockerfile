FROM python:3.11-slim

# Arbeitsverzeichnis erstellen
WORKDIR /app

# System-Abhängigkeiten installieren
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Python-Abhängigkeiten kopieren und installieren
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Anwendungs-Code kopieren
COPY . .

# Datenverzeichnis für SQLite anlegen
RUN mkdir -p /app/data

# Ports exponieren (5000: Web/API, 1025: SMTP)
EXPOSE 5000 1025

# App starten
CMD ["python", "app.py"]