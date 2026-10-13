# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jérémy BEAUFRERE — JEREMiA (https://jerem-ia.fr)
# Éclipse Studio est un logiciel libre : vous pouvez le redistribuer et/ou le
# modifier selon les termes de la GNU GPL v3 ou ultérieure (voir LICENSE).
"""
=====================================================================
 Éclipse Studio — CONSTRUCTION DES VERSIONS INSTALLABLES (sans Python)
=====================================================================
 À lancer sur le système visé (PyInstaller ne fait pas de compilation
 croisée) : Windows → .zip contenant EclipseStudio.exe
             macOS   → .dmg contenant « Eclipse Studio.app »
             Linux   → .tar.gz contenant le binaire EclipseStudio

   python empaquetage/construire.py [--suffixe macOS-AppleSilicon]

 Prérequis : pip install -r empaquetage/requirements-construction.txt
 Sur GitHub, le fichier .github/workflows/construire.yml fait tout cela
 automatiquement pour les 3 systèmes.
=====================================================================
"""
from __future__ import annotations

import argparse
import os
import platform
import plistlib
import shutil
import subprocess
import sys
import tarfile
import zipfile

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # signature_mac.py
EMP = os.path.join(RACINE, "empaquetage")
DIST = os.path.join(RACINE, "dist")
PAQUETS = os.path.join(DIST, "paquets")
NOM = "EclipseStudio"                 # nom technique (sans accent : chemins sûrs partout)
NOM_MAC = "Eclipse Studio"            # nom affiché de l'application macOS
ID_MAC = "fr.jerem-ia.eclipse-studio"
SYSTEME = {"Windows": "windows", "Darwin": "mac"}.get(platform.system(), "linux")


# ---------------------------------------------------------------------
# 1. Outils
# ---------------------------------------------------------------------
def version() -> str:
    sys.path.insert(0, RACINE)
    from eclipse_studio import __version__
    return __version__


def lancer(cmd: list[str], **kw):
    print("→", " ".join(cmd), flush=True)
    subprocess.run(cmd, check=True, **kw)


def module_present(nom: str) -> bool:
    try:
        __import__(nom)
        return True
    except Exception:  # noqa: BLE001
        return False


# ---------------------------------------------------------------------
# 2. PyInstaller
# ---------------------------------------------------------------------
def pyinstaller():
    sep = os.pathsep
    pkg = os.path.join(RACINE, "eclipse_studio")
    cmd = [sys.executable, "-m", "PyInstaller", os.path.join(RACINE, "lanceur.py"),
           "--noconfirm", "--clean", "--onedir",
           "--name", NOM_MAC if SYSTEME == "mac" else NOM,
           "--distpath", DIST, "--workpath", os.path.join(RACINE, "build"),
           "--specpath", os.path.join(RACINE, "build"),
           "--icon", os.path.join(EMP, "icone.png"),
           # Code et données de l'application
           "--collect-submodules", "eclipse_studio",
           "--add-data", f"{os.path.join(pkg, 'ui')}{sep}eclipse_studio/ui",
           "--add-data", f"{os.path.join(pkg, 'donnees')}{sep}eclipse_studio/donnees",
           "--add-data", f"{os.path.join(RACINE, 'LICENSE')}{sep}.",
           # FFmpeg (export vidéo) est un binaire livré dans imageio_ffmpeg
           "--collect-all", "imageio_ffmpeg",
           # Modules inutiles (allège nettement le paquet)
           "--exclude-module", "tkinter", "--exclude-module", "matplotlib",
           "--exclude-module", "scipy", "--exclude-module", "pandas"]
    if module_present("tzdata"):
        cmd += ["--collect-data", "tzdata"]       # fuseaux horaires (Windows n'en a pas)
    if module_present("rawpy"):
        cmd += ["--collect-all", "rawpy"]          # lecture RAW (LibRaw)
    if SYSTEME == "mac":
        # Application sans terminal : on quitte par le bouton « Quitter » de l'interface
        cmd += ["--windowed", "--osx-bundle-identifier", ID_MAC]
    lancer(cmd, cwd=RACINE)


