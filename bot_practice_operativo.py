#!/usr/bin/env python3
"""
🚀 BOT EN VIVO PRACTICE - Operativo 24/7 SIN RESTRICCIONES
"""

import subprocess
import sys
from pathlib import Path

bot_path = Path(__file__).parent / "bot_final.py"

subprocess.run([sys.executable, str(bot_path)])
