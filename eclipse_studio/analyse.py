# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jérémy BEAUFRERE — JEREMiA (https://jerem-ia.fr)
# Éclipse Studio est un logiciel libre : vous pouvez le redistribuer et/ou le
# modifier selon les termes de la GNU GPL v3 ou ultérieure (voir LICENSE).
"""
=====================================================================
 Éclipse Studio — Module ANALYSE (alignement de la série)
=====================================================================
 Étape A — ÉTALONNAGE : sur ~24 images réparties dans la série, on
           mesure une ellipse libre → rayon solaire A de la série et
           orientation θ de l'aplatissement.
 Étape B — DÉTECTION (parallèle, tous les cœurs) : pour chaque image,
           centre du Soleil au sous-pixel avec la forme connue, puis
           extraction d'un recadrage centré 16 bits dans le cache
           + masque des zones hors capteur (soleils coupés).
 Étape C — TRAJECTOIRE : lissage de l'aplatissement k(t), ré-ajustement
           des centres, rejet des sauts isolés (erreurs), interpolation
           temporelle des images ratées (nuages épais, totalité).
=====================================================================
"""

from __future__ import annotations

import datetime as dt
import math
import os
import time
import traceback
from concurrent.futures import ProcessPoolExecutor, as_completed

import cv2
import numpy as np

from .detection import Forme, ajuster_ellipse, detecter_disque
from . import astro
from .io_images import charger_image, famille, horodatage, infos_prise_de_vue, niveau_blanc_probable
from .projet import Projet


class Annulation(Exception):
    """Levée quand l'utilisateur interrompt le traitement."""


# ---------------------------------------------------------------------
# 1. OUTILS
# ---------------------------------------------------------------------
def nb_processus(demande: int) -> int:
    if demande and demande > 0:
        return int(demande)
    return max(1, (os.cpu_count() or 2) - 1)


def ecrire_png16(chemin: str, img: np.ndarray):
    """Écrit un PNG 16 bits (mono ou RGB float 0..1) — chemins unicode OK."""
    u16 = np.clip(img * 65535.0 + 0.5, 0, 65535).astype(np.uint16)
    if u16.ndim == 3:
        u16 = cv2.cvtColor(u16, cv2.COLOR_RGB2BGR)
    ok, buf = cv2.imencode(".png", u16, [cv2.IMWRITE_PNG_COMPRESSION, 1])
    if not ok:
        raise IOError("écriture PNG impossible")
    buf.tofile(chemin)


def lire_png16(chemin: str) -> np.ndarray:
    data = np.fromfile(chemin, dtype=np.uint8)
    img = cv2.imdecode(data, cv2.IMREAD_UNCHANGED)
    if img is None:
        raise IOError(f"cache illisible : {chemin}")
    if img.ndim == 3:
        img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    div = 65535.0 if img.dtype == np.uint16 else 255.0
    return img.astype(np.float32) / div


def coords_ellipse(n: int, centre: float, A: float, k: float, theta: float):
    """Coordonnées normalisées (ρ) de chaque pixel d'une grille n×n
    par rapport à une ellipse centrée (1 = sur le limbe)."""
    y, x = np.mgrid[0:n, 0:n].astype(np.float32)
    dx, dy = x - centre, y - centre
    c, s = math.cos(theta), math.sin(theta)
    xp = (dx * c + dy * s) / A
    yp = (-dx * s + dy * c) / (A * k)
    return np.sqrt(xp * xp + yp * yp)


# ---------------------------------------------------------------------
# 2. TRAVAIL D'UNE IMAGE (exécuté dans un processus séparé)
# ---------------------------------------------------------------------
def _travail_etalonnage(args):
    chemin, demi, rayon_approx, idx = (tuple(args) + (None, None))[:4]
    try:
        # Mesure rapide à demi-résolution (le rayon reste précis au dixième de pixel),
        # ramenée ensuite à l'échelle de travail.
        rapide = famille(chemin) in ("raw", "fits")
        img, infos = charger_image(chemin, couleur=False, raw_demi=(demi or rapide))
        echelle_mes = 1.0
        if rapide and not demi:
            echelle_mes = 2.0
        elif not rapide and max(img.shape) > 3000:
            img = cv2.resize(img, None, fx=0.5, fy=0.5, interpolation=cv2.INTER_AREA)
            echelle_mes = 2.0
        maximum = infos.get("maximum", float(img.max()))
        r = detecter_disque(img, forme=None, etalonnage=True,
                            rayon_approx=None if rayon_approx is None else rayon_approx / echelle_mes)
        if r.forme is not None:
            r.forme.A *= echelle_mes
            r.largeur_bord *= echelle_mes
        return {"index": idx, "ok": r.ok and r.mode == "soleil", "A": r.forme.A if r.forme else None,
                "k": r.forme.k if r.forme else None, "theta": r.forme.theta if r.forme else None,
                "couverture": r.couverture, "residu": r.residu, "methode": infos["methode"],
                "taille": list(img.shape[:2]), "maximum": maximum,
                "largeur_bord": r.largeur_bord, "fond_relatif": r.fond_relatif}
    except Exception as e:  # pragma: no cover
        return {"index": idx, "ok": False, "erreur": str(e)}


