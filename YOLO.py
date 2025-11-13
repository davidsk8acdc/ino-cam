#!/usr/bin/env python
# -*- coding: utf-8 -*-

import asyncio
from bleak import BleakClient, BleakScanner, BleakError
import sys
import struct
from datetime import datetime
import cv2
from ultralytics import YOLO
from collections import deque
import threading
import queue
import time
import os
import subprocess
import logging
from logging.handlers import TimedRotatingFileHandler

# --- CONFIGURACOES GERAIS ---
OUTPUT_VIDEO_DIR = "videos"
LOG_DIR = "logs"
LOG_LEVEL = logging.INFO

# --- CONFIGURACOES BLE ---
DEVICE_NAME = "GS 865513070677451"
SERVER_TX_UUID = "0783b03e-8535-b5a0-7140-a304d2495cb8"
SERVER_RX_UUID = "0783b03e-8535-b5a0-7140-a304d2495cba"

TAG_SIZES = {
    0x01: 1, 0x02: 1, 0x03: 15, 0x04: 2, 0x10: 2, 0x20: 4, 0x30: 9,
    0x33: 4, 0x34: 2, 0x35: 1, 0x40: 2, 0x41: 2, 0x42: 2, 0x43: 1,
    0x44: 4, 0x45: 2, 0x46: 2, 0x50: 2, 0x51: 2, 0x52: 2, 0x53: 2,
    0x54: 2, 0x55: 2, 0x56: 2, 0x57: 2, 0x58: 2, 0x59: 2,
    0x60: 2, 0x61: 2, 0x62: 2, 0x63: 3, 0x64: 3, 0x6F: 3,
    0x70: 2, 0x71: 2, 0x72: 2, 0x73: 2, 0x74: 2, 0x75: 2, 0x76: 2, 0x77: 2,
    0x78: 2, 0x79: 2, 0x7A: 2, 0x7B: 2, 0x7C: 2, 0x7D: 2,
    0x80: 3, 0x81: 3, 0x82: 3, 0x83: 3, 0x84: 3, 0x85: 3, 0x86: 3, 0x87: 3,
    0x88: 1, 0x89: 1, 0x8A: 1, 0x8B: 1, 0x8C: 1,
    0x90: 4, 0xC0: 4, 0xC1: 4, 0xC2: 4, 0xC3: 4, 0xC4: 1, 0x5: 1,
    0xC6: 1, 0xC7: 1, 0xC8: 1, 0xC9: 1, 0xCA: 1, 0xCB: 1, 0xCC: 1,
    0xCD: 1, 0xCE: 1, 0xCF: 1, 0xD0: 1, 0xD1: 1, 0xD2: 1,
    0xD3: 4, 0xD4: 4, 0xD5: 1, 0xD6: 2, 0xD7: 2, 0xD8: 2, 0xD9: 2,
    0xDA: 2, 0xDB: 4, 0xDC: 4, 0xDD: 4, 0xDE: 4, 0xDF: 4,
    0xE2: 4, 0xE3: 4, 0xE4: 4, 0xE5: 4, 0xE6: 4, 0xE7: 4, 0xE8: 4,
    0x47: 4, 0x5D: 3, 0xEB: 2, 0x48: 2, 0x49: 1, 0x11: 4, 0x36: 1,
    0x5B: -1, 0x5C: -1, 0xE9: -1, 0xEA: -1, 0xFE: -1
}

# --- CONFIGURACOES YOLO/RTSP ---
RTSP_URL = "rtsp://admin:Arvore32!@192.168.100.176:554/cam/realmonitor?channel=1&subtype=1"
TARGET_CLASS_NAME = "standing"

# NOVO: Define a velocidade minima (em km/h) para ligar a IA
VELOCIDADE_MINIMA_PARA_IA = 5.0 # (ex: 5.0 km/h)

CONFIDENCE_THRESHOLD = 0.8
YOLO_CHECK_INTERVAL_SECONDS = 2.0
RECORD_COOLDOWN_SECONDS = 30.0
PRE_BUFFER_SECONDS = 5
POST_BUFFER_SECONDS = 5

