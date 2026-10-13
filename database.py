import sqlite3
import os

DB_FILE = os.getenv('DB_FILE', '/app/data/gateway.db')

def init_db():
    os.makedirs(os.path.dirname(DB_FILE), exist_ok=True)
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    
    # Einstellungen
    c.execute('''
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    ''')
    
    # SMS Logs
    c.execute('''
        CREATE TABLE IF NOT EXISTS sms_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            recipient TEXT NOT NULL,
            message TEXT NOT NULL,
            source TEXT NOT NULL,
            status TEXT NOT NULL,
            error_details TEXT
        )
    ''')

    # Signal-Verlauf fuer Grafiken / Logging
    c.execute('''
        CREATE TABLE IF NOT EXISTS signal_metrics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            rsrp INTEGER,
            rsrq INTEGER,
            sinr INTEGER,
            rssi INTEGER,
            ca_active INTEGER,
            band TEXT
        )
    ''')

    defaults = {
        'router_url': 'http://192.168.8.1/',
        'router_user': 'admin',
        'router_password': '',
        'default_phone': '',
        'api_key': 'MeinGeheimerApiKey123'
    }
    for k, v in defaults.items():
        c.execute('INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)', (k, v))

    conn.commit()
    conn.close()

def save_metric(rsrp, rsrq, sinr, rssi, ca_active, band):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''
        INSERT INTO signal_metrics (rsrp, rsrq, sinr, rssi, ca_active, band)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (rsrp, rsrq, sinr, rssi, 1 if ca_active else 0, band))
    # Altes Log nach 24h aufräumen
    c.execute("DELETE FROM signal_metrics WHERE timestamp < datetime('now', '-24 hours')")
    conn.commit()
    conn.close()

def get_metrics_history(limit=60):
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute('SELECT * FROM signal_metrics ORDER BY timestamp DESC LIMIT ?', (limit,))
    rows = [dict(row) for row in c.fetchall()]
    conn.close()
    return list(reversed(rows)) # Umgedreht für korrekte Zeitachse von links nach rechts

def get_settings():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute('SELECT key, value FROM settings')
    rows = c.fetchall()
    conn.close()
    return {row['key']: row['value'] for row in rows}

def save_setting(key, value):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)', (key, str(value)))
    conn.commit()
    conn.close()

def log_sms(recipient, message, source, status, error_details=None):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''
        INSERT INTO sms_logs (recipient, message, source, status, error_details)
        VALUES (?, ?, ?, ?, ?)
    ''', (recipient, message, source, status, error_details))
    conn.commit()
    conn.close()

def get_logs(limit=100):
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute('SELECT * FROM sms_logs ORDER BY timestamp DESC LIMIT ?', (limit,))
    rows = [dict(row) for row in c.fetchall()]
    conn.close()
    return rows