import requests
import logging
import re

logger = logging.getLogger("ZabbixService")

def decode_huawei_snmp_index(snmp_index_str: str):
    """
    Convierte un SNMP INDEX de Huawei (ej. '4194345728.2' o '4194312192.0')
    en frame, slot, port, ont_id exactos.
    """
    try:
        parts = str(snmp_index_str).strip().split(".")
        base_index = int(parts[0])
        ont_id = int(parts[1]) if len(parts) > 1 else 0

        # Máscara para eliminar el prefijo 0xFA000000 (4194304000) de Huawei GPON
        offset = base_index & 0x00FFFFFF

        frame = (offset >> 19) & 0x1F
        slot = (offset >> 13) & 0x3F
        port = (offset >> 8) & 0x1F

        return frame, slot, port, ont_id
    except Exception as e:
        logger.error(f"Error decodificando SNMP Index '{snmp_index_str}': {e}")
        return 0, 1, 0, 0
        

class ZabbixService:
    def __init__(self, url: str, token: str):
        self.url = f"{url.rstrip('/')}/api_jsonrpc.php"
        self.token = token

    def get_registered_onts(self):
        headers = {
            "Content-Type": "application/json-rpc",
            "Authorization": f"Bearer {self.token}"
        }

        # Pedimos snmp_oid además de key_
        payload = {
            "jsonrpc": "2.0",
            "method": "item.get",
            "params": {
                "output": ["itemid", "name", "key_", "snmp_oid", "lastvalue"],
                "search": {
                    "name": "ONTB-"
                },
                "searchByAny": True
            },
            "id": 1
        }

        try:
            response = requests.post(self.url, json=payload, headers=headers, timeout=20)
            response.raise_for_status()
            data = response.json()

            if "error" in data:
                logger.error(f"Error Zabbix API: {data['error']}")
                return []

            results = data.get("result", [])
            onts_map = {}

            for item in results:
                raw_name = item.get("name", "")
                item_key = item.get("key_", "")
                snmp_oid = item.get("snmp_oid", "")
                last_val = item.get("lastvalue", "N/A")

                is_ip_item = "IP ONT:" in raw_name
                is_ping_item = "ICMP Ping:" in raw_name

                if not (is_ip_item or is_ping_item):
                    continue

                clean_name = raw_name.replace("IP ONT:", "").replace("ICMP Ping:", "").strip()
                if "_zone" in clean_name:
                    clean_name = clean_name.split("_zone")[0]

                match = re.search(r'ONTB-[A-Za-z0-9_-]+', clean_name)
                client_id = match.group(0) if match else clean_name

                if client_id not in onts_map:
                    onts_map[client_id] = {
                        "client": client_id,
                        "ip": "N/A",
                        "status": "N/A",
                        "frame": 0,
                        "slot": 1,
                        "port": 0,
                        "ont_id": 0
                    }

                # Buscar SNMP Index en snmp_oid, key_ o name
                # Ejemplo de OID: .1.3.6.1.4.1.2011.6.128.1.1.2.43.1.9.4194312192.2
                combined_text = f"{snmp_oid} {item_key} {raw_name}"
                
                # Busca cualquier patrón del tipo 4194XXXXXX.Y
                idx_match = re.search(r'(\d{9,10}\.\d+)', combined_text)
                if idx_match:
                    snmp_idx = idx_match.group(1)
                    f, s, p, ont_id = decode_huawei_snmp_index(snmp_idx)
                    onts_map[client_id]["frame"] = f
                    onts_map[client_id]["slot"] = s
                    onts_map[client_id]["port"] = p
                    onts_map[client_id]["ont_id"] = ont_id

                if is_ip_item:
                    onts_map[client_id]["ip"] = last_val
                elif is_ping_item:
                    onts_map[client_id]["status"] = last_val

            return list(onts_map.values())

        except Exception as e:
            logger.error(f"Error consultando items en Zabbix: {e}")
            return []