FPS = 15
WIDTH, HEIGHT = 640, 480
FFMPEG_BITRATE = "2500k"

# --- VARIAVEIS GLOBAIS COMPARTILHADAS ---
ble_data_lock = threading.Lock()
# MODIFICADO: Adicionado 'velocidade_float'
latest_ble_data = {
    "timestamp_ble": None,
    "latitude_hex": "NOLAT",
    "longitude_hex": "NOLON",
    "velocidade_hex": "NOVEL",
    "velocidade_float": 0.0, # Padrao e 0.0 (parado)
    "user_tag_1_hex": "NOTAG"
}

frame_queue = queue.Queue(maxsize=128)
stop_event = threading.Event()

# --- SISTEMA DE LOG (OTIMIZADO) ---
os.makedirs(OUTPUT_VIDEO_DIR, exist_ok=True)
os.makedirs(LOG_DIR, exist_ok=True)

def setup_logging():
    log_formatter = logging.Formatter(
        f"[%(asctime)s] [%(threadName)-7s] [%(levelname)s] %(message)s",
        "%Y-%m-%d %H:%M:%S"
    )
    
    log_file_path = os.path.join(LOG_DIR, f"detec.log")
    
    file_handler = TimedRotatingFileHandler(
        log_file_path,
        when="midnight",
        interval=1,
        backupCount=7,
        encoding="utf-8"
    )
    file_handler.setFormatter(log_formatter)
    
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(log_formatter)
    
    logger = logging.getLogger()
    logger.setLevel(LOG_LEVEL)
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    
    logging.info("Sistema de logging configurado.")

# --- FUNCOES BLE ---

# MODIFICADO: Agora decodifica o float da velocidade
def notification_handler(sender_handle: int, data: bytearray):
    logging.debug(f"Dados Brutos BLE: {data.hex()}")

    dados_filtrados = data[4:]
    
    if not dados_filtrados or dados_filtrados[0] != 0x01:
        return

    try:
        L_com_flag = struct.unpack('<H', dados_filtrados[1:3])[0]
        L_payload = L_com_flag & 0x7FFF
        
        payload = dados_filtrados[3 : 3 + L_payload]
        
        raw_data = {}
        index = 0
        
        while index < len(payload):
            tag = payload[index]
            index += 1
            
            data_size = TAG_SIZES.get(tag, -2)
            
            if data_size == -2: break 
            if data_size == -1: break
            if index + data_size > len(payload): break
                
            tag_data = payload[index : index + data_size]
            
            if tag == 0x20:
                timestamp_unix = struct.unpack('<I', tag_data)[0]
                raw_data["timestamp_ble"] = timestamp_unix
            
            elif tag == 0x30:
                raw_data["latitude_hex"] = tag_data[1:5].hex()
                raw_data["longitude_hex"] = tag_data[5:9].hex()

            elif tag == 0x33:
                # Salva o HEX (para o nome do arquivo)
                raw_data["velocidade_hex"] = tag_data[0:2].hex()
                # Salva o FLOAT (para a logica da IA)
                spd_raw = struct.unpack('<H', tag_data[0:2])[0]
                raw_data["velocidade_float"] = spd_raw / 10.0

            elif tag == 0xE3:
                raw_data["user_tag_1_hex"] = tag_data.hex()
            
            index += data_size
        
        if raw_data:
            global latest_ble_data, ble_data_lock
            with ble_data_lock:
                latest_ble_data.update(raw_data)

    except Exception as e:
        logging.error(f"Erro ao processar pacote BLE (light): {e}")
        logging.error(f"Pacote com erro (light): {data.hex()}")


