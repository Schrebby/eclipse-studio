# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jérémy BEAUFRERE — JEREMiA (https://jerem-ia.fr)
# Éclipse Studio est un logiciel libre : vous pouvez le redistribuer et/ou le
# modifier selon les termes de la GNU GPL v3 ou ultérieure (voir LICENSE).
"""
=====================================================================
 Éclipse Studio — FABRICATION DU KIT PORTABLE (Windows + macOS + Linux)
=====================================================================
 Un seul .zip pour les 3 systèmes, sans installation :
   • au 1er lancement, le lanceur télécharge un Python autonome et les
     bibliothèques DANS le dossier du kit (runtime/<système>/) ;
   • ensuite tout fonctionne hors-ligne, même depuis une clé USB ;
   • plusieurs systèmes peuvent partager la même clé (un runtime chacun) ;
   • pour « désinstaller » : supprimer le dossier.

   python empaquetage/kit_portable.py     →  dist/paquets/EclipseStudio-<v>-portable.zip
 Aucun téléchargement n'est nécessaire pour FABRIQUER le kit.
=====================================================================
"""
from __future__ import annotations

import os
import sys
import time
import zipfile

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PORT = os.path.join(RACINE, "empaquetage", "portable")
SORTIE = os.path.join(RACINE, "dist", "paquets")
DOSSIER = "EclipseStudio-portable"

LISEZMOI = """Éclipse Studio {v} — VERSION PORTABLE
Logiciel libre et gratuit (licence GPL-3.0) — https://jerem-ia.fr — contact@jerem-ia.fr

Rien à installer : l'application tourne depuis ce dossier (disque, clé USB…).

DÉMARRER
  • Windows : double-clic sur « Eclipse Studio (Windows).bat »
      Si Windows affiche « Windows a protégé votre ordinateur » :
      Informations complémentaires › Exécuter quand même.
  • Mac     : clic droit sur « Eclipse Studio (Mac).command » › Ouvrir
      (la 1re fois seulement ; ensuite le double-clic suffit).
      Sur macOS 15 et plus : si l'ouverture est refusée, allez dans
      Réglages Système › Confidentialité et sécurité › « Ouvrir quand même ».
  • Linux   : ./"Eclipse Studio (Linux).sh"

PREMIER LANCEMENT (une seule fois par système, connexion Internet nécessaire)
  Le lanceur télécharge un Python autonome (~30 Mo) et les bibliothèques de
  calcul (~80 Mo) dans le sous-dossier « runtime ». Comptez 2 à 5 minutes.
  Rien n'est installé sur l'ordinateur ni ailleurs que dans ce dossier.

ENSUITE
  Démarrage immédiat, sans Internet. L'interface s'ouvre dans votre navigateur.
  Pour quitter : bouton « Quitter » de l'interface (ou fermez la fenêtre noire).

DÉSINSTALLER
  Supprimez simplement ce dossier.

Astuce clé USB : préparez le kit une fois sur chaque système (Windows, Mac…) ;
chacun garde son propre runtime et la clé fonctionne ensuite partout, hors-ligne.

Sur Mac, préférez la version .dmg (signée et notarisée par Apple : aucun avertissement).
"""

README = """Eclipse Studio {v} — PORTABLE VERSION
Free and open-source software (GPL-3.0 licence) — https://jerem-ia.fr — contact@jerem-ia.fr

Nothing to install: the app runs from this folder (drive, USB stick…).

START
  • Windows: double-click "Eclipse Studio (Windows).bat"
      If Windows shows "Windows protected your PC":
      More info › Run anyway.
  • Mac:     right-click "Eclipse Studio (Mac).command" › Open
      (first time only; afterwards a double-click is enough).
      On macOS 15 and later, if opening is refused, go to
      System Settings › Privacy & Security › "Open Anyway".
      Tip: on Mac, the signed .dmg version opens without any warning.
  • Linux:   ./"Eclipse Studio (Linux).sh"

FIRST LAUNCH (once per system, Internet connection required)
  The launcher downloads a standalone Python (~30 MB) and the computing
  libraries (~80 MB) into the "runtime" subfolder. Allow 2 to 5 minutes.
  Nothing is installed on the computer or anywhere outside this folder.

AFTERWARDS
  Instant start-up, no Internet needed. The interface opens in your browser
  (currently in French — an English guide is in README.md on the project page).
  To quit: "Quitter" (Quit) button in the interface, or close the black window.

UNINSTALL
  Just delete this folder.

USB stick tip: prepare the kit once on each system (Windows, Mac…); each one
keeps its own runtime, and the stick then works everywhere, offline.
"""


