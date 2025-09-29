# -*- coding: utf-8 -*-

import os
import cv2
import socket
import subprocess
import time
from flask import Flask, Response, render_template_string, request, redirect, url_for, flash

# --- 1. CONFIGURACAO DO APP FLASK ---
app = Flask(__name__)
app.secret_key = 'chave-secreta-para-manter-seguranca' # Mude para uma chave de sua preferência
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# --- 2. CONSTANTES E CONFIGURACOES ---
RTSP_URL = "rtsp://admin:Arvore32!@192.168.100.167:554/cam/realmonitor?channel=1&subtype=1"

# --- 3. FUNCOES DE INFORMACAO DO SISTEMA ---

def get_serial():
    """Obtem o numero de serie da CPU (especifico para Raspberry Pi)."""
    try:
        with open('/proc/cpuinfo', 'r') as f:
            for line in f:
                if line.startswith('Serial'):
                    return line.split(':')[1].strip()
    except Exception:
        return "N/A"
    return "N/A"

def get_ip():
    """Obtem o endereco IP local."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
    except Exception:
        ip = "Desconectado"
    finally:
        s.close()
    return ip

def get_tailscale_status():
    """Verifica o status do Tailscale."""
    try:
        subprocess.check_output(["tailscale", "status"], stderr=subprocess.STDOUT)
        return "Conectado"
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "Nao Disponivel"
    return "Desconhecido"

# --- 4. FUNCOES DE GERENCIAMENTO DE WI-FI (VERSAO ROBUSTA) ---

def scan_wifi():
    """Escaneia e retorna uma lista de redes Wi-Fi usando nmcli com formato CSV."""
    networks = []
    try:
        # Pede ao nmcli um formato amigavel para scripts (terse) e campos separados por ":"
        # Este metodo e muito mais robusto que ler a tabela de texto.
        cmd = [
            "nmcli", "--terse", "--fields", "SSID,SIGNAL,SECURITY", 
            "dev", "wifi", "list", "--rescan", "yes"
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        lines = result.stdout.strip().split('\n')
        
        for line in lines:
            # A saida sera algo como: "MeuWiFi:88:WPA2"
            parts = [p.replace('\\:', ':') for p in line.split(':')]
            if len(parts) >= 2 and parts[0]:
                ssid = parts[0]
                signal = int(parts[1])
                security = ":".join(parts[2:]) if len(parts) > 2 else "Aberta"
                networks.append({'ssid': ssid, 'signal': signal, 'security': security if security else "Aberta"})

    except (subprocess.CalledProcessError, FileNotFoundError, IndexError):
        return []
    
    unique_networks = {net['ssid']: net for net in networks}.values()
    return sorted(list(unique_networks), key=lambda x: x['signal'], reverse=True)

def connect_to_wifi(ssid, password):
    """Tenta conectar a uma rede Wi-Fi usando nmcli."""
    try:
        cmd = ["nmcli", "dev", "wifi", "connect", ssid, "password", password]
        subprocess.run(cmd, check=True, capture_output=True, text=True)
        return True, f"Conexao com '{ssid}' iniciada com sucesso."
    except subprocess.CalledProcessError as e:
        error_message = e.stderr.strip()
        if "secret" in error_message.lower() or "senha" in error_message.lower():
            return False, f"Falha ao conectar: Senha incorreta para '{ssid}'."
        elif "already" in error_message.lower():
             return True, f"Ja existe uma conexao configurada para '{ssid}'."
        return False, f"Falha ao conectar com '{ssid}'."
    except FileNotFoundError:
        return False, "Erro: O comando 'nmcli' nao foi encontrado."

# --- 5. FUNCOES DE STREAMING DE VIDEO (VERSAO ROBUSTA) ---

try:
    cap = cv2.VideoCapture(RTSP_URL)
    if not cap.isOpened():
        cap = None
except Exception:
    cap = None

def gen_frames():
    """Gera os frames do video da camera ou uma imagem de fallback com tratamento de erros."""
    global cap
    while True:
        frame = None
        if cap:
            ret, frame_cam = cap.read()
            if ret:
                frame = frame_cam
            else:
                cap.release()
                cap = None
        
        if frame is None:
            fallback_path = os.path.join(BASE_DIR, "foto_onibus.jpg")
            if os.path.exists(fallback_path):
                frame = cv2.imread(fallback_path)
            
            if frame is None:
                frame = cv2.UMat(240, 320, cv2.CV_8UC3).get()
                cv2.putText(frame, "ERRO DE IMAGEM", (40, 120), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
            
            time.sleep(1)

        ret, buffer = cv2.imencode('.jpg', frame)
        if ret:
            frame_bytes = buffer.tobytes()
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')

# --- 6. ROTAS DO FLASK E INTERFACE HTML ---

@app.route("/")
def index():
    """Renderiza a pagina principal com todas as informacoes e o layout."""
    status_info = {
        'serial': get_serial(),
        'ip': get_ip(),
        'tailscale': get_tailscale_status()
    }
    wifi_networks = scan_wifi()
    
    # O HTML e o CSS estao todos aqui para manter em um unico arquivo.
    html_template = """
    <!DOCTYPE html>
    <html lang="pt-BR">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Painel de Controle</title>
        <style>
            :root {
                --cor-fundo: #f0f2f5;
                --cor-card: #ffffff;
                --cor-texto: #333333;
                --cor-titulo: #1c1e21;
                --cor-primaria: #007bff;
                --cor-primaria-hover: #0056b3;
                --cor-borda: #dddddd;
                --sombra-card: 0 4px 12px rgba(0,0,0,0.08);
                --raio-borda: 12px;
            }
            body { 
                font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif; 
                background-color: var(--cor-fundo); 
                margin: 0; 
                padding: 20px; 
                color: var(--cor-texto);
            }
            .container { max-width: 700px; margin: auto; display: grid; gap: 25px; }
            .card { 
                background-color: var(--cor-card); 
                padding: 25px; 
                border-radius: var(--raio-borda); 
                box-shadow: var(--sombra-card); 
            }
            h2 { 
                color: var(--cor-titulo); 
                text-align: center; 
                border-bottom: 1px solid var(--cor-borda); 
                padding-bottom: 15px; 
                margin-top: 0;
                margin-bottom: 20px;
            }
            .status-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 15px; margin-bottom: 20px; }
            .status-grid p { background-color: #f7f7f7; padding: 12px; border-radius: 8px; margin: 0; }
            img.video-stream { width: 100%; border-radius: 8px; border: 1px solid var(--cor-borda); }
            .wifi-list { list-style: none; padding: 0; max-height: 250px; overflow-y: auto; border: 1px solid var(--cor-borda); border-radius: 8px; }
            .wifi-list li { padding: 12px 15px; border-bottom: 1px solid #eee; display: flex; justify-content: space-between; align-items: center; }
            .wifi-list li:last-child { border-bottom: none; }
            .wifi-list small { color: #666; background-color: #eee; padding: 3px 8px; border-radius: 5px; font-size: 0.8em;}
            .form-section h3 { margin-top: 25px; margin-bottom: 15px; text-align: center; color: #555; }
            .form-wifi { display: flex; flex-direction: column; gap: 12px; }
            .form-wifi input { padding: 12px; border: 1px solid var(--cor-borda); border-radius: 8px; font-size: 1em; }
            .form-wifi button { 
                padding: 14px; border: none; border-radius: 8px; background-color: var(--cor-primaria); 
                color: white; font-weight: bold; font-size: 1em; cursor: pointer; transition: background-color 0.2s;
            }
            .form-wifi button:hover { background-color: var(--cor-primaria-hover); }
            .flash-message { padding: 15px; border-radius: 8px; margin-bottom: 20px; text-align: center; border: 1px solid transparent; }
            .flash-success { background-color: #d4edda; color: #155724; border-color: #c3e6cb; }
            .flash-error { background-color: #f8d7da; color: #721c24; border-color: #f5c6cb; }
        </style>
    </head>
    <body>
        <div class="container">
            {% with messages = get_flashed_messages(with_categories=true) %}
                {% if messages %}
                    {% for category, message in messages %}
                        <div class="flash-message flash-{{ category }}">{{ message }}</div>
                    {% endfor %}
                {% endif %}
            {% endwith %}

            <div class="card">
                <h2>Status do Equipamento</h2>
                <div class="status-grid">
                    <p><strong>Serial:</strong> {{ status.serial }}</p>
                    <p><strong>IP Local:</strong> {{ status.ip }}</p>
                    <p><strong>Tailscale:</strong> {{ status.tailscale }}</p>
                </div>
                <img class="video-stream" src="{{ url_for('video_feed') }}" alt="Stream da camera">
            </div>

            <div class="card">
                <h2>Gerenciador de Wi-Fi</h2>
                {% if networks %}
                    <ul class="wifi-list">
                    {% for net in networks %}
                        <li>
                            <span>{{ net.ssid }} (Sinal: {{ net.signal }}%)</span>
                            <small>{{ net.security }}</small>
                        </li>
                    {% endfor %}
                    </ul>
                {% else %}
                    <p>Nenhuma rede Wi-Fi encontrada. Verifique se o Wi-Fi esta ativado.</p>
                {% endif %}
                <div class="form-section">
                    <h3>Conectar a uma Rede</h3>
                    <form class="form-wifi" action="{{ url_for('handle_wifi_connect') }}" method="post">
                        <input type="text" name="ssid" placeholder="Nome da Rede (SSID)" required>
                        <input type="password" name="password" placeholder="Senha da Rede" required>
                        <button type="submit">Conectar</button>
                    </form>
                </div>
            </div>
        </div>
    </body>
    </html>
    """
    return render_template_string(html_template, status=status_info, networks=wifi_networks)

@app.route('/video_feed')
def video_feed():
    """Rota para o streaming de video."""
    return Response(gen_frames(), mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/connect', methods=['POST'])
def handle_wifi_connect():
    """Recebe os dados do formulario Wi-Fi e tenta conectar."""
    if request.method == 'POST':
        ssid = request.form.get('ssid')
        password = request.form.get('password')
        
        if not ssid or not password:
            flash("Nome da rede e senha sao obrigatorios.", "error")
        else:
            success, message = connect_to_wifi(ssid, password)
            flash(message, "success" if success else "error")
            
    return redirect(url_for('index'))

# --- 7. EXECUCAO PRINCIPAL ---
if __name__ == "__main__":
    print("===================================================")
    print("Servidor iniciado. Acesse o IP do dispositivo na porta 80.")
    print("Exemplo: http://192.168.1.32")
    print("Pressione CTRL+C para encerrar.")
    print("===================================================")
    app.run(host="0.0.0.0", port=80, debug=False)