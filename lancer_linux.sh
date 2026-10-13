#!/bin/bash
# =====================================================================
#  Éclipse Studio — lanceur Linux :  ./lancer_linux.sh
# =====================================================================
cd "$(dirname "$0")" || exit 1
PY=$(command -v python3 || true)
if [ -z "$PY" ]; then echo "Installez python3 (ex. sudo apt install python3 python3-venv)"; exit 1; fi
if [ ! -x ".venv/bin/python" ]; then
  echo "Première installation…"
  "$PY" -m venv .venv || { echo "Paquet python3-venv manquant : sudo apt install python3-venv"; exit 1; }
  .venv/bin/python -m pip install --upgrade pip >/dev/null
  .venv/bin/python -m pip install numpy opencv-python-headless pillow imageio-ffmpeg tzdata || exit 1
  .venv/bin/python -m pip install rawpy || echo "⚠ rawpy indisponible : aperçu JPEG intégré utilisé pour les RAW."
fi
exec .venv/bin/python -m eclipse_studio "$@"
