#!/usr/bin/env python3
"""
VERIFICADOR DE BOTS - Muestra todos los bots disponibles
"""
import os
import sys
from pathlib import Path
from datetime import datetime

def main():
    print("\n" + "="*80)
    print("VERIFICADOR DE BOTS DISPONIBLES")
    print("="*80)
    
    # Directorio actual
    current_dir = Path(".")
    
    # Buscar todos los archivos bot_*.py
    bots = list(current_dir.glob("bot_*.py"))
    
    if not bots:
        print("\n❌ No se encontraron bots")
        return
    
    print(f"\nSe encontraron {len(bots)} bots:\n")
    
    # Mostrar información de cada bot
    for i, bot in enumerate(bots, 1):
        stat = bot.stat()
        size_kb = stat.st_size / 1024
        modified = datetime.fromtimestamp(stat.st_mtime).strftime('%Y-%m-%d %H:%M:%S')
        
        # Leer primeras líneas para identificar
        try:
            with open(bot, 'r', encoding='utf-8') as f:
                first_lines = ''.join([f.readline() for _ in range(10)])
        except:
            first_lines = ""
        
        # Identificar tipo de bot
        if "VERSIÓN CORREGIDA" in first_lines or "cooldown" in first_lines.lower():
            tipo = "✅ CORREGIDO (RECOMENDADO)"
            color = "green"
        elif "APRENDIZAJE PROGRESIVO" in first_lines:
            tipo = "⚠️ CON IA (SIN COOLDOWN)"
            color = "yellow"
        elif "DETECTOR DE CONTEXTO" in first_lines:
            tipo = "⚠️ SOLO CONTEXTO"
            color = "yellow"
        else:
            tipo = "❌ ORIGINAL (NO RECOMENDADO)"
            color = "red"
        
        print(f"{i}. {bot.name}")
        print(f"   Tipo: {tipo}")
        print(f"   Tamaño: {size_kb:.1f} KB")
        print(f"   Modificado: {modified}")
        print()
    
    # Mostrar bot recomendado
    print("="*80)
    print("RECOMENDACIÓN:")
    print("="*80)
    print("\n✅ Ejecutar: python bot_con_ia_corregido.py")
    print("\nO usar el iniciador seguro:")
    print("   python iniciar_bot.py")
    print("\n" + "="*80)
    
    # Verificar si hay bots corriendo
    print("\nVERIFICANDO BOTS ACTIVOS:")
    print("="*80)
    
    try:
        import subprocess
        result = subprocess.run(['tasklist', '/FI', 'IMAGENAME eq python.exe'], 
                              capture_output=True, text=True, timeout=5)
        
        lines = result.stdout.strip().split('\n')
        python_processes = [l for l in lines if 'python.exe' in l.lower()]
        
        if python_processes:
            print(f"\n⚠️ HAY {len(python_processes)} PROCESOS PYTHON CORRIENDO:")
            for proc in python_processes:
                print(f"   {proc}")
            print("\n   Para detener todos:")
            print("   taskkill /F /IM python.exe")
        else:
            print("\n✅ No hay procesos Python corriendo")
        
    except Exception as e:
        print(f"\n❌ Error verificando procesos: {e}")
    
    print("\n" + "="*80)

if __name__ == "__main__":
    main()