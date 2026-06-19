@echo off
REM Mata todos los procesos de Python que ejecuten run.py
echo Apagando servidor...
taskkill /F /IM python.exe /T >nul 2>&1

REM Espera 3 segundos
timeout /t 3 /nobreak

REM Inicia el servidor
echo Iniciando servidor...
python run.py --web

pause
