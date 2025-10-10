# -*- coding: utf-8 -*-

#1.0 [DAVID H.] - 10-10-25

import cv2
from ultralytics import YOLO
from collections import deque
import threading
import queue
import time
import os
from datetime import datetime
import subprocess

# --- CONFIGURACOES ---
#RTSP_URL = "rtsp://admin:Arvore32!@192.168.100.167:554/cam/realmonitor?channel=1&subtype=1"  # REDE 4G INO-CAM-001
RTSP_URL = "rtsp://admin:Arvore32!@192.168.1.45:554/cam/realmonitor?channel=1&subtype=1" # REDE INOPRIME
OUTPUT_VIDEO_DIR = "videos"
LOG_DIR = "logs"

# DEFINIMOS A CLASSE ALVO PELO NOME
TARGET_CLASS_NAME = "standing"

CONFIDENCE_THRESHOLD = 0.8
YOLO_CHECK_INTERVAL_SECONDS = 2.0
RECORD_COOLDOWN_SECONDS = 30.0
PRE_BUFFER_SECONDS = 5
POST_BUFFER_SECONDS = 5

FPS = 15
WIDTH, HEIGHT = 640, 480
# Aumentamos o bitrate, pois H.264 (H.265 e mais eficiente)
FFMPEG_BITRATE = "2500k"

os.makedirs(OUTPUT_VIDEO_DIR, exist_ok=True)
os.makedirs(LOG_DIR, exist_ok=True)

# Fila para comunicacao segura entre threads
frame_queue = queue.Queue(maxsize=128)
# Evento para sinalizar o encerramento de todas as threads
stop_event = threading.Event()

# --- SISTEMA DE LOG MELHORADO ---
def log(msg, level="INFO", thread_name="MAIN"):
    """
    Funcao de log aprimorada para incluir o nome da thread e salvar em arquivo.
    """
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_file = os.path.join(LOG_DIR, f"detec_{datetime.now().strftime('%Y-%m-%d')}.log")
    
    # Formato: [TIMESTAMP] [NOME_DA_THREAD] [NIVEL] Mensagem
    line = f"[{timestamp}] [{thread_name.upper()}] [{level}] {msg}"
    print(line)
    
    try:
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception as e:
        print(f"[{timestamp}] [LOG] [ERRO] Falha ao escrever no arquivo de log: {e}")

# --- FUNCAO DE DESENHO (FILTRA PELO NOME) ---
def draw_boxes(frame, results):
    if results is None or not hasattr(results, 'names'):
        return frame
    
    target_class_id = -1
    for cls_id, cls_name in results.names.items():
        if cls_name == TARGET_CLASS_NAME:
            target_class_id = cls_id
            break

    if target_class_id == -1:
        # Este log so ocorrera uma vez se a classe nao for encontrada
        return frame

    for box in results.boxes:
        cls_id = int(box.cls[0])
        if cls_id != target_class_id:
            continue
            
        x1, y1, x2, y2 = map(int, box.xyxy[0])
        conf = float(box.conf[0])
        color = (0, 0, 255) # Vermelho para a deteccao
        cv2.rectangle(frame, (x1, y1), (x2, y2), color, 1, cv2.LINE_AA)
        label = f"{TARGET_CLASS_NAME} {conf:.2f}"
        ((text_w, text_h), _) = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
        cv2.rectangle(frame, (x1, y1 - text_h - 4), (x1 + text_w, y1), color, -1)
        cv2.putText(frame, label, (x1, y1 - 2), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1, cv2.LINE_AA)
    return frame

# --- THREAD DE CAPTURA COM RECONEXAO ROBUSTA ---
def video_capture_thread(rtsp_url):
    log("Thread de captura iniciada.", thread_name="CAPTURE")
    while not stop_event.is_set():
        cap = None
        try:
            log(f"Tentando conectar a stream RTSP: {rtsp_url}", thread_name="CAPTURE")
            cap = cv2.VideoCapture(rtsp_url, cv2.CAP_FFMPEG)
            
            if not cap.isOpened():
                log("Nao foi possivel abrir a stream. Tentando novamente em 5s...", "ERRO", "CAPTURE")
                time.sleep(5)
                continue

            log("Stream RTSP conectado com sucesso!", "INFO", "CAPTURE")
            while not stop_event.is_set():
                ret, frame = cap.read()
                
                if not ret:
                    log("Stream de video perdida. Tentando reconectar...", "AVISO", "CAPTURE")
                    break # Sai do loop interno para tentar reconectar no loop externo

                if frame_queue.full():
                    try:
                        # Descarta frame antigo para dar lugar a um novo
                        frame_queue.get_nowait()
                    except queue.Empty:
                        pass
                frame_queue.put(frame)
        
        except Exception as e:
            log(f"Erro inesperado na thread de captura: {e}", "ERRO", "CAPTURE")
            log("Tentando reconectar em 10 segundos...", "INFO", "CAPTURE")
            time.sleep(10)
        
        finally:
            if cap is not None:
                cap.release()
                
    log("Thread de captura finalizada.", thread_name="CAPTURE")

