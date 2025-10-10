# -*- coding: utf-8 -*-

#1.0 [DAVID H.] - 10-10-25

import face_recognition
import cv2
import numpy as np
import os
import time
import pickle
from threading import Thread
import logging
from datetime import datetime

# (A classe VideoStream continua a mesma)
class VideoStream:
    def __init__(self, src=0):
        self.stream = cv2.VideoCapture(src, cv2.CAP_FFMPEG)
        (self.grabbed, self.frame) = self.stream.read()
        self.stopped = False
    def start(self):
        Thread(target=self.update, args=()).start()
        return self
    def update(self):
        while True:
            if self.stopped: self.stream.release(); return
            (self.grabbed, self.frame) = self.stream.read()
    def read(self): return self.frame
    def stop(self): self.stopped = True

# --- CONFIGURACOES ---
#RTSP_URL = "rtsp://admin:Arvore32!@192.168.18.10:554/cam/realmonitor?channel=1&subtype=1"
RTSP_URL = "rtsp://admin:Arvore32!@192.168.1.45:554/cam/realmonitor?channel=1&subtype=1"
ENCODINGS_FILE = 'pesos/encodings.pickle'
RESIZE_FACTOR = 1
TOLERANCE = 0.55
PROCESS_EVERY_N_FRAMES = 10
CHECK_FOR_UPDATES_INTERVAL = 15.0
MAX_ANALYSIS_FAILURES = 3

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
    format="%(asctime)s [%(levelname)s] %(message)s",
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

# --- PASSO 1: CARREGAMENTO INICIAL ---
known_face_encodings, known_face_names = load_encodings(ENCODINGS_FILE)
last_modified_time = os.path.getmtime(ENCODINGS_FILE) if os.path.exists(ENCODINGS_FILE) else 0
last_check_time = time.time()

# --- PASSO 2: INICIALIZAR CAPTURA DE VIDEO ---
logging.info(f"Iniciando stream da camera...")
vs = VideoStream(src=RTSP_URL).start()
time.sleep(2.0)
logging.info("Camera conectada. Pressione CTRL+C para sair.")

# --- VARIAVEIS DE CONTROLE ---
frame_counter = 0
analysis_failures = 0
last_log_time = {}
last_save_time = {}
seen_unknown_faces = {}
unknown_counter = 0

# --- PASSO 3: LOOP DE PROCESSAMENTO ---
try:
    while True:
        current_time = time.time()
        # ... (bloco de checagem de atualizacao do pickle continua o mesmo) ...

        frame = vs.read()
        if frame is None:
            logging.warning("Frame nulo recebido da camera.")
            time.sleep(2.0)
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
                    best_match_index = np.argmin(face_recognition.face_distance(known_face_encodings, encoding))
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
                analysis_failures = 0
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
            else:
                analysis_failures += 1

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
    if 'vs' in locals() and vs is not None:
        vs.stop()
    print("Script finalizado.")