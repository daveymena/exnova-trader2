#!/usr/bin/env python3
"""
STOP LOCAL BOT - Windows/Linux/Mac
"""
import os
import sys
import subprocess
import glob
from pathlib import Path

print("\n" + "="*60)
print("STOPPING LOCAL BOT")
print("="*60)

# 1. Kill Python processes
print("\n[1] Stopping bot processes...")

system = sys.platform

if system == 'win32':
    # Windows
    try:
        subprocess.run(['taskkill', '/F', '/IM', 'python.exe'], capture_output=True)
        print("   OK: python.exe stopped")
    except:
        pass
    try:
        subprocess.run(['taskkill', '/F', '/IM', 'pythonw.exe'], capture_output=True)
        print("   OK: pythonw.exe stopped")
    except:
        pass
else:
    # Linux/Mac
    try:
        subprocess.run(['pkill', '-f', 'bot_con_ia.py'], capture_output=True)
        print("   OK: bot_con_ia.py stopped")
    except:
        pass
    try:
        subprocess.run(['pkill', '-9', 'python'], capture_output=True)
        print("   OK: python stopped")
    except:
        pass

# 2. Clean lock files
print("\n[2] Cleaning lock files...")

lock_paths = [
    "data/ai_learning/operation.lock",
    "data/locks/operation.lock",
    "bot.lock",
    "/tmp/bot.lock",
    "/tmp/bot.pid",
    "data/EMERGENCY_STOP"
]

for lock_path in lock_paths:
    try:
        if os.path.exists(lock_path):
            os.remove(lock_path)
            print(f"   OK: Removed {lock_path}")
    except Exception as e:
        print(f"   WARN: Could not remove {lock_path}")

# 3. Find and remove any .lock files
print("\n[3] Searching for additional .lock files...")
for lock_file in glob.glob("**/*.lock", recursive=True):
    try:
        os.remove(lock_file)
        print(f"   OK: Removed {lock_file}")
    except:
        pass

# 4. Create stop signal
print("\n[4] Creating STOP signal...")
os.makedirs("data", exist_ok=True)
with open("data/EMERGENCY_STOP", "w") as f:
    f.write("STOPPED")
print("   OK: Created data/EMERGENCY_STOP")

print("\n" + "="*60)
print("LOCAL BOT STOPPED")
print("="*60)
print("\nIMPORTANT:")
print("   If there are OPEN trades on Exnova,")
print("   close them manually at: https://app.exnova.com")
print("="*60)
