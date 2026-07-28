import sys
import os

# Asegurar que la ruta base esté en sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from bot.brain.opencode_ai_client import OpenCodeAIClient

print("Iniciando prueba del cliente OpenCodeAIClient del bot hacia EasyPanel...")

client = OpenCodeAIClient()

# Probamos con un prompt que requiera análisis estructurado
test_prompt = "analizar mercado EURUSD, tendencia alcista, volumen alto. Indica si comprar o vender."
print(f"\nEnviando prompt al servidor en la nube de EasyPanel: '{test_prompt}'")

result = client.analyze_opportunity(test_prompt)

print("\n===========================================")
if result:
    print("¡RESPUESTA PROCESADA CON ÉXITO EN EL BOT!")
    print(f"Resultado recibido estructurado: {result}")
else:
    print("❌ Fallo en la llamada o el JSON devuelto no se pudo parsear.")
print("===========================================")
