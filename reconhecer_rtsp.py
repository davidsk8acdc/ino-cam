# -*- coding: utf-8 -*-

# 2.0 [DAVID H. / Gemini] - 11-10-25
# - Adicionada thread de captura dedicada com logica de reconexao (retry).
# - Implementado padrao produtor/consumidor com queue.Queue para desacoplar captura e analise.

import face_recognition
import cv2
import numpy as np
import os
import time
import pickle
import threading
import queue
import logging
from datetime import datetime

# --- CONFIGURACOES ---
#RTSP_URL = "rtsp://admin:Arvore32!@192.168.18.10:554/cam/realmonitor?channel=1&subtype=1" #david
RTSP_URL = "rtsp://admin:Arvore32!@192.168.1.45:554/cam/realmonitor?channel=1&subtype=1" #inoprime

ENCODINGS_FILE = 'pesos/encodings.pickle'
RESIZE_FACTOR = 1
TOLERANCE = 0.50
PROCESS_EVERY_N_FRAMES = 10
CHECK_FOR_UPDATES_INTERVAL = 15
RECONNECT_DELAY_SECONDS = 5

# --- NOVAS CONFIGURACOES DE LOG E CAPTURA ---
LOGS_DIR = 'logs'
CAPTURAS_DIR = 'capturas'
LOG_COOLDOWN_SECONDS = 60
SAVE_KNOWN_COOLDOWN_SECONDS = 300   # 5 minutos para pessoas conhecidas
SAVE_UNKNOWN_COOLDOWN_SECONDS = 900 # 15 minutos para um mesmo desconhecido
UNKNOWN_MEMORY_SECONDS = 1800 # 30 minutos

# --- PASSO 0: CONFIGURAR LOGS E PASTAS ---
os.makedirs(LOGS_DIR, exist_ok=True)
os.makedirs(CAPTURAS_DIR, exist_ok=True)

log_filename = os.path.join(LOGS_DIR, f"reconhecimento_{datetime.now().strftime('%Y-%m-%d')}.log")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(threadName)s] [%(levelname)s] %(message)s",
    handlers=[logging.FileHandler(log_filename), logging.StreamHandler()]
)

# --- FUNCAO AUXILIAR ---
def load_encodings(file_path):
    logging.info("Carregando ou recarregando encodings...")
    try:
        with open(file_path, 'rb') as f: data_por_pessoa = pickle.load(f)
        all_encodings, all_names = [], []
        for person_name, person_data in data_por_pessoa.items():
            encodings = person_data["encodings"]
            all_encodings.extend(encodings)
            all_names.extend([person_name] * len(encodings))
        logging.info(f"Encodings carregados com {len(all_encodings)} rostos de {len(data_por_pessoa)} pessoas.")
        return all_encodings, all_names
    except Exception as e:
        logging.error(f"Nao foi possivel carregar o arquivo de encodings: {e}")
        return [], []

# --- NOVA THREAD DE CAPTURA COM RETRY ---
def video_capture_thread(rtsp_url, frame_queue, stop_event):
    """
    Thread dedicada a capturar frames da stream RTSP e coloca-los em uma fila.
    Tenta reconectar automaticamente em caso de falha.
    """
    logging.info("Thread de captura iniciada.")
    while not stop_event.is_set():
        cap = None
        try:
            logging.info(f"Tentando conectar a stream RTSP: {rtsp_url}")
            cap = cv2.VideoCapture(rtsp_url, cv2.CAP_FFMPEG)
            
            if not cap.isOpened():
                logging.error(f"Nao foi possivel abrir a stream. Tentando novamente em {RECONNECT_DELAY_SECONDS}s...")
                time.sleep(RECONNECT_DELAY_SECONDS)
                continue

            logging.info("Stream RTSP conectada com sucesso!")
            while not stop_event.is_set():
                ret, frame = cap.read()
                
                if not ret:
                    logging.warning("Stream de video perdida. Tentando reconectar...")
                    break # Sai do loop interno para tentar reconectar no loop externo

                # Garante que a fila sempre tenha o frame mais recente
                if frame_queue.full():
                    try:
                        frame_queue.get_nowait() # Descarta frame antigo
                    except queue.Empty:
                        pass
                frame_queue.put(frame)
        
        except Exception as e:
            logging.error(f"Erro inesperado na thread de captura: {e}")
            time.sleep(RECONNECT_DELAY_SECONDS)
        
        finally:
            if cap is not None:
                cap.release()
                logging.info("Recurso de captura liberado.")
                
    logging.info("Thread de captura finalizada.")


# --- PASSO 1: CARREGAMENTO INICIAL ---
known_face_encodings, known_face_names = load_encodings(ENCODINGS_FILE)
last_modified_time = os.path.getmtime(ENCODINGS_FILE) if os.path.exists(ENCODINGS_FILE) else 0
last_check_time = time.time()

# --- PASSO 2: INICIALIZAR CAPTURA DE VIDEO EM THREAD SEPARADA ---
frame_queue = queue.Queue(maxsize=1)
stop_event = threading.Event()

capture_thread = threading.Thread(
    target=video_capture_thread, 
    args=(RTSP_URL, frame_queue, stop_event),
    name="CaptureThread"
)
capture_thread.daemon = True # Permite que o programa principal saia mesmo que a thread esteja rodando
capture_thread.start()

