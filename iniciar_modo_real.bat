@echo off
REM Inicia a Sala Automatica no modo real (camera, microfone, OBS).
REM Na primeira vez, rode antes o preparar_python.bat.
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  echo Ambiente ainda nao preparado. Rodando preparar_python.bat...
  call preparar_python.bat
  if errorlevel 1 exit /b 1
)
start "" /min cmd /c "timeout /t 3 >nul & start http://localhost:8080"
.venv\Scripts\python main.py
pause
