@echo off
setlocal
cd /d "%~dp0"

where python >nul 2>nul
if %errorlevel%==0 (
  python -c "import pyodbc, reportlab" >nul 2>nul
  if errorlevel 1 (
    echo.
    echo [NORMADATA] Faltan dependencias en el Python activo.
    echo Ejecuta: python -m pip install -r requirements.txt
    echo.
    pause
    exit /b 1
  )
  python run.py
  exit /b %errorlevel%
)

where py >nul 2>nul
if %errorlevel%==0 (
  py -3 -c "import pyodbc, reportlab" >nul 2>nul
  if errorlevel 1 (
    echo.
    echo [NORMADATA] Faltan dependencias en el Python activo.
    echo Ejecuta: py -3 -m pip install -r requirements.txt
    echo.
    pause
    exit /b 1
  )
  py -3 run.py
  exit /b %errorlevel%
)

echo No se encontro Python. Instale Python 3.10 o superior y vuelva a ejecutar.
pause
exit /b 1
