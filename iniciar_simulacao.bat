@echo off
REM Testa a Sala Automatica sem equipamento (modo simulacao).
REM Nao precisa instalar nada: usa so o Python.
cd /d "%~dp0"
start "" /min cmd /c "timeout /t 3 >nul & start http://localhost:8080"
where py >nul 2>nul && (py main.py --sim) || (python main.py --sim)
pause
