@echo off
REM Teste com OBS e microfone REAIS (cameras simuladas).
REM Antes: abra o OBS e ative o servidor WebSocket com a senha sala2026.
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  call preparar_python.bat
  if errorlevel 1 exit /b 1
)
echo.
echo  [1/2] Criando as cenas no OBS...
.venv\Scripts\python configurar_obs.py --config config_teste_notebook.toml > configurar_obs.log 2>&1
type configurar_obs.log
if errorlevel 1 (
  pause
  exit /b 1
)
echo.
echo  [2/2] Iniciando a Sala Automatica. Fale perto do notebook!
start "" /min cmd /c "timeout /t 3 >nul & start http://localhost:8080"
.venv\Scripts\python main.py --config config_teste_notebook.toml > teste_obs_microfone.log 2>&1
type teste_obs_microfone.log
pause
