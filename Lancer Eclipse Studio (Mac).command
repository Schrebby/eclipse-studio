#!/bin/bash
# =====================================================================
#  Éclipse Studio — lanceur macOS (double-clic)
#  1er lancement : crée un environnement Python privé (.venv) et
#  installe les dépendances. Ensuite : démarre directement.
# =====================================================================
cd "$(dirname "$0")" || exit 1

# ---- 1. Trouver Python 3.9+ ----
PY=""
for c in python3.13 python3.12 python3.11 python3.10 python3.9 python3; do
  if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' 2>/dev/null; then
    PY="$c"; break
  fi
done
if [ -z "$PY" ]; then
  echo "Python 3.9 ou plus récent est nécessaire."
  echo "Installez-le depuis https://www.python.org/downloads/ puis relancez ce fichier."
  read -r -p "Appuyez sur Entrée pour fermer…"; exit 1
fi

# ---- 2. Environnement privé + dépendances (1re fois) ----
if [ ! -x ".venv/bin/python" ]; then
  echo "Première installation (2 à 5 minutes)…"
  "$PY" -m venv .venv || { echo "Création de l'environnement impossible"; read -r; exit 1; }
  .venv/bin/python -m pip install --upgrade pip >/dev/null
  .venv/bin/python -m pip install numpy opencv-python-headless pillow imageio-ffmpeg tzdata || { echo "Installation impossible (connexion ?)"; read -r; exit 1; }
  .venv/bin/python -m pip install rawpy || echo "⚠ rawpy indisponible : les RAW seront lus via leur aperçu JPEG intégré."
fi

# ---- 3. Démarrage (l'interface s'ouvre dans le navigateur) ----
exec .venv/bin/python -m eclipse_studio "$@"
