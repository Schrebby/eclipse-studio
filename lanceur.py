# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jérémy BEAUFRERE — JEREMiA (https://jerem-ia.fr)
# Éclipse Studio est un logiciel libre : vous pouvez le redistribuer et/ou le
# modifier selon les termes de la GNU GPL v3 ou ultérieure (voir LICENSE).
"""
=====================================================================
 Éclipse Studio — LANCEUR UNIQUE (point d'entrée des versions installables)
=====================================================================
 C'est ce fichier que PyInstaller transforme en application autonome
 (.exe Windows, .app macOS, binaire Linux) : aucun Python à installer.

   EclipseStudio                  → ouvre l'interface dans le navigateur
   EclipseStudio analyser …       → ligne de commande (traitement par lots)
   EclipseStudio --verifier       → auto-test de l'application empaquetée
=====================================================================
"""
import multiprocessing
import os
import sys


# ---------------------------------------------------------------------
# 1. Sorties standard absentes (application sans fenêtre de terminal)
# ---------------------------------------------------------------------
def _sorties_sures():
    """Sans terminal (macOS .app, Windows sans console), sys.stdout peut
    valoir None : le moindre print() planterait. On redirige vers le néant."""
    for nom in ("stdout", "stderr"):
        flux = getattr(sys, nom)
        if flux is None:
            setattr(sys, nom, open(os.devnull, "w", encoding="utf-8"))
        else:
            try:   # accents et symboles sans plantage, même sur une console Windows ancienne
                flux.reconfigure(encoding="utf-8", errors="replace")
            except Exception:  # noqa: BLE001
                pass


# ---------------------------------------------------------------------
# 2. Auto-test (utilisé après chaque construction)
# ---------------------------------------------------------------------
def _carre(x):
    return x * x


def verifier() -> int:
    """Vérifie que tout ce dont l'application a besoin est bien embarqué."""
    import importlib
    from concurrent.futures import ProcessPoolExecutor

    erreurs = []
    for mod in ("numpy", "cv2", "PIL", "imageio_ffmpeg",
                "eclipse_studio.serveur", "eclipse_studio.analyse", "eclipse_studio.modele",
                "eclipse_studio.modele_lunaire", "eclipse_studio.poussieres", "eclipse_studio.rendu",
                "eclipse_studio.export", "eclipse_studio.cli"):
        try:
            importlib.import_module(mod)
        except Exception as e:  # noqa: BLE001
            erreurs.append(f"module {mod} : {e}")
    # Fichiers de données (interface, villes, licence)
    try:
        from eclipse_studio import serveur
        for f in ("index.html", "logo.png"):
            if not os.path.exists(os.path.join(serveur.DOSSIER_UI, f)):
                erreurs.append(f"fichier d'interface manquant : {f}")
        lic = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(serveur.__file__))), "LICENSE")
        if not os.path.exists(lic):
            erreurs.append("fichier LICENSE manquant")
        from eclipse_studio import lieux
        if not lieux.chercher("Paris"):
            erreurs.append("liste des villes vide")
    except Exception as e:  # noqa: BLE001
        erreurs.append(f"données : {e}")
    # FFmpeg (export vidéo)
    try:
        import imageio_ffmpeg
        if not os.path.exists(imageio_ffmpeg.get_ffmpeg_exe()):
            erreurs.append("FFmpeg introuvable")
    except Exception as e:  # noqa: BLE001
        erreurs.append(f"FFmpeg : {e}")
    # Calcul parallèle (processus séparés) : le point sensible des exécutables
    try:
        with ProcessPoolExecutor(max_workers=2) as ex:
            if list(ex.map(_carre, range(6))) != [0, 1, 4, 9, 16, 25]:
                erreurs.append("calcul parallèle incorrect")
    except Exception as e:  # noqa: BLE001
        erreurs.append(f"calcul parallèle : {e}")
    # Lecture RAW (facultative)
    try:
        import rawpy  # noqa: F401
        raw = "oui"
    except Exception:  # noqa: BLE001
        raw = "non (aperçu JPEG intégré utilisé)"

    from eclipse_studio import __version__
    print(f"Éclipse Studio {__version__} — lecture RAW : {raw}")
    for e in erreurs:
        print("  ✗", e)
    print("VÉRIFICATION OK" if not erreurs else f"ÉCHEC : {len(erreurs)} problème(s)")
    return 0 if not erreurs else 1


# ---------------------------------------------------------------------
# 3. Aiguillage
# ---------------------------------------------------------------------
def principal():
    _sorties_sures()
    # macOS (anciennes versions) ajoute « -psn_… » quand on lance une .app : on l'ignore
    args = [a for a in sys.argv[1:] if not a.startswith("-psn_")]
    if args[:1] == ["--verifier"]:
        sys.exit(verifier())
    if args[:1] and args[0] in ("analyser", "modeliser", "exporter"):
        from eclipse_studio.cli import main as cli
        sys.exit(cli(args))
    sys.argv = [sys.argv[0]] + args
    from eclipse_studio.__main__ import main
    main()


if __name__ == "__main__":
    multiprocessing.freeze_support()   # indispensable : les processus de calcul relancent l'exécutable
    principal()
