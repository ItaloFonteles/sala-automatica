@echo off
REM Testa a Sala Automatica sem equipamento (modo simulacao)
cd /d "%~dp0"
if not exist .venv (
  echo Criando ambiente Python...
  py -m venv .venv
  .venv\Scripts\python -m pip install -r requirements.txt
)
start "" /min cmd /c "timeout /t 5 >nul & start http://localhost:8080"
.venv\Scripts\python main.py --sim
pause