def mediane_ponderee(v, w) -> float:
    v, w = np.asarray(v, float), np.asarray(w, float)
    o = np.argsort(v)
    c = np.cumsum(w[o])
    return float(v[o][np.searchsorted(c, 0.5 * c[-1])])


def extraire_cache(img, lum, idx, cx, cy, k, f, echelle, hc, dossier_cache):
    """Recadre l'image autour du centre (cx, cy), la met à l'échelle du cache,
    écrit le PNG 16 bits (+ masque des zones hors capteur) et mesure la
    photométrie du disque. Renvoie un dict d'infos, ou None si hors champ."""
    n = 2 * hc + 1
    h, w = lum.shape[:2]
    demi_roi = (hc + 3) / echelle
    x0, x1 = int(math.floor(cx - demi_roi)), int(math.ceil(cx + demi_roi)) + 1
    y0, y1 = int(math.floor(cy - demi_roi)), int(math.ceil(cy + demi_roi)) + 1
    xa, xb, ya, yb = max(0, x0), min(w, x1), max(0, y0), min(h, y1)
    if xb <= xa or yb <= ya:
        return None
    roi = img[ya:yb, xa:xb]
    if echelle < 0.8:  # anti-repliement avant réduction
        sig = 0.45 / echelle
        roi = cv2.GaussianBlur(roi, (0, 0), sig)
    M = np.array([[echelle, 0, hc - echelle * (cx - xa)],
                  [0, echelle, hc - echelle * (cy - ya)]], np.float32)
    crop = cv2.warpAffine(roi, M, (n, n), flags=cv2.INTER_LINEAR,
                          borderMode=cv2.BORDER_CONSTANT, borderValue=0)
    # Masque de validité : 255 = pixel réellement mesuré par le capteur
    un = np.full((yb - ya, xb - xa), 255, np.uint8)
    # Les bords extrêmes du capteur (dématriçage, vignetage) sont écartés
    bord = max(4, int(0.003 * max(h, w)))
    if ya == 0:
        un[:bord, :] = 0
    if yb == h:
        un[-bord:, :] = 0
    if xa == 0:
        un[:, :bord] = 0
    if xb == w:
        un[:, -bord:] = 0
    masque = cv2.warpAffine(un, M, (n, n), flags=cv2.INTER_LINEAR,
                            borderMode=cv2.BORDER_CONSTANT, borderValue=0)
    nom = f"img_{idx:05d}"
    ecrire_png16(os.path.join(dossier_cache, nom + ".png"), crop)
    complet = bool(masque.min() >= 250)
    if not complet:
        ok, buf = cv2.imencode(".png", masque)
        buf.tofile(os.path.join(dossier_cache, nom + "_masque.png"))
    # ---- Photométrie (Soleil connu : ellipse au centre du cache) ----
    lumc = crop if crop.ndim == 2 else crop @ np.array([0.2126, 0.7152, 0.0722], np.float32)
    Ac = f.A * echelle
    rho = coords_ellipse(n, hc, Ac, k, f.theta)
    disque = (rho < 0.95) & (masque > 250)
    visible_frac = float(((rho < 1.0) & (masque > 250)).sum() / max(1, (rho < 1.0).sum()))
    mu = np.sqrt(np.clip(1 - rho * rho, 0, 1))
    L = 1 - 0.55 * (1 - mu)
    info_photo = {"I0": None, "obscuration": None, "saturation": 0.0}
    if disque.sum() > 100:
        ratio = lumc[disque] / L[disque]
        p99 = float(np.percentile(ratio, 99))
        eclaire = ratio > 0.35 * p99
        if eclaire.sum() > 50:
            I0 = float(np.median(ratio[eclaire]))
            info_photo["I0"] = I0
            info_photo["obscuration"] = float(1 - eclaire.mean())
            info_photo["saturation"] = float((lumc[disque][eclaire] > 0.985).mean())
            if crop.ndim == 3:
                info_photo["couleur"] = [float(np.median(crop[:, :, c][disque][eclaire] / L[disque][eclaire]))
                                         for c in range(3)]
    info_photo.update({"cx0": cx, "cy0": cy, "cache": nom + ".png",
                       "masque": None if complet else nom + "_masque.png",
                       "visible": visible_frac})
    return info_photo


