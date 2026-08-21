import re
import time
import telnetlib
import logging
from config import settings

logger = logging.getLogger("HuaweiOLT")

TRAFFIC_TABLES = {
    "100M": {"up": 14, "down": 15},
    "200M": {"up": 8, "down": 9},
    "300M": {"up": 12, "down": 13},
    "400M": {"up": 10, "down": 11},
    "500M": {"up": 16, "down": 17},
    "600M": {"up": 18, "down": 19},
}

class HuaweiOLT:
    def __init__(self, host=None, username=None, password=None, port=None):
        self.host = host or settings.OLT_HOST
        self.username = username or settings.OLT_USER
        self.password = password or settings.OLT_PASS
        self.port = port or settings.OLT_PORT

    def _execute_telnet_session(self, commands: list) -> str:
        full_output = ""
        try:
            tn = telnetlib.Telnet(self.host, self.port, timeout=15)
            
            # 1. Login
            time.sleep(1)
            tn.write(self.username.encode('ascii') + b"\n")
            time.sleep(0.5)
            tn.write(self.password.encode('ascii') + b"\n")
            time.sleep(1)
            
            # 2. Privilegios y ajustes de terminal
            tn.write(b"enable\n")
            time.sleep(0.5)
            tn.write(b"config\n")
            time.sleep(0.5)
            tn.write(b"undo smart\n")
            time.sleep(0.5)
            tn.write(b"scroll 512\n")
            time.sleep(0.5)
            
            # Limpiar buffer de bienvenida
            _ = tn.read_very_eager()
            
            # 3. Ejecutar comandos y esperar prompt
            for cmd in commands:
                tn.write(cmd.encode('ascii') + b"\n")
                cmd_buffer = ""
                start_time = time.time()
                while time.time() - start_time < 5:
                    time.sleep(0.3)
                    chunk = tn.read_very_eager().decode('utf-8', errors='ignore')
                    cmd_buffer += chunk
                    # Manejar confirmación automática (y/n)
                    if "y/n" in chunk.lower() or "are you sure" in chunk.lower():
                        tn.write(b"y\n")
                    if "#" in chunk or ">" in chunk:
                        break
                        
                full_output += cmd_buffer

            tn.write(b"quit\n")
            tn.close()
            return full_output

        except Exception as e:
            logger.error(f"Error en sesión Telnet OLT: {e}")
            raise RuntimeError(f"Error Telnet OLT: {e}")

    def get_unconfigured_onts(self):
        try:
            output = self._execute_telnet_session(["display ont autofind all"])
            if "do not exist" in output or "Failure" in output:
                return []
                
            onts = []
            blocks = output.split("Number")
            
            for block in blocks[1:]:
                ont_data = {}
                fsp_match = re.search(r"F/S/P\s*:\s*(\d+)/(\d+)/(\d+)", block)
                if fsp_match:
                    ont_data["frame"] = int(fsp_match.group(1))
                    ont_data["slot"] = int(fsp_match.group(2))
                    ont_data["port"] = int(fsp_match.group(3))
                
                sn_match = re.search(r"Ont SN\s*:\s*([A-Z0-9]{16})", block)
                if sn_match:
                    ont_data["sn"] = sn_match.group(1)
                
                if "frame" in ont_data and "sn" in ont_data:
                    onts.append(ont_data)
                    
            return onts
        except Exception as e:
            logger.error(f"Error obteniendo autofind: {e}")
            return []

    def _get_next_free_ont_id(self, frame: int, slot: int, port: int) -> int:
        try:
            cmd = f"display ont info {frame} {slot} {port} all"
            output = self._execute_telnet_session([cmd])
            
            logger.debug(f"[GET_FREE_ID] Salida CLI recibida de MA5800:\n{output}")
            
            used_ids = set()

            # Regex flexible: Tolera espacios opcionales alrededor de las barras del F/S/P
            # Ejemplo de match: "0/ 2/7   0", "0/2/7 1", "0 / 2 / 7 \t 15"
            pattern = rf"{frame}\s*/\s*{slot}\s*/\s*{port}\s+(\d+)"
            matches = re.findall(pattern, output)
            
            for m in matches:
                used_ids.add(int(m))

            logger.info(f"[GET_FREE_ID] IDs ocupados detectados en {frame}/{slot}/{port}: {sorted(list(used_ids))}")

            # Buscar el primer ID libre entre 0 y 127
            for candidate in range(128):
                if candidate not in used_ids:
                    logger.info(f"[GET_FREE_ID] Próximo ID libre para asignar: {candidate}")
                    return candidate
                    
            raise Exception(f"El puerto {frame}/{slot}/{port} esta lleno (128 ONTs ocupadas).")

        except Exception as e:
            logger.error(f"[GET_FREE_ID] Error calculando ONT ID libre en {frame}/{slot}/{port}: {e}")
            raise e
    
    def provision_ont_excel_flow(
        self, frame: int, slot: int, port: int, ont_id: int = None, sn: str = "",
        contract: str = "", client_name: str = "", ip: str = "", plan: str = "", vlan: int = 100
    ):
        # 1. LOG DE ENTRADA: Validar qué tipos y valores llegan de la llamada
        logger.debug(
            f"[PROVISION] Params recibidos -> F/S/P: {frame}/{slot}/{port} | "
            f"ont_id_raw: {ont_id} (tipo: {type(ont_id).__name__}) | SN: '{sn}' | Contrato: '{contract}'"
        )
        # 2. Evaluación del ID
        if ont_id is None or ont_id == "" or ont_id == 0 or str(ont_id).strip() == "0":
            logger.info(f"[PROVISION] 'ont_id' no valido ({ont_id}). Buscando proximo ID libre en OLT...")
            ont_id = self._get_next_free_ont_id(frame, slot, port)
            logger.info(f"[PROVISION] ONT ID libre retornado por OLT para {sn}: {ont_id}")
        else:
            logger.info(f"[PROVISION] Usando 'ont_id' pasado explícitamente: {ont_id}")

        clean_name = client_name.replace(" ", "_").upper()
        description = f"ONTB-INT{contract}-{clean_name}"
        
        indices = TRAFFIC_TABLES.get(plan.upper(), {"up": 12, "down": 13})
        idx_up = indices["up"]
        idx_down = indices["down"]

        # 3. CORRECCIÓN EN COMANDOS: Se añade 'ont-id {ont_id}' a la confirmación
        commands = [
            f"interface gpon {frame}/{slot}",
            f'ont confirm {port} sn-auth {sn} omci ont-lineprofile-id 1 ont-srvprofile-id 1 desc "{description}"',
            f"ont port native-vlan {port} {ont_id} eth 1 vlan {vlan} priority 0",
            f"ont ipconfig {port} {ont_id} static ip-address {ip} mask 255.255.255.0",
            "quit",
            f"service-port vlan {vlan} gpon {frame}/{slot}/{port} ont {ont_id} gemport 1 multi-service user-vlan {vlan} tag-transform translate inbound traffic-table index {idx_up} outbound traffic-table index {idx_down}",
            "save"
        ]

        # 4. LOG DE SALIDA: Imprimir la lista de comandos que se enviarán por Telnet
        logger.debug(f"[PROVISION] Lista de comandos a ejecutar en OLT:\n" + "\n".join(commands))

        return self._execute_telnet_session(commands)

    def get_current_plan(self, frame: int, slot: int, port: int, ont_id: int) -> str:
        try:
            commands = [f"display service-port port {frame}/{slot}/{port} ont {ont_id}"]
            output = self._execute_telnet_session(commands)
            
            logger.info(f"[GET_PLAN] Salida CLI para {frame}/{slot}/{port} ONT {ont_id}:\n{output}")
            
            # Mapeo inverso evaluando tanto la bajada (TX/down) como la subida (RX/up)
            # TRAFFIC_TABLES: {"600M": {"up": 18, "down": 19}, ...}
            
            # Buscar la fila de datos que contiene el estado 'up' o 'down' al final
            # Ejemplo de fila: "368  100 common  gpon 0/1 /4  0  1  vlan 100  19  18  up"
            lines = output.splitlines()
            for line in lines:
                if "gpon" in line.lower() and ("up" in line.lower() or "down" in line.lower()):
                    parts = line.split()
                    # En la tabla Huawei: parts[-3] es RX, parts[-2] es TX, parts[-1] es STATE
                    if len(parts) >= 3:
                        try:
                            rx_idx = int(parts[-3]) # Inbound / Subida
                            tx_idx = int(parts[-2]) # Outbound / Bajada

                            # Mapear contra el diccionario TRAFFIC_TABLES
                            for plan_name, idx_dict in TRAFFIC_TABLES.items():
                                if idx_dict["up"] == rx_idx or idx_dict["down"] == tx_idx or idx_dict["up"] == tx_idx or idx_dict["down"] == rx_idx:
                                    return plan_name

                            return f"Index RX:{rx_idx} TX:{tx_idx}"
                        except ValueError:
                            continue

            return "No asignado"
            
        except Exception as e:
            logger.error(f"Error consultando plan actual en OLT: {e}")
            return "Error al consultar"

    def change_ont_plan(self, frame: int, slot: int, port: int, ont_id: int, new_plan: str, vlan: int = 100):
        try:
            indices = TRAFFIC_TABLES.get(new_plan.upper(), {"up": 12, "down": 13})
            idx_up = indices["up"]
            idx_down = indices["down"]

            # 1. Consultar service-ports activos para esa ONT
            check_sp_cmd = [f"display service-port port {frame}/{slot}/{port} ont {ont_id}"]
            sp_output = self._execute_telnet_session(check_sp_cmd)

            sp_ids = re.findall(r'^\s*(\d+)\s+', sp_output, re.MULTILINE)

            # 2. Generar comandos para actualizar las traffic-tables del service-port
            commands = []

            for sp_id in sp_ids:
                commands.append(f"service-port {sp_id} inbound traffic-table index {idx_up} outbound traffic-table index {idx_down}")

            commands.append("save")

            output = self._execute_telnet_session(commands)
            logger.info(f"Salida OLT cambio de plan: {output}")

            if "Error" in output or "Failure" in output:
                return False, output.strip()

            return True, "Plan cambiado correctamente en la OLT"

        except Exception as e:
            logger.error(f"Error Telnet en change_ont_plan: {e}")
            return False, str(e)

    def delete_ont(self, frame: int, slot: int, port: int, ont_id: int, vlan: int = 100):
        try:
            # 1. Consultar service-ports asociados para eliminarlos primero
            check_sp_cmd = [f"display service-port port {frame}/{slot}/{port} ont {ont_id}"]
            sp_output = self._execute_telnet_session(check_sp_cmd)

            sp_ids = re.findall(r'^\s*(\d+)\s+', sp_output, re.MULTILINE)
            logger.info(f"Service-ports encontrados para borrar en ONT {frame}/{slot}/{port} ID {ont_id}: {sp_ids}")

            commands = []
            for sp_id in sp_ids:
                commands.append(f"undo service-port {sp_id}")

            commands.extend([
                f"interface gpon {frame}/{slot}",
                f"ont delete {port} {ont_id}",
                "quit",
                "save"
            ])

            output = self._execute_telnet_session(commands)
            logger.info(f"Salida OLT borrado ONT: {output}")

            if "Error" in output or "Failure" in output:
                return False, output.strip()

            return True, "ONT y Service-Ports eliminados exitosamente"

        except Exception as e:
            logger.error(f"Error Telnet en delete_ont: {e}")
            return False, str(e)

    def change_ont_description(self, frame: int, slot: int, port: int, ont_id: int, new_description: str):
        try:
            # Formatear la descripción: reemplaza espacios por guiones bajos y pasa a mayúsculas
            clean_desc = new_description.strip().replace(" ", "_").upper()

            commands = [
                f"interface gpon {frame}/{slot}",
                f'ont modify {port} {ont_id} desc "{clean_desc}"',
                "quit",
                "save"
            ]

            logger.info(f"[CHANGE_DESC] Enviando comandos a OLT para {frame}/{slot}/{port} ONT {ont_id}: {commands}")

            output = self._execute_telnet_session(commands)
            logger.info(f"[CHANGE_DESC] Salida OLT cambio descripción:\n{output}")

            if "Error" in output or "Failure" in output or "Unknown command" in output:
                return False, output.strip()

            return True, "Descripción actualizada correctamente en la OLT"

        except Exception as e:
            logger.error(f"Error Telnet en change_ont_description: {e}")
            return False, str(e)