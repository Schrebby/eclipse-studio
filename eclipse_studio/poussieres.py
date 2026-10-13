# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jérémy BEAUFRERE — JEREMiA (https://jerem-ia.fr)
# Éclipse Studio est un logiciel libre : vous pouvez le redistribuer et/ou le
# modifier selon les termes de la GNU GPL v3 ou ultérieure (voir LICENSE).
"""
=====================================================================
 Éclipse Studio — Module POUSSIÈRES DU CAPTEUR
=====================================================================
 Une poussière posée sur le capteur (ou sur un filtre) fait une petite
 ombre TOUJOURS AU MÊME ENDROIT DU CAPTEUR, alors que le Soleil, lui,
 se déplace sur le capteur au fil de la série (dérive du suivi).
 Une tache solaire, au contraire, reste au même endroit DU SOLEIL.

 Méthode :
   1. Sur chaque image, on isole les petits détails sombres de la
      photosphère : rapport image / image très floutée (passe-haut),
      loin des bords du disque et de la Lune.
   2. Ces rapports sont reportés dans le repère du CAPTEUR et moyennés
      sur toute la série : les taches solaires (qui bougent sur le
      capteur) s'effacent dans la moyenne, les poussières (fixes) restent.
   3. Garde-fou : un point n'est déclaré « poussière » que si le Soleil
      a réellement bougé sous ce point pendant la série ; sinon on ne
      peut pas distinguer poussière et tache solaire → on n'y touche pas.
   4. Chaque image est divisée par la carte d'ombre des poussières
      (correction de type « flat »), avant toute autre opération.
=====================================================================
"""

from __future__ import annotations

import math
import os
from concurrent.futures import ProcessPoolExecutor

import cv2
import numpy as np

from .projet import Projet

FACTEUR = 0.5           # grille capteur à demi-échelle du cache (les ombres de poussières sont floues)
_CACHE_CARTE: dict = {}


def _grille(F: dict, taille) -> tuple[int, int, float]:
    s = F["echelle"] * FACTEUR
    return int(math.ceil(taille[0] * s)) + 2, int(math.ceil(taille[1] * s)) + 2, s


def _flou_norm(v: np.ndarray, w: np.ndarray, sig: float) -> np.ndarray:
    """Flou gaussien normalisé (moyenne locale pondérée par w)."""
    return cv2.GaussianBlur(v * w, (0, 0), sig) / np.maximum(cv2.GaussianBlur(w, (0, 0), sig), 1e-3)


def _passe_haut(L: np.ndarray, poids: np.ndarray, sig: float) -> np.ndarray:
    """log(image / fond local). Le fond est ré-estimé en EXCLUANT les creux
    déjà repérés : sinon la poussière elle-même abaisse le fond et sa
    profondeur est sous-estimée."""
    w = poids.astype(np.float32)
    lr = np.zeros_like(L, np.float32)
    for _ in range(3):
        fond = _flou_norm(L, w, sig)
        lr = np.clip(np.log(np.maximum(L, 1e-5) / np.maximum(fond, 1e-5)), -0.7, 0.3)
        w = poids * (lr > -0.008)
    return lr


