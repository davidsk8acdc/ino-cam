# -*- coding: utf-8 -*-

import asyncio
from bleak import BleakClient, BleakScanner, BleakError
import struct
from datetime import datetime

DEVICE_NAME = "GS7X 862311067401446"
SERVER_TX_UUID = "0783b03e-8535-b5a0-7140-a304d2495cb8"

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
    0x90: 4, 0xC0: 4, 0xC1: 4, 0xC2: 4, 0xC3: 4, 0xC4: 1, 0xC5: 1,
    0xC6: 1, 0xC7: 1, 0xC8: 1, 0xC9: 1, 0xCA: 1, 0xCB: 1, 0xCC: 1,
    0xCD: 1, 0xCE: 1, 0xCF: 1, 0xD0: 1, 0xD1: 1, 0xD2: 1,
    0xD3: 4, 0xD4: 4, 0xD5: 1, 0xD6: 2, 0xD7: 2, 0xD8: 2, 0xD9: 2,
    0xDA: 2, 0xDB: 4, 0xDC: 4, 0xDD: 4, 0xDE: 4, 0xDF: 4,
    0xE2: 4, 0xE3: 4, 0xE4: 4, 0xE5: 4, 0xE6: 4, 0xE7: 4, 0xE8: 4,
    0x47: 4, 0x5D: 3, 0xEB: 2, 0x48: 2, 0x49: 1, 0x11: 4, 0x36: 1,
    0x5B: -1, 0x5C: -1, 0xE9: -1, 0xEA: -1, 0xFE: -1
}

packet_buffer = bytearray()

# Funcao separada para processar um pacote COMPLETO
def parse_packet(data: bytearray):
    # 'data' aqui inclui o wrapper 41a4...
    print(f"PROCESSANDO PACOTE COMPLETO: {data.hex()}")
    
    # 1. Remove o wrapper
    dados_filtrados = data[4:]
    
    if not dados_filtrados or dados_filtrados[0] != 0x01:
        print("[ERRO PARSE]: Pacote completo nao comeca com 0x01 (apos wrapper)")
        return

    try:
        # 2. Le o tamanho do payload (L)
        L_com_flag = struct.unpack('<H', dados_filtrados[1:3])[0]
        L_payload = L_com_flag & 0x7FFF
        
        # 3. Valida o tamanho total
        # O pacote filtrado (sem wrapper) deve ter:
        # 1 (header 01) + 2 (tamanho) + L_payload + 2 (checksum)
        expected_galileo_len = 5 + L_payload
        
        if len(dados_filtrados) != expected_galileo_len:
            print(f"[ERRO PARSE]: Tamanho do pacote (sem wrapper) inconsistente.")
            print(f"Esperado={expected_galileo_len}, Recebido={len(dados_filtrados)}")
            return

        # 4. Extrai o payload e o checksum
        payload = dados_filtrados[3 : 3 + L_payload]
        checksum_start = 3 + L_payload
        checksum = dados_filtrados[checksum_start : checksum_start + 2]

        parsed_data = {}
        index = 0
        
        while index < len(payload):
            tag = payload[index]
            index += 1
            
            data_size = -1
            
            if tag in TAG_SIZES:
                data_size = TAG_SIZES[tag]
            
            if data_size == -1:
                print(f"[WARN PARSE]: Tag desconhecida {hex(tag)}, parando o parse.")
                break

            if index + data_size > len(payload):
                print(f"[WARN PARSE]: Fim inesperado do payload ao ler tag {hex(tag)}.")
                break
                
            tag_data = payload[index : index + data_size]

            if tag == 0x20:
                timestamp_unix = struct.unpack('<I', tag_data)[0]
                parsed_data["timestamp"] = datetime.fromtimestamp(timestamp_unix).strftime('%Y-%m-%d %H:%M:%S')
            
            elif tag == 0x30:
                lat_raw = struct.unpack('<i', tag_data[1:5])[0]
                parsed_data["latitude"] = lat_raw / 1000000.0
                lon_raw = struct.unpack('<i', tag_data[5:9])[0]
                parsed_data["longitude"] = lon_raw / 1000000.0

            elif tag == 0x33:
                spd_raw = struct.unpack('<H', tag_data[0:2])[0]
                parsed_data["velocidade"] = spd_raw / 10.0

            elif tag == 0xE3:
                parsed_data["user_tag_1"] = struct.unpack('<I', tag_data)[0]

            
            index += data_size
        
        if parsed_data:
            print("--- DADOS DO GPS ---")
            print(f"Data/Hora: {parsed_data.get('timestamp', 'N/A')}")
            print(f"Latitude: {parsed_data.get('latitude', 'N/A')}")
            print(f"Longitude: {parsed_data.get('longitude', 'N/A')}")
            print(f"Velocidade: {parsed_data.get('velocidade', 'N/A')} km/h")
            print(f"User Tag 1: {parsed_data.get('user_tag_1', 'N/A')}")
            print(f"Checksum: {checksum.hex()}")
            print("----------------------")

    except Exception as e:
        print(f"[ERRO PARSE]: Erro ao decodificar: {e}")
        print(f"[ERRO PARSE]: Dados brutos (do pacote completo): {data.hex(' ')}")