def version() -> str:
    sys.path.insert(0, RACINE)
    from eclipse_studio import __version__
    return __version__


def crlf(texte: str) -> bytes:
    return texte.replace("\r\n", "\n").replace("\n", "\r\n").encode("utf-8")


def ajouter(z: zipfile.ZipFile, chemin_zip: str, donnees: bytes, executable: bool = False):
    """Ajoute un fichier en conservant le droit d'exécution (lu par macOS/Linux)."""
    info = zipfile.ZipInfo(f"{DOSSIER}/{chemin_zip}", date_time=time.localtime()[:6])
    info.compress_type = zipfile.ZIP_DEFLATED
    info.create_system = 3                                   # attributs Unix
    info.external_attr = ((0o755 if executable else 0o644) | 0o100000) << 16
    z.writestr(info, donnees)


def lire(ch: str) -> bytes:
    with open(ch, "rb") as f:
        return f.read()


def main():
    v = version()
    os.makedirs(SORTIE, exist_ok=True)
    sortie = os.path.join(SORTIE, f"EclipseStudio-{v}-portable.zip")
    unix = lire(os.path.join(PORT, "lanceur_unix.sh"))
    bat = lire(os.path.join(PORT, "lanceur_windows.bat")).decode("utf-8")
    ps1 = lire(os.path.join(PORT, "preparer.ps1")).decode("utf-8")
    n = 0
    with zipfile.ZipFile(sortie, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        # Lanceurs (racine du kit)
        ajouter(z, "Eclipse Studio (Mac).command", unix, executable=True)
        ajouter(z, "Eclipse Studio (Linux).sh", unix, executable=True)
        ajouter(z, "Eclipse Studio (Windows).bat", crlf(bat))
        ajouter(z, "LISEZ-MOI.txt", b"\xef\xbb\xbf" + crlf(LISEZMOI.format(v=v)))
        ajouter(z, "README.txt", b"\xef\xbb\xbf" + crlf(README.format(v=v)))
        ajouter(z, "LICENSE.txt", lire(os.path.join(RACINE, "LICENSE")))
        # Application
        ajouter(z, "app/lanceur.py", lire(os.path.join(RACINE, "lanceur.py")))
        ajouter(z, "app/LICENSE", lire(os.path.join(RACINE, "LICENSE")))
        ajouter(z, "app/portable/preparer.sh", lire(os.path.join(PORT, "preparer.sh")), executable=True)
        # PowerShell 5.1 exige l'UTF-8 AVEC BOM pour lire correctement les accents
        ajouter(z, "app/portable/preparer.ps1", b"\xef\xbb\xbf" + crlf(ps1))
        pkg = os.path.join(RACINE, "eclipse_studio")
        for rac, dossiers, fichiers in os.walk(pkg):
            dossiers[:] = [d for d in dossiers if d != "__pycache__"]
            for f in sorted(fichiers):
                if f.endswith((".pyc", ".pyo")) or f.startswith("."):
                    continue
                ch = os.path.join(rac, f)
                ajouter(z, "app/" + os.path.relpath(ch, RACINE).replace(os.sep, "/"), lire(ch))
                n += 1
    print(f"✓ Kit portable : {sortie}  ({os.path.getsize(sortie) / 1e6:.1f} Mo, {n} fichiers d'application)")
    return sortie


if __name__ == "__main__":
    main()
