# -*- coding: utf-8 -*-

#1.0 [DAVID H.] - 10-10-25

import os
import requests
import time
import subprocess
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor

API_URL = "https://trackerprime.inoprime.com.br/api/infractions"
VIDEO_DIR = "videos"
INTERVALO = 10  # segundos entre tentativas
LOG_FILE = "logs/cliente.log"
MAX_THREADS = 3

def log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    linha = f"[{ts}] {msg}"
    print(linha)
    os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(linha + "\n")

def get_raspberry_id():
    serial = "unknown"
    try:
        with open('/proc/cpuinfo','r') as f:
            for line in f:
                if line.startswith('Serial'):
                    serial = line.split(':')[1].strip()
                    break
    except Exception:
        pass
    return serial

RASPBERRY_ID = get_raspberry_id()

def detectar_modem_qualcomm():
    """Procura um modem Qualcomm via lsusb e retorna o ID vendor:product"""
    try:
        resultado = subprocess.run(["lsusb"], capture_output=True, text=True)
        for linha in resultado.stdout.splitlines():
            if "Qualcomm" in linha:
                # Exemplo: Bus 001 Device 013: ID 05c6:9024 Qualcomm, Inc. Android
                parts = linha.split("ID")
                if len(parts) > 1:
                    modem_id = parts[1].split()[0]
                    return modem_id
        return None
    except Exception as e:
        log(f"Erro ao executar lsusb: {e}")
        return None

def internet_disponivel(timeout=5):
    """Verifica se a internet esta funcionando"""
    try:
        requests.head("http://www.google.com", timeout=timeout)
        return True
    except:
        log("Internet indisponivel.")
        return False

def arquivo_em_uso(caminho, espera=2):
    """Verifica se o arquivo ainda esta sendo gravado pelo tamanho"""
    try:
        tamanho1 = os.path.getsize(caminho)
        time.sleep(espera)
        tamanho2 = os.path.getsize(caminho)
        return tamanho1 != tamanho2
    except FileNotFoundError:
        return True
    except Exception as e:
        log(f"Erro ao verificar arquivo {caminho}: {e}")
        return True

def parse_video_info(video_name):
    """Extrai type e datetime do nome do video"""
    # Exemplo esperado: standing_20250912_165514.mp4
    base, _ = os.path.splitext(video_name)
    partes = base.split("_")
    if len(partes) >= 3:
        tipo = partes[0]
        data_str = partes[1] + partes[2]  # YYYYMMDDHHMMSS
        try:
            dt = datetime.strptime(data_str, "%Y%m%d%H%M%S")
            datahora = dt.isoformat()
        except:
            datahora = None
    else:
        tipo = "desconhecido"
        datahora = None
    return tipo, datahora

def enviar_video(caminho):
    video = os.path.basename(caminho)
    if arquivo_em_uso(caminho):
        log(f"Ignorando {video}, arquivo ainda em uso.")
        return

    tipo, datahora = parse_video_info(video)
    modem_id = detectar_modem_qualcomm()
    if not modem_id:
        log("Nenhum modem Qualcomm detectado. Video sera enviado apenas se internet estiver disponivel.")

    log(f"Enviando {video} ... (id={RASPBERRY_ID}, type={tipo}, datetime={datahora}, modem={modem_id})")
    try:
        with open(caminho, "rb") as f:
            files = {"file": (video, f, "video/mp4")}
            data = {
                "device_id": RASPBERRY_ID,
                "type": tipo,
                "datetime": datahora,
            }
            r = requests.post(API_URL, files=files, data=data, timeout=300, stream=True)

        if r.ok:
            log(f"{video} enviado com sucesso. Apagando...")
            os.remove(caminho)
        else:
            log(f"Falha ao enviar {video}: {r.status_code} {r.text}")
    except Exception as e:
        log(f"Erro ao enviar {video}: {e}")

def enviar_videos():
    if not os.path.exists(VIDEO_DIR):
        log("Diretorio de videos nao encontrado.")
        return
    videos = [os.path.join(VIDEO_DIR, v) for v in os.listdir(VIDEO_DIR)
              if os.path.isfile(os.path.join(VIDEO_DIR, v))]
    if not videos:
        return
    with ThreadPoolExecutor(max_workers=MAX_THREADS) as executor:
        executor.map(enviar_video, videos)

# =========================
# Loop principal
# =========================
if __name__ == "__main__":
    while True:
        if internet_disponivel():
            enviar_videos()
        else:
            log("Internet indisponivel. Aguardando...")
        time.sleep(INTERVALO)