# MODIFICADO: Reseta 'velocidade_float' ao desconectar
async def main_loop(name_to_find):
    while not stop_event.is_set():
        logging.info(f"Procurando dispositivo pelo NOME: '{name_to_find}'...")
        client = None
        
        try:
            device = await BleakScanner.find_device_by_name(name_to_find, timeout=10.0)
            
            if not device:
                logging.warning(f"Dispositivo com nome '{name_to_find}' nao encontrado. Tentando novamente em 10s...")
                await asyncio.sleep(10)
                continue

            logging.info(f"Dispositivo encontrado! (Endereco: {device.address}) Conectando...")

            async with BleakClient(device) as client:
                logging.info(f"Conectado com sucesso!")
                
                await client.start_notify(SERVER_TX_UUID, notification_handler)
                logging.info("Inscrito para notificacoes. Ouvindo...")

                while client.is_connected and not stop_event.is_set():
                    await asyncio.sleep(1)
                
                if stop_event.is_set():
                    break

        except BleakError as e:
            logging.error(f"Erro de Conexao (BleakError): {e}")
            
        except Exception as e:
            logging.error(f"Erro inesperado no loop BLE: {e}")
            
        finally:
            logging.info("Desconectado. Resetando dados BLE para o padrao.")
            
            global latest_ble_data, ble_data_lock
            with ble_data_lock:
                latest_ble_data["timestamp_ble"] = None
                latest_ble_data["latitude_hex"] = "NOLAT"
                latest_ble_data["longitude_hex"] = "NOLON"
                latest_ble_data["velocidade_hex"] = "NOVEL"
                latest_ble_data["velocidade_float"] = 0.0 # Reseta para 0.0 (parado)
                latest_ble_data["user_tag_1_hex"] = "NOTAG"
            
            if client and client.is_connected:
                try:
                    await client.disconnect()
                except Exception as disc_e:
                    logging.error(f"Erro ao desconectar: {disc_e}")
                    
            if not stop_event.is_set():
                logging.info("Tentando reconectar em 5 segundos...")
                await asyncio.sleep(5)

def ble_thread_function():
    try:
        asyncio.run(main_loop(DEVICE_NAME))
    except Exception as e:
        logging.critical(f"Erro critico na thread BLE: {e}")
    logging.info("Thread BLE finalizada.")


# --- FUNCOES DE VIDEO/YOLO ---

def draw_boxes(frame, results, target_class_id, target_class_name):
    if results is None:
        return frame
    
    for box in results.boxes:
        cls_id = int(box.cls[0])
        if cls_id != target_class_id:
            continue
            
        x1, y1, x2, y2 = map(int, box.xyxy[0])
        conf = float(box.conf[0])
        color = (0, 0, 255)
        cv2.rectangle(frame, (x1, y1), (x2, y2), color, 1, cv2.LINE_AA)
        label = f"{target_class_name} {conf:.2f}"
        ((text_w, text_h), _) = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
        cv2.rectangle(frame, (x1, y1 - text_h - 4), (x1 + text_w, y1), color, -1)
        cv2.putText(frame, label, (x1, y1 - 2), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1, cv2.LINE_AA)
    return frame

def video_capture_thread(rtsp_url):
    while not stop_event.is_set():
        cap = None
        try:
            logging.info(f"Tentando conectar a stream RTSP: {rtsp_url}")
            cap = cv2.VideoCapture(rtsp_url, cv2.CAP_FFMPEG)
            
            if not cap.isOpened():
                logging.error("Nao foi possivel abrir a stream. Tentando novamente em 5s...")
                time.sleep(5)
                continue

            logging.info("Stream RTSP conectado com sucesso!")
            while not stop_event.is_set():
                ret, frame = cap.read()
                
                if not ret:
                    logging.warning("Stream de video perdida. Tentando reconectar...")
                    break

                frame_resized = cv2.resize(frame, (WIDTH, HEIGHT))

                if frame_queue.full():
                    try:
                        frame_queue.get_nowait()
                    except queue.Empty:
                        pass
                frame_queue.put(frame_resized)
        
        except Exception as e:
            logging.error(f"Erro inesperado na thread de captura: {e}")
            logging.info("Tentando reconectar em 10 segundos...")
            time.sleep(10)
        
        finally:
            if cap is not None:
                cap.release()
                
    logging.info("Thread de captura finalizada.")

