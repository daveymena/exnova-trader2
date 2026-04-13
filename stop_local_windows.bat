@echo off
chcp 65001 >nul
cls
echo ================================================
echo 🛑 DETENIENDO BOT LOCAL (WINDOWS)
echo ================================================
echo.

REM 1. Buscar y matar procesos de Python relacionados con el bot
echo [1] Buscando procesos del bot...
taskkill /F /FI "IMAGENAME eq python.exe" /FI "WINDOWTITLE *bot*" 2>nul
taskkill /F /FI "IMAGENAME eq python.exe" 2>nul

REM 2. Buscar específicamente bot_con_ia.py
echo [2] Deteniendo bot_con_ia.py...
for /f "tokens=2" %%a in ('tasklist ^| findstr python') do (
    taskkill /PID %%a /F 2>nul
)

echo.
echo ================================================
echo [3] Limpiando archivos lock...
echo ================================================

REM Eliminar locks
if exist "data\ai_learning\operation.lock" (
    del /Q "data\ai_learning\operation.lock"
    echo    ✓ Eliminado: data\ai_learning\operation.lock
)

if exist "bot.lock" (
    del /Q "bot.lock"
    echo    ✓ Eliminado: bot.lock
)

if exist "data\locks\operation.lock" (
    del /Q "data\locks\operation.lock"
    echo    ✓ Eliminado: data\locks\operation.lock
)

REM Crear señal de stop
if not exist "data" mkdir data
echo STOPPED > data\EMERGENCY_STOP
echo    ✓ Creado: data\EMERGENCY_STOP

echo.
echo ================================================
echo ✅ BOT LOCAL DETENIDO
echo ================================================
echo.
echo Verificando procesos restantes...
tasklist | findstr python
echo.
echo Si ves procesos de Python arriba, ejecuta manualmente:
echo    taskkill /F /IM python.exe
echo.
pause