# --- THREAD DE DETECCAO E GRAVACAO ---
def detection_thread():
    log("Carregando modelo YOLO...", thread_name="DETECT")
    try:
        model = YOLO("pesos/best.pt")
    except Exception as e:
        log(f"Erro critico ao carregar modelo YOLO: {e}. Encerrando thread.", "ERRO", "DETECT")
        return

    try:
        class_names = model.names
        target_class_id = next((cls_id for cls_id, name in class_names.items() if name == TARGET_CLASS_NAME), -1)
        
        if target_class_id == -1:
            log(f"Classe alvo '{TARGET_CLASS_NAME}' nao encontrada no modelo.", "ERRO", "DETECT")
        else:
            log(f"Classe '{TARGET_CLASS_NAME}' mapeada para o ID: {target_class_id}", "INFO", "DETECT")
            
    except Exception as e:
        log(f"Erro ao ler nomes das classes do modelo: {e}", "ERRO", "DETECT")
        target_class_id = -1

    log("Thread de deteccao iniciada.", thread_name="DETECT")
    pre_buffer = deque(maxlen=int(FPS * PRE_BUFFER_SECONDS))
    recording = False
    ffmpeg_process = None
    post_frames_remaining = 0
    last_yolo_check_time = 0
    last_record_trigger_time = 0
    last_results = None

    while not stop_event.is_set():
        try:
            frame = frame_queue.get(timeout=1.0) # Timeout para nao bloquear para sempre
        except queue.Empty:
            continue

        frame_high = cv2.resize(frame, (WIDTH, HEIGHT))
        now = time.time()
        standing_detected_in_check = False

        if now - last_yolo_check_time > YOLO_CHECK_INTERVAL_SECONDS and target_class_id != -1:
            try:
                results = model.predict(frame_high, conf=CONFIDENCE_THRESHOLD, classes=[target_class_id], verbose=False)[0]
                last_yolo_check_time = now
                
                if len(results.boxes) > 0:
                    last_results = results
                    standing_detected_in_check = True
                else:
                    last_results = None
            except Exception as e:
                log(f"Erro na predicao YOLO: {e}", "ERRO", "DETECT")
                continue

        annotated_frame = frame_high.copy()
        if last_results:
            annotated_frame = draw_boxes(annotated_frame, last_results)

        pre_buffer.append(annotated_frame.copy())

        if standing_detected_in_check and not recording and (now - last_record_trigger_time > RECORD_COOLDOWN_SECONDS):
            last_record_trigger_time = now
            filename = os.path.join(OUTPUT_VIDEO_DIR, time.strftime("55_%Y%m%d_%H%M%S.mp4"))
            
            try:
                ffmpeg_command = [
                    'ffmpeg', '-y', '-f', 'rawvideo', '-vcodec', 'rawvideo',
                    '-pix_fmt', 'bgr24', '-s', f'{WIDTH}x{HEIGHT}', '-r', str(FPS),
                    '-i', '-', '-c:v', 'libx264', '-b:v', FFMPEG_BITRATE,
                    '-pix_fmt', 'yuv420p', filename
                ]
                ffmpeg_process = subprocess.Popen(ffmpeg_command, stdin=subprocess.PIPE, stderr=subprocess.DEVNULL)
                
                log(f"Gravacao de '{TARGET_CLASS_NAME}' iniciada: {filename}", "INFO", "DETECT")
                
                for f in list(pre_buffer):
                    ffmpeg_process.stdin.write(f.tobytes())
                    
                recording = True
                post_frames_remaining = int(FPS * POST_BUFFER_SECONDS)
            
            except FileNotFoundError:
                log("Comando 'ffmpeg' nao encontrado. Verifique se o FFmpeg esta instalado.", "ERRO", "DETECT")
                ffmpeg_process = None
            except Exception as e:
                log(f"Erro ao iniciar gravacao com FFmpeg: {e}", "ERRO", "DETECT")
                if ffmpeg_process:
                    ffmpeg_process.kill()
                ffmpeg_process = None

        if recording and ffmpeg_process:
            try:
                ffmpeg_process.stdin.write(annotated_frame.tobytes())
                post_frames_remaining -= 1
                
                if post_frames_remaining <= 0:
                    ffmpeg_process.stdin.close()
                    ffmpeg_process.wait()
                    ffmpeg_process = None
                    recording = False
                    log(f"Gravacao finalizada.", "INFO", "DETECT")
            except Exception as e:
                log(f"Erro durante a gravacao: {e}", "ERRO", "DETECT")
                if ffmpeg_process:
                    ffmpeg_process.kill()
                ffmpeg_process = None
                recording = False

    # Garante que o ffmpeg seja finalizado se a thread parar durante uma gravacao
    if ffmpeg_process:
        try:
            ffmpeg_process.stdin.close()
            ffmpeg_process.wait()
        except Exception:
            pass
            
    log("Thread de deteccao finalizada.", thread_name="DETECT")

# --- EXECUCAO PRINCIPAL ---
if __name__ == '__main__':
    log("Iniciando aplicacao de vigilancia...")
    
    capture_thread = threading.Thread(target=video_capture_thread, args=(RTSP_URL,))
    detector_thread = threading.Thread(target=detection_thread)
    
    # Daemon = True faz com que as threads sejam encerradas se o programa principal fechar
    capture_thread.daemon = True
    detector_thread.daemon = True
    
    capture_thread.start()
    detector_thread.start()
    
    try:
        # Mantem o programa principal rodando para que as threads possam trabalhar.
        # O programa pode ser interrompido com Ctrl+C.
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        log("Sinal de interrupcao recebido (Ctrl+C). Encerrando threads...", "INFO")
    finally:
        stop_event.set()
        
        # Espera as threads terminarem de forma limpa
        capture_thread.join()
        detector_thread.join()
        
        log("Aplicacao finalizada.")