# -*- coding: utf-8 -*-
import cv2
from flask import Flask, Response, render_template_string
from ultralytics import YOLO
from collections import deque
import threading
import queue
import time
import os
from datetime import datetime

# --- CONFIGURACOES ---
RTSP_URL = "rtsp://admin:Arvore32!@192.168.100.167:554/cam/realmonitor?channel=1&subtype=1"
OUTPUT_VIDEO_DIR = "videos"
LOG_DIR = "logs"
TARGET_CLASS = 0
CONFIDENCE_THRESHOLD = 0.8
YOLO_CHECK_INTERVAL_SECONDS = 2.0
RECORD_COOLDOWN_SECONDS = 30.0
PRE_BUFFER_SECONDS = 5
POST_BUFFER_SECONDS = 5

FPS = 20
WIDTH, HEIGHT = 640, 480
WEB_FPS = 20

os.makedirs(OUTPUT_VIDEO_DIR, exist_ok=True)
os.makedirs(LOG_DIR, exist_ok=True)

frame_queue = queue.Queue(maxsize=128)
web_output_frame = None
lock = threading.Lock()
stop_event = threading.Event()

# --- LOG ---
def log(msg, level="INFO"):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_file = os.path.join(LOG_DIR, f"detec_{datetime.now().strftime('%Y-%m-%d')}.log")
    line = f"[{timestamp}] [{level}] {msg}"
    print(line)
    try:
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception as e:
        print(f"[ERRO LOG] {e}")

# --- FUNCAO DE DESENHO ---
def draw_boxes(frame, results):
    if results is None:
        return frame
    for box in results.boxes:
        cls_id = int(box.cls[0])
        if cls_id != TARGET_CLASS:
            continue
        x1, y1, x2, y2 = map(int, box.xyxy[0])
        conf = float(box.conf[0])
        cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 1, cv2.LINE_AA)
        label = f"Person {conf:.2f}"
        ((text_w, text_h), _) = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
        cv2.rectangle(frame, (x1, y1 - text_h - 4), (x1 + text_w, y1), (0, 255, 0), -1)
        cv2.putText(frame, label, (x1, y1 - 2), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1, cv2.LINE_AA)
    return frame

# --- THREAD DE CAPTURA ---
def video_capture_thread(rtsp_url):
    log("Thread de captura iniciada")
    while not stop_event.is_set():
        cap = cv2.VideoCapture(rtsp_url)
        if not cap.isOpened():
            log("Nao foi possivel abrir stream. Tentando reconectar em 10s...", "ERRO")
            time.sleep(10)
            continue
        log("Stream RTSP conectado com sucesso")
        while not stop_event.is_set():
            try:
                ret, frame = cap.read()
                if not ret:
                    log("Stream perdido. Reconectando...", "AVISO")
                    break
                if frame_queue.full():
                    try:
                        frame_queue.get_nowait()
                    except queue.Empty:
                        pass
                frame_queue.put(frame)
            except Exception as e:
                log(f"Erro ao capturar frame: {e}", "ERRO")
        cap.release()
        time.sleep(2)
    log("Thread de captura finalizada")

