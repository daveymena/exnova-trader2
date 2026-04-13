#!/usr/bin/env python3
"""
Script para remover TODOS los emojis de los archivos Python
Soluciona problemas de encoding en Windows PowerShell
"""
import os
import re
from pathlib import Path

def remove_emojis(text):
    """Elimina emojis del texto"""
    # Patrón para detectar emojis
    emoji_pattern = re.compile(
        "["
        "\U0001F600-\U0001F64F"  # emoticons
        "\U0001F300-\U0001F5FF"  # symbols & pictographs
        "\U0001F680-\U0001F6FF"  # transport & map symbols
        "\U0001F1E0-\U0001F1FF"  # flags (iOS)
        "\U00002702-\U000027B0"
        "\U000024C2-\U0001F251"
        "\U0001f926-\U0001f937"
        "\U00010000-\U0010ffff"
        "\u2640-\u2642"
        "\u2600-\u2B55"
        "\u200d"
        "\u23cf"
        "\u23e9"
        "\u231a"
        "\ufe0f"  # dingbats
        "\u3030"
        "]+"
    )
    return emoji_pattern.sub("", text)

def process_file(filepath):
    """Procesa un archivo y remueve emojis"""
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Detectar si hay emojis
        if re.search(r"[\U0001F600-\U0001F64F\U0001F300-\U0001F5FF\U0001F680-\U0001F6FF\U0001F1E0-\U0001F1FF\u2640-\u2642\u2600-\u2B55]", content):
            original_lines = content.count('\n')
            new_content = remove_emojis(content)
            
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(new_content)
            
            print(f"[OK] {filepath} - Emojis removidos")
            return True
        else:
            return False
    except Exception as e:
        print(f"[ERROR] {filepath}: {e}")
        return False

def main():
    print("=" * 80)
    print("[CLEANUP] Removiendo TODOS los emojis de archivos Python")
    print("=" * 80)
    
    # Archivos a procesar
    core_dir = Path("core")
    ai_dir = Path("ai")
    data_dir = Path("data")
    strategies_dir = Path("strategies")
    
    directories = [core_dir, ai_dir, data_dir, strategies_dir]
    
    total_files = 0
    cleaned_files = 0
    
    for directory in directories:
        if directory.exists():
            for py_file in directory.glob("*.py"):
                total_files += 1
                if process_file(py_file):
                    cleaned_files += 1
    
    # Procesar main files
    for main_file in Path(".").glob("main_*.py"):
        total_files += 1
        if process_file(main_file):
            cleaned_files += 1
    
    # Procesar scripts principales
    for script_file in ["run_bot_practice.py", "start_bot_simple.py"]:
        if Path(script_file).exists():
            total_files += 1
            if process_file(script_file):
                cleaned_files += 1
    
    print("\n" + "=" * 80)
    print(f"[RESULTADO] {cleaned_files}/{total_files} archivos procesados y limpiados")
    print("=" * 80)
    print("\n[INFO] Ahora puede ejecutar: python start_bot_simple.py")

if __name__ == "__main__":
    main()