def _travail(args):
    """Accumule, pour un paquet d'images, les détails sombres dans le repère capteur."""
    dossier, indices, H, W = args
    from .analyse import lire_png16
    p = Projet.ouvrir(dossier)
    F = p.donnees["forme"]
    e, hc = F["echelle"], F["hc"]
    Rc = F["A"] * e
    sig = max(5.0, 0.03 * Rc)            # échelle d'une ombre de poussière typique
    S = np.zeros((H, W), np.float32)
    Wt = np.zeros((H, W), np.float32)
    SU = np.zeros((H, W), np.float32)
    SV = np.zeros((H, W), np.float32)
    SQ = np.zeros((H, W), np.float32)
    SC = np.zeros((H, W), np.float32)      # nombre d'images où le point est assombri
    n = 2 * hc + 1
    yy, xx = np.mgrid[0:n, 0:n].astype(np.float32)
    for i in indices:
        im = p.images[i]
        try:
            src = lire_png16(p.chemin("cache", im["cache"]))
        except Exception:
            continue
        L = src if src.ndim == 2 else src @ np.array([0.2126, 0.7152, 0.0722], np.float32)
        if im.get("masque"):
            m = cv2.imdecode(np.fromfile(p.chemin("cache", im["masque"]), np.uint8), cv2.IMREAD_GRAYSCALE)
            val = (m > 250).astype(np.float32)
        else:
            val = np.ones_like(L)
        # Photosphère : zones nettement éclairées (exclut ciel, Lune, nuages épais)
        niveau = float(np.percentile(L[val > 0], 99)) if (val > 0).any() else 1.0
        photo = ((L > 0.45 * niveau) & (val > 0)).astype(np.float32)
        # Loin des bords (limbe, bord lunaire) : sinon le passe-haut y crée de faux creux
        # Loin des bords (limbe, bord lunaire) : sinon le passe-haut y crée de faux creux
        loin = (cv2.distanceTransform(photo.astype(np.uint8), cv2.DIST_L2, 5) > 2.0 * sig).astype(np.float32)
        if loin.sum() < 500:
            continue
        lr = _passe_haut(L, photo, sig) * loin
        # Repère capteur (demi-échelle) : simple translation + réduction
        s = FACTEUR
        M = np.array([[s, 0, (im["cx0"] * e - hc) * s], [0, s, (im["cy0"] * e - hc) * s]], np.float32)
        wl = cv2.warpAffine(loin, M, (W, H), flags=cv2.INTER_LINEAR)
        S += cv2.warpAffine(lr, M, (W, H), flags=cv2.INTER_LINEAR)
        Wt += wl
        # Position par rapport au Soleil (pour savoir si le Soleil a bougé sous ce point)
        u = (xx - hc) / Rc * loin
        v = (yy - hc) / Rc * loin
        SU += cv2.warpAffine(u, M, (W, H), flags=cv2.INTER_LINEAR)
        SV += cv2.warpAffine(v, M, (W, H), flags=cv2.INTER_LINEAR)
        SQ += cv2.warpAffine(u * u + v * v, M, (W, H), flags=cv2.INTER_LINEAR)
        SC += cv2.warpAffine(((lr < np.log(0.99)) * loin).astype(np.float32), M, (W, H), flags=cv2.INTER_LINEAR)
    return S, Wt, SU, SV, SQ, SC


def calculer_carte(projet: Projet, journal, progression, nproc: int) -> dict | None:
    """Construit modele/poussieres.npy (carte d'atténuation dans le repère capteur)."""
    F = projet.donnees["forme"]
    ims = projet.images
    utiles = [i for i, im in enumerate(ims) if im.get("statut") in ("ok", "ok-lune") and im.get("cache")]
    if len(utiles) < 10:
        return None
    taille = ims[utiles[0]].get("taille") or [3000, 4500]
    H, W, s = _grille(F, taille)
    paquets = [utiles[k::nproc * 2] for k in range(nproc * 2)]
    S = np.zeros((H, W), np.float32)
    Wt = np.zeros_like(S)
    SU = np.zeros_like(S)
    SV = np.zeros_like(S)
    SQ = np.zeros_like(S)
    SC = np.zeros_like(S)
    progression(0.02, "Recherche des poussières du capteur…")
    with ProcessPoolExecutor(max_workers=nproc) as ex:
        for r in ex.map(_travail, [(projet.dossier, pq, H, W) for pq in paquets if pq]):
            for acc, v in zip((S, Wt, SU, SV, SQ, SC), r):
                acc += v
    ok = Wt > 4
    moy = np.where(ok, S / np.maximum(Wt, 1e-6), 0.0)
    # Le Soleil a-t-il bougé sous ce point ? (écart-type de la position, en rayons solaires)
    mu = SU / np.maximum(Wt, 1e-6)
    mv = SV / np.maximum(Wt, 1e-6)
    disp = np.sqrt(np.maximum(SQ / np.maximum(Wt, 1e-6) - mu * mu - mv * mv, 0))
    Rc = F["A"] * F["echelle"]
    # Le Soleil doit avoir glissé d'au moins ~2 diamètres de tache sous le point
    discernable = ok & (disp > 0.06)
    # Poussière = creux (≥ 1,5 %) présent sur la grande majorité des images qui
    # couvrent ce point. Une tache solaire n'y passe que sur quelques images.
    frequence = SC / np.maximum(Wt, 1e-6)
    # Second passe-haut DANS LE REPÈRE CAPTEUR : retire les grandes structures
    # résiduelles (bord lunaire, assombrissement centre-bord) qui ne sont pas des poussières.
    Rg = Rc * FACTEUR                      # rayon solaire en pixels de la grille capteur
    fin = np.where(ok, _passe_haut(np.exp(moy).astype(np.float32), ok.astype(np.float32), max(3.0, 0.05 * Rg)), 0.0)
    # Seuils faibles (≥ 0,6 %) : une poussière loin du capteur ne fait qu'un
    # anneau très pâle ; c'est la RÉGULARITÉ (fréquence) qui la trahit.
    creux = (discernable & (fin < math.log(0.994)) & (frequence > 0.5)).astype(np.uint8)
    # Regroupement des points proches (un « donut » de poussière est souvent fragmenté)
    amas = cv2.dilate(creux, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5)))
    nb, etiq, _, _ = cv2.connectedComponentsWithStats(amas, 8)
    carte = np.ones((H, W), np.float32)
    garde = np.zeros((H, W), np.uint8)
    taches = 0
    wt_min = max(5.0, 0.1 * float(np.percentile(Wt[ok], 95))) if ok.any() else 5.0
    d_max = 0.25 * Rg                      # une ombre de poussière reste petite devant le Soleil
    for k in range(1, nb):
        sel = (etiq == k) & (creux > 0)
        pts = np.argwhere(sel)[:, ::-1].astype(np.int32)
        if len(pts) < 6:
            continue
        # Région = enveloppe convexe des points (remplit l'intérieur du donut)
        env = cv2.convexHull(pts)
        reg = np.zeros((H, W), np.uint8)
        cv2.fillConvexPoly(reg, env, 1)
        _, _, lw, lh = cv2.boundingRect(env)
        aire = int(reg.sum())
        if aire < 12 or max(lw, lh) > d_max:
            continue                       # trop petit (bruit) ou trop grand (artefact de bord)
        if max(lw, lh) > 2.5 * max(1, min(lw, lh)) or len(pts) < 0.15 * aire:
            continue                       # allongé ou clairsemé : traînée de tache solaire / bord lunaire
        if float(np.median(frequence[sel])) < 0.6:
            continue                       # pas assez régulier : pas fixe sur le capteur
        if float(Wt[reg > 0].min()) < wt_min:
            continue                       # trop peu d'images couvrent ce point (bord du champ)
        garde |= reg
        taches += 1
    if taches:
        zone = cv2.dilate(garde, np.ones((5, 5), np.uint8)).astype(bool) & ok
        carte[zone] = np.exp(np.minimum(fin[zone], 0.0))
        carte = cv2.GaussianBlur(carte, (0, 0), 0.8)
    non_disc = float((ok & ~discernable).sum() / max(1, ok.sum()))
    np.save(projet.chemin("modele", "poussieres.npy"), carte.astype(np.float32))
    info = {"nombre": int(taches), "facteur": s, "taille": [H, W],
            "attenuation_max": float(1 - carte.min()), "zone_indiscernable": non_disc}
    if taches:
        journal(f"{taches} poussière(s) du capteur détectée(s) et effacée(s) "
                f"(ombre la plus marquée : {100 * info['attenuation_max']:.0f} %)")
    else:
        journal("Aucune poussière du capteur détectée")
    if non_disc > 0.3:
        journal(f"⚠ Le Soleil a peu bougé sur le capteur sur {100 * non_disc:.0f} % de la zone : "
                "poussières et taches solaires y sont indiscernables, ces zones ne sont pas corrigées")
    _CACHE_CARTE.clear()
    return info


