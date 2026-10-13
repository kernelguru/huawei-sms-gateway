# -*- coding: utf-8 -*-
import os
import time
import asyncio
import threading
from email import message_from_bytes
from flask import Flask, request, jsonify, render_template

from database import init_db, get_settings, save_setting, log_sms, get_logs, save_metric, get_metrics_history
from huawei_client import HuaweiGateway
from aiosmtpd.controller import Controller

init_db()
app = Flask(__name__)

WEB_PORT = 5000
SMTP_PORT = 1025

def dispatch_sms(phone, message, source):
    settings = get_settings()
    url = settings.get('router_url')
    user = settings.get('router_user')
    pwd = settings.get('router_password')
    default_phone = settings.get('default_phone')

    target_phone = phone if phone else default_phone
    if not target_phone:
        err = "Keine Rufnummer uebergeben und keine Standard-Zielrufnummer konfiguriert."
        log_sms('UNBEKANNT', message, source, 'FAILED', err)
        return False, err

    success, msg = HuaweiGateway.send_sms(url, user, pwd, target_phone, message)
    log_sms(target_phone, message, source, 'SENT' if success else 'FAILED', None if success else msg)
    return success, msg

# --- BACKGROUND MONITORING THREAD ---
def signal_poller_thread():
    while True:
        try:
            s = get_settings()
            if s.get('router_url') and s.get('router_user'):
                st = HuaweiGateway.get_modem_status(s.get('router_url'), s.get('router_user'), s.get('router_password'))
                if st.get('online') and isinstance(st.get('rsrp'), int):
                    save_metric(
                        rsrp=st.get('rsrp'),
                        rsrq=st.get('rsrq') if isinstance(st.get('rsrq'), int) else 0,
                        sinr=st.get('sinr') if isinstance(st.get('sinr'), int) else 0,
                        rssi=st.get('rssi') if isinstance(st.get('rssi'), int) else 0,
                        ca_active=st.get('carrier_aggregation'),
                        band=st.get('band')
                    )
        except Exception:
            pass
        time.sleep(15)

# --- ROUTES ---
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/v1/settings', methods=['GET', 'POST'])
def api_settings():
    if request.method == 'POST':
        data = request.get_json() or {}
        for key in ['router_url', 'router_user', 'router_password', 'default_phone', 'api_key']:
            if key in data:
                save_setting(key, data[key])
        return jsonify({'status': 'success', 'message': 'Einstellungen gespeichert'}), 200

    settings = get_settings()
    return jsonify({
        'router_url': settings.get('router_url'),
        'router_user': settings.get('router_user'),
        'has_password': bool(settings.get('router_password')),
        'default_phone': settings.get('default_phone'),
        'api_key': settings.get('api_key')
    }), 200

@app.route('/api/v1/modem/status', methods=['GET'])
def api_modem_status():
    s = get_settings()
    status = HuaweiGateway.get_modem_status(s.get('router_url'), s.get('router_user'), s.get('router_password'))
    return jsonify(status), 200

@app.route('/api/v1/modem/history', methods=['GET'])
def api_modem_history():
    return jsonify(get_metrics_history(60)), 200

@app.route('/api/v1/logs', methods=['GET'])
def api_logs():
    return jsonify(get_logs(100)), 200

@app.route('/api/v1/sms/send', methods=['POST'])
def api_send_sms():
    data = request.get_json() or {}
    s = get_settings()
    source = data.get('source', 'API')
    
    if source != 'WEB':
        provided_key = request.headers.get('X-API-Key') or data.get('api_key')
        if s.get('api_key') and provided_key != s.get('api_key'):
            return jsonify({'status': 'error', 'message': 'Ungueltiger API-Key'}), 401

    phone = data.get('to')
    message = data.get('message') or data.get('text')
    
    if not message:
        return jsonify({'status': 'error', 'message': 'Nachrichteninhalt ("message") fehlt'}), 400

    success, msg = dispatch_sms(phone, message, source)
    return jsonify({'status': 'success' if success else 'error', 'message': msg}), 200 if success else 500

@app.route('/api/v1/webhook', methods=['POST'])
def api_webhook():
    data = request.get_json(force=True, silent=True) or {}
    phone = data.get('to') or data.get('phone') or data.get('number')
    message = data.get('message') or data.get('text') or data.get('summary') or data.get('description') or str(data)

    success, msg = dispatch_sms(phone, message, 'WEBHOOK')
    return jsonify({'status': 'success' if success else 'error', 'message': msg}), 200 if success else 500

# --- SMTP HANDLER ---
class SMTPSMSHandler:
    async def handle_DATA(self, server, session, envelope):
        msg = message_from_bytes(envelope.content)
        body = ""
        if msg.is_multipart():
            for part in msg.walk():
                if part.get_content_type() == 'text/plain' and 'attachment' not in str(part.get('Content-Disposition')):
                    body = part.get_payload(decode=True).decode('utf-8', errors='ignore')
                    break
        else:
            body = msg.get_payload(decode=True).decode('utf-8', errors='ignore')

        if not body.strip():
            body = msg.get('Subject', '[Kein Text]')

        for recipient in envelope.rcpt_tos:
            phone_part = recipient.split('@')[0]
            phone = phone_part if phone_part.replace('+', '').isdigit() else None
            dispatch_sms(phone, body.strip(), 'SMTP')

        return '250 OK - SMS weitergeleitet'

def run_smtp_server():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    controller = Controller(SMTPSMSHandler(), hostname='0.0.0.0', port=SMTP_PORT)
    controller.start()
    loop.run_forever()

if __name__ == '__main__':
    threading.Thread(target=signal_poller_thread, daemon=True).start()
    threading.Thread(target=run_smtp_server, daemon=True).start()
    app.run(host='0.0.0.0', port=WEB_PORT)