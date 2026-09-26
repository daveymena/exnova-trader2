"""Bucle de mejora - MINIMAL (evita crashes)
El Cerebro funciona sin auto-mejora IA hasta Ollama disponible
"""
import time
import logging

log = logging.getLogger("improvement_loop")

def main():
    log.info("[improvement] Bucle DESHABILITADO - Ollama detectado")
    log.info("[improvement] Cerebro funciona en modo BASICO sin auto-mejora IA")
    log.info("[improvement] Para auto-mejora: configura OPENCODE_API_KEY")

    while True:
        time.sleep(60)

if __name__ == "__main__":
    main()
