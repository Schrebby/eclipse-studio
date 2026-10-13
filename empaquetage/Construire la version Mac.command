#!/bin/bash
# =====================================================================
#  Éclipse Studio — construit la version Mac installable (.dmg) SUR CE MAC
#  Double-clic. Résultat : dist/paquets/EclipseStudio-<version>-macOS-….dmg
#  (application autonome : vos utilisateurs n'auront pas besoin de Python)
# =====================================================================
cd "$(dirname "$0")/.." || exit 1

# ---- 1. Python 3.9+ ----
PY=""
for c in python3.13 python3.12 python3.11 python3.10 python3.9 python3; do
  if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' 2>/dev/null; then
    PY="$c"; break
  fi
done
[ -z "$PY" ] && { echo "Python 3.9+ nécessaire (https://www.python.org/downloads/)"; read -r; exit 1; }

# ---- 2. Environnement de construction séparé (.venv-construction) ----
if [ ! -x ".venv-construction/bin/python" ]; then
  echo "Préparation de l'environnement de construction (quelques minutes, une seule fois)…"
  "$PY" -m venv .venv-construction || { echo "Impossible de créer l'environnement"; read -r; exit 1; }
fi
.venv-construction/bin/python -m pip install --upgrade pip >/dev/null
.venv-construction/bin/python -m pip install -r empaquetage/requirements-construction.txt || { echo "Installation impossible (connexion ?)"; read -r; exit 1; }

# ---- 3. Signature Apple : certificat + identifiants de notarisation ----
if security find-identity -v -p codesigning | grep -q "Developer ID Application"; then
  echo "✓ Certificat trouvé : $(security find-identity -v -p codesigning | grep -o '"Developer ID Application[^"]*"' | head -1)"
  if ! xcrun notarytool history --keychain-profile eclipse-studio >/dev/null 2>&1; then
    echo ""
    echo "=== Notarisation Apple : enregistrement des identifiants (une seule fois) ==="
    echo "Il vous faut : l'adresse de votre compte Apple Developer, votre Team ID"
    echo "(developer.apple.com/account › Membership details) et un mot de passe pour app"
    echo "(account.apple.com › Connexion et sécurité › Mots de passe pour app)."
    echo "Ils sont rangés dans le trousseau macOS, nulle part ailleurs."
    echo ""
    read -r -p "Adresse Apple ID : " AID
    read -r -p "Team ID (10 caractères) : " TID
    xcrun notarytool store-credentials eclipse-studio --apple-id "$AID" --team-id "$TID" \
      || echo "⚠ Identifiants non enregistrés : l'app sera signée mais pas notarisée."
  fi
else
  echo "⚠ Aucun certificat « Developer ID Application » dans le trousseau : l'app ne sera pas signée."
  echo "  (Xcode › Réglages › Comptes › Gérer les certificats › + › Developer ID Application)"
fi

# ---- 4. Construction + auto-test + signature + notarisation + .dmg ----
# Toute la sortie est aussi enregistrée dans dist/journal_construction_mac.txt
mkdir -p dist
.venv-construction/bin/python -u empaquetage/construire.py 2>&1 | tee dist/journal_construction_mac.txt
[ "${PIPESTATUS[0]}" -eq 0 ] && open dist/paquets
read -r -p "Terminé. Appuyez sur Entrée pour fermer…"
