# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jérémy BEAUFRERE — JEREMiA (https://jerem-ia.fr)
# Éclipse Studio est un logiciel libre : vous pouvez le redistribuer et/ou le
# modifier selon les termes de la GNU GPL v3 ou ultérieure (voir LICENSE).
"""
=====================================================================
 Éclipse Studio — Module PROJET (sauvegarde / chargement)
=====================================================================
 Un projet = un dossier de travail contenant :
   projet.json        paramètres + résultats image par image
   points.npz         points de limbe détectés (pour ré-ajustements)
   cache/             images recadrées, centrées, 16 bits (PNG)
   modele/            Soleil de référence reconstitué, etc.
   exports/           vidéos, GIF, séquences, planches
 Tout est réouvrable sans refaire l'analyse.
=====================================================================
"""

from __future__ import annotations

import datetime as dt
import json
import os
import threading

import numpy as np

VERSION_PROJET = 1


# ---------------------------------------------------------------------
# PARAMÈTRES PAR DÉFAUT
# ---------------------------------------------------------------------
PARAMS_ANALYSE = {
    "type_eclipse": "auto",      # auto | solaire | lunaire
    "diametre_cache": 1000,      # diamètre du Soleil dans le cache (px)
    "marge_cache": 0.55,         # champ conservé autour du Soleil (× rayon)
    "couleur": True,             # garder la couleur (nécessaire à l'uniformisation des teintes)
    "raw_demi": "auto",          # RAW/CFA à demi-résolution : auto / oui / non
    "aplatissement": True,       # modéliser l'aplatissement (réfraction près de l'horizon)
    "ecart_max_interp_s": 900,   # trou max (s) comblé par interpolation de trajectoire
    "processus": 0,              # 0 = automatique (nb de cœurs − 1)
    "pas": 1,                    # 1 image sur N
}

PARAMS_MODELE = {
    "latitude": None,            # lieu d'observation (degrés, Nord +)
    "longitude": None,           # (degrés, Est +)
    "decalage_utc_h": None,      # heure EXIF − UTC (h) ; None = auto (FITS = UTC)
    "monture": "auto",           # auto (rotation mesurée via la Lune) | equatoriale | altaz
    "sens_derotation": 1,        # +1 / −1
    "trajectoire": "auto",       # auto | ephemerides | polynome
    "uniformisation": "complete",  # aucune | exposition | couleur | complete
    "lissage_photometrique": 5,  # lissage temporel des corrections (images)
    "effacer_poussieres": True,  # détecter et effacer les poussières du capteur
    "teinte_cible": "naturelle",   # naturelle | neutre | chaude | origine
}

PARAMS_RENDU = {
    "lumiere_lune": "hdr",       # éclipse de Lune : hdr | reelle | compensee
    "compression_hdr": 0.0002,   # éclipse de Lune : plus petit = ombre plus visible
    "taille": 1080,              # taille de la vidéo (px, carré)
    "marge": 0.35,               # marge autour du disque (× rayon)
    "palette": "naturel",
    "point_noir": 0.02,
    "point_blanc": 1.0,
    "gamma": 1.0,
    "contraste": 0.0,            # courbe en S (−1..1)
    "saturation": 1.0,
    "accentuation": 0.0,         # masque flou (0..3)
    "rayon_accentuation": 2.0,
    "aplanir_limbe": 0.0,        # correction de l'assombrissement centre-bord (0..1)
    "redresser_ellipse": True,   # rendre le disque parfaitement rond
    "rotation": 0.0,             # rotation libre (°)
    "miroir_h": False,
    "miroir_v": False,
    "ciel_noir": "auto",          # auto | True | False (couronne en totalité)
    "corriger_horloge": True,     # appliquer le décalage d'horloge trouvé par les éphémérides
    "reconstituer_coupes": True,  # compléter les soleils coupés
    "synthese_debut_fin": True,   # recréer début / fin d'éclipse
    "marge_synthese_s": 120,      # disque plein avant C1 / après C4 (s)
    "cadence_synthese_s": None,   # rythme des images recréées (s) ; None = celui de la prise de vue
    "combler_trous": True,        # recréer les images manquantes (nuages épais)
    "lissage_temporel": 1,        # moyenne glissante (images)
    "inc_heure": True,
    "inc_obscuration": True,
    "inc_titre": "",
    "inc_credit": "",
    "inc_reconstitue": True,      # mention « reconstitué » sur les images de synthèse
    "fuseau_affichage_h": None,   # décalage pour afficher l'heure locale ; None = UTC
    "fps": 25,
    "fond": [0, 0, 0],
}


