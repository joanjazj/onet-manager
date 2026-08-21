import os
from fastapi import FastAPI, HTTPException, Query, UploadFile, File
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from config import settings
from olt_service import HuaweiOLT
from typing import Optional
from zabbix_service import ZabbixService
import logging
import io
import pandas as pd
from mikrotik_service import sanitizar_texto, aplicar_corte_mikrotik, probar_conexion_mikrotik


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("MainAPI")

app = FastAPI(
    title="ISP Provisioning Engine",
    description="API REST y Panel Web para aprovisionamiento de ONTs en OLT Huawei MA5800",
    version="1.0.0"
)

# -------------------------------------------------------------------
# ARCHIVOS ESTÁTICOS (FRONTEND)
# -------------------------------------------------------------------
# Asegurarse de que exista el directorio estático
static_dir = os.path.join(os.path.dirname(__file__), "static")
if not os.path.exists(static_dir):
    os.makedirs(static_dir)

# Montar la carpeta /static en la ruta /app
app.mount("/app", StaticFiles(directory=static_dir, html=True), name="static")


# -------------------------------------------------------------------
# MODELOS DE DATOS (PYDANTIC)
# -------------------------------------------------------------------
class FullProvisionRequest(BaseModel):
    frame: int = 0
    slot: int
    port: int
    ont_id: Optional[int] = None
    sn: str
    contract: str
    client_name: str
    ip: str
    plan: str  # Ej: "100M", "200M", "300M"
    vlan: int = settings.DEFAULT_VLAN


# -------------------------------------------------------------------
# ENDPOINTS DE LA API
# -------------------------------------------------------------------
@app.get("/")
def health_check():
    return {"status": "ok", "service": "Provisioning Engine", "frontend": "/app/"}

@app.get("/api/v1/unprovisioned-onts")
def get_unprovisioned():
    """Retorna lista de ONTs detectadas por autofind."""
    olt = HuaweiOLT(settings.OLT_HOST, settings.OLT_USER, settings.OLT_PASS, settings.OLT_PORT)
    return {"unprovisioned": olt.get_unconfigured_onts()}

@app.post("/api/v1/provision-ont-full")
def provision_full(data: FullProvisionRequest):
    """Ejecuta el flujo completo de aprovisionamiento idéntico al Excel."""
    try:
        olt = HuaweiOLT(settings.OLT_HOST, settings.OLT_USER, settings.OLT_PASS, settings.OLT_PORT)
        log = olt.provision_ont_excel_flow(
            frame=data.frame,
            slot=data.slot,
            port=data.port,
            ont_id=data.ont_id,
            sn=data.sn,
            contract=data.contract,
            client_name=data.client_name,
            ip=data.ip,
            plan=data.plan,
            vlan=data.vlan
        )
        return {"status": "success", "log": log}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# Endpoint para obtener todas las ONTs registradas desde Zabbix
@app.get("/api/v1/registered-onts")
def get_registered_onts():
    zbx = ZabbixService(settings.ZABBIX_URL, settings.ZABBIX_TOKEN)
    data = zbx.get_registered_onts()
    return {"status": "success", "data": data}
    
#Fase 2
# Modelos para peticiones de gestión
class ChangePlanRequest(BaseModel):
    frame: int
    slot: int
    port: int
    ont_id: int
    new_plan: str
    vlan: Optional[int] = 100

class DeleteOntRequest(BaseModel):
    frame: int
    slot: int
    port: int
    ont_id: int
    vlan: Optional[int] = 100

