# Huawei 5G CPE SMS Gateway (H153-381)

Ein schlankes Docker-Gateway für Huawei 5G/LTE CPE Router (z. B. H153-381, B535, B818) mit grafischem Web-Dashboard, REST-API, Webhook-Receiver und SMTP-Bridge.

## Features
- **Web Interface:** SMS manuell versenden, Live-Signalgrafiken (RSRP, SINR), Carrier Aggregation Status.
- **REST & Webhook API:** Kompatibel mit Uptime Kuma, Grafana, Home Assistant & Zabbix.
- **SMTP Server:** Mails direkt als SMS weiterleiten (Port 1025).
- **Web Configuration:** Router-Zugangsdaten und Fallback-Zielrufnummer direkt im UI konfigurieren.

## Quickstart

```bash
docker compose up -d --build

Öffne anschließend http://<server-ip>:5000 im Browser.