def carte_cache(projet: Projet, im: dict, n: int) -> np.ndarray | None:
    """Carte d'atténuation des poussières ramenée dans le recadrage (cache) d'une image."""
    if not projet.donnees["params_modele"].get("effacer_poussieres", True):
        return None
    ch = projet.chemin("modele", "poussieres.npy")
    if not os.path.exists(ch):
        return None
    cle = (ch, os.path.getmtime(ch))
    if cle not in _CACHE_CARTE:
        _CACHE_CARTE.clear()
        _CACHE_CARTE[cle] = np.load(ch)
    carte = _CACHE_CARTE[cle]
    if float(carte.min()) > 0.999:
        return None
    F = projet.donnees["forme"]
    e, hc, s = F["echelle"], F["hc"], FACTEUR
    # cache (x) → grille capteur (X) : X = s·(x + cx0·e − hc)  ⇒ inverse pour warpAffine
    M = np.array([[s, 0, (im["cx0"] * e - hc) * s], [0, s, (im["cy0"] * e - hc) * s]], np.float32)
    return cv2.warpAffine(carte, M, (n, n), flags=cv2.INTER_LINEAR | cv2.WARP_INVERSE_MAP,
                          borderMode=cv2.BORDER_CONSTANT, borderValue=1.0)


def appliquer(src: np.ndarray, cp: np.ndarray) -> np.ndarray:
    """Divise l'image par la carte d'ombre, UNIQUEMENT sur la photosphère.
    Dans le ciel ou sur la Lune, le signal est dominé par le fond (niveau
    de noir résiduel, lumière diffuse) : diviser y créerait un anneau clair."""
    L = src if src.ndim == 2 else src.mean(axis=2)
    niveau = float(np.percentile(L, 99.5)) or 1.0
    w = np.clip((L / niveau - 0.25) / 0.25, 0.0, 1.0)          # 0 dans le ciel → 1 sur le disque
    w = cv2.GaussianBlur(w.astype(np.float32), (0, 0), 2.0)
    gain = 1.0 + w * (1.0 / np.maximum(cp, 0.2) - 1.0)
    return src * gain[:, :, None] if src.ndim == 3 else src * gain
