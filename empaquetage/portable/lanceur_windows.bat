@echo off
REM =====================================================================
REM  Éclipse Studio PORTABLE — lanceur Windows (double-clic)
REM  1er lancement : prépare un Python autonome DANS le dossier du kit.
REM  Ensuite : démarrage immédiat, hors-ligne. Aucune installation système.
REM =====================================================================
chcp 65001 >nul
set "KIT=%~dp0."
set "T=x86_64-pc-windows-msvc"
if /i "%PROCESSOR_ARCHITECTURE%"=="ARM64" set "T=aarch64-pc-windows-msvc"
if exist "%KIT%\runtime\%T%\.pret" goto lancer
powershell -NoProfile -ExecutionPolicy Bypass -File "%KIT%\app\portable\preparer.ps1" -Kit "%KIT%" -T "%T%"
if errorlevel 1 (
  pause
  exit /b 1
)
:lancer
"%KIT%\runtime\%T%\python\python.exe" "%KIT%\app\lanceur.py" %*
if errorlevel 1 pause
