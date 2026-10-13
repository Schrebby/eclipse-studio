# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jérémy BEAUFRERE — JEREMiA (https://jerem-ia.fr)
# Éclipse Studio est un logiciel libre : vous pouvez le redistribuer et/ou le
# modifier selon les termes de la GNU GPL v3 ou ultérieure (voir LICENSE).
"""Compare les résultats d'un projet à la vérité terrain du générateur synthétique."""
import json, math, sys
sys.path.insert(0, __file__.rsplit("/tests", 1)[0])
import numpy as np
from eclipse_studio.projet import Projet
p = Projet.ouvrir(sys.argv[1]); v = json.load(open(sys.argv[2]))
vt = {x["nom"]: x for x in v["images"]}
F = p.donnees["forme"]
print(f"A={F['A']:.2f} (vrai {v['A']})  k={F['k']:.4f} theta={math.degrees(F['theta']):.1f}° (vrai {math.degrees(v['theta']):.1f}°)")
errs = []
for im in p.images:
    t = vt[im["nom"]]
    e = math.hypot(im["cx"] - t["cx"], im["cy"] - t["cy"]) if im.get("cx") is not None else float("nan")
    errs.append(e)
    lm = im.get("lune_modele"); l = im.get("lune")
    el = math.hypot(lm[0]-t["lune"][0], lm[1]-t["lune"][1]) if lm else float("nan")
    print(f"{im['nom']} {im['statut']:9s} err={e:6.3f}px k={im.get('k_lisse',0):.4f}/{t['k']:.4f} vis={im.get('visible',0):.2f} lune_err={el:.4f} sig={im.get('sigma',0):.3f}")
e = np.array(errs); ok = np.isfinite(e)
print(f"Erreur centre : médiane {np.median(e[ok]):.3f} px, max {e[ok].max():.3f} px, RMS {np.sqrt(np.mean(e[ok]**2)):.3f} px")
