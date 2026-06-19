@echo off
REM Mata procesos de Python
echo [1/4] Matando procesos Python...
taskkill /F /IM python.exe /T >nul 2>&1

REM Mata el puerto 8080 si está en uso
echo [2/4] Liberando puerto 8080...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr :8080') do (
    taskkill /PID %%a /F >nul 2>&1
)

REM Espera
echo [3/4] Esperando...
timeout /t 3 /nobreak

REM Inicia el servidor
echo [4/4] Iniciando servidor...
python run.py --web

pause