def retoucher_app_mac(app: str):
    """macOS : l'app ne doit pas encombrer le Dock (pas de fenêtre native,
    l'interface est dans le navigateur). Signature ensuite (voir signature_mac.py)."""
    plist = os.path.join(app, "Contents", "Info.plist")
    with open(plist, "rb") as f:
        p = plistlib.load(f)
    p.update({"LSUIElement": True, "CFBundleShortVersionString": version(),
              "CFBundleVersion": version(), "NSHumanReadableCopyright": "© 2026 JEREMiA — GPL-3.0",
              "LSMinimumSystemVersion": "11.0"})
    with open(plist, "wb") as f:
        plistlib.dump(p, f)
    # Signature Developer ID (si certificat disponible), sinon ad hoc
    import signature_mac
    signature_mac.signer_app(app, signature_mac.identite())


# ---------------------------------------------------------------------
# 3. Auto-test de l'exécutable construit
# ---------------------------------------------------------------------
def executable() -> str:
    if SYSTEME == "mac":
        return os.path.join(DIST, f"{NOM_MAC}.app", "Contents", "MacOS", NOM_MAC)
    return os.path.join(DIST, NOM, NOM + (".exe" if SYSTEME == "windows" else ""))


def verifier():
    r = subprocess.run([executable(), "--verifier"], capture_output=True, text=True, timeout=300,
                       encoding="utf-8", errors="replace")
    print(r.stdout, r.stderr)
    if r.returncode != 0 or "VÉRIFICATION OK" not in r.stdout:
        sys.exit("✗ L'exécutable construit ne passe pas l'auto-test")


# ---------------------------------------------------------------------
# 4. Paquet à télécharger
# ---------------------------------------------------------------------
LISEZMOI = {
    "windows": """Éclipse Studio {v} — Windows (logiciel libre et gratuit, licence GPL-3.0)

1. Décompressez ce dossier où vous voulez (ex. Documents).
2. Double-cliquez sur EclipseStudio.exe : l'interface s'ouvre dans votre navigateur.
3. Au premier lancement, Windows peut afficher « Windows a protégé votre ordinateur » :
   cliquez sur « Informations complémentaires » puis « Exécuter quand même ».
   (L'application n'est pas signée par un certificat payant ; elle est sûre et son code est public.)
Pour quitter : bouton « Quitter » de l'interface, ou fermez la fenêtre noire.
Site : https://jerem-ia.fr — contact@jerem-ia.fr
""",
    "mac": """Éclipse Studio {v} — macOS (logiciel libre et gratuit, licence GPL-3.0)

1. Glissez « Eclipse Studio » dans le dossier Applications.
2. Double-cliquez dessus : l'interface s'ouvre dans votre navigateur.
   (Application signée et notarisée par Apple : aucun avertissement.)
Pour quitter : bouton « Quitter » de l'interface.
Site : https://jerem-ia.fr — contact@jerem-ia.fr
""",
    "linux": """Éclipse Studio {v} — Linux (logiciel libre et gratuit, licence GPL-3.0)

  tar xzf EclipseStudio-*.tar.gz && ./EclipseStudio/EclipseStudio
L'interface s'ouvre dans votre navigateur. Pour quitter : bouton « Quitter » ou Ctrl+C.
Site : https://jerem-ia.fr — contact@jerem-ia.fr
""",
}


README = {
    "windows": """Eclipse Studio {v} — Windows (free and open-source software, GPL-3.0 licence)

1. Unzip this folder anywhere you like (e.g. Documents).
2. Double-click EclipseStudio.exe: the interface opens in your web browser.
3. On first launch, Windows may show "Windows protected your PC":
   click "More info", then "Run anyway".
   (The app is not signed with a paid certificate; it is safe and its source code is public.)
To quit: "Quitter" (Quit) button in the interface, or close the black window.
The interface is currently in French — an English guide is in README.md on the project page.
Website: https://jerem-ia.fr — contact@jerem-ia.fr
""",
    "mac": """Eclipse Studio {v} — macOS (free and open-source software, GPL-3.0 licence)

1. Drag "Eclipse Studio" into the Applications folder.
2. Double-click it: the interface opens in your web browser.
   (The app is signed and notarised by Apple: no warning.)
To quit: "Quitter" (Quit) button in the interface.
The interface is currently in French — an English guide is in README.md on the project page.
Website: https://jerem-ia.fr — contact@jerem-ia.fr
""",
    "linux": """Eclipse Studio {v} — Linux (free and open-source software, GPL-3.0 licence)

  tar xzf EclipseStudio-*.tar.gz && ./EclipseStudio/EclipseStudio
The interface opens in your web browser. To quit: "Quitter" (Quit) button or Ctrl+C.
The interface is currently in French — an English guide is in README.md on the project page.
Website: https://jerem-ia.fr — contact@jerem-ia.fr
""",
}


