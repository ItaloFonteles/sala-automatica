@echo off
REM Instala as bibliotecas do modo real (camera, microfone, OBS) e inicia.
cd /d "%~dp0"
if not exist .venv (
  echo Criando ambiente Python...
  py -m venv .venv
)
.venv\Scripts\python -m pip install --upgrade pip
.venv\Scripts\python -m pip install -r requirements.txt
if errorlevel 1 (
  echo.
  echo Falhou ao instalar. Se o erro fala de "Visual C++", instale o Python 3.13
  echo em python.org e rode de novo. Mande o print do erro se precisar de ajuda.
  pause
  exit /b 1
)
start "" /min cmd /c "timeout /t 3 >nul & start http://localhost:8080"
.venv\Scripts\python main.py
pause
