# -*- coding: utf-8 -*-

import os
from flask import Flask, Response
import cv2
import threading
import time

# --- Configuracao ---

# IMPORTANTE: Forca o OpenCV a usar UDP para o stream RTSP.
# E mais rapido e nao trava, mas pode perder pacotes (causar glitches).
os.environ['OPENCV_FFMPEG_CAPTURE_OPTIONS'] = 'rtsp_transport;udp'

# URL da camera RTSP
RTSP_URL = "rtsp://admin:Arvore32!@192.168.100.176:554/cam/realmonitor?channel=1&subtype=1"

# --- NOVAS VARIAVEIS DE CONFIGURACAO ---
# Qualidade do JPEG (0-100, menor = mais rapido, pior imagem)
# Um bom valor para preview rapido e entre 30 e 50.
QUALIDADE_JPEG = 40

# Largura do preview (em pixels). A altura sera ajustada automaticamente.
# Menor = mais rapido. 640 e um bom padrao.
LARGURA_PREVIEW = 640
# ----------------------------------------

# Variaveis globais
frame_bruto = None
frame_codificado = None
lock_bruto = threading.Lock()
lock_codificado = threading.Lock()
captura_ativa = True
# --- Fim da Configuracao ---


def capturar_frames_camera():
    """
    THREAD 1: Apenas le o frame da camera (I/O) via UDP.
    """
    global frame_bruto, captura_ativa
    
    cap = None
    
    while captura_ativa:
        try:
            if cap is None or not cap.isOpened():
                print("[Captura] Tentando (re)conectar a camera (via UDP)...")
                cap = cv2.VideoCapture(RTSP_URL, cv2.CAP_FFMPEG)
                
                # Definir um buffer de captura menor (ajuda com UDP)
                cap.set(cv2.CAP_PROP_BUFFERSIZE, 3)
                
                # Tenta definir resolucao/fps (raramente funciona em RTSP)
                cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
                cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
                cap.set(cv2.CAP_PROP_FPS, 20)

                if not cap.isOpened():
                    print("[Captura] Erro: Falha ao conectar. Tentando novamente em 5s...")
                    if cap: cap.release()
                    cap = None
                    time.sleep(5)
                    continue
                else:
                    print("[Captura] Conexao com a camera estabelecida (UDP).")

            ret, frame = cap.read()
            
            if not ret:
                print("[Captura] Erro: Nao foi possivel ler o frame. Reconectando...")
                if cap: cap.release()
                cap = None
                time.sleep(2)
                continue
            
            with lock_bruto:
                frame_bruto = frame.copy()
                
        except Exception as e:
            print(f"[Captura] Excecao na thread de captura: {e}")
            if cap: cap.release()
            cap = None
            time.sleep(5)

    if cap: cap.release()
    print("[Captura] Thread de captura finalizada.")


def codificar_frames_para_jpeg():
    """
    THREAD 2: Redimensiona, Pega o frame bruto e o codifica para JPEG (CPU)
    """
    global frame_bruto, frame_codificado, captura_ativa
    
    frame_local = None
    
    while captura_ativa:
        with lock_bruto:
            if frame_bruto is not None:
                frame_local = frame_bruto.copy()
                frame_bruto = None # Limpa para a proxima captura
            else:
                time.sleep(0.01) # Espera 10ms
                continue

        if frame_local is None:
            continue

        # --- OTIMIZACAO 1: Redimensionar o frame ---
        # Isso reduz drasticamente o custo de codificacao e o tamanho da transmissao
        frame_processado = None
        try:
            altura_original, largura_original = frame_local.shape[:2]
            
            # So redimensiona se a imagem for maior que o desejado
            if largura_original > LARGURA_PREVIEW:
                proporcao = LARGURA_PREVIEW / float(largura_original)
                altura_preview = int(altura_original * proporcao)
                
                # Usa interpolacao linear, que e rapida
                frame_processado = cv2.resize(frame_local, 
                                            (LARGURA_PREVIEW, altura_preview), 
                                            interpolation=cv2.INTER_LINEAR)
            else:
                frame_processado = frame_local
        except Exception as e:
            print(f"[Codificacao] Erro ao redimensionar: {e}")
            continue # Pula este frame

        if frame_processado is None:
            continue

        # --- OTIMIZACAO 2: Reduzir a qualidade do JPEG ---
        # Usa a variavel QUALIDADE_JPEG definida na configuracao
        (flag, encoded_image) = cv2.imencode(".jpg", frame_processado, 
                                           [cv2.IMWRITE_JPEG_QUALITY, QUALIDADE_JPEG])

        if not flag:
            continue
            
        with lock_codificado:
            frame_codificado = bytearray(encoded_image)


def gerar_frames_para_web():
    """
    GERADOR (Executado pelo Flask): Envia o frame JPEG mais recente.
    """
    global frame_codificado
    
    while True:
        frame_bytes = None
        with lock_codificado:
            if frame_codificado is not None:
                frame_bytes = frame_codificado
                # Nao limpamos o frame_codificado, 
                # para que multiplos clientes vejam o ultimo frame
            
        if frame_bytes:
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')
        
        # Pausa para tentar limitar o FPS de envio e nao sobrecarregar
        time.sleep(1/30) # ~30 FPS


app = Flask(__name__)

@app.route('/')
def index():
    return """
    <html>
        <head><title>Stream da Camera (UDP Otimizado)</title></head>
        <body style="background-color:#111;">
            <img src="/video_feed" style="display: block; margin: 50px auto; border: 1px solid #444; width: {}px;">
        </body>
    </html>
    """.format(LARGURA_PREVIEW) # Ajusta o tamanho no HTML

@app.route('/video_feed')
def video_feed():
    return Response(gerar_frames_para_web(),
                    mimetype='multipart/x-mixed-replace; boundary=frame')


if __name__ == '__main__':
    thread_captura = threading.Thread(target=capturar_frames_camera)
    thread_captura.daemon = True
    thread_captura.start()

    thread_codificacao = threading.Thread(target=codificar_frames_para_jpeg)
    thread_codificacao.daemon = True
    thread_codificacao.start()
    
    print("\n----------------------------------------------------")
    print(f"Servidor Flask (Otimizado - {LARGURA_PREVIEW}p Q{QUALIDADE_JPEG} UDP) iniciado.")
    print("Acesse no seu navegador: http://127.0.0.1:5000")
    print("----------------------------------------------------\n")
    
    try:
        # Usar 'threaded=True' e crucial para o Flask lidar com multiplos acessos
        app.run(host='0.0.0.0', port=5000, debug=False, threaded=True)
    except KeyboardInterrupt:
        print("\nServidor Flask interrompido.")
    finally:
        captura_ativa = False
        if thread_captura.is_alive(): thread_captura.join()
        if thread_codificacao.is_alive(): thread_codificacao.join()
        print("Servidor finalizado.")