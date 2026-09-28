import re
import unicodedata
from netmiko import ConnectHandler
from config import settings

def sanitizar_texto(texto: str) -> str:
    """
    Elimina tildes, acentos, caracteres especiales y convierte a mayúsculas.
    Ejemplo: 'José Carrión - Ñ' -> 'JOSE CARRION N'
    """
    if not texto:
        return ""
    # Descomponer caracteres con acentos
    nfkd = unicodedata.normalize('NFKD', str(texto))
    texto_sin_acentos = "".join([c for c in nfkd if not unicodedata.combining(c)])
    # Dejar solo letras, números y espacios, luego pasar a mayúsculas
    texto_limpio = re.sub(r'[^A-Z0-9\s]', '', texto_sin_acentos.upper())
    return " ".join(texto_limpio.split())

def aplicar_corte_mikrotik(datos_corte: list):
    """
    Ejecuta en el MikroTik:
    /ip firewall address-list add address=10.10.1.X list=MOROSOS comment="NOMBRE LIMPIO"
    """
    device = {
        'device_type': 'mikrotik_routeros',
        'host': settings.MIKROTIK_HOST,
        'username': settings.MIKROTIK_USER,
        'password': settings.MIKROTIK_PASS,
        'port': settings.MIKROTIK_PORT,
    }

    # Construir lista de comandos CLI
    comandos = []
    for item in datos_corte:
        ip = item['ip']
        comentario = item['nombre']
        cmd = f'/ip firewall address-list add address={ip} list={settings.MIKROTIK_ADDRESS_LIST} comment="{comentario}"'
        comandos.append(cmd)

    try:
        net_connect = ConnectHandler(**device)
        resultados = []
        for cmd in comandos:
            output = net_connect.send_command(cmd)
            resultados.append({"cmd": cmd, "output": output})
        net_connect.disconnect()
        return {"status": "success", "ejecutados": len(comandos), "detalles": resultados}
    except Exception as e:
        return {"status": "error", "message": str(e)}

def probar_conexion_mikrotik():
    """
    Ejecuta un comando de lectura liviano para verificar credenciales y reachability.
    """
    device = {
        'device_type': 'mikrotik_routeros',
        'host': settings.MIKROTIK_HOST,
        'username': settings.MIKROTIK_USER,
        'password': settings.MIKROTIK_PASS,
        'port': settings.MIKROTIK_PORT,
        'timeout': 5,
    }

    try:
        net_connect = ConnectHandler(**device)
        output = net_connect.send_command('/system resource print')
        net_connect.disconnect()
        return {"status": "ok", "message": "Conexión exitosa", "resource": output}
    except Exception as e:
        return {"status": "error", "message": str(e)}

def reactivar_cliente_mikrotik(ip: str):
    device = {
        'device_type': 'mikrotik_routeros',
        'host': settings.MIKROTIK_HOST,
        'username': settings.MIKROTIK_USER,
        'password': settings.MIKROTIK_PASS,
        'port': getattr(settings, 'MIKROTIK_PORT', 22),
    }

    address_list = getattr(settings, 'MIKROTIK_ADDRESS_LIST', 'SUSPENDIDOS')

    # 1. Comando para verificar si la IP está suspendida
    cmd_print = f'/ip firewall address-list print count-only where list="{address_list}" and address="{ip}"'
    # 2. Comando para remover
    cmd_remove = f'/ip firewall address-list remove [find where list="{address_list}" and address="{ip}"]'

    try:
        net_connect = ConnectHandler(**device)
        
        # Ejecutar conteo
        count_output = net_connect.send_command(cmd_print).strip()
        
        # Si count_output es mayor a 0, la IP sí está en la lista
        if count_output.isdigit() and int(count_output) > 0:
            output_remove = net_connect.send_command(cmd_remove)
            net_connect.disconnect()
            return {
                "status": "success",
                "was_suspended": True,
                "ip": ip,
                "message": f"IP {ip} reconectada exitosamente."
            }
        else:
            net_connect.disconnect()
            return {
                "status": "success",
                "was_suspended": False,
                "ip": ip,
                "message": f"La IP {ip} no se encontraba suspendida."
            }

    except Exception as e:
        return {"status": "error", "message": str(e)}


def obtener_clientes_suspendidos_mikrotik():
    device = {
        'device_type': 'mikrotik_routeros',
        'host': settings.MIKROTIK_HOST,
        'username': settings.MIKROTIK_USER,
        'password': settings.MIKROTIK_PASS,
        'port': getattr(settings, 'MIKROTIK_PORT', 22),
    }

    address_list = getattr(settings, 'MIKROTIK_ADDRESS_LIST', 'SUSPENDIDOS')
    
    cmd_list = f'/ip firewall address-list print terse without-paging where list="{address_list}"'

    try:
        net_connect = ConnectHandler(**device)
        output = net_connect.send_command(cmd_list)
        net_connect.disconnect()

        clientes = []
        for line in output.splitlines():
            line = line.strip()
            if not line:
                continue
            
            # 1. Extraer IP
            ip_match = re.search(r'address=([^\s]+)', line)
            
            # 2. Extraer comentario (captura entre comillas O hasta el siguiente atributo clave=valor)
            comment_match = re.search(r'comment="([^"]+)"|comment=(.*?)(?=\s+[a-zA-Z0-9-]+=|$)', line)
            
            # 3. Extraer creation-time
            creation_match = re.search(r'creation-time="([^"]+)"|creation-time=([^\s]+)', line)

            if ip_match:
                ip = ip_match.group(1)
                
                comment = ""
                if comment_match:
                    # Toma el valor entre comillas (grupo 1) o el valor sin comillas extenso (grupo 2)
                    comment = comment_match.group(1) or comment_match.group(2) or ""
                    comment = comment.strip()

                creation_time = ""
                if creation_match:
                    creation_time = creation_match.group(1) or creation_match.group(2) or ""

                clientes.append({
                    "ip": ip,
                    "comment": comment,
                    "created_at": creation_time
                })

        return {
            "status": "success",
            "total": len(clientes),
            "data": clientes
        }

    except Exception as e:
        return {"status": "error", "message": str(e), "data": []}