def _travail_image(args):
    """Détection + extraction du recadrage pour UNE image.
    Renvoie un dictionnaire de résultats (sérialisable)."""
    (idx, chemin, forme, demi, couleur, k_libre, echelle, hc, dossier_cache, blanc, type_ecl) = args
    out = {"index": idx, "ok": False, "mode": "echec", "message": ""}
    try:
        img, infos = charger_image(chemin, couleur=couleur, raw_demi=demi, blanc=blanc)
        lum = img if img.ndim == 2 else (0.2126 * img[:, :, 0] + 0.7152 * img[:, :, 1] + 0.0722 * img[:, :, 2])
        f = Forme(*forme)
        # Éclipse de Lune : le disque suivi est la Lune elle-même (pas de recherche de disque sombre)
        r = detecter_disque(lum, forme=f, k_libre=k_libre, mode_lune=(type_ecl != "lunaire"))
        out.update({"ok": bool(r.ok), "mode": r.mode, "cx": r.cx, "cy": r.cy,
                    "k": r.forme.k if r.forme else f.k, "sigma": r.sigma_centre, "sigma_k": r.sigma_k,
                    "couverture": r.couverture, "residu": r.residu, "nettete": r.nettete,
                    "message": r.message, "methode": infos["methode"], "taille": list(lum.shape[:2])})
        if not np.isfinite(r.cx):
            out["message"] = r.message or "Soleil introuvable"
            return out, None
        info = extraire_cache(img, lum, idx, float(r.cx), float(r.cy), out["k"], f, echelle, hc, dossier_cache)
        if info is None:
            out["message"] = "Soleil hors champ"
            return out, None
        out.update(info)
        return out, r.points
    except Exception as e:
        out["message"] = f"erreur : {e}"
        out["trace"] = traceback.format_exc(limit=3)
        return out, None


# ---------------------------------------------------------------------
# 3. ÉTAPE A : ÉTALONNAGE DE LA FORME
# ---------------------------------------------------------------------
def _moyenne_angle_axial(thetas, poids):
    """Moyenne d'angles définis modulo 180° (axes)."""
    c = np.sum(poids * np.cos(2 * thetas))
    s = np.sum(poids * np.sin(2 * thetas))
    return 0.5 * math.atan2(s, c)


def message_inexploitable(F: dict | None, type_ecl: str | None = None) -> str | None:
    """Renvoie un message clair si la série ne permet PAS un alignement sur le
    disque (paysage grand-angle, Soleil sans filtre…), sinon None.
    Un projet créé par une version antérieure (sans contrôle) est vérifié
    avec les mesures disponibles."""
    if not F:
        return None
    astre = "de la Lune" if (type_ecl == "lunaire" or F.get("type") == "lunaire") else "du Soleil"
    c = F.get("controle") or {}
    raisons = []
    if F.get("A", 0) < 90:
        raisons.append(f"disque trop petit ({F.get('A', 0):.0f} px de rayon)")
    if c and c.get("couverture", 1) < 0.25:
        raisons.append(f"bord net visible sur seulement {100 * c['couverture']:.0f} % du tour")
    disp = c.get("dispersion", F.get("dispersion_rayon", 0))
    if disp > 0.15 or (disp > 0.05 and c.get("largeur_bord", 0) > 0.03):
        raisons.append(f"taille incohérente d'une image à l'autre ({100 * disp:.0f} %)")
    if (1 - F.get("k", 1)) > 0.15:
        raisons.append("forme très éloignée d'un disque")
    if not raisons:
        return None
    return (f"Ces photos ne montrent pas un disque net {astre} : " + " ; ".join(raisons) + ". "
            "C'est typique de photos de PAYSAGE au grand-angle ou d'un Soleil photographié sans filtre "
            "(tache surexposée et halo : le croissant n'est pas enregistré). L'alignement sur le disque et "
            "la reconstitution de l'éclipse sont donc impossibles avec cette série. Il faut des photos au "
            "téléobjectif, avec filtre solaire, où le disque mesure au moins ~200 px de diamètre.")