def empaqueter(suffixe: str) -> str:
    v = version()
    os.makedirs(PAQUETS, exist_ok=True)
    base = f"{NOM}-{v}-{suffixe}"
    texte = LISEZMOI[SYSTEME].format(v=v)
    texte_en = README[SYSTEME].format(v=v)

    if SYSTEME == "windows":
        dossier = os.path.join(DIST, NOM)
        for nom, contenu in (("LISEZ-MOI.txt", texte), ("README.txt", texte_en)):
            with open(os.path.join(dossier, nom), "w", encoding="utf-8-sig") as f:
                f.write(contenu)
        shutil.copy(os.path.join(RACINE, "LICENSE"), os.path.join(dossier, "LICENSE.txt"))
        sortie = os.path.join(PAQUETS, base + ".zip")
        with zipfile.ZipFile(sortie, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
            for rac, _, fichiers in os.walk(dossier):
                for fi in fichiers:
                    ch = os.path.join(rac, fi)
                    z.write(ch, os.path.join(NOM, os.path.relpath(ch, dossier)))
        return sortie

    if SYSTEME == "mac":
        app = os.path.join(DIST, f"{NOM_MAC}.app")
        mise = os.path.join(DIST, "dmg")
        shutil.rmtree(mise, ignore_errors=True)
        os.makedirs(mise)
        lancer(["ditto", app, os.path.join(mise, f"{NOM_MAC}.app")])
        os.symlink("/Applications", os.path.join(mise, "Applications"))
        for nom, contenu in (("LISEZ-MOI.txt", texte), ("README.txt", texte_en)):
            with open(os.path.join(mise, nom), "w", encoding="utf-8") as f:
                f.write(contenu)
        shutil.copy(os.path.join(RACINE, "LICENSE"), os.path.join(mise, "LICENSE.txt"))
        sortie = os.path.join(PAQUETS, base + ".dmg")
        if os.path.exists(sortie):
            os.remove(sortie)
        lancer(["hdiutil", "create", "-volname", f"{NOM_MAC} {v}", "-srcfolder", mise,
                "-ov", "-format", "UDZO", sortie])
        # Signature + notarisation Apple du .dmg (si compte développeur configuré)
        import signature_mac
        signature_mac.notariser_dmg(sortie, signature_mac.identite())
        return sortie

    dossier = os.path.join(DIST, NOM)
    for nom, contenu in (("LISEZ-MOI.txt", texte), ("README.txt", texte_en)):
        with open(os.path.join(dossier, nom), "w", encoding="utf-8") as f:
            f.write(contenu)
    shutil.copy(os.path.join(RACINE, "LICENSE"), os.path.join(dossier, "LICENSE"))
    sortie = os.path.join(PAQUETS, base + ".tar.gz")
    with tarfile.open(sortie, "w:gz") as t:
        t.add(dossier, arcname=NOM)
    return sortie


# ---------------------------------------------------------------------
# 5. Programme principal
# ---------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description="Construit la version installable d'Éclipse Studio")
    ap.add_argument("--suffixe", default="", help="ex. Windows, macOS-AppleSilicon, Linux-x86_64")
    ap.add_argument("--sans-test", action="store_true")
    a = ap.parse_args()
    suffixe = a.suffixe or {"windows": "Windows", "linux": f"Linux-{platform.machine()}",
                            "mac": "macOS-AppleSilicon" if platform.machine() == "arm64" else "macOS-Intel"}[SYSTEME]
    print(f"=== Éclipse Studio {version()} — construction {suffixe} ===", flush=True)
    pyinstaller()
    if SYSTEME == "mac":
        retoucher_app_mac(os.path.join(DIST, f"{NOM_MAC}.app"))
    if not a.sans_test:
        verifier()
    sortie = empaqueter(suffixe)
    print(f"\n✓ Paquet prêt : {sortie}  ({os.path.getsize(sortie) / 1e6:.0f} Mo)")


if __name__ == "__main__":
    main()
