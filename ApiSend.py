# -*- coding: utf-8 -*-

# 1.0 [DAVID H.] - 10-10-25
# 2.0 [Gemini] - 22-10-25 - Remocao da logica Qualcomm e adicao de reset USB por tempo.
# 2.1 [Gemini] - 22-10-25 - Correcao reset USB para Pi 5 (usando -l 1 e -l 3)
# 2.2 [Gemini] - 22-10-25 - Adicao de logs de inicializacao

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
LIMITE_TEMPO_SEM_INTERNET = 30 # 1 hora (em segundos)
# LIMITE_TEMPO_SEM_INTERNET = 30 # Para testes rapidos

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

def resetar_usb_ports():
    """
    Reseta todas as portas USB usando uhubctl, especificando os hubs do Pi 5.
    Requer 'sudo apt install uhubctl' e permissao NOPASSWD no sudoers.
    """
    log("Tentando resetar todas as portas USB (requer 'sudo' e 'uhubctl')...")
    
    # Locais padrao dos hubs USB do Pi 5 (ex: 1 para USB 3.0, 3 para USB 2.0)
    hubs_para_resetar = ["1", "3"] 
    
    try:
        # Primeiro, desliga (off = -a 0) todos os hubs
        log("Desligando hubs USB...")
        for hub_location in hubs_para_resetar:
            log(f"Desligando hub -l {hub_location}...")
            resultado = subprocess.run(
                ["sudo", "uhubctl", "-l", hub_location, "-a", "0"], 
                capture_output=True, text=True, timeout=10, check=True
            )
            if resultado.stderr:
                log(f"uhubctl stderr (hub {hub_location} off): {resultado.stderr}")
            
        # Espera um segundo para garantir o desligamento
        time.sleep(1)
        
        # Agora, liga (on = -a 1) todos os hubs
        log("Ligando hubs USB...")
        for hub_location in hubs_para_resetar:
            log(f"Ligando hub -l {hub_location}...")
            resultado = subprocess.run(
                ["sudo", "uhubctl", "-l", hub_location, "-a", "1"], 
                capture_output=True, text=True, timeout=10, check=True
            )
            if resultado.stderr:
                log(f"uhubctl stderr (hub {hub_location} on): {resultado.stderr}")
                
        log("Reset dos hubs USB concluido.")

    except FileNotFoundError:
        log("Erro: 'uhubctl' nao encontrado. Instale com 'sudo apt install uhubctl'")
    except subprocess.CalledProcessError as e:
        # Se o comando falhar (stderr nao vazio e codigo de saida != 0)
        log(f"Erro ao executar uhubctl (CalledProcessError): {e.stderr}")
    except subprocess.TimeoutExpired:
        log("Erro: Comando 'uhubctl' demorou demais (timeout).")
    except Exception as e:
        log(f"Erro inesperado ao resetar USB: {e}")

def internet_disponivel(timeout=5):
    """Verifica se a internet esta funcionando"""
    try:
        requests.head("http://www.google.com", timeout=timeout)
        return True
    except:
        # Nao logamos aqui para nao poluir o log a cada 10s
        # O loop principal vai logar
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
    
    # Logica do modem removida
    log(f"Enviando {video} ... (id={RASPBERRY_ID}, type={tipo}, datetime={datahora})")
    
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
        # Nao logamos aqui para nao poluir o log
        return
    videos = [os.path.join(VIDEO_DIR, v) for v in os.listdir(VIDEO_DIR)
              if os.path.isfile(os.path.join(VIDEO_DIR, v))]
    if not videos:
        # Nao logamos aqui para nao poluir o log
        return
        
    log(f"Encontrados {len(videos)} video(s) para processar.")
    with ThreadPoolExecutor(max_workers=MAX_THREADS) as executor:
        executor.map(enviar_video, videos)

# =========================
# Loop principal
# =========================
if __name__ == "__main__":
    # --- LOGS DE INICIALIZACAO ---
    log("==================================================")
    log(f"Iniciando servico de upload. RASPBERRY_ID: {RASPBERRY_ID}")
    log(f"Monitorando diretorio: {VIDEO_DIR}")
    log(f"URL da API: {API_URL}")
    log(f"Intervalo de verificacao: {INTERVALO}s")
    log(f"Limite sem internet para reset USB: {LIMITE_TEMPO_SEM_INTERNET}s")
    log("==================================================")
    
    tempo_sem_internet_inicio = None
    
    while True:
        try:
            if internet_disponivel():
                # Internet esta OK
                if tempo_sem_internet_inicio is not None:
                    log("Internet restabelecida.")
                    tempo_sem_internet_inicio = None # Reseta o contador
                
                enviar_videos()
                
            else:
                # Internet esta FORA
                agora = time.time()
                
                if tempo_sem_internet_inicio is None:
                    # Marcar o inicio da queda
                    log("Internet indisponivel. Marcando inicio da queda de internet.")
                    tempo_sem_internet_inicio = agora
                else:
                    # Internet ja estava fora, verificar tempo
                    tempo_decorrido = agora - tempo_sem_internet_inicio
                    
                    # Logar apenas a cada 60s para nao poluir o log
                    if int(tempo_decorrido) % 60 == 0:
                        log(f"Internet indisponivel. Tempo sem conexao: {int(tempo_decorrido)}s / {LIMITE_TEMPO_SEM_INTERNET}s")
                    
                    if tempo_decorrido > LIMITE_TEMPO_SEM_INTERNET:
                        log(f"Limite de {LIMITE_TEMPO_SEM_INTERNET}s sem internet atingido. Resetando USB...")
                        resetar_usb_ports() # Chama a funcao de reset
                        
                        # Apos resetar, dar um tempo extra (ex: 60s) antes de checar de novo
                        # e resetar o contador para nao ficar resetando a cada 'INTERVALO' segundos
                        log("Aguardando 60s apos o reset do USB...")
                        time.sleep(60) 
                        tempo_sem_internet_inicio = None # Reseta o contador para um novo ciclo de 1h
                        continue # Pula o sleep de 'INTERVALO' e comeca o loop de novo

        except Exception as e:
            log(f"Erro critico no loop principal: {e}")
            log("Aguardando 30 segundos antes de tentar novamente...")
            time.sleep(30) # Evita spam de logs em caso de falha rapida

        time.sleep(INTERVALO)