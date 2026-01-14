# -*- coding: utf-8 -*-

import asyncio
from bleak import BleakScanner

# UUID do servico SPS (Nao estamos usando para o scan geral, mas deixei aqui)
SPS_SERVICE_UUID = "0783b03e-8535-b5a0-7140-a304d2495cb7"

async def main():
    # Vamos mudar a mensagem para refletir o que estamos fazendo
    print("Procurando por TODOS os dispositivos BLE proximos...")
    
    # Faz o scan sem filtro de UUID
    devices = await BleakScanner.discover()
    
    if not devices:
        print("Nenhum dispositivo encontrado.")
        return

    print(f"Dispositivos encontrados ({len(devices)}):")
    for device in devices:
        print(f"  - Endereco (Address): {device.address}")
        print(f"  - Nome (Name): {device.name}")
        # A linha abaixo foi removida para evitar o 'AttributeError'
        # print(f"  - RSSI: {device.rssi} dBm")
        print("-" * 20)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nScan interrompido pelo usuario.")