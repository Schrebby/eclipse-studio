@echo off
REM =====================================================================
REM  Eclipse Studio - lanceur Windows (double-clic)
REM =====================================================================
cd /d "%~dp0"
chcp 65001 >nul
set PY=
where py >nul 2>nul && set PY=py -3
if not defined PY ( where python >nul 2>nul && set PY=python )
if not defined PY (
  echo Python 3.9+ est necessaire : https://www.python.org/downloads/  ^(cochez "Add Python to PATH"^)
  pause
  exit /b 1
)
if not exist ".venv\Scripts\python.exe" (
  echo Premiere installation, 2 a 5 minutes...
  %PY% -m venv .venv || ( echo Creation de l environnement impossible & pause & exit /b 1 )
  ".venv\Scripts\python.exe" -m pip install --upgrade pip >nul
  ".venv\Scripts\python.exe" -m pip install numpy opencv-python-headless pillow imageio-ffmpeg tzdata || ( echo Installation impossible & pause & exit /b 1 )
  ".venv\Scripts\python.exe" -m pip install rawpy || echo rawpy indisponible : apercu JPEG integre utilise pour les RAW.
)
".venv\Scripts\python.exe" -m eclipse_studio %*
pause
