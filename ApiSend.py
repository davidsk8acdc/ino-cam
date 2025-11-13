# -*- coding: utf-8 -*-

# 1.0 [DAVID H.] - 10-10-25
# 2.0 [Gemini] - 22-10-25 - Remocao da logica Qualcomm e adicao de reset USB por tempo.
# 2.1 [Gemini] - 22-10-25 - Correcao reset USB para Pi 5 (usando -l 1 e -l 3)
# 2.2 [Gemini] - 22-10-25 - Adicao de logs de inicializacao
# 3.0 [Gemini] - 07-11-25 - Remocao da logica de reset USB e resumo de erro POST.
# 4.0 [Gemini] - 07-11-25 - Remocao da logica de disponibilidade de internet.
# 5.0 [Gemini] - 12-11-25 - Modificacao para decodificar dados do GPS (lat, lon, vel) do nome do arquivo.
# 6.0 [Gemini] - 12-11-25 - Adicao de captura de temperatura da CPU e melhoria nos logs de erro HTTP.

import os
import requests
import time
import subprocess
import struct
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

def get_raspberry_temp():
    try:
        with open('/sys/class/thermal/thermal_zone0/temp', 'r') as f:
            temp_str = f.read().strip()
        return round(int(temp_str) / 1000.0, 1)
    except FileNotFoundError:
        return None
    except Exception as e:
        log(f"Erro ao ler temperatura: {e}")
        return None

RASPBERRY_ID = get_raspberry_id()


def arquivo_em_uso(caminho, espera=2):
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
    base, _ = os.path.splitext(video_name)
    partes = base.split("_")
    
    if len(partes) != 6:
        log(f"Formato de nome de arquivo invalido: {video_name}")
        return None

    parsed_data = {
        "type": None,
        "datetime": None,
        "latitude": None,
        "longitude": None,
        "velocidade": None,
        "user_tag_1": None
    }

    try:
        parsed_data["type"] = partes[0]
        
        try:
            dt = datetime.strptime(partes[1], "%Y%m%d%H%M%S")
            parsed_data["datetime"] = dt.isoformat()
        except Exception:
            log(f"Erro ao decodificar data: {partes[1]}")
            parsed_data["datetime"] = None

        try:
            lat_bytes = bytes.fromhex(partes[2])
            lat_raw = struct.unpack('<i', lat_bytes)[0]
            parsed_data["latitude"] = lat_raw / 1000000.0
        except Exception:
            log(f"Erro ao decodificar latitude: {partes[2]}")
            parsed_data["latitude"] = None

        try:
            lon_bytes = bytes.fromhex(partes[3])
            lon_raw = struct.unpack('<i', lon_bytes)[0]
            parsed_data["longitude"] = lon_raw / 1000000.0
        except Exception:
            log(f"Erro ao decodificar longitude: {partes[3]}")
            parsed_data["longitude"] = None
        
        try:
            vel_bytes = bytes.fromhex(partes[4])
            spd_raw = struct.unpack('<H', vel_bytes)[0]
            parsed_data["velocidade"] = spd_raw / 10.0
        except Exception:
            log(f"Erro ao decodificar velocidade: {partes[4]}")
            parsed_data["velocidade"] = None
            
        try:
            tag_bytes = bytes.fromhex(partes[5])
            parsed_data["user_tag_1"] = struct.unpack('<i', tag_bytes)[0]
        except Exception:
            log(f"Erro ao decodificar user_tag_1: {partes[5]}")
            parsed_data["user_tag_1"] = None

    except Exception as e:
        log(f"Erro critico ao decodificar nome {video_name}: {e}")
        return None
        
    return parsed_data

def enviar_video(caminho):
    video = os.path.basename(caminho)
    if arquivo_em_uso(caminho):
        log(f"Ignorando {video}, arquivo ainda em uso.")
        return

    parsed_info = parse_video_info(video)
    
    if not parsed_info:
        log(f"Ignorando {video}, formato de nome invalido.")
        return
    
    log(f"Enviando {video} ... (id={RASPBERRY_ID}, type={parsed_info.get('type')})")
    
    temp_cpu = get_raspberry_temp()
    
    try:
        with open(caminho, "rb") as f:
            files = {"file": (video, f, "video/mp4")}
            
            data = {"device_id": RASPBERRY_ID}
            
            for key, value in parsed_info.items():
                if value is not None:
                    data[key] = value
            
            if temp_cpu is not None:
                data["device_temp"] = temp_cpu
            
            log(f"Payload: {data}")
            
            r = requests.post(API_URL, files=files, data=data, timeout=300, stream=True)

        if r.ok:
            log(f"{video} enviado com sucesso. Apagando...")
            os.remove(caminho)
        else:
            erro_msg = f"Falha ao enviar {video}: {r.status_code}"
            
            if r.status_code >= 500:
                erro_msg += " (Erro Interno no Servidor)"
            else:
                try:
                    erro_json = r.json()
                    erro_msg += f" (Detalhe: {erro_json.get('message', erro_json)})"
                except requests.exceptions.JSONDecodeError:
                    erro_resumido = (r.text[:100] + '...').replace(os.linesep, ' ')
                    erro_msg += f" (Resposta: {erro_resumido})"
            log(erro_msg)
            
    except Exception as e:
        log(f"Erro ao enviar {video}: {e}")

def enviar_videos():
    if not os.path.exists(VIDEO_DIR):
        return
    videos = [os.path.join(VIDEO_DIR, v) for v in os.listdir(VIDEO_DIR)
              if os.path.isfile(os.path.join(VIDEO_DIR, v))]
    if not videos:
        return
        
    log(f"Encontrados {len(videos)} video(s) para processar.")
    with ThreadPoolExecutor(max_workers=MAX_THREADS) as executor:
        executor.map(enviar_video, videos)

# =========================
# Loop principal
# =========================
if __name__ == "__main__":
    log("==================================================")
    log(f"Iniciando servico de upload. RASPBERRY_ID: {RASPBERRY_ID}")
    log(f"Monitorando diretorio: {VIDEO_DIR}")
    log(f"URL da API: {API_URL}")
    log(f"Intervalo de verificacao: {INTERVALO}s")
    log("==================================================")
    
    while True:
        try:
            enviar_videos()
            
        except Exception as e:
            log(f"Erro critico no loop principal: {e}")
            log("Aguardando 30 segundos antes de tentar novamente...")
            time.sleep(30)

        time.sleep(INTERVALO)