@echo off
REM =====================================================================
REM  Éclipse Studio — construit la version Windows installable (.zip) SUR CE PC
REM  Double-clic. Résultat : dist\paquets\EclipseStudio-<version>-Windows.zip
REM =====================================================================
chcp 65001 >nul
cd /d "%~dp0\.."
where py >nul 2>nul && (set PY=py -3) || (set PY=python)
if not exist ".venv-construction\Scripts\python.exe" (
  echo Préparation de l'environnement de construction (une seule fois)...
  %PY% -m venv .venv-construction || (echo Python 3.9+ nécessaire : https://www.python.org/downloads/ & pause & exit /b 1)
)
".venv-construction\Scripts\python.exe" -m pip install --upgrade pip >nul
".venv-construction\Scripts\python.exe" -m pip install -r empaquetage\requirements-construction.txt || (echo Installation impossible & pause & exit /b 1)
set PYTHONUTF8=1
".venv-construction\Scripts\python.exe" empaquetage\construire.py && explorer dist\paquets
pause
