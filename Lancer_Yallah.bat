@echo off
chcp 65001 >nul
REM Lanceur double-clic Windows — Yallah Services (sans ligne de commande)
cd /d "%~dp0"

set "PORT=%YALLAH_PORT%"
if "%PORT%"=="" set "PORT=8000"

where py >nul 2>nul
if %ERRORLEVEL% EQU 0 (
    echo Demarrage de Yallah Services sur http://127.0.0.1:%PORT% ...
    py -3 webapp.py --port %PORT% --open
    goto :end
)

where python >nul 2>nul
if %ERRORLEVEL% EQU 0 (
    echo Demarrage de Yallah Services sur http://127.0.0.1:%PORT% ...
    python webapp.py --port %PORT% --open
    goto :end
)

echo Python 3 est introuvable. Installez Python 3 depuis https://www.python.org/downloads/
pause
exit /b 1

:end
if %ERRORLEVEL% NEQ 0 pause