def _json_defaut(o):
    if isinstance(o, (dt.datetime, dt.date)):
        return o.isoformat()
    if isinstance(o, (np.floating,)):
        return float(o)
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, np.ndarray):
        return o.tolist()
    raise TypeError(str(type(o)))


class Projet:
    """Conteneur de l'état complet d'un projet."""

    def __init__(self, dossier: str):
        self.dossier = os.path.abspath(dossier)
        self.verrou = threading.RLock()
        self.donnees: dict = {
            "version": VERSION_PROJET,
            "cree": dt.datetime.now().isoformat(timespec="seconds"),
            "dossier_images": "",
            "params_analyse": dict(PARAMS_ANALYSE),
            "params_modele": dict(PARAMS_MODELE),
            "params_rendu": dict(PARAMS_RENDU),
            "forme": None,
            "images": [],
            "modele": {},
            "etape": "vide",
        }
        self.points: dict[int, np.ndarray] = {}

    # ---- chemins ----
    def chemin(self, *parties) -> str:
        return os.path.join(self.dossier, *parties)

    @property
    def images(self) -> list[dict]:
        return self.donnees["images"]

    # ---- persistance ----
    def sauver(self):
        with self.verrou:
            os.makedirs(self.dossier, exist_ok=True)
            tmp = self.chemin("projet.json.tmp")
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.donnees, f, ensure_ascii=False, indent=1, default=_json_defaut)
            os.replace(tmp, self.chemin("projet.json"))
            if self.points:
                np.savez_compressed(self.chemin("points.npz"),
                                    **{f"i{k}": v for k, v in self.points.items()})

    @classmethod
    def ouvrir(cls, dossier: str) -> "Projet":
        p = cls(dossier)
        with open(p.chemin("projet.json"), encoding="utf-8") as f:
            d = json.load(f)
        # Compléter les paramètres apparus dans une version plus récente
        for cle, defaut in (("params_analyse", PARAMS_ANALYSE), ("params_modele", PARAMS_MODELE),
                            ("params_rendu", PARAMS_RENDU)):
            base = dict(defaut)
            base.update(d.get(cle, {}))
            d[cle] = base
        p.donnees.update(d)
        if os.path.exists(p.chemin("points.npz")):
            with np.load(p.chemin("points.npz")) as z:
                p.points = {int(k[1:]): z[k] for k in z.files}
        return p

    # ---- temps ----
    def temps_utc(self, im: dict) -> dt.datetime | None:
        """Date UTC d'une image (en tenant compte du décalage horaire EXIF)."""
        if not im.get("t"):
            return None
        t = dt.datetime.fromisoformat(im["t"])
        if im.get("utc"):
            return t
        dec = self.donnees["params_modele"].get("decalage_utc_h")
        if dec is None:
            return t   # inconnu : supposé UTC
        return t - dt.timedelta(hours=float(dec))

    def secondes(self) -> np.ndarray:
        """Temps relatifs (s) de toutes les images (indices pour séries sans date)."""
        ts = [im.get("t") for im in self.images]
        if not ts or any(t is None for t in ts):
            return np.arange(len(self.images), dtype=float)
        t0 = dt.datetime.fromisoformat(ts[0])
        s = np.array([(dt.datetime.fromisoformat(t) - t0).total_seconds() for t in ts])
        # Dates du fichier identiques (copie) → repli sur l'ordre des fichiers
        if len(s) > 1 and np.ptp(s) == 0:
            return np.arange(len(self.images), dtype=float)
        return s
