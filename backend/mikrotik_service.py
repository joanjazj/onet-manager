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