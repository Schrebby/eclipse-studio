#!/bin/bash
# =====================================================================
#  Éclipse Studio PORTABLE — lanceur macOS / Linux (double-clic)
#  1er lancement : prépare un Python autonome DANS le dossier du kit.
#  Ensuite : démarrage immédiat, hors-ligne. Aucune installation système.
# =====================================================================
KIT="$(cd "$(dirname "$0")" && pwd)"
case "$(uname -s)-$(uname -m)" in
  Darwin-arm64)            T=aarch64-apple-darwin ;;
  Darwin-*)                T=x86_64-apple-darwin ;;
  Linux-aarch64|Linux-arm64) T=aarch64-unknown-linux-gnu ;;
  *)                       T=x86_64-unknown-linux-gnu ;;
esac
RT="$KIT/runtime/$T"
if [ ! -f "$RT/.pret" ]; then
  bash "$KIT/app/portable/preparer.sh" "$KIT" "$T" || { read -r -p "Appuyez sur Entrée pour fermer…"; exit 1; }
fi
exec "$RT/python/bin/python3" "$KIT/app/lanceur.py" "$@"
