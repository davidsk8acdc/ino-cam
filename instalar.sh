#!/bin/bash

# Script de instalação do projeto INO-CAM (Versão de Instalação Manual e Otimizada)
# Este script prepara o ambiente, mas não executa nem configura serviços.

# Encerra o script imediatamente se um comando falhar
set -e

# --- Variáveis de Configuração ---
REPO_URL="https://github.com/davidsk8acdc/ino-cam.git"
BRANCH="10out"
PROJECT_DIR="$HOME/ino-cam"
VENV_DIR="$PROJECT_DIR/venv"

echo "======================================================="
echo "  INICIANDO INSTALAÇÃO DO AMBIENTE INO-CAM"
echo "======================================================="

# --- PASSO 1: PREPARAÇÃO DO SISTEMA OPERACIONAL ---
echo -e "\n### PASSO 1: Preparando o Sistema Operacional... ###\n"

echo "[INFO] Atualizando a lista de pacotes e o sistema..."
sudo apt update && sudo apt upgrade -y

echo "[INFO] Instalando dependências de sistema (isso pode demorar)..."
sudo apt install -y build-essential cmake pkg-config libjpeg-dev libpng-dev libtiff-dev libwebp-dev libopenjp2-7-dev libavcodec-dev libavformat-dev libswscale-dev libv4l-dev libxvidcore-dev libx264-dev libgtk-3-dev libopenblas-dev libpango1.0-dev libgdk-pixbuf-xlib-2.0-dev libhdf5-dev gfortran python3-dev git ffmpeg

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

echo "[INFO] Instalando todas as bibliotecas Python necessárias (isso pode demorar)..."
# --- LINHA ATUALIZADA COM TODOS OS PACOTES NECESSÁRIOS ---
"$VENV_DIR/bin/pip" install opencv-python face_recognition watchdog ultralytics requests setuptools


echo "======================================================="
echo "    INSTALAÇÃO DO AMBIENTE CONCLUÍDA COM SUCESSO!"
echo "======================================================="
echo "O ambiente está pronto. Nenhum programa foi executado ou configurado para iniciar automaticamente."
echo ""
echo "Para usar o projeto, siga os passos abaixo:"
echo "1. Navegue até o diretório do projeto:"
echo "   cd ~/ino-cam"
echo ""
echo "2. Ative o ambiente virtual:"
echo "   source venv/bin/activate"
echo ""
echo "3. Execute os scripts manualmente conforme a necessidade:"
echo "   - Para criar/atualizar o banco de dados de rostos:"
echo "     python gerenciar_rostos.py"
echo ""
echo "   - Para iniciar o reconhecimento facial:"
echo "     python reconhecer_rtsp.py"
echo ""
echo "   - Para iniciar a detecção com YOLO:"
echo "     python YOLO.py"
echo ""