def etalonner(projet: Projet, executeur, journal, annule, progression=None) -> dict:
    """1) PHOTO PIVOT : la photo du milieu de la série (la plus proche qui donne
          un disque net) fixe un premier rayon.
       2) TOUTES LES PHOTOS sont ensuite mesurées (rayon cherché à ±15 % du pivot)
          → rayon, aplatissement et orientation déduits de l'ensemble de la série
          (médiane pondérée par la part du bord visible sur chaque photo)."""
    ims = projet.images
    pa = projet.donnees["params_analyse"]
    n = len(ims)
    progression = progression or (lambda f, t: None)
    milieu = n // 2
    ordre = sorted(range(n), key=lambda i: abs(i - milieu))
    # Décision demi-résolution pour RAW / FITS CFA
    demi = pa["raw_demi"] == "oui"
    fam0 = famille(ims[0]["chemin"])
    if pa["raw_demi"] == "auto" and fam0 in ("raw", "fits"):
        essai = _travail_etalonnage((ims[milieu]["chemin"], True))
        if essai.get("ok") and 2 * essai["A"] >= 1.15 * pa["diametre_cache"]:
            demi = True
    etat = projet.donnees.setdefault("etal_partiel", {})
    if etat.get("demi") is not None:
        demi = etat["demi"]
    # ---- 1. Photo pivot (milieu de la série) ----
    if etat.get("A_pivot") is None:
        pivot = None
        candidats = ordre[:9]
        resultats = list(executeur.map(_travail_etalonnage, [(ims[i]["chemin"], demi, None, i) for i in candidats]))
        for i, r in zip(candidats, resultats):
            if r.get("ok") and r["couverture"] >= 0.3 and r["residu"] < 3.0 + 0.01 * r["A"]:
                pivot = (i, r)
                break
        if pivot is None:
            ok = [(i, r) for i, r in zip(candidats, resultats) if r.get("ok")]
            pivot = max(ok, key=lambda ir: ir[1]["couverture"]) if ok else None
        if pivot is None:
            raise RuntimeError("Impossible de trouver le disque sur les photos du milieu de la série.")
        etat.update({"A_pivot": pivot[1]["A"], "pivot": ims[pivot[0]]["nom"], "demi": demi, "mesures": {}})
        projet.sauver()
    A_pivot = etat["A_pivot"]
    projet.donnees["photo_pivot"] = etat["pivot"]
    journal(f"Photo pivot (milieu de la série) : {etat['pivot']} — rayon {A_pivot:.1f} px")
    # ---- 2. Toutes les photos (sauvegarde régulière : reprise possible) ----
    deja = etat.setdefault("mesures", {})
    journal(f"Mesure du disque sur les {n} photos" + (" (demi-résolution RAW)" if demi else ""))
    restants = [i for i in range(n) if str(i) not in deja]
    futurs = [executeur.submit(_travail_etalonnage, (ims[i]["chemin"], demi, A_pivot, i)) for i in restants]
    derniere = time.time()
    try:
        for fu in as_completed(futurs):
            r = fu.result()
            if r.get("index") is not None:
                deja[str(r["index"])] = {c: r.get(c) for c in ("ok", "A", "k", "theta", "couverture", "residu",
                                                                "methode", "maximum", "largeur_bord", "fond_relatif")}
            progression(0.02 + 0.28 * len(deja) / n, f"Mesure du disque {len(deja)}/{n}")
            if time.time() - derniere > 20:
                projet.sauver()
                derniere = time.time()
            if annule():
                for f2 in futurs:
                    f2.cancel()
                raise Annulation()
    except Annulation:
        projet.donnees["etape"] = "etalonnage-partiel"
        projet.sauver()
        raise
    mesures = []
    for k_, r in deja.items():
        ims[int(k_)]["etalonnage"] = {c: r.get(c) for c in ("ok", "A", "k", "couverture", "residu")}
        if r.get("ok"):
            mesures.append(r)
    bons = [m for m in mesures if m["couverture"] >= 0.3 and m["residu"] < 3.0 + 0.01 * m["A"]]
    if not bons:
        bons = mesures
    if not bons:
        raise RuntimeError("Impossible de trouver le disque solaire sur les images d'étalonnage.")
    A = mediane_ponderee([m["A"] for m in bons], [m["couverture"] for m in bons])
    journal(f"Rayon mesuré sur {len(bons)} photos exploitables sur {n}")
    ks = np.array([m["k"] for m in bons])
    th = np.array([m["theta"] for m in bons])
    aplat = (1 - ks)
    if pa.get("aplatissement", True) and np.any(aplat > 0.004):
        theta = _moyenne_angle_axial(th, np.clip(aplat, 0, None) ** 2 + 1e-9)
        k = float(np.median(ks))
    else:
        theta, k = 0.0, 1.0
    dispersion = float(np.std([m["A"] for m in bons]) / A)
    blanc = None
    if famille(ims[0]["chemin"]) == "fits":
        blanc = niveau_blanc_probable(max(m.get("maximum", 1.0) for m in mesures))
        if blanc < 1.0:
            journal(f"FITS : saturation du capteur à {blanc * 65535:.0f}/65535, ramenée à 1")
    forme = {"A": A, "k": k, "theta": theta, "demi": demi, "dispersion_rayon": dispersion,
             "methode": bons[0]["methode"], "blanc": blanc}
    journal(f"Rayon du disque : {A:.1f} px, aplatissement médian {100 * (1 - k):.2f} %, "
            f"orientation {math.degrees(theta):.1f}°")
    # ---- Garde-fous : la série permet-elle un alignement sur le disque ? ----
    # Un disque photographié avec filtre (ou la Lune) a un bord net, bien visible
    # sur une grande partie du tour, et une taille stable. Une tache surexposée
    # (Soleil sans filtre, paysage au grand-angle) n'a rien de tout cela.
    astre = "de la Lune" if projet.donnees["params_analyse"].get("type_eclipse") == "lunaire" else "du Soleil"
    tous_A = np.array([m["A"] for m in mesures if m.get("A")])
    disp_rob = float(1.4826 * np.median(np.abs(tous_A - np.median(tous_A))) / max(1e-6, np.median(tous_A))) \
        if len(tous_A) >= 3 else 0.0
    couv_med = float(np.median([m["couverture"] for m in mesures])) if mesures else 0.0
    larg_rel = float(np.median([m.get("largeur_bord", 0) / max(1.0, m["A"]) for m in mesures])) if mesures else 0.0
    journal(f"Contrôle de la série : bord vu sur {100 * couv_med:.0f} % du tour, largeur du bord "
            f"{100 * larg_rel:.1f} % du rayon, stabilité du rayon {100 * disp_rob:.1f} %")
    forme["controle"] = {"couverture": couv_med, "largeur_bord": larg_rel, "dispersion": disp_rob}
    msg = message_inexploitable(forme, projet.donnees["params_analyse"].get("type_eclipse"))
    if msg:
        raise RuntimeError(msg)
    if dispersion > 0.03:
        journal("⚠ Le rayon varie de plus de 3 % : zoom/focale modifiés pendant la série ?")
    return forme


