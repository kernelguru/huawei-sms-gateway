# -*- coding: utf-8 -*-
import re
from huawei_lte_api.Client import Client
from huawei_lte_api.Connection import Connection

class HuaweiGateway:
    @staticmethod
    def send_sms(url, username, password, phone_number: str, message: str):
        clean_phone = re.sub(r'[^\d+]', '', phone_number)
        if not clean_phone:
            return False, "Ungueltige Empfaenger-Rufnummer"

        try:
            with Connection(url, username=username, password=password) as connection:
                client = Client(connection)
                client.sms.send_sms(phone_numbers=[clean_phone], message=message)
            return True, f"SMS erfolgreich an {clean_phone} gesendet"
        except Exception as e:
            return False, f"Huawei H153 Fehler: {str(e)}"

    @staticmethod
    def parse_signal_val(val_str):
        if not val_str:
            return None
        match = re.search(r'(-?\d+)', str(val_str))
        if match:
            return int(match.group(1))
        return None

    @staticmethod
    def get_modem_status(url, username, password):
        try:
            with Connection(url, username=username, password=password) as connection:
                client = Client(connection)
                net_info = client.net.current_plmn()
                signal = client.device.signal()
                status_info = client.monitoring.status()

                ca_active = False
                scell_info = signal.get('scell_info') or signal.get('pcell_info')
                if scell_info or signal.get('ca_state') == '1' or '+' in str(status_info.get('CurrentNetworkTypeEx', '')):
                    ca_active = True

                rsrp_val = HuaweiGateway.parse_signal_val(signal.get('rsrp'))
                rsrq_val = HuaweiGateway.parse_signal_val(signal.get('rsrq'))
                sinr_val = HuaweiGateway.parse_signal_val(signal.get('sinr'))
                rssi_val = HuaweiGateway.parse_signal_val(signal.get('rssi'))

                return {
                    'online': True,
                    'provider': net_info.get('FullName', 'Unbekannt'),
                    'network_type': net_info.get('rat', '5G/LTE'),
                    'band': str(signal.get('band') or signal.get('workmode') or 'N/A'),
                    'cell_id': str(signal.get('cell_id') or 'N/A'),
                    'carrier_aggregation': ca_active,
                    'rsrp': rsrp_val if rsrp_val is not None else (signal.get('rsrp') or 'N/A'),
                    'rsrq': rsrq_val if rsrq_val is not None else (signal.get('rsrq') or 'N/A'),
                    'rssi': rssi_val if rssi_val is not None else (signal.get('rssi') or 'N/A'),
                    'sinr': sinr_val if sinr_val is not None else (signal.get('sinr') or 'N/A')
                }
        except Exception as e:
            return {'online': False, 'error': str(e)}