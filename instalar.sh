#!/bin/bash

# =======================================================================
#               SCRIPT DE INSTALAÇÃO E CONFIGURAÇÃO DO PROJETO
# =======================================================================
# Autor: Gemini & David
# Versão: 7.0 - Modelo Simplificado: Instala, Configura e Reinicia.
# Este script prepara todo o ambiente e, ao final, reinicia o sistema
# para que todos os serviços iniciem corretamente.
# =======================================================================

# --- BANNER INICIAL ---
echo "============================================================================="
echo ""
echo "      ¦¦+¦¦¦+   ¦¦+ ¦¦¦¦¦¦+ ¦¦¦¦¦¦+ ¦¦¦¦¦¦+ ¦¦+¦¦¦+   ¦¦¦+¦¦¦¦¦¦¦+"
echo "      ¦¦¦¦¦¦¦+  ¦¦¦¦¦+---¦¦+¦¦+--¦¦+¦¦+--¦¦+¦¦¦¦¦¦¦+ ¦¦¦¦¦¦¦+----+"
echo "      ¦¦¦¦¦+¦¦+ ¦¦¦¦¦¦   ¦¦¦¦¦¦¦¦¦++¦¦¦¦¦¦++¦¦¦¦¦+¦¦¦¦+¦¦¦¦¦¦¦¦+  "
echo "      ¦¦¦¦¦¦+¦¦+¦¦¦¦¦¦   ¦¦¦¦¦+----+¦¦+--¦¦+¦¦¦¦¦¦+¦¦++¦¦¦¦¦+--+  "
echo "      ¦¦¦¦¦¦ +¦¦¦¦¦+¦¦¦¦¦¦++¦¦¦     ¦¦¦  ¦¦¦¦¦¦¦¦¦ +-+ ¦¦¦¦¦¦¦¦¦¦+"
echo "      +-++-+  +---+ +-----+ +-+     +-+  +-++-++-+     +-++------+"
echo ""
echo "============================================================================="
echo "           INICIANDO INSTALAÇÃO E CONFIGURAÇÃO DO AMBIENTE"
echo "============================================================================="


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
echo -e "\n### PASSO 3: Configurando o Supervisor... ###\n"

echo "[INFO] Garantindo que o diretório de configuração do Supervisor existe..."
sudo mkdir -p /etc/supervisor/conf.d/

PYTHON_EXEC="$VENV_DIR/bin/python"

# Cria o arquivo de configuração com inicialização ordenada
sudo tee /etc/supervisor/conf.d/ino-cam.conf > /dev/null <<EOF
[program:gerenciar_rostos]
command=$PYTHON_EXEC $PROJECT_DIR/gerenciar_rostos.py
directory=$PROJECT_DIR
user=$USER_NAME
autostart=true
autorestart=true
priority=100
stdout_logfile=/dev/null
stderr_logfile=/dev/null

[program:apisend]
command=bash -c "sleep 10 && $PYTHON_EXEC $PROJECT_DIR/ApiSend.py"
directory=$PROJECT_DIR
user=$USER_NAME
autostart=true
autorestart=true
priority=200
stdout_logfile=/dev/null
stderr_logfile=/dev/null

[program:reconhecer_rtsp]
command=$PYTHON_EXEC $PROJECT_DIR/reconhecer_rtsp.py
directory=$PROJECT_DIR
user=$USER_NAME
autostart=true
autorestart=true
priority=300
stdout_logfile=/dev/null
stderr_logfile=/dev/null

[program:yolo]
command=$PYTHON_EXEC $PROJECT_DIR/YOLO.py
directory=$PROJECT_DIR
user=$USER_NAME
autostart=true
autorestart=true
priority=300
stdout_logfile=/dev/null
stderr_logfile=/dev/null
EOF

echo "[INFO] Arquivo de configuração '/etc/supervisor/conf.d/ino-cam.conf' criado."

echo "[INFO] Ativando a interface web do Supervisor com login admin/admin..."
CONFIG_FILE="/etc/supervisor/supervisord.conf"

if ! grep -q "\[inet_http_server\]" "$CONFIG_FILE"; then
    sudo tee -a "$CONFIG_FILE" > /dev/null <<EOF

[inet_http_server]
port=*:9001
username=admin
password=admin
EOF
fi

# --- PASSO 4: FINALIZAÇÃO ---
echo -e "\n### PASSO 4: Finalizando a configuração... ###\n"

echo "[INFO] Configurando o fuso horário para America/Sao_Paulo..."
sudo timedatectl set-timezone America/Sao_Paulo

echo "[INFO] Habilitando o serviço do Supervisor para iniciar no próximo boot..."
sudo systemctl enable supervisor

# --- MENSAGEM FINAL ---
echo "============================================================================="
echo ""
echo "      ¦¦+¦¦¦+   ¦¦+ ¦¦¦¦¦¦+ ¦¦¦¦¦¦+ ¦¦¦¦¦¦+ ¦¦+¦¦¦+   ¦¦¦+¦¦¦¦¦¦¦+"
echo "      ¦¦¦¦¦¦¦+  ¦¦¦¦¦+---¦¦+¦¦+--¦¦+¦¦+--¦¦+¦¦¦¦¦¦¦+ ¦¦¦¦¦¦¦+----+"
echo "      ¦¦¦¦¦+¦¦+ ¦¦¦¦¦¦   ¦¦¦¦¦¦¦¦¦++¦¦¦¦¦¦++¦¦¦¦¦+¦¦¦¦+¦¦¦¦¦¦¦¦+  "
echo "      ¦¦¦¦¦¦+¦¦+¦¦¦¦¦¦   ¦¦¦¦¦+----+¦¦+--¦¦+¦¦¦¦¦¦+¦¦++¦¦¦¦¦+--+  "
echo "      ¦¦¦¦¦¦ +¦¦¦¦¦+¦¦¦¦¦¦++¦¦¦     ¦¦¦  ¦¦¦¦¦¦¦¦¦ +-+ ¦¦¦¦¦¦¦¦¦¦+"
echo "      +-++-+  +---+ +-----+ +-+     +-+  +-++-++-+     +-++------+"
echo ""
echo "======================================================================="
echo "    INSTALAÇÃO E CONFIGURAÇÃO CONCLUÍDAS COM SUCESSO!"
echo "======================================================================="
echo ""
echo "O sistema será reiniciado em 5 segundos para aplicar todas as configurações."
echo "Após o reboot, seus scripts serão iniciados automaticamente."
echo ""
sleep 5
sudo reboot
sudo reboot