# Este handler agora apenas gerencia o buffer de remontagem
def notification_handler(sender_handle: int, data: bytearray):
    global packet_buffer
    
    if not data:
        print("DADO BRUTO RECEBIDO: (Vazio)")
        return
        
    packet_buffer.extend(data)
    print(f"DADO BRUTO RECEBIDO: {data.hex()}")
    
    # Tenta processar pacotes enquanto houver dados no buffer
    while True:
        # 1. Procura o inicio do nosso pacote (o wrapper)
        start_index = packet_buffer.find(b'\x41\xa4\x12\x21')
        
        if start_index == -1:
            # Nao achou o inicio, espera mais dados
            if len(packet_buffer) > 1024:
                 print("[WARN BUFFER]: Buffer grande sem marcador, limpando.")
                 packet_buffer.clear()
            break # Sai do 'while True' e espera a proxima notificacao
            
        if start_index > 0:
            # Descarta dados invalidos no inicio do buffer
            print(f"[INFO BUFFER]: Descartando {start_index} bytes invalidos do inicio.")
            packet_buffer = packet_buffer[start_index:]
        
        # 2. Temos o '41a41221'. Precisamos de pelo menos 7 bytes
        # para ler o tamanho do pacote Galileosky
        # 4 (wrapper) + 1 (header 01) + 2 (tamanho) = 7 bytes
        if len(packet_buffer) < 7:
            break # Nao tem o cabecalho completo, espera mais dados
            
        # 3. Checa o marcador 0x01
        if packet_buffer[4] != 0x01:
            print(f"[WARN BUFFER]: Encontrado 41a41221, mas marcador 0x01 ausente. Byte 4 e {hex(packet_buffer[4])}. Descartando.")
            packet_buffer = packet_buffer[1:] # Descarta o '41' falso
            continue # Volta ao inicio do 'while True'

        # 4. Se chegou aqui, temos um 41a4122101. Vamos ler o tamanho.
        try:
            L_com_flag = struct.unpack('<H', packet_buffer[5:7])[0]
            L_payload = L_com_flag & 0x7FFF
            
            # --- A LOGICA CORRETA ---
            # Tamanho total = 4 (wrapper) + 1 (header) + 2 (tamanho) + L_payload + 2 (checksum)
            total_packet_len = 9 + L_payload
            
            # 5. Checa se o pacote completo esta no buffer
            if len(packet_buffer) < total_packet_len:
                # Pacote incompleto, espera mais dados
                break # Sai do 'while True' e espera a proxima notificacao
                
            # 6. Temos um pacote completo!
            full_packet_data = packet_buffer[:total_packet_len]
            
            # 7. Remove o pacote do buffer
            packet_buffer = packet_buffer[total_packet_len:]
            
            # 8. Envia o pacote completo (com wrapper) para o parser
            parse_packet(full_packet_data)
            
        except Exception as e:
            print(f"[ERRO BUFFER]: Erro na logica do buffer: {e}. Resetando buffer.")
            packet_buffer.clear()
            break

async def main_loop(name_to_find):
    while True:
        print(f"Procurando dispositivo pelo NOME: '{name_to_find}'...")
        device = None
        
        try:
            device = await BleakScanner.find_device_by_name(name_to_find, timeout=10.0)
            
            if not device:
                print(f"Dispositivo com nome '{name_to_find}' nao encontrado. Tentando novamente em 10s...")
                await asyncio.sleep(10)
                continue

            print(f"Dispositivo encontrado! (Endereco: {device.address}) Conectando...")

            async with BleakClient(device) as client:
                print(f"Conectado com sucesso!")
                
                await client.start_notify(SERVER_TX_UUID, notification_handler)
                print("Inscrito para notificacoes. Ouvindo...")

                while client.is_connected:
                    await asyncio.sleep(1)

        except BleakError as e:
            print(f"Erro de Conexao (BleakError): {e}")
            
        except Exception as e:
            print(f"Erro inesperado: {e}")
            
        print("Desconectado.")
        print("Tentando reconectar em 5 segundos...")
        await asyncio.sleep(5)


if __name__ == "__main__":
    try:
        asyncio.run(main_loop(DEVICE_NAME))
    except KeyboardInterrupt:
        print("\nScript interrompido pelo usuario (Ctrl+C).")