# ---------------------------------------------------------------------
# 4. ÉTAPE C : TRAJECTOIRE ET CONTRÔLE
# ---------------------------------------------------------------------
def lissage_local(t: np.ndarray, v: np.ndarray, t_cible: np.ndarray, voisins: int = 9) -> np.ndarray:
    """Régression linéaire locale robuste (les « voisins » points les plus proches
    en temps) évaluée à chaque instant voulu. Suit bien les tendances, y compris
    aux extrémités de la série (contrairement à une médiane glissante)."""
    if len(v) == 0:
        return np.full(len(t_cible), np.nan)
    if len(v) < 3:
        return np.full(len(t_cible), float(np.median(v)))
    out = np.empty(len(t_cible))
    for j, tc in enumerate(t_cible):
        sel = np.argsort(np.abs(t - tc))[:voisins]
        tt, vv = t[sel], v[sel]
        if np.ptp(tt) == 0:
            out[j] = float(np.median(vv))
            continue
        w = np.ones(len(vv))
        for _ in range(3):
            a, b = np.polyfit(tt - tc, vv, 1, w=w)
            r = vv - (a * (tt - tc) + b)
            w = 1.0 / (1.0 + (r / max(1e-5, 2.5 * np.median(np.abs(r)))) ** 2)
        out[j] = b
    return out


def recadrer(projet: Projet, i: int, cx: float, cy: float):
    """Ré-extrait le cache d'une image autour d'un centre imposé (interpolé)."""
    F = projet.donnees["forme"]
    pa = projet.donnees["params_analyse"]
    im = projet.images[i]
    img, _ = charger_image(im["chemin"], couleur=bool(pa["couleur"]), raw_demi=F["demi"], blanc=F.get("blanc"))
    lum = img if img.ndim == 2 else img @ np.array([0.2126, 0.7152, 0.0722], np.float32)
    f = Forme(F["A"], im.get("k_lisse", F["k"]), F["theta"])
    info = extraire_cache(img, lum, i, cx, cy, f.k, f, F["echelle"], F["hc"], projet.chemin("cache"))
    if info is None:
        raise RuntimeError("Soleil hors champ")
    im.update(info)


