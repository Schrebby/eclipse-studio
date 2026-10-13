#!/bin/bash
# =====================================================================
#  Éclipse Studio PORTABLE — préparation du Python autonome (macOS / Linux)
#  Appelé par le lanceur au 1er démarrage. Tout est écrit DANS le dossier
#  du kit (runtime/<système>/) : rien n'est installé sur l'ordinateur.
#    preparer.sh <dossier_du_kit> <triplet>   ex. aarch64-apple-darwin
# =====================================================================
set -u
KIT="$1"; T="$2"
RT="$KIT/runtime/$T"
PY="$RT/python/bin/python3"
API="https://api.github.com/repos/astral-sh/python-build-standalone/releases/latest"
# Version de secours si l'API GitHub ne répond pas (limite de requêtes…)
SECOURS="https://github.com/astral-sh/python-build-standalone/releases/download/20241016/cpython-3.12.7%2B20241016-${T}-install_only.tar.gz"

echo ""
echo "  Éclipse Studio portable — première préparation pour ce système ($T)"
echo "  Téléchargement d'un Python autonome (~30 Mo) et des bibliothèques (~80 Mo)."
echo "  Une connexion Internet est nécessaire UNE SEULE FOIS. Rien n'est installé"
echo "  sur l'ordinateur : tout reste dans le dossier « runtime » du kit."
echo ""

# ---- 1. Python autonome (python-build-standalone) ----
if [ ! -x "$PY" ]; then
  mkdir -p "$RT" || { echo "✗ Dossier non inscriptible : $RT"; exit 1; }
  URL=""
  LISTE="$(curl -fsSL -m 30 -H 'User-Agent: EclipseStudio' "$API" 2>/dev/null | grep -o '"browser_download_url": *"[^"]*"' | sed 's/.*"\(https[^"]*\)"/\1/')"
  for v in 12 13; do
    URL="$(printf '%s\n' "$LISTE" | grep -E "/cpython-3\.${v}\.[0-9]+(\+|%2B)[0-9]+-${T}-install_only\.tar\.gz$" | head -1)"
    [ -n "$URL" ] && break
  done
  [ -z "$URL" ] && URL="$SECOURS"
  echo "→ $URL"
  curl -fL --progress-bar -m 900 -o "$RT/python.tar.gz" "$URL" || { echo "✗ Téléchargement impossible (connexion ?)"; rm -f "$RT/python.tar.gz"; exit 1; }
  tar -xzf "$RT/python.tar.gz" -C "$RT" || { echo "✗ Archive Python illisible"; exit 1; }
  rm -f "$RT/python.tar.gz"
fi
"$PY" -c "import sys; print('  Python', sys.version.split()[0], 'prêt')" || { echo "✗ Python autonome inutilisable"; exit 1; }

# ---- 2. Bibliothèques (dans le Python du kit) ----
export PIP_DISABLE_PIP_VERSION_CHECK=1
"$PY" -m pip install --no-warn-script-location -q numpy opencv-python-headless pillow imageio-ffmpeg tzdata \
  || { echo "✗ Installation des bibliothèques impossible (connexion ?)"; exit 1; }
"$PY" -m pip install --no-warn-script-location -q rawpy \
  || echo "⚠ rawpy indisponible : les RAW seront lus via leur aperçu JPEG intégré."

# ---- 3. Auto-test puis marqueur « prêt » ----
"$PY" "$KIT/app/lanceur.py" --verifier || { echo "✗ L'auto-test a échoué"; exit 1; }
date > "$RT/.pret"
echo "✓ Préparation terminée. Les prochains lancements seront immédiats et hors-ligne."
