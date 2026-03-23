#!/usr/bin/env python3
"""🚀 BOT EN VIVO PRACTICE - Operativo 24/7"""
import subprocess, sys
from pathlib import Path
bot_path = Path(__file__).parent / "bot_operando.py"
subprocess.run([sys.executable, str(bot_path)])