def consolider(projet: Projet, journal):
    """Étape C : rend la trajectoire du Soleil cohérente sur toute la série."""
    ims = projet.images
    F = projet.donnees["forme"]
    secs = projet.secondes()
    pa = projet.donnees["params_analyse"]
    n = len(ims)

    # ---- C1. Aplatissement lissé dans le temps ----
    bons_k = [i for i, im in enumerate(ims) if im.get("ok") and im.get("mode") == "soleil"
              and im.get("sigma_k", 1) < 0.004 and im.get("couverture", 0) > 0.3]
    if F["k"] < 1.0 and len(bons_k) >= 3:
        k_l = lissage_local(secs[bons_k], np.array([ims[i]["k"] for i in bons_k]), secs, 9)
    else:
        k_l = np.full(n, F["k"])
    for i, im in enumerate(ims):
        im["k_lisse"] = float(np.clip(k_l[i], 0.6, 1.0))

    # ---- C2. Ré-ajustement des centres avec k(t) lissé ----
    for i, im in enumerate(ims):
        if im.get("ok") and im.get("mode") == "soleil" and i in projet.points and len(projet.points[i]) >= 8:
            forme = Forme(F["A"], im["k_lisse"], F["theta"])
            vals, sig, rms, _ = ajuster_ellipse(projet.points[i], im["cx"], im["cy"], forme, ("cx", "cy"),
                                                echelle=max(1.5, 0.004 * F["A"]))
            im["cx"], im["cy"] = float(vals["cx"]), float(vals["cy"])
            im["sigma"] = float(math.hypot(sig["cx"], sig["cy"]))
        im["statut"] = "exclu" if im.get("exclu") else ("ok" if im.get("ok") else "echec")
        if im.get("ok") and im.get("mode") == "lune":
            im["statut"] = "lune"

    # ---- C3. Rejet des « pics » isolés (erreurs de détection) ----
    tol = max(3.0, 0.01 * F["A"])
    valides = [i for i, im in enumerate(ims) if im["statut"] == "ok"]
    rejets = 0
    for j in range(1, len(valides) - 1):
        a, i, b = valides[j - 1], valides[j], valides[j + 1]
        ta, ti, tb = secs[a], secs[i], secs[b]
        if tb == ta:
            continue
        u = (ti - ta) / (tb - ta)
        px = ims[a]["cx"] + u * (ims[b]["cx"] - ims[a]["cx"])
        py = ims[a]["cy"] + u * (ims[b]["cy"] - ims[a]["cy"])
        ecart = math.hypot(ims[i]["cx"] - px, ims[i]["cy"] - py)
        d_ia = math.hypot(ims[i]["cx"] - ims[a]["cx"], ims[i]["cy"] - ims[a]["cy"])
        d_ib = math.hypot(ims[i]["cx"] - ims[b]["cx"], ims[i]["cy"] - ims[b]["cy"])
        d_ab = math.hypot(ims[a]["cx"] - ims[b]["cx"], ims[a]["cy"] - ims[b]["cy"])
        # Pic : loin de l'interpolation ET des deux voisins, voisins cohérents entre eux,
        # et précision annoncée médiocre ou écart très net
        if ecart > tol and d_ia > tol and d_ib > tol and d_ab < 0.5 * min(d_ia, d_ib) \
                and (ims[i].get("sigma", 1) > 0.3 or ecart > 5 * tol):
            ims[i]["statut"] = "pic"
            rejets += 1
    if rejets:
        journal(f"{rejets} détection(s) aberrante(s) isolée(s) corrigée(s) par interpolation")

    # ---- C4. Interpolation des images ratées / totalité / pics ----
    valides = np.array([i for i, im in enumerate(ims) if im["statut"] == "ok"])
    interp = 0
    for i, im in enumerate(ims):
        if im["statut"] in ("ok", "exclu"):
            continue
        if len(valides) == 0:
            im["statut"] = "rejete"
            continue
        av = valides[valides < i]
        ap = valides[valides > i]
        if len(av) and len(ap):
            a, b = av[-1], ap[0]
            gap = secs[b] - secs[a]
            if gap <= pa["ecart_max_interp_s"] or im["statut"] == "lune":
                u = (secs[i] - secs[a]) / max(1e-9, gap)
                cx = ims[a]["cx"] + u * (ims[b]["cx"] - ims[a]["cx"])
                cy = ims[a]["cy"] + u * (ims[b]["cy"] - ims[a]["cy"])
                # La lune donne le centre en totalité : on le garde s'il est cohérent
                if im["statut"] == "lune" and math.hypot(im["cx"] - cx, im["cy"] - cy) < 0.1 * F["A"]:
                    im["statut"] = "ok-lune"
                    continue
                # Si le recadrage initial était mal centré (nuage épais…),
                # on recadre à nouveau l'image originale au bon endroit.
                dec = math.hypot(cx - im.get("cx0", 1e9), cy - im.get("cy0", 1e9)) * F["echelle"]
                if dec >= 0.5 * pa["marge_cache"] * F["A"] * F["echelle"]:
                    try:
                        recadrer(projet, i, cx, cy)
                    except Exception as e:
                        journal(f"  {im['nom']} : recadrage impossible ({e})")
                        im["statut"] = "rejete"
                        continue
                im["cx"], im["cy"] = float(cx), float(cy)
                im["statut"] = "interpole"
                interp += 1
                continue
        if im["statut"] == "lune":
            im["statut"] = "ok-lune"
        else:
            im["statut"] = "rejete"
    if interp:
        journal(f"{interp} image(s) recalée(s) par interpolation de trajectoire")
    nb_ok = sum(1 for im in ims if im["statut"] in ("ok", "ok-lune", "interpole"))
    journal(f"Alignement final : {nb_ok}/{n} images utilisables")


