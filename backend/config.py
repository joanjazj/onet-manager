import os
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    # Parámetros de la OLT Huawei MA5800
    OLT_HOST: str = "172.31.31.2"       # IP de gestión de tu OLT
    OLT_PORT: int = 23
    OLT_USER: str = "root"              # Usuario SSH
    OLT_PASS: str = "admin123"    # Contraseña SSH

    # Perfiles por defecto definidos para tu red
    DEFAULT_LINEPROFILE: str = "1"
    DEFAULT_SRVPROFILE: str = "1"
    DEFAULT_VLAN: int = 100
    
    #Consulta ONT registradas
    ZABBIX_URL: str = os.getenv("ZABBIX_URL", "http://172.25.57.2")
    ZABBIX_TOKEN: str = os.getenv("ZABBIX_TOKEN", "cdce27eb4eb6d74571c4215fca416a5d9610b1e40d02f7443b164b1916bf0cdd")

    class Config:
        env_file = ".env"

settings = Settings()
