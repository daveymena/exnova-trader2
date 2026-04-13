#!/usr/bin/env python3
"""Verificar modelos disponibles en Ollama"""
import requests
import json

print("="*60)
print("VERIFICANDO ENDPOINTS DE OLLAMA")
print("="*60)

# Ollama Easypanel
print("\n1. Ollama Easypanel:")
try:
    r1 = requests.get('https://biblia-ollama.ginee6.easypanel.host/api/tags', timeout=5)
    if r1.status_code == 200:
        data = json.loads(r1.text)
        models = data.get('models', [])
        if models:
            print(f"   ✅ Disponible ({len(models)} modelos)")
            for m in models:
                print(f"      - {m['name']}")
        else:
            print("   ⚠️ Sin modelos instalados")
    else:
        print(f"   ❌ Error: {r1.status_code}")
except Exception as e:
    print(f"   ❌ Error: {e}")

# Ollama Local
print("\n2. Ollama Local:")
try:
    r2 = requests.get('http://localhost:11434/api/tags', timeout=2)
    if r2.status_code == 200:
        data = json.loads(r2.text)
        models = data.get('models', [])
        if models:
            print(f"   ✅ Disponible ({len(models)} modelos)")
            for m in models:
                print(f"      - {m['name']}")
        else:
            print("   ⚠️ Sin modelos instalados")
    else:
        print(f"   ❌ Error: {r2.status_code}")
except Exception as e:
    print(f"   ❌ Error: {e}")

print("\n" + "="*60)
print("RECOMENDACIÓN:")
print("="*60)
print("Usar el primer modelo disponible de la lista.")
print("El sistema de fallback probará en orden:")
print("  1. GitHub Models (gpt-4o-mini)")
print("  2. Ollama Easypanel (primer modelo disponible)")
print("  3. Ollama Local (primer modelo disponible)")
print("="*60)