# Endpoint para cambiar plan de velocidad (traffic-table)
@app.post("/api/v1/onts/change-plan")
def change_plan(req: ChangePlanRequest):
    try:
        olt = HuaweiOLT(settings.OLT_HOST, settings.OLT_USER, settings.OLT_PASS, settings.OLT_PORT)
        output = olt.change_ont_plan(
            frame=req.frame,
            slot=req.slot,
            port=req.port,
            ont_id=req.ont_id,
            new_plan=req.new_plan,
            vlan=req.vlan or 100
        )
        return {"status": "success", "output": output}
    except Exception as e:
        logger.error(f"Error al cambiar plan: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# Endpoint para consultar plan
@app.get("/api/v1/onts/current-plan")
def get_current_plan(
    frame: int = Query(...),
    slot: int = Query(...),
    port: int = Query(...),
    ont_id: int = Query(...)
):
    """
    Endpoint invocado por la interfaz HTML/JS para consultar
    el plan configurado en la OLT antes de abrir el prompt.
    """
    try:
        olt = HuaweiOLT(settings.OLT_HOST, settings.OLT_USER, settings.OLT_PASS, settings.OLT_PORT)
        plan = olt.get_current_plan(frame, slot, port, ont_id)
        return {
            "status": "success",
            "current_plan": plan
        }
    except Exception as e:
        logger.error(f"Error consultando plan actual: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# Endpoint para cancelar/eliminar ONT
@app.post("/api/v1/onts/delete")
def delete_ont(req: DeleteOntRequest):
    try:
        olt = HuaweiOLT(settings.OLT_HOST, settings.OLT_USER, settings.OLT_PASS, settings.OLT_PORT)
        output = olt.delete_ont(
            frame=req.frame,
            slot=req.slot,
            port=req.port,
            ont_id=req.ont_id,
            vlan=req.vlan or 100
        )
        return {"status": "success", "output": output}
    except Exception as e:
        logger.error(f"Error al eliminar ONT: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/corte-masivo")
async def procesar_corte_masivo(file: UploadFile = File(...)):
    filename = file.filename.lower()
    
    if not filename.endswith(('.csv', '.xlsx', '.xls')):
        raise HTTPException(
            status_code=400, 
            detail="Formato no soportado. Debe subir un archivo .csv o .xlsx"
        )

    try:
        contents = await file.read()
        
        if filename.endswith('.csv'):
            # Detectar automáticamente si el separador es coma (,), punto y coma (;) o tabulación (\t)
            df = pd.read_csv(io.BytesIO(contents), sep=None, engine='python', encoding='utf-8-sig')
        else:
            df = pd.read_excel(io.BytesIO(contents))
            
    except Exception as e:
        raise HTTPException(
            status_code=400, 
            detail=f"Error al leer el archivo: {str(e)}"
        )

    # Normalizar encabezados (quitar espacios y pasar a mayúsculas)
    df.columns = [str(col).strip().upper() for col in df.columns]

    # Mapeo de alias para identificar la columna del nombre/cliente
    columna_cliente = None
    posibles_nombres_cliente = ['CLIENTE', 'NOMBRE', 'NOMBRE CLIENTE', 'SUSCRIPTOR', 'RAZON SOCIAL']
    
    for alias in posibles_nombres_cliente:
        if alias in df.columns:
            columna_cliente = alias
            break

    # Validar presencia de columna IP y alguna variación de Nombre/Cliente
    if 'IP' not in df.columns or not columna_cliente:
        raise HTTPException(
            status_code=400, 
            detail=f"El archivo debe contener al menos una columna 'IP' y una columna de nombre/cliente (Detectadas: {list(df.columns)})"
        )

    datos_procesados = []
    for _, row in df.iterrows():
        ip = str(row['IP']).strip()
        nombre_raw = str(row[columna_cliente]) if pd.notna(row[columna_cliente]) else ""

        # Ignorar filas vacías o nulas
        if ip and ip.lower() != 'nan':
            nombre_limpio = sanitizar_texto(nombre_raw)
            datos_procesados.append({'ip': ip, 'nombre': nombre_limpio})

    if not datos_procesados:
        raise HTTPException(
            status_code=400, 
            detail="No se encontraron registros válidos de IP y Cliente en el archivo"
        )

    # Aplicar comandos en bloque en MikroTik
    res = aplicar_corte_mikrotik(datos_corte=datos_procesados)

    if res["status"] == "error":
        raise HTTPException(
            status_code=500, 
            detail=f"Error al aplicar en MikroTik: {res['message']}"
        )

    return {"status": "ok", "procesados": res["ejecutados"]}

@app.get("/api/test-mikrotik")
def test_mikrotik():
    res = probar_conexion_mikrotik()
    if res["status"] == "error":
        raise HTTPException(status_code=500, detail=f"Fallo de conexión: {res['message']}")
    return res