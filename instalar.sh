#!/bin/bash

# =======================================================================
#               SCRIPT DE INSTALAÇÃO E CONFIGURAÇÃO DO PROJETO
# =======================================================================
# Autor: Gemini & David
# Versão: 4.4 - Adiciona login e senha (admin/admin) para a interface web.
# Este script prepara o ambiente, baixa o código e configura o supervisor
# para gerenciar os processos, incluindo a ativação da interface web.
# =======================================================================

# --- BANNER INICIAL ---
echo "======================================================================="
echo ""
echo "      ██╗███╗   ██╗ ██████╗ ██████╗ ██╗███╗   ███╗███████╗"
echo "      ██║████╗  ██║██╔═══██╗██╔══██╗██║████╗ ████║██╔════╝"
echo "      ██║██╔██╗ ██║██║   ██║██████╔╝██║██╔████╔██║█████╗  "
echo "      ██║██║╚██╗██║██║   ██║██╔══██╗██║██║╚██╔╝██║██╔══╝  "
echo "      ██║██║ ╚████║╚██████╔╝██║  ██║██║██║ ╚═╝ ██║███████╗"
echo "      ╚═╝╚═╝  ╚═══╝ ╚═════╝ ╚═╝  ╚═╝╚═╝╚═╝     ╚═╝╚══════╝"
echo ""
echo "======================================================================="
echo "        INICIANDO INSTALAÇÃO E CONFIGURAÇÃO DO AMBIENTE"
echo "======================================================================="


# Encerra o script imediatamente se um comando falhar
set -e

# --- Variáveis de Configuração ---
REPO_URL="https://github.com/davidsk8acdc/ino-cam.git"
BRANCH="10out"
PROJECT_DIR="$HOME/ino-cam"
VENV_DIR="$PROJECT_DIR/venv"
USER_NAME=$(whoami)

# --- PASSO 1: PREPARAÇÃO DO SISTEMA OPERACIONAL ---
echo -e "\n### PASSO 1: Preparando o Sistema Operacional... ###\n"

echo "[INFO] Atualizando a lista de pacotes e o sistema..."
sudo apt update && sudo apt upgrade -y

echo "[INFO] Instalando dependências de sistema (isso pode demorar)..."
sudo apt install -y supervisor build-essential cmake pkg-config libjpeg-dev libpng-dev libtiff-dev libwebp-dev libopenjp2-7-dev libavcodec-dev libavformat-dev libswscale-dev libv4l-dev libxvidcore-dev libx264-dev libgtk-3-dev libopenblas-dev libpango1.0-dev libgdk-pixbuf-xlib-2.0-dev libhdf5-dev gfortran python3-dev git ffmpeg

# --- PASSO 2: DOWNLOAD E CONFIGURAÇÃO DO PROJETO ---
echo -e "\n### PASSO 2: Baixando e configurando o projeto... ###\n"

if [ -d "$PROJECT_DIR" ]; then
    echo "[AVISO] O diretório do projeto '$PROJECT_DIR' já existe. Pulando o git clone."
else
    echo "[INFO] Baixando o código-fonte do Git (branch: $BRANCH)..."
    git clone -b "$BRANCH" "$REPO_URL" "$PROJECT_DIR"
fi

cd "$PROJECT_DIR"

echo "[INFO] Criando o ambiente virtual Python em '$VENV_DIR'..."
python3 -m venv venv

echo "[INFO] Instalando todas as bibliotecas Python (isso pode demorar)..."
"$VENV_DIR/bin/pip" install opencv-python face_recognition watchdog ultralytics requests setuptools

# --- PASSO 3: CONFIGURAÇÃO DO SUPERVISOR ---
echo -e "\n### PASSO 3: Configurando o Supervisor para gerenciar os scripts... ###\n"

echo "[INFO] Garantindo que o diretório de configuração do Supervisor existe..."
sudo mkdir -p /etc/supervisor/conf.d/

PYTHON_EXEC="$VENV_DIR/bin/python"