# --- THREAD DE DETECCAO ---
def detection_thread():
    global web_output_frame
    log("Carregando modelo YOLO...")
    try:
        model = YOLO("yolov8n.pt")
    except Exception as e:
        log(f"Erro ao carregar modelo YOLO: {e}", "ERRO")
        return

    log("Thread de deteccao iniciada")
    pre_buffer = deque(maxlen=int(FPS*PRE_BUFFER_SECONDS))
    recording = False
    record_writer = None
    post_frames_remaining = 0
    last_yolo_check_time = 0
    last_record_trigger_time = 0
    last_results = None

    while not stop_event.is_set():
        try:
            frame = frame_queue.get(timeout=1)
        except queue.Empty:
            continue

        frame_high = cv2.resize(frame, (WIDTH, HEIGHT))
        now = time.time()
        person_detected = False

        if now - last_yolo_check_time > YOLO_CHECK_INTERVAL_SECONDS:
            try:
                results = model.predict(frame_high, conf=CONFIDENCE_THRESHOLD, classes=[TARGET_CLASS], verbose=False)[0]
                last_yolo_check_time = now
                if len(results.boxes) > 0:
                    last_results = results
                    person_detected = True
                else:
                    last_results = None
            except Exception as e:
                log(f"Erro na predicao YOLO: {e}", "ERRO")
                continue

        annotated_frame = frame_high.copy()
        if last_results:
            annotated_frame = draw_boxes(annotated_frame, last_results)

        pre_buffer.append(annotated_frame.copy())

        if person_detected and not recording and (now - last_record_trigger_time > RECORD_COOLDOWN_SECONDS):
            last_record_trigger_time = now
            filename = os.path.join(OUTPUT_VIDEO_DIR, time.strftime("detec_%Y%m%d_%H%M%S.mp4"))
            try:
                fourcc = cv2.VideoWriter_fourcc(*'XVID')
                record_writer = cv2.VideoWriter(filename, fourcc, FPS, (WIDTH, HEIGHT))
                if not record_writer.isOpened():
                    log(f"Erro ao abrir VideoWriter para {filename}", "ERRO")
                    record_writer = None
                else:
                    log(f"Gravacao iniciada: {filename}")
                    for f in list(pre_buffer):
                        record_writer.write(f)
                    recording = True
                    post_frames_remaining = int(FPS * POST_BUFFER_SECONDS)
            except Exception as e:
                log(f"Erro ao iniciar gravacao: {e}", "ERRO")
                record_writer = None

        if recording and record_writer:
            try:
                record_writer.write(annotated_frame)
                post_frames_remaining -= 1
                if post_frames_remaining <= 0:
                    record_writer.release()
                    record_writer = None
                    recording = False
                    log("Gravacao finalizada (~10s)")
            except Exception as e:
                log(f"Erro durante gravacao: {e}", "ERRO")
                if record_writer:
                    record_writer.release()
                    record_writer = None
                recording = False

        # Atualiza frame web
        with lock:
            frame_web = cv2.resize(annotated_frame, (480, 360))
            encode_param = [int(cv2.IMWRITE_JPEG_QUALITY), 90]
            web_output_frame = cv2.imencode('.jpg', frame_web, encode_param)[1]

    if record_writer:
        record_writer.release()
    log("Thread de deteccao finalizada")

# --- FLASK ---
app = Flask(__name__)

def generate_web_frames():
    global web_output_frame, lock
    while True:
        with lock:
            if web_output_frame is None:
                time.sleep(0.05)
                continue
            frame_bytes = web_output_frame.tobytes()
        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')
        time.sleep(1/WEB_FPS)

@app.route('/')
def index():
    return render_template_string("""
    <html>
      <head><title>Vigilancia Inteligente</title></head>
      <body style="text-align: center; background-color: #222; color: #eee;">
        <h1>Vigilancia Inteligente</h1>
        <img src="/video" width="640" height="480" style="border:2px solid #555;">
      </body>
    </html>
    """)

@app.route('/video')
def video():
    return Response(generate_web_frames(), mimetype='multipart/x-mixed-replace; boundary=frame')

# --- EXECUCAO ---
if __name__ == '__main__':
    try:
        capture_thread = threading.Thread(target=video_capture_thread, args=(RTSP_URL,))
        detector_thread = threading.Thread(target=detection_thread)
        capture_thread.daemon = True
        detector_thread.daemon = True
        capture_thread.start()
        detector_thread.start()
        log("Servidor Flask rodando em http://0.0.0.0:5000")
        app.run(host='0.0.0.0', port=5000)
    except Exception as e:
        log(f"Erro no servidor principal: {e}", "ERRO")
    finally:
        stop_event.set()
        capture_thread.join()
        detector_thread.join()
        log("Aplicacao finalizada")
