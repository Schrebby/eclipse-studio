# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jérémy BEAUFRERE — JEREMiA (https://jerem-ia.fr)
# Éclipse Studio est un logiciel libre : vous pouvez le redistribuer et/ou le
# modifier selon les termes de la GNU GPL v3 ou ultérieure (voir LICENSE).
"""
=====================================================================
 Éclipse Studio — Ligne de commande (traitements par lots)
=====================================================================
 Exemples :
   python -m eclipse_studio.cli analyser  IMAGES PROJET --filtre "IMG_" --ext .cr2
   python -m eclipse_studio.cli modeliser PROJET --lat 47.66 --lon -3.20 --utc 2
   python -m eclipse_studio.cli exporter  PROJET video --palette halpha --taille 1080
=====================================================================
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time

from .analyse import Annulation, analyser
from .export import exporter
from .io_images import lister_images
from .modele import modeliser
from .projet import Projet


def _prog():
    t0 = time.time()
    dernier = [0.0]

    def progression(f, txt):
        if time.time() - dernier[0] > 2 or f >= 1:
            dernier[0] = time.time()
            print(f"  [{100 * f:5.1f} %] {txt}  ({time.time() - t0:.0f} s)", flush=True)
    return progression


def main(argv=None):
    ap = argparse.ArgumentParser(prog="eclipse_studio", description="Éclipse Studio — alignement et animation d'éclipses")
    sp = ap.add_subparsers(dest="cmd", required=True)

    a = sp.add_parser("analyser", help="détecter et aligner le Soleil sur toute la série")
    a.add_argument("images")
    a.add_argument("projet")
    a.add_argument("--ext", default="", help="extension à retenir, ex. .cr2 ou .fit")
    a.add_argument("--filtre", default="", help="texte que doit contenir le nom des fichiers")
    a.add_argument("--pas", type=int, default=1)
    a.add_argument("--diametre", type=int, default=1000, help="diamètre du Soleil dans le cache (px)")
    a.add_argument("--mono", action="store_true", help="ne pas conserver la couleur")
    a.add_argument("--processus", type=int, default=0)
    a.add_argument("--nouveau", action="store_true", help="ne pas reprendre une analyse interrompue")
    a.add_argument("--duree-max", type=float, default=0, help="s'arrêter proprement après N secondes (reprise ensuite)")

    m = sp.add_parser("modeliser", help="trajectoire lunaire, Soleil de référence, uniformisation")
    m.add_argument("projet")
    m.add_argument("--lat", type=float)
    m.add_argument("--lon", type=float, help="longitude, Est positive")
    m.add_argument("--utc", type=float, help="décalage horaire des dates EXIF (ex. 2 pour l'heure d'été française)")
    m.add_argument("--monture", choices=["auto", "equatoriale", "altaz"])
    m.add_argument("--trajectoire", choices=["auto", "ephemerides", "polynome"])
    m.add_argument("--uniformisation", choices=["aucune", "exposition", "couleur", "complete"])
    m.add_argument("--teinte", choices=["naturelle", "neutre", "chaude", "origine"])
    m.add_argument("--duree-max", type=float, default=0, help="s'arrêter proprement après N secondes (reprise ensuite)")
    m.add_argument("--nouveau", action="store_true", help="tout recalculer")

    e = sp.add_parser("exporter", help="produire vidéo / GIF / séquence / planche / CSV")
    e.add_argument("projet")
    e.add_argument("type", choices=["video", "gif", "png16", "tiff16", "jpeg", "planche", "frise", "csv"])
    e.add_argument("--rendu", default="", help="paramètres de rendu en JSON")
    e.add_argument("--palette")
    e.add_argument("--taille", type=int)
    e.add_argument("--fps", type=float)
    e.add_argument("--debut", type=int, default=0, help="1re image de la chronologie (séquences)")
    e.add_argument("--fin", type=int, help="dernière image exclue (séquences)")
    e.add_argument("--dossier", help="dossier de séquence à compléter")

    args = ap.parse_args(argv)
    journal = lambda t: print(t, flush=True)  # noqa: E731
    t_fin = time.time() + args.duree_max if getattr(args, "duree_max", 0) else None
    annule = lambda: bool(t_fin and time.time() > t_fin)  # noqa: E731

    if args.cmd == "analyser":
        fichiers = lister_images(args.images)
        if args.ext:
            fichiers = [f for f in fichiers if f.lower().endswith(args.ext.lower())]
        if args.filtre:
            fichiers = [f for f in fichiers if args.filtre in os.path.basename(f)]
        p = Projet(args.projet)
        p.donnees["dossier_images"] = os.path.abspath(args.images)
        pa = p.donnees["params_analyse"]
        pa.update({"pas": args.pas, "diametre_cache": args.diametre, "couleur": not args.mono,
                   "processus": args.processus})
        try:
            analyser(p, fichiers, _prog(), journal, annule, reprendre=not args.nouveau)
        except Annulation:
            print("⏸ Analyse interrompue (durée max) — relancez la même commande pour continuer.")
            return 3
    elif args.cmd == "modeliser":
        p = Projet.ouvrir(args.projet)
        pm = p.donnees["params_modele"]
        for cle, val in (("latitude", args.lat), ("longitude", args.lon), ("decalage_utc_h", args.utc),
                         ("monture", args.monture), ("trajectoire", args.trajectoire),
                         ("uniformisation", args.uniformisation), ("teinte_cible", args.teinte)):
            if val is not None:
                pm[cle] = val
        try:
            modeliser(p, _prog(), journal, annule, reprendre=not args.nouveau)
        except Annulation:
            print("⏸ Modélisation interrompue (durée max) — relancez la même commande pour continuer.")
            return 3
    elif args.cmd == "exporter":
        p = Projet.ouvrir(args.projet)
        pr = dict(p.donnees["params_rendu"])
        if args.rendu:
            pr.update(json.loads(args.rendu))
        if args.palette:
            pr["palette"] = args.palette
        if args.taille:
            pr["taille"] = args.taille
        if args.fps:
            pr["fps"] = args.fps
        opts = {"debut": args.debut, "fin": args.fin, "dossier": args.dossier}
        sortie = exporter(p, args.type, pr, _prog(), journal, annule, opts)
        print("→", sortie)
    return 0


if __name__ == "__main__":
    sys.exit(main())