# MODIFICADO: Adicionada logica de verificacao de velocidade
def detection_thread():
    model = None
    try:
        logging.info("Carregando modelo YOLO (CPU forcado)...")
        model = YOLO("pesos/best.pt")
    except Exception as e:
        logging.critical(f"Erro critico ao carregar modelo YOLO: {e}. Encerrando thread.", exc_info=True)
        return

    target_class_id = -1
    try:
        class_names = model.names
        target_class_id = next((cls_id for cls_id, name in class_names.items() if name == TARGET_CLASS_NAME), -1)
        
        if target_class_id == -1:
            logging.error(f"Classe alvo '{TARGET_CLASS_NAME}' nao encontrada no modelo.")
        else:
            logging.info(f"Classe '{TARGET_CLASS_NAME}' mapeada para o ID: {target_class_id}")
            
    except Exception as e:
        logging.error(f"Erro ao ler nomes das classes do modelo: {e}")

    logging.info("Thread de deteccao iniciada.")
    pre_buffer = deque(maxlen=int(FPS * PRE_BUFFER_SECONDS))
    recording = False
    ffmpeg_process = None
    post_frames_remaining = 0
    last_yolo_check_time = 0
    last_record_trigger_time = 0
    last_results = None

    while not stop_event.is_set():
        try:
            frame = frame_queue.get(timeout=1.0)
        except queue.Empty:
            continue

        now = time.time()
        
        # --- LOGICA DE ANOTACAO E PRE-BUFFER (SEMPRE ACONTECE) ---
        annotated_frame = frame.copy()
        if last_results:
            draw_boxes(annotated_frame, last_results, target_class_id, TARGET_CLASS_NAME)

        pre_buffer.append(annotated_frame)
        
        # --- LOGICA DE VELOCIDADE ---
        with ble_data_lock:
            velocidade_atual = latest_ble_data["velocidade_float"]

        if velocidade_atual < VELOCIDADE_MINIMA_PARA_IA:
            # Velocidade baixa: Pula a IA e a gravacao para economizar CPU
            
            if last_results is not None:
                logging.debug("Velocidade baixa, limpando detecoes antigas.")
                
            last_results = None # Limpa caixas antigas
            last_yolo_check_time = 0 # Reseta o timer do YOLO
            continue # Pula para o proximo frame
        
        # --- SE CHEGOU AQUI, A VELOCIDADE ESTA ALTA ---
        
        standing_detected_in_check = False

        if now - last_yolo_check_time > YOLO_CHECK_INTERVAL_SECONDS and target_class_id != -1:
            logging.debug("Velocidade ALTA, rodando predicao YOLO...")
            try:
                results = model.predict(frame, 
                                        conf=CONFIDENCE_THRESHOLD, 
                                        classes=[target_class_id], 
                                        device='cpu', 
                                        verbose=False)[0]
                
                last_yolo_check_time = now
                
                if len(results.boxes) > 0:
                    last_results = results
                    standing_detected_in_check = True
                else:
                    last_results = None
            except Exception as e:
                logging.error(f"Erro na predicao YOLO: {e}", exc_info=True)
                continue

        # --- LOGICA DE GRAVACAO (So acontece se a velocidade estiver alta) ---
        if standing_detected_in_check and not recording and (now - last_record_trigger_time > RECORD_COOLDOWN_SECONDS):
            last_record_trigger_time = now
            
            timestamp_str = None
            
            with ble_data_lock:
                ts_ble_value = latest_ble_data["timestamp_ble"]
                lat_hex = latest_ble_data["latitude_hex"]
                lon_hex = latest_ble_data["longitude_hex"]
                vel_hex = latest_ble_data["velocidade_hex"]
                tag_hex = latest_ble_data["user_tag_1_hex"]
            
            if ts_ble_value is not None:
                try:
                    timestamp_str = datetime.fromtimestamp(ts_ble_value).strftime('%Y%m%d%H%M%S')
                    logging.info("Usando timestamp do BLE para o nome do arquivo.")
                except Exception as e:
                    logging.warning(f"Erro ao formatar timestamp do BLE ({ts_ble_value}): {e}")
                    timestamp_str = None
            
            if timestamp_str is None:
                logging.warning("Timestamp do BLE indisponivel. Usando timestamp do sistema.")
                timestamp_str = time.strftime('%Y%m%d%H%M%S')

            
            filename_str = f"55_{timestamp_str}_{lat_hex}_{lon_hex}_{vel_hex}_{tag_hex}.mp4"
            filename = os.path.join(OUTPUT_VIDEO_DIR, filename_str)
            
            try:
                ffmpeg_command = [
                    'ffmpeg', '-y', '-f', 'rawvideo', '-vcodec', 'rawvideo',
                    '-pix_fmt', 'bgr24', '-s', f'{WIDTH}x{HEIGHT}', '-r', str(FPS),
                    '-i', '-', '-c:v', 'libx264', '-b:v', FFMPEG_BITRATE,
                    '-pix_fmt', 'yuv420p', filename
                ]
                ffmpeg_process = subprocess.Popen(ffmpeg_command, stdin=subprocess.PIPE, stderr=subprocess.DEVNULL)
                
                logging.info(f"Gravacao com dados BLE iniciada: {filename}")
                
                # Descarrega o pre-buffer (que ja tem os frames corretos)
                for f in list(pre_buffer):
                    ffmpeg_process.stdin.write(f.tobytes())
                    
                recording = True
                post_frames_remaining = int(FPS * POST_BUFFER_SECONDS)
            
            except FileNotFoundError:
                logging.error("Comando 'ffmpeg' nao encontrado. Verifique se o FFmpeg esta instalado.")
                ffmpeg_process = None
            except Exception as e:
                logging.error(f"Erro ao iniciar gravacao com FFmpeg: {e}", exc_info=True)
                if ffmpeg_process:
                    ffmpeg_process.kill()
                ffmpeg_process = None

        if recording and ffmpeg_process:
            try:
                # O frame ja foi anotado no inicio do loop
                ffmpeg_process.stdin.write(annotated_frame.tobytes())
                post_frames_remaining -= 1
                
                if post_frames_remaining <= 0:
                    ffmpeg_process.stdin.close()
                    ffmpeg_process.wait()
                    ffmpeg_process = None
                    recording = False
                    logging.info(f"Gravacao finalizada.")
            except Exception as e:
                logging.error(f"Erro durante a gravacao: {e}", exc_info=True)
                if ffmpeg_process:
                    ffmpeg_process.kill()
                ffmpeg_process = None
                recording = False

    if ffmpeg_process:
        try:
            ffmpeg_process.stdin.close()
            ffmpeg_process.wait()
        except Exception:
            pass
            
    logging.info("Thread de deteccao finalizada.")