# ---------------------------------------------------------------------
# 5. ORCHESTRATION COMPLÈTE
# ---------------------------------------------------------------------
def type_eclipse(projet: Projet, journal) -> str:
    """Solaire ou lunaire ? Choix de l'utilisateur, sinon déduit de la date :
    près de la nouvelle Lune → solaire, près de la pleine Lune → lunaire."""
    choix = projet.donnees["params_analyse"].get("type_eclipse", "auto")
    if choix in ("solaire", "lunaire"):
        return choix
    ims = projet.images
    t = ims[len(ims) // 2].get("t") if ims else None
    if not t or ims[len(ims) // 2].get("t_source") == "date du fichier":
        journal("Type d'éclipse : solaire (date de prise de vue inconnue — modifiable à l'étape 1)")
        return "solaire"
    import datetime as dt
    jd = astro.jour_julien(dt.datetime.fromisoformat(t))
    sa, sd, _ = astro.soleil_geocentrique(jd)
    ma, md, _ = astro.lune_geocentrique(jd)
    cos_e = math.sin(sd) * math.sin(md) + math.cos(sd) * math.cos(md) * math.cos(ma - sa)
    elong = math.degrees(math.acos(max(-1, min(1, cos_e))))
    genre = "lunaire" if elong > 120 else "solaire"
    journal(f"Type d'éclipse détecté : {genre} (élongation Lune–Soleil {elong:.0f}°)")
    return genre


def analyser(projet: Projet, fichiers: list[str], progression, journal, annule, reprendre: bool = True):
    """Étapes A + B + C. progression(fraction, texte), journal(texte), annule() → bool.
    reprendre=True : si le dossier contient une analyse interrompue des mêmes
    images avec les mêmes réglages, seules les images manquantes sont traitées."""
    pa = projet.donnees["params_analyse"]
    fichiers = fichiers[:: max(1, int(pa.get("pas", 1)))]
    if not fichiers:
        raise RuntimeError("Aucune image à analyser.")
    os.makedirs(projet.chemin("cache"), exist_ok=True)

    # ---- Reprise d'une analyse interrompue ? ----
    ancien = None
    ancien_etal = None
    refus = None
    if reprendre and os.path.exists(projet.chemin("projet.json")):
        try:
            prec = Projet.ouvrir(projet.dossier)
            memes = sorted(im["chemin"] for im in prec.images) == sorted(fichiers)
            cles = ("diametre_cache", "marge_cache", "couleur", "raw_demi", "aplatissement", "type_eclipse")
            memes = memes and all(prec.donnees["params_analyse"].get(c) == pa.get(c) for c in cles)
            F_prec = prec.donnees.get("forme")
            if memes and F_prec and "controle" in F_prec:
                refus = message_inexploitable(F_prec)
                ancien = prec
            elif memes and not F_prec and prec.donnees.get("etal_partiel"):
                ancien_etal = prec      # étalonnage interrompu : on le poursuit
        except Exception:
            ancien = ancien_etal = None
    if refus:
        raise RuntimeError(refus)

    if ancien is not None:
        ims = ancien.images
        projet.donnees["images"] = ims
        projet.donnees["forme"] = ancien.donnees["forme"]
        projet.points = ancien.points
        forme = projet.donnees["forme"]
        a_faire = [i for i, im in enumerate(ims) if not im.get("traite")]
        journal(f"Reprise de l'analyse : {len(ims) - len(a_faire)}/{len(ims)} images déjà traitées")
    elif ancien_etal is not None:
        ims = ancien_etal.images
        projet.donnees["images"] = ims
        projet.donnees["etal_partiel"] = ancien_etal.donnees["etal_partiel"]
        projet.points = {}
        forme = None
        a_faire = list(range(len(ims)))
        journal(f"Reprise de la mesure du disque : {len(projet.donnees['etal_partiel'].get('mesures', {}))}"
                f"/{len(ims)} photos déjà mesurées")
    else:
        # ---- Horodatage + tri chronologique ----
        progression(0.0, "Lecture des dates de prise de vue…")
        ims = []
        for ch in fichiers:
            t, src, utc = horodatage(ch)
            ims.append({"nom": os.path.basename(ch), "chemin": ch, "t": t.isoformat() if t else None,
                        "t_source": src, "utc": utc, "prise": infos_prise_de_vue(ch)})
        if all(im["t"] for im in ims):
            ims.sort(key=lambda im: im["t"])
        projet.donnees["images"] = ims
        projet.points = {}
        srcs = {im["t_source"] for im in ims}
        journal(f"{len(ims)} images — horodatage : {', '.join(sorted(srcs))}")
        forme = None
        a_faire = list(range(len(ims)))

    type_ecl = type_eclipse(projet, journal)

    with ProcessPoolExecutor(max_workers=nb_processus(pa.get("processus", 0))) as ex:
        # ---- Étape A ----
        if forme is None:
            progression(0.02, "Étalonnage du rayon solaire…")
            forme = etalonner(projet, ex, journal, annule, progression)
            A = forme["A"]
            echelle = min(1.0, (pa["diametre_cache"] / 2.0) / A)
            hc = int(math.ceil(A * echelle * (1 + pa["marge_cache"]))) + 2
            forme.update({"echelle": echelle, "hc": hc, "type": type_ecl})
            projet.donnees["forme"] = forme
            projet.donnees.pop("etal_partiel", None)
            journal(f"Cache : disque de {2 * A * echelle:.0f} px, images {2 * hc + 1}×{2 * hc + 1}")
            projet.sauver()
        A, echelle, hc = forme["A"], forme["echelle"], forme["hc"]

        # ---- Étape B (sauvegarde régulière : reprise possible à tout moment) ----
        args = [(i, ims[i]["chemin"], (A, forme["k"], forme["theta"]), forme["demi"], bool(pa["couleur"]),
                 bool(pa.get("aplatissement", True) and forme["k"] < 1.0), echelle, hc, projet.chemin("cache"),
                 forme.get("blanc"), forme.get("type", "solaire"))
                for i in a_faire]
        futurs = [ex.submit(_travail_image, a) for a in args]
        fait = len(ims) - len(a_faire)
        derniere_sauvegarde = time.time()
        try:
            for fu in as_completed(futurs):
                res, pts = fu.result()
                i = res.pop("index")
                ims[i].update(res)
                ims[i]["traite"] = True
                if pts is not None and len(pts):
                    projet.points[i] = pts
                fait += 1
                if not res["ok"]:
                    journal(f"  {ims[i]['nom']} : {res.get('message', 'échec')}")
                progression(0.3 + 0.65 * fait / len(ims), f"Alignement {fait}/{len(ims)}")
                if time.time() - derniere_sauvegarde > 20:
                    projet.sauver()
                    derniere_sauvegarde = time.time()
                if annule():
                    for f2 in futurs:
                        f2.cancel()
                    raise Annulation()
        except Annulation:
            projet.donnees["etape"] = "analyse-partielle"
            projet.sauver()
            raise

    # ---- Étape C ----
    progression(0.96, "Consolidation de la trajectoire…")
    consolider(projet, journal)
    projet.donnees["etape"] = "analyse"
    projet.sauver()
    progression(1.0, "Analyse terminée")
