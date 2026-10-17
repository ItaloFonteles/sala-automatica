@echo off
REM Verifica o Python e prepara o modo real (camera, microfone, OBS).
REM Instala o Python 3.13 se precisar e cria o ambiente com as bibliotecas.
REM Tudo fica registrado em preparar_python.log
cd /d "%~dp0"
set LOG=%~dp0preparar_python.log
echo ==== Preparar Python - %date% %time% ==== > "%LOG%"

echo.
echo  [1/4] Verificando versoes do Python instaladas...
echo [1] Versoes instaladas (py -0p): >> "%LOG%"
py -0p >> "%LOG%" 2>&1

call :TEM_313
if not errorlevel 1 goto TEM313

echo  [2/4] Python 3.13 nao encontrado. Instalando (pode levar alguns minutos)...
echo [2] Instalando Python 3.13 com o gerenciador oficial: py install 3.13 >> "%LOG%"
py install 3.13 >> "%LOG%" 2>&1
echo py install saiu com codigo %errorlevel% >> "%LOG%"
call :TEM_313
if errorlevel 1 (
  echo [2b] Tentando pelo winget >> "%LOG%"
  winget install --id Python.Python.3.13 -e --scope user --silent --accept-source-agreements --accept-package-agreements >> "%LOG%" 2>&1
)
call :TEM_313
if errorlevel 1 (
  echo [ERRO] Python 3.13 continua indisponivel depois do winget >> "%LOG%"
  echo.
  echo  Nao consegui instalar o Python 3.13 automaticamente.
  echo  Baixe em https://www.python.org/downloads/release/python-3130/ e rode este arquivo de novo.
  echo FIM_COM_ERRO >> "%LOG%"
  pause
  exit /b 1
)
goto SEGUE

:TEM313
echo  [2/4] Python 3.13 ja esta instalado.
echo [2] Python 3.13 ja instalado >> "%LOG%"

:SEGUE
py -3.13 --version >> "%LOG%" 2>&1

echo  [3/4] Criando ambiente .venv com Python 3.13...
echo [3] Criando .venv com 3.13 >> "%LOG%"
if exist .venv (
  .venv\Scripts\python --version 2>nul | find "3.13" >nul
  if errorlevel 1 (
    echo .venv antigo nao e 3.13: recriando >> "%LOG%"
    rmdir /s /q .venv
  )
)
if not exist .venv py -3.13 -m venv .venv >> "%LOG%" 2>&1
.venv\Scripts\python --version >> "%LOG%" 2>&1

echo  [4/4] Instalando bibliotecas do modo real...
echo [4] pip install >> "%LOG%"
.venv\Scripts\python -m pip install --upgrade pip >> "%LOG%" 2>&1
.venv\Scripts\python -m pip install -r requirements.txt >> "%LOG%" 2>&1
if errorlevel 1 (
  echo [ERRO] pip install falhou >> "%LOG%"
  echo FIM_COM_ERRO >> "%LOG%"
  echo.
  echo  Deu erro ao instalar as bibliotecas. Veja preparar_python.log
  pause
  exit /b 1
)

echo [5] Conferindo imports >> "%LOG%"
.venv\Scripts\python -c "import numpy, sounddevice, obsws_python; print('numpy', numpy.__version__); print('sounddevice', sounddevice.__version__); print('obsws OK')" >> "%LOG%" 2>&1
echo [6] Placas de som encontradas: >> "%LOG%"
.venv\Scripts\python main.py --listar-audio >> "%LOG%" 2>&1
echo FIM_OK >> "%LOG%"

echo.
echo  Pronto! Python 3.13 e bibliotecas do modo real instalados.
echo  Agora o iniciar_modo_real.bat vai funcionar.
pause
exit /b 0

:TEM_313
REM Retorna 0 so se o Python 3.13 roda de verdade (o "py" novo nao avisa pelo codigo de saida)
py -3.13 -c "print('OK313')" 2>nul | find "OK313" >nul
exit /b %errorlevel%