# --- EXECUCAO PRINCIPAL ---
if __name__ == '__main__':
    setup_logging()
    
    threading.current_thread().name = "MAIN"
    
    logging.info("Iniciando aplicacao...")
    
    capture_thread = threading.Thread(target=video_capture_thread, args=(RTSP_URL,), name="CAPTURE")
    detector_thread = threading.Thread(target=detection_thread, name="DETECT")
    ble_thread = threading.Thread(target=ble_thread_function, name="BLE")
    
    capture_thread.start()
    detector_thread.start()
    ble_thread.start()
    
    try:
        while True:
            if not capture_thread.is_alive():
                logging.critical("Thread de Captura morreu. Encerrando...")
                break
            if not detector_thread.is_alive():
                logging.critical("Thread de Deteccao morreu. Encerrando...")
                break
            
            if not ble_thread.is_alive():
                 logging.warning("Thread BLE morreu. Tentando reiniciar...")
                 ble_thread.join()
                 ble_thread = threading.Thread(target=ble_thread_function, name="BLE")
                 ble_thread.start()

            time.sleep(1)
            
    except KeyboardInterrupt:
        logging.info("Sinal de interrupcao recebido (Ctrl+C). Encerrando threads...")
    finally:
        stop_event.set()
        
        logging.info("Aguardando thread de captura...")
        capture_thread.join()
        logging.info("Aguardando thread de deteccao...")
        detector_thread.join()
        logging.info("Aguardando thread BLE...")
        ble_thread.join()
        
        logging.info("Aplicacao finalizada.")