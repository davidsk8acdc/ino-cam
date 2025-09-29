# -*- coding: utf-8 -*-
import time
import logging
import psutil
import subprocess
from logging.handlers import RotatingFileHandler

LOG_FILE = "/home/david/ino-cam/logs/monitor.log"
SERVICES = ["supervisor", "nginx", "ssh"]  # coloque aqui os servicos que quer monitorar

# Configura logger com rotacao
logger = logging.getLogger("Monitor")
logger.setLevel(logging.INFO)

handler = RotatingFileHandler(LOG_FILE, maxBytes=1_000_000, backupCount=5)
formatter = logging.Formatter("[%(asctime)s] %(levelname)s - %(message)s")
handler.setFormatter(formatter)
logger.addHandler(handler)

def get_service_status(service):
    """Verifica status de um servico do systemd"""
    try:
        result = subprocess.run(
            ["systemctl", "is-active", service],
            capture_output=True,
            text=True,
            timeout=5
        )
        return result.stdout.strip()
    except Exception as e:
        return f"erro: {e}"

def log_system_info():
    """Loga informacoes do hardware e servicos"""
    # CPU
    cpu_percent = psutil.cpu_percent(interval=1)
    cpu_temp = None
    try:
        with open("/sys/class/thermal/thermal_zone0/temp") as f:
            cpu_temp = int(f.read()) / 1000
    except FileNotFoundError:
        cpu_temp = "N/A"

    # Memoria
    mem = psutil.virtual_memory()
    disk = psutil.disk_usage("/")

    logger.info(
        f"CPU {cpu_percent}% | Temp {cpu_temp}C | "
        f"Mem {mem.percent}% ({mem.used // (1024**2)}MB/{mem.total // (1024**2)}MB) | "
        f"Disco {disk.percent}% ({disk.used // (1024**3)}GB/{disk.total // (1024**3)}GB)"
    )

    # Servicos
    for service in SERVICES:
        status = get_service_status(service)
        logger.info(f"Servico {service}: {status}")

if __name__ == "__main__":
    logger.info("Monitor iniciado")
    while True:
        log_system_info()
        time.sleep(60)
