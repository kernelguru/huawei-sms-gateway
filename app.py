# -*- coding: utf-8 -*-
import os
import ast
import time
import asyncio
import threading
from functools import wraps
from email import message_from_bytes
from flask import Flask, request, jsonify, render_template, session, redirect, url_for

from database import init_db, get_settings, save_setting, log_sms, get_logs, save_metric, get_metrics_history
from huawei_client import HuaweiGateway
from aiosmtpd.controller import Controller
from aiosmtpd.smtp import AuthResult, LoginPassword

init_db()
app = Flask(__name__)
app.secret_key = os.urandom(24)

WEB_PORT = 5000
SMTP_PORT = 1025

# --- AUTH DECORATOR FUER WEB DASHBOARD ---
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('logged_in'):
            if request.path.startswith('/api/'):
                return jsonify({'status': 'error', 'message': 'Nicht eingeloggt'}), 401
            return redirect(url_for('login_page'))
        return f(*args, **kwargs)
    return decorated_function

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

# --- LOGIN & LOGOUT ROUTES ---
@app.route('/login', methods=['GET', 'POST'])
def login_page():
    if request.method == 'POST':
        data = request.get_json(silent=True) or request.form
        password = data.get('password')
        s = get_settings()
        if password and password == s.get('web_password'):
            session['logged_in'] = True
            return jsonify({'status': 'success'}), 200
        return jsonify({'status': 'error', 'message': 'Falsches Passwort'}), 401
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login_page'))

# --- PROTECTED WEB DASHBOARD ROUTES ---
@app.route('/')
@login_required
def index():
    return render_template('index.html')

@app.route('/api/v1/settings', methods=['GET', 'POST'])
@login_required
def api_settings():
    if request.method == 'POST':
        data = request.get_json() or {}
        for key in ['router_url', 'router_user', 'router_password', 'default_phone', 'api_key', 'web_password']:
            if key in data and data[key] != '':
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
@login_required
def api_modem_status():
    s = get_settings()
    status = HuaweiGateway.get_modem_status(s.get('router_url'), s.get('router_user'), s.get('router_password'))
    return jsonify(status), 200

@app.route('/api/v1/modem/history', methods=['GET'])
@login_required
def api_modem_history():
    return jsonify(get_metrics_history(60)), 200

@app.route('/api/v1/logs', methods=['GET'])
@login_required
def api_logs():
    return jsonify(get_logs(100)), 200

# --- REST & WEBHOOK API ---
@app.route('/api/v1/sms/send', methods=['POST'])
def api_send_sms():
    data = request.get_json() or {}
    s = get_settings()
    configured_key = s.get('api_key')
    
    if session.get('logged_in'):
        pass
    else:
        provided_key = request.headers.get('X-API-Key') or data.get('api_key') or request.args.get('api_key')
        if configured_key and provided_key != configured_key:
            return jsonify({'status': 'error', 'message': 'Ungueltiger oder fehlender API-Key'}), 401

    phone = data.get('to')
    message = data.get('message') or data.get('text')
    source = 'WEB' if session.get('logged_in') else 'API'
    
    if not message:
        return jsonify({'status': 'error', 'message': 'Nachrichteninhalt ("message") fehlt'}), 400

    success, msg = dispatch_sms(phone, message, source)
    return jsonify({'status': 'success' if success else 'error', 'message': msg}), 200 if success else 500

@app.route('/api/v1/webhook', methods=['POST'])
def api_webhook():
    data = request.get_json(force=True, silent=True) or {}
    s = get_settings()
    configured_key = s.get('api_key')

    if configured_key and not session.get('logged_in'):
        provided_key = (
            request.headers.get('X-API-Key') 
            or data.get('api_key') 
            or request.args.get('api_key')
        )
        if provided_key != configured_key:
            return jsonify({'status': 'error', 'message': 'Ungueltiger oder fehlender API-Key'}), 401

    phone = data.get('to') or data.get('phone') or data.get('number')
    message = None
    
    if 'msg' in data:
        raw_msg = data['msg']
        if isinstance(raw_msg, str) and raw_msg.startswith('{') and 'msg' in raw_msg:
            try:
                parsed_dict = ast.literal_eval(raw_msg)
                if isinstance(parsed_dict, dict) and 'msg' in parsed_dict:
                    message = parsed_dict['msg']
            except Exception:
                pass
        if not message:
            message = str(raw_msg)

    if not message and 'monitor' in data and isinstance(data['monitor'], dict):
        monitor_name = data['monitor'].get('name', 'Dienst')
        status = "DOWN ??" if data.get('heartbeat', {}).get('status') == 0 else "UP ??"
        msg_text = data.get('heartbeat', {}).get('msg', '')
        message = f"Uptime Kuma: {monitor_name} ist {status}. ({msg_text})"

    if not message:
        message = data.get('text') or data.get('summary') or data.get('description') or str(data)

    success, msg = dispatch_sms(phone, message, 'WEBHOOK')
    return jsonify({'status': 'success' if success else 'error', 'message': msg}), 200 if success else 500

# --- ABGESICHERTER SMTP SERVER HANDLER (MIT AUTH) ---
class Authenticator:
    def __call__(self, mechanism, login, password):
        s = get_settings()
        api_key = s.get('api_key')
        web_pass = s.get('web_password')

        # Akzeptiert als Passwort entweder den konfigurierten API-Key oder das Web-Passwort
        if password in [api_key, web_pass] and password != '':
            return AuthResult(success=True)
        return AuthResult(success=False, handled=True)

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
    
    # SMTP-Authentifizierung aktivieren
    handler = SMTPSMSHandler()
    controller = Controller(
        handler, 
        hostname='0.0.0.0', 
        port=SMTP_PORT, 
        authenticator=Authenticator(),
        auth_required=True,
        auth_require_tls=False
    )
    controller.start()
    loop.run_forever()

if __name__ == '__main__':
    threading.Thread(target=signal_poller_thread, daemon=True).start()
    threading.Thread(target=run_smtp_server, daemon=True).start()
    app.run(host='0.0.0.0', port=WEB_PORT)