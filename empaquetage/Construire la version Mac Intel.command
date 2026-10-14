#!/bin/bash
# =====================================================================
#  Éclipse Studio — construit la version Mac INTEL (.dmg) sur un Mac
#  Apple Silicon, grâce à Rosetta 2 :
#   1. Python autonome x86_64 (python-build-standalone) téléchargé dans
#      le dossier du projet (rien d'installé sur le système)
#   2. Environnement de construction x86_64 (.venv-intel)
#   3. construire.py exécuté en mode Intel : signature Developer ID,
#      notarisation Apple, .dmg « macOS-Intel »
#  Journal : dist/journal_construction_mac_intel.txt
# =====================================================================
cd "$(dirname "$0")/.." || exit 1
mkdir -p dist
exec > >(tee dist/journal_construction_mac_intel.txt) 2>&1
stop() { echo "✗ $1"; echo "FIN : ÉCHEC"; read -r -p "Entrée pour fermer…"; exit 1; }
X86="arch -x86_64"

# ---- 0. Rosetta 2 ----
$X86 /usr/bin/true 2>/dev/null || stop "Rosetta 2 absent : lancez « softwareupdate --install-rosetta » puis recommencez"

# ---- 1. Python autonome x86_64 ----
PBS="build/python-intel"
PY="$PBS/python/bin/python3"
if [ ! -x "$PY" ]; then
  echo "Téléchargement d'un Python autonome Intel…"
  mkdir -p "$PBS"
  URL="$(curl -fsSL -m 30 https://api.github.com/repos/astral-sh/python-build-standalone/releases/latest \
        | grep -o '"browser_download_url": *"[^"]*"' | sed 's/.*"\(https[^"]*\)"/\1/' \
        | grep -E '/cpython-3\.12\.[0-9]+(\+|%2B)[0-9]+-x86_64-apple-darwin-install_only\.tar\.gz$' | head -1)"
  [ -z "$URL" ] && URL="https://github.com/astral-sh/python-build-standalone/releases/download/20241016/cpython-3.12.7%2B20241016-x86_64-apple-darwin-install_only.tar.gz"
  echo "→ $URL"
  curl -fL -m 900 -o "$PBS/python.tar.gz" "$URL" || stop "téléchargement impossible"
  tar -xzf "$PBS/python.tar.gz" -C "$PBS" || stop "archive illisible"
  rm -f "$PBS/python.tar.gz"
fi
$X86 "$PY" -c "import platform,sys; print('Python', sys.version.split()[0], platform.machine())" || stop "Python Intel inutilisable"

# ---- 2. Environnement de construction Intel ----
if [ ! -x ".venv-intel/bin/python" ]; then
  $X86 "$PY" -m venv .venv-intel || stop "création de .venv-intel impossible"
fi
$X86 .venv-intel/bin/python -m pip install -q --upgrade pip
# rawpy n'a plus de version précompilée récente pour Mac Intel : installé à part,
# uniquement en binaire (la dernière version disponible) ; sinon l'app lit les
# RAW via leur aperçu JPEG intégré.
grep -v "^rawpy" empaquetage/requirements-construction.txt > build/requirements-intel.txt
$X86 .venv-intel/bin/python -m pip install -q -r build/requirements-intel.txt || stop "installation des dépendances impossible"
$X86 .venv-intel/bin/python -m pip install -q --only-binary=:all: rawpy \
  && echo "✓ rawpy (lecture RAW) installé" || echo "⚠ rawpy indisponible en Intel : RAW lus via l'aperçu JPEG intégré"
$X86 .venv-intel/bin/python -c "import platform; assert platform.machine()=='x86_64'; print('✓ environnement x86_64')" || stop "l'environnement n'est pas en x86_64"

# ---- 3. Construction + auto-test + signature + notarisation ----
$X86 .venv-intel/bin/python -u empaquetage/construire.py --suffixe macOS-Intel || stop "construction Intel échouée"
echo "FIN : OK"
open dist/paquets
read -r -p "Terminé. Entrée pour fermer…"