sudo tee /etc/supervisor/conf.d/ino-cam.conf > /dev/null <<EOF
[program:ino-cam-api]
command=$PYTHON_EXEC $PROJECT_DIR/ApiSend.py
directory=$PROJECT_DIR
user=$USER_NAME
autostart=true
autorestart=true
stdout_logfile=/dev/null
stderr_logfile=/dev/null

[program:ino-cam-gerenciar-rostos]
command=$PYTHON_EXEC $PROJECT_DIR/gerenciar_rostos.py
directory=$PROJECT_DIR
user=$USER_NAME
autostart=true
autorestart=true
stdout_logfile=/dev/null
stderr_logfile=/dev/null

[program:ino-cam-reconhecer]
command=$PYTHON_EXEC $PROJECT_DIR/reconhecer_rtsp.py
directory=$PROJECT_DIR
user=$USER_NAME
autostart=true
autorestart=true
stdout_logfile=/dev/null
stderr_logfile=/dev/null

[program:ino-cam-yolo]
command=$PYTHON_EXEC $PROJECT_DIR/YOLO.py
directory=$PROJECT_DIR
user=$USER_NAME
autostart=true
autorestart=true
stdout_logfile=/dev/null
stderr_logfile=/dev/null
EOF

echo "[INFO] Arquivo de configuração '/etc/supervisor/conf.d/ino-cam.conf' criado."

# --- PASSO 4: ATIVANDO OS SERVIÇOS E A INTERFACE WEB ---
echo -e "\n### PASSO 4: Ativando os serviços e a interface web... ###\n"

CONFIG_FILE="/etc/supervisor/supervisord.conf"

# Verifica se a seção [inet_http_server] já existe no arquivo
if ! grep -q "\[inet_http_server\]" "$CONFIG_FILE"; then
    echo "[INFO] Seção [inet_http_server] não encontrada. Adicionando com login e senha..."
    # Adiciona a configuração da interface web com credenciais no final do arquivo
    sudo tee -a "$CONFIG_FILE" > /dev/null <<EOF

[inet_http_server]
port=*:9001
username=admin
password=admin
EOF
else
    echo "[INFO] Seção [inet_http_server] já existe. Garantindo que está ativa..."
    # Garante que a porta está correta caso a seção já exista, mas comentada
    sudo sed -i 's/^;port=.*:9001/port=*:9001/' "$CONFIG_FILE"
fi

echo "[INFO] Habilitando e reiniciando o serviço do Supervisor para aplicar todas as mudanças..."
sudo systemctl enable supervisor
sudo systemctl restart supervisor

echo "[INFO] Aguardando 3 segundos para o serviço do Supervisor estabilizar..."
sleep 3

echo "[INFO] Recarregando a configuração dos scripts e garantindo que todos iniciem..."
sudo supervisorctl reread
sudo supervisorctl update
sudo supervisorctl start all

# --- MENSAGEM FINAL ---
echo "======================================================================="
echo ""
echo "      ██╗███╗   ██╗ ██████╗ ██████╗ ██╗███╗   ███╗███████╗"
echo "      ██║████╗  ██║██╔═══██╗██╔══██╗██║████╗ ████║██╔════╝"
echo "      ██║██╔██╗ ██║██║   ██║██████╔╝██║██╔████╔██║█████╗  "
echo "      ██║██║╚██╗██║██║   ██║██╔══██╗██║██║╚██╔╝██║██╔══╝  "
echo "      ██║██║ ╚████║╚██████╔╝██║  ██║██║██║ ╚═╝ ██║███████╗"
echo "      ╚═╝╚═╝  ╚═══╝ ╚═════╝ ╚═╝  ╚═╝╚═╝╚═╝     ╚═╝╚══════╝"
echo ""
echo "======================================================================="
echo "    INSTALAÇÃO E CONFIGURAÇÃO CONCLUÍDAS COM SUCESSO!"
echo "======================================================================="
echo ""
echo "O Supervisor agora está gerenciando os 4 scripts do projeto."
echo ""
echo "Para verificar o status pelo terminal, use o comando:"
echo "    sudo supervisorctl status"
echo ""
echo "A interface gráfica do Supervisor está acessível em:"
echo "    http://<ip-do-seu-raspberry-pi>:9001"
echo "    Usuário: admin"
echo "    Senha:   admin"
echo ""