#!/usr/bin/env python3
"""
🛑 EMERGENCY STOP - Mata todo y limpia
"""
import os
import sys
import glob

print("🛑 EMERGENCY STOP")
print("="*50)

# 1. Kill all Python processes related to bot
print("\n[1] Killing bot processes...")
os.system("pkill -9 -f 'bot_con_ia.py' 2>/dev/null")
os.system("pkill -9 -f 'python.*bot.*\.py' 2>/dev/null")
os.system("pkill -9 -f 'python.*trading' 2>/dev/null")
print("   ✓ Processes killed")

# 2. Remove ALL lock files
print("\n[2] Cleaning lock files...")
lock_files = [
    "/tmp/bot.lock",
    "/tmp/bot.pid",
    "bot.lock",
    "data/ai_learning/operation.lock",
    "data/EMERGENCY_STOP"
]

for f in lock_files:
    try:
        if os.path.exists(f):
            os.remove(f)
            print(f"   ✓ Removed: {f}")
    except:
        pass

# 3. Find and remove all operation locks
print("\n[3] Searching for lock files...")
for root, dirs, files in os.walk('.'):
    for file in files:
        if 'lock' in file.lower() or file.endswith('.pid'):
            filepath = os.path.join(root, file)
            try:
                os.remove(filepath)
                print(f"   ✓ Removed: {filepath}")
            except:
                pass

print("\n" + "="*50)
print("✅ ALL OPERATIONS STOPPED")
print("="*50)
print("\n⚠️  Check your Exnova account manually")
print("    for any open trades!")
