# -*- coding: utf-8 -*-

#1.0 [DAVID H.] - 10-10-25

import face_recognition
import pickle
import os
import time
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

# --- CONFIGURACOES ---
DATASET_PATH = 'fotos'
ENCODINGS_FILE = 'pesos/encodings.pickle'
DEBOUNCE_SECONDS = 5.0

last_sync_time = 0

def sincronizar_banco_de_dados():
    global last_sync_time
    if time.time() - last_sync_time < DEBOUNCE_SECONDS:
        return
    
    print("\n[SYNC] Mudanca detectada no sistema de arquivos. Iniciando sincronizacao...")
    
    try:
        with open(ENCODINGS_FILE, 'rb') as f: data = pickle.load(f)
    except FileNotFoundError: data = {}

    mudanca_detectada = False
    pessoas_no_disco = {p for p in os.listdir(DATASET_PATH) if os.path.isdir(os.path.join(DATASET_PATH, p))}
    pessoas_no_pickle = set(data.keys())

    # (L�gica de remo��o de pessoas continua a mesma)
    pessoas_para_remover = pessoas_no_pickle - pessoas_no_disco
    if pessoas_para_remover:
        print(f"[SYNC] Removendo {len(pessoas_para_remover)} pessoa(s): {', '.join(pessoas_para_remover)}")
        for pessoa in pessoas_para_remover: del data[pessoa]
        mudanca_detectada = True

    for person_name in pessoas_no_disco:
        person_folder = os.path.join(DATASET_PATH, person_name)
        if person_name not in data:
            print(f"[SYNC] Nova pessoa detectada: {person_name}")
            data[person_name] = {"source_files": [], "encodings": []}
        
        imagens_processadas = set(data[person_name]["source_files"])
        imagens_no_disco = set(os.listdir(person_folder))

        # (L�gica de remo��o de fotos individuais continua a mesma)
        imagens_para_remover = imagens_processadas - imagens_no_disco
        if imagens_para_remover:
            print(f"[SYNC] Removendo {len(imagens_para_remover)} foto(s) de {person_name}: {', '.join(imagens_para_remover)}")
            novos_arquivos, novos_encodings = [], []
            for filename, encoding in zip(data[person_name]["source_files"], data[person_name]["encodings"]):
                if filename not in imagens_para_remover:
                    novos_arquivos.append(filename); novos_encodings.append(encoding)
            data[person_name]["source_files"] = novos_arquivos
            data[person_name]["encodings"] = novos_encodings
            mudanca_detectada = True

        imagens_para_adicionar = imagens_no_disco - imagens_processadas
        if imagens_para_adicionar:
            print(f"[SYNC] Encontradas {len(imagens_para_adicionar)} nova(s) foto(s) para {person_name}.")
            for image_name in imagens_para_adicionar:
                image_path = os.path.join(person_folder, image_name)
                
                # --- NOVA VERIFICA��O DE ESTABILIDADE DO ARQUIVO ---
                try:
                    last_size = -1
                    is_stable = False
                    # Espera ate o tamanho do arquivo parar de mudar
                    while not is_stable:
                        current_size = os.path.getsize(image_path)
                        if current_size == last_size and current_size > 0:
                            is_stable = True
                        else:
                            last_size = current_size
                            print(f"    - Arquivo '{image_name}' ainda esta sendo copiado ({current_size} bytes). Aguardando...")
                            time.sleep(1.0) # Espera 1 segundo antes de verificar de novo

                    print(f"    - Arquivo '{image_name}' estavel. Processando...")
                    image = face_recognition.load_image_file(image_path)
                    boxes = face_recognition.face_locations(image, model='hog')
                    encodings = face_recognition.face_encodings(image, boxes)
                    
                    if not encodings:
                        print(f"    [AVISO] Nenhum rosto encontrado em '{image_name}'. Pulando.")
                        continue
                        
                    for encoding in encodings:
                        data[person_name]["encodings"].append(encoding)
                        data[person_name]["source_files"].append(image_name)
                    mudanca_detectada = True
                except Exception as e:
                    print(f"    [ERRO] Nao foi possivel processar {image_path}: {type(e).__name__} - {e}")
    
    if mudanca_detectada:
        print("[SYNC] Salvando o banco de dados atualizado...")
        temp_file = ENCODINGS_FILE + ".tmp"
        with open(temp_file, "wb") as f: f.write(pickle.dumps(data))
        os.rename(temp_file, ENCODINGS_FILE)
        print("[SYNC] Banco de dados salvo com sucesso.")
    else:
        print("[SYNC] Nenhuma mudanca necessaria no banco de dados.")
        
    last_sync_time = time.time()

# (O resto do script com o MyEventHandler e o Observer continua o mesmo)
class MyEventHandler(FileSystemEventHandler):
    def on_any_event(self, event):
        sincronizar_banco_de_dados()

if __name__ == "__main__":
    print("[INFO] Servico de gerenciamento de rostos iniciado com Watchdog.")
    sincronizar_banco_de_dados()
    event_handler = MyEventHandler()
    observer = Observer()
    observer.schedule(event_handler, path=DATASET_PATH, recursive=True)
    observer.start()
    print(f"[INFO] Vigiando a pasta '{DATASET_PATH}' por mudancas...")
    print("[INFO] Pressione Ctrl+C para encerrar.")
    try:
        while True: time.sleep(1)
    except KeyboardInterrupt:
        print("\n[INFO] Servico encerrado pelo usuario.")
    finally:
        observer.stop()
        observer.join()