logging.info("Aguardando o primeiro frame da camera...")
time.sleep(5.0) # Espera um pouco para a conexao ser estabelecida
logging.info("Sistema iniciado. Pressione CTRL+C para sair.")

# --- VARIAVEIS DE CONTROLE ---
frame_counter = 0
last_log_time = {}
last_save_time = {}
seen_unknown_faces = {}
unknown_counter = 0

# --- PASSO 3: LOOP DE PROCESSAMENTO ---
try:
    while True:
        current_time = time.time()
        
        # --- Bloco de checagem de atualizacao do pickle ---
        if current_time - last_check_time > CHECK_FOR_UPDATES_INTERVAL:
            last_check_time = current_time
            if os.path.exists(ENCODINGS_FILE):
                current_modified_time = os.path.getmtime(ENCODINGS_FILE)
                if current_modified_time > last_modified_time:
                    logging.info("Arquivo de encodings modificado. Recarregando...")
                    known_face_encodings, known_face_names = load_encodings(ENCODINGS_FILE)
                    last_modified_time = current_modified_time

        try:
            # Tenta obter o frame mais recente da fila, com timeout
            frame = frame_queue.get(timeout=2.0)
        except queue.Empty:
            logging.warning("Nenhum frame recebido da camera. Verificando conexao...")
            continue

        if frame_counter % PROCESS_EVERY_N_FRAMES == 0:
            small_frame = cv2.resize(frame, (0, 0), fx=RESIZE_FACTOR, fy=RESIZE_FACTOR)
            rgb_small_frame = cv2.cvtColor(small_frame, cv2.COLOR_BGR2RGB)
            
            face_locations = face_recognition.face_locations(rgb_small_frame)
            face_encodings = face_recognition.face_encodings(rgb_small_frame, face_locations)

            # --- PASSO 4: LOGICA DE IDENTIFICACAO, LOG E CAPTURA ---
            processed_faces_names = []
            for encoding in face_encodings:
                matches = face_recognition.compare_faces(known_face_encodings, encoding, tolerance=TOLERANCE)
                name = "Desconhecido"

                if True in matches:
                    face_distances = face_recognition.face_distance(known_face_encodings, encoding)
                    best_match_index = np.argmin(face_distances)
                    if matches[best_match_index]:
                        name = known_face_names[best_match_index]
                else:
                    is_new_unknown = True
                    for unknown_id, data in seen_unknown_faces.items():
                        match = face_recognition.compare_faces([data['encoding']], encoding, tolerance=TOLERANCE)[0]
                        if match:
                            name = unknown_id
                            seen_unknown_faces[unknown_id]['last_seen'] = current_time
                            is_new_unknown = False
                            break
                    
                    if is_new_unknown:
                        unknown_counter += 1
                        name = f"Desconhecido_{unknown_counter}"
                        seen_unknown_faces[name] = {
                            'encoding': encoding,
                            'last_seen': current_time
                        }
                        logging.info(f"NOVO rosto desconhecido detectado. Atribuido ID: {name}")

                processed_faces_names.append(name)

            if len(processed_faces_names) > 0:
                for name in processed_faces_names:
                    # --- Logica de Log ---
                    if name not in last_log_time or (current_time - last_log_time.get(name, 0)) > LOG_COOLDOWN_SECONDS:
                        log_message = f"Pessoa reconhecida: {name}"
                        if name.startswith("Desconhecido"):
                            log_message = f"Pessoa desconhecida vista: {name}"
                        logging.info(log_message)
                        last_log_time[name] = current_time
                    
                    # --- Logica de Salvar Imagem ---
                    cooldown = SAVE_UNKNOWN_COOLDOWN_SECONDS if name.startswith("Desconhecido") else SAVE_KNOWN_COOLDOWN_SECONDS
                    if name not in last_save_time or (current_time - last_save_time.get(name, 0)) > cooldown:
                        timestamp = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
                        safe_name = name.replace(' ', '_')
                        filename = os.path.join(CAPTURAS_DIR, f"{safe_name}_{timestamp}.jpg")
                        
                        # Salva o frame original, sem desenhos
                        cv2.imwrite(filename, frame) 
                        
                        logging.info(f"IMAGEM SALVA para {name}: {filename}")
                        last_save_time[name] = current_time
        
        # Limpa a memoria de desconhecidos que nao aparecem ha muito tempo
        if frame_counter % (PROCESS_EVERY_N_FRAMES * 10) == 0:
            expired_unknowns = [uid for uid, data in seen_unknown_faces.items() if current_time - data['last_seen'] > UNKNOWN_MEMORY_SECONDS]
            for uid in expired_unknowns:
                del seen_unknown_faces[uid]
                logging.info(f"ID de desconhecido {uid} removido da memoria por inatividade.")
        
        frame_counter += 1

except KeyboardInterrupt:
    logging.info("Solicitacao de encerramento recebida (Ctrl+C).")
finally:
    logging.info("Encerrando o programa...")
    stop_event.set() # Sinaliza para a thread de captura parar
    if 'capture_thread' in locals() and capture_thread.is_alive():
        capture_thread.join() # Espera a thread terminar
    print("Script finalizado.")