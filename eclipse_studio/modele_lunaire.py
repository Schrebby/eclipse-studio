# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jérémy BEAUFRERE — JEREMiA (https://jerem-ia.fr)
# Éclipse Studio est un logiciel libre : vous pouvez le redistribuer et/ou le
# modifier selon les termes de la GNU GPL v3 ou ultérieure (voir LICENSE).
"""
=====================================================================
 Éclipse Studio — Module MODÉLISATION D'UNE ÉCLIPSE DE LUNE
=====================================================================
 Repère canonique : la LUNE est centrée, ronde, de rayon Rc (= 1 unité).
 L'objet mobile est le CENTRE DE L'OMBRE DE LA TERRE.

 L1. Expositions : temps × ISO / ouverture² lus dans les EXIF / FITS
     → toutes les images sont ramenées à une même échelle de LUMINANCE
     réelle (indispensable : la totalité est ~10 000× plus sombre).
 L2. Mesure du bord de l'ombre sur chaque image partielle (arc sombre
     dedans / clair dehors, rayon ≈ 2,7 rayons lunaires) — le centre de
     l'ombre est le plus souvent HORS de l'image : accumulateur élargi.
 L3. Trajectoire de l'ombre : éphémérides géocentriques (Meeus, rayons
     de Danjon) calées sur les mesures (orientation, horloge, rotation de
     champ), sinon ajustement polynomial → contacts P1, U1, U2, U3, U4, P4.
 L4. LUNE DE RÉFÉRENCE (pleine Lune non éclipsée) : empilement des zones
     hors ombre, la pénombre étant compensée par le modèle théorique.
 L5. COURBE D'ATTÉNUATION MESURÉE, par canal, en fonction de la distance
     au centre de l'ombre : contient la vraie couleur rouge de l'ombre
     de CETTE éclipse. Les zones non photographiées utilisent la théorie.
 Synthèse d'une image à l'instant t :  Lune de référence × atténuation(d).
=====================================================================
"""

from __future__ import annotations

import datetime as dt
import json
import math
import os
import time
from concurrent.futures import ProcessPoolExecutor, as_completed

import cv2
import numpy as np

from . import astro
from .analyse import Annulation, nb_processus
from .detection import Forme, ajuster_ellipse, detecter_bords
from .io_images import facteur_exposition
from .modele import (LUM, STATUTS_UTILES, Trajectoire, angles_derotation, caler_ephemerides, grille_rho,
                     image_canonique)
from .projet import Projet

ROUGE_OMBRE = np.array([1.0, 0.42, 0.16], np.float32)   # teinte par défaut de l'ombre (si non mesurée)


# ---------------------------------------------------------------------
# 1. MODÈLE THÉORIQUE DE LA PÉNOMBRE / OMBRE
# ---------------------------------------------------------------------
def fraction_soleil_visible(d: np.ndarray, rho_u: float, rho_p: float) -> np.ndarray:
    """Fraction du disque solaire visible depuis un point de la Lune situé à
    la distance d du centre de l'ombre (même unité que rho_u, rho_p).
    Le bord de la Terre est assimilé à une droite qui balaie le Soleil."""
    s = np.clip((2 * d - (rho_u + rho_p)) / max(1e-6, rho_p - rho_u), -1, 1)
    cache = (np.arccos(s) - s * np.sqrt(1 - s * s)) / math.pi
    return (1 - cache).astype(np.float32)


def attenuation_theorique(d: np.ndarray, rho_u: float, rho_p: float) -> np.ndarray:
    """Atténuation (N, 3) : pénombre géométrique + ombre rougie (lumière
    réfractée par l'atmosphère terrestre, Danjon ≈ 2–3)."""
    f = fraction_soleil_visible(d, rho_u, rho_p)
    x = np.clip(d / rho_u, 0, 1)
    ombre = (10 ** (-3.4 + 1.4 * x ** 2))[:, None] * ROUGE_OMBRE[None, :]
    return np.maximum(f[:, None] * np.ones(3, np.float32)[None, :], ombre).astype(np.float32)


# ---------------------------------------------------------------------
# 2. L2 — MESURE DU BORD DE L'OMBRE (centre souvent hors image)
# ---------------------------------------------------------------------
def mesurer_ombre(lum: np.ndarray, valide: np.ndarray, Rc: float, rho_u: float, rayon_libre: bool = False):
    """Ajuste un arc de cercle de rayon ≈ rho_u·Rc au bord de l'ombre visible
    sur le disque lunaire. Renvoie dict(x, y [rayons lunaires], rho, couverture,
    residu, n) ou None si aucun bord d'ombre exploitable."""
    n = lum.shape[0]
    c = (n - 1) / 2.0
    # Travail en LOGARITHME de la luminance : le bord de l'ombre (chute ×50 à ×1000)
    # domine alors les contrastes d'albédo (mers, cratères ×1,5), et la mesure ne
    # dépend plus de l'exposition (zones saturées comprises).
    rho_l = np.hypot(*np.meshgrid(np.arange(n) - c, np.arange(n) - c)) / Rc
    ciel = lum[(rho_l > 1.15) & (rho_l < 1.45)]
    fond = float(np.median(ciel)) if ciel.size else 0.0
    bruit = max(1e-4, float(np.std(ciel)) if ciel.size else 1e-3)
    sig = np.clip(lum - fond, 0, None) + 2 * bruit
    lg = np.log(sig)
    lo, hi = float(np.log(2 * bruit)), float(np.percentile(lg[rho_l < 0.95], 99.5))
    norm = np.clip((lg - lo) / max(1e-6, hi - lo), 0, 1).astype(np.float32)
    norm[rho_l > 0.985] = np.nan   # le limbe lunaire ne doit pas voter
    norm = np.nan_to_num(norm, nan=0.0)
    f = min(1.0, 500.0 / n)
    petite = cv2.resize(norm, None, fx=f, fy=f, interpolation=cv2.INTER_AREA) if f < 1 else norm
    vpet = cv2.resize(valide, (petite.shape[1], petite.shape[0]), interpolation=cv2.INTER_AREA) if f < 1 else valide
    # Points de fort gradient À L'INTÉRIEUR du disque seulement (le limbe est exclu
    # avant le seuillage, sinon il écraserait le bord de l'ombre)
    cc = (petite.shape[0] - 1) / 2.0
    lis = cv2.GaussianBlur(petite, (0, 0), 2.0)
    gx = cv2.Sobel(lis, cv2.CV_32F, 1, 0, ksize=3) / 8.0
    gy = cv2.Sobel(lis, cv2.CV_32F, 0, 1, ksize=3) / 8.0
    mag = np.hypot(gx, gy)
    yy, xx = np.mgrid[0:petite.shape[0], 0:petite.shape[1]]
    dedans = (np.hypot(xx - cc, yy - cc) < 0.9 * Rc * f) & (vpet > 0.99)
    if dedans.sum() < 100:
        return None
    seuil = 0.3 * float(np.percentile(mag[dedans], 99.5))
    ys, xs = np.nonzero(dedans & (mag > seuil))
    if len(xs) < 25:
        return None
    m = mag[ys, xs]
    ux, uy = gx[ys, xs] / m, gy[ys, xs] / m
    xs, ys = xs.astype(np.float32), ys.astype(np.float32)
    # Accumulateur ÉLARGI : le centre de l'ombre est à 1,5–4 rayons de la Lune
    marge = int((rho_u + 1.3) * Rc * f) + 4
    H = petite.shape[0] + 2 * marge
    meilleur = None
    rayons = [rho_u] if not rayon_libre else list(np.linspace(rho_u * 0.9, rho_u * 1.1, 11))
    for r in rayons:
        rr = r * Rc * f
        vx = np.rint(xs - rr * ux + marge).astype(np.int64)      # vote vers le sombre (centre de l'ombre)
        vy = np.rint(ys - rr * uy + marge).astype(np.int64)
        ok = (vx >= 0) & (vx < H) & (vy >= 0) & (vy < H)
        acc = np.bincount(vy[ok] * H + vx[ok], weights=m[ok], minlength=H * H).astype(np.float32).reshape(H, H)
        acc = cv2.GaussianBlur(acc, (0, 0), 2.5)
        k = int(np.argmax(acc))
        if meilleur is None or acc.flat[k] > meilleur[0]:
            meilleur = (float(acc.flat[k]), (k % H - marge) / f, (k // H - marge) / f, r)
    _, ox, oy, r = meilleur
    # Le centre de l'ombre doit être hors du cœur du disque lunaire (sinon : totalité / pas d'arc)
    lisse = cv2.GaussianBlur(norm, (0, 0), 1.5)
    forme = Forme(r * Rc, 1.0, 0.0)
    res = None
    for demi in (0.25 * Rc, 0.08 * Rc + 4, 0.05 * Rc + 3):
        # Rayons concentrés sur le secteur qui traverse la Lune
        dirc = math.atan2(c - oy, c - ox)
        dist = math.hypot(c - ox, c - oy)
        larg = math.asin(min(1.0, 1.05 * Rc / max(dist, 1.05 * Rc))) if dist > Rc else math.pi
        phi = np.linspace(dirc - larg, dirc + larg, 400).astype(np.float32)
        n_ech = int(min(800, max(16, 2 * demi / 0.5)))
        rho = (forme.A + np.linspace(-demi, demi, n_ech, dtype=np.float32))[None, :].repeat(len(phi), 0)
        mx = (ox + rho * np.cos(phi)[:, None]).astype(np.float32)
        my = (oy + rho * np.sin(phi)[:, None]).astype(np.float32)
        prof = cv2.remap(lisse, mx, my, cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=np.nan)
        hors = np.hypot(mx - c, my - c) > 0.97 * Rc     # hors du disque lunaire : inutilisable
        prof[hors] = np.nan
        rb, clair, sombre, pente, okr = detecter_bords(phi, rho, prof, -1, lissage=3.0)
        if okr.sum() < 10:
            return None
        # Contraste exigé : luminance au moins divisée par 2 de part et d'autre du bord
        bon = okr & ((clair - sombre) > 0.69 / max(1e-6, hi - lo))
        px = ox + rb * np.cos(phi)
        py = oy + rb * np.sin(phi)
        xi, yi = np.clip(px.astype(int), 0, n - 1), np.clip(py.astype(int), 0, n - 1)
        bon &= valide[yi, xi] > 0.99
        if bon.sum() < 10:
            return None
        pts = np.stack([px[bon], py[bon]], axis=1)
        libres = ("cx", "cy", "A") if rayon_libre else ("cx", "cy")
        vals, sig, rms, w = ajuster_ellipse(pts, ox, oy, forme, libres, echelle=2.5)
        ox, oy = vals["cx"], vals["cy"]
        forme = Forme(vals["A"], 1.0, 0.0)
        res = {"x": (ox - c) / Rc, "y": (oy - c) / Rc, "rho": forme.A / Rc, "n": int(bon.sum()),
               "couverture": float(bon.sum() / len(phi)), "residu": rms,
               "sigma": float(math.hypot(sig["cx"], sig["cy"]) / Rc),
               "pts": np.round((pts[w > 0.3] - c) / Rc, 5).tolist()}
    if res is None or res["residu"] > 0.02 * Rc + 3 or math.hypot(res["x"], res["y"]) < 0.3 or res["n"] < 30:
        return None
    return res


def _travail_ombre(args):
    dossier, i, phi, rho_u, libre = args
    try:
        p = Projet.ouvrir(dossier)
        F = p.donnees["forme"]
        can, val = image_canonique(p, i, phi)
        lum = can if can.ndim == 2 else can @ LUM
        Rc = F["A"] * F["echelle"]
        val = cv2.erode(val, np.ones((5, 5), np.uint8))
        return i, mesurer_ombre(lum, val, Rc, rho_u, libre)
    except Exception as e:  # pragma: no cover
        return i, {"erreur": str(e)}


# ---------------------------------------------------------------------
# 3. L3 — TRAJECTOIRE DE L'OMBRE
# ---------------------------------------------------------------------
def table_ombre(t0_utc: dt.datetime, t_min: float, t_max: float, pas: float = 20.0):
    ts = np.arange(t_min, t_max + pas, pas)
    xi, eta, ru, rp = [], [], [], []
    for s in ts:
        g = astro.geometrie_lunaire(t0_utc + dt.timedelta(seconds=float(s)))
        xi.append(g["xi"])
        eta.append(g["eta"])
        ru.append(g["rho_u"])
        rp.append(g["rho_p"])
    return ts, np.array(xi), np.array(eta), float(np.median(ru)), float(np.median(rp))


def ajuster_ombre(projet: Projet, mesures: dict, rho_u: float, rho_p: float, journal,
                  rayons_officiels: tuple[float, float] | None = None) -> dict | None:
    """rayons_officiels : (ombre, pénombre) de la théorie de Danjon, utilisés pour
    annoncer les contacts officiels ; le rendu utilise les rayons mesurés."""
    secs = projet.secondes()
    idx = sorted(i for i, m in mesures.items() if m and "x" in m)
    if len(idx) < 3:
        journal("Ombre de la Terre : trop peu d'images partielles pour calculer sa trajectoire")
        return None
    t = secs[idx]
    mx = np.array([mesures[i]["x"] for i in idx])
    my = np.array([mesures[i]["y"] for i in idx])
    pm = projet.donnees["params_modele"]
    mode = pm.get("trajectoire", "auto")
    t0 = projet.temps_utc(projet.images[0])
    res = None
    if mode in ("auto", "ephemerides") and t0 is not None and projet.images[0].get("t_source") != "date du fichier":
        marge = 8 * 3600.0
        tt, txi, teta, ru_e, rp_e = table_ombre(t0, t.min() - marge - 14 * 3600, t.max() + marge + 14 * 3600, 30.0)
        res = caler_ephemerides(t, mx, my, tt, txi, teta, plage_dt=14 * 3600.0)
        if res is not None:
            r = res.pop("_r")
            if res["rms"] > 0.06 and mode == "auto":
                journal(f"Éphémérides peu cohérentes avec l'ombre mesurée (écart {res['rms']:.3f}) → ajustement")
                res = None
            else:
                journal(f"Trajectoire de l'ombre calée sur les éphémérides : écart RMS {res['rms'] * 1000:.0f} ‰ "
                        f"du rayon lunaire, horloge de l'appareil décalée de {res['dt_horloge']:+.0f} s, "
                        f"rotation de champ {res['omega_deg_h']:+.2f}°/h")
    if res is None:
        deg = 2 if len(t) > 8 and np.ptp(t) > 1200 else 1
        tr = float(np.median(t))
        w = np.ones(len(t))
        for _ in range(4):
            px = np.polyfit(t - tr, mx, deg, w=w)
            py = np.polyfit(t - tr, my, deg, w=w)
            r = np.hypot(np.polyval(px, t - tr) - mx, np.polyval(py, t - tr) - my)
            w = 1.0 / (1.0 + (r / max(0.01, 2 * np.median(r))) ** 2)
        res = {"mode": "polynome", "px": px.tolist(), "py": py.tolist(), "t_ref": tr,
               "rms": float(np.sqrt(np.average(r ** 2, weights=w)))}
        journal(f"Trajectoire de l'ombre (ajustement degré {deg}) : écart RMS {res['rms'] * 1000:.0f} ‰")
    res.update({"rho_u": rho_u, "rho_p": rho_p, "rho_m": rho_u, "lunaire": True})
    res["residus"] = {int(i): float(v) for i, v in zip(idx, r)}
    # ---- Contacts (en temps relatif) ----
    traj = Trajectoire(res)
    ts = np.arange(t.min() - 8 * 3600, t.max() + 8 * 3600, 5.0)
    x, y = traj.position(ts)
    d = np.hypot(x, y)
    if rayons_officiels:
        rho_u, rho_p = rayons_officiels
    cont = {}
    for ne, ns, seuil in (("P1", "P4", rho_p + 1), ("U1", "U4", rho_u + 1), ("U2", "U3", rho_u - 1)):
        dedans = d < seuil
        if dedans.any():
            k0, k1 = int(np.argmax(dedans)), len(d) - 1 - int(np.argmax(dedans[::-1]))
            if k0 > 0:
                cont[ne] = float(ts[k0])
            if k1 < len(ts) - 1:
                cont[ns] = float(ts[k1])
    km = int(np.argmin(d))
    cont["max"] = float(ts[km])
    cont["magnitude_ombre"] = float((rho_u + 1 - d[km]) / 2)
    cont["magnitude_penombre"] = float((rho_p + 1 - d[km]) / 2)
    # Alias utilisés par la chronologie (début / fin de l'éclipse visible)
    if "P1" in cont:
        cont["C1"] = cont["P1"]
    if "P4" in cont:
        cont["C4"] = cont["P4"]
    res["contacts"] = cont
    return res


# ---------------------------------------------------------------------
# 4. L4 / L5 — LUNE DE RÉFÉRENCE ET COURBE D'ATTÉNUATION
# ---------------------------------------------------------------------
NB_BINS = 400


def _ciel_noir(can, val, rho):
    sel = (rho > 1.15) & (rho < 1.5) & (val > 0.99)
    if sel.sum() < 300:
        return np.zeros(3, np.float32)
    return np.array([float(np.percentile(can[:, :, ch][sel], 20)) for ch in range(3)], np.float32)


def _travail_lune_ref(args):
    """Passe d'accumulation sur un paquet d'images (exécutée en parallèle).
    etape 'ref'  : empilement de la Lune de référence (gain par image).
    etape 'att'  : courbe d'atténuation radiance / référence en fonction de d."""
    dossier, indices, phis, centres, rho_u, rho_p, etape, reference, K, d_max = args
    p = Projet.ouvrir(dossier)
    F = p.donnees["forme"]
    n = 2 * F["hc"] + 1
    Rc = F["A"] * F["echelle"]
    rho, X, Y = grille_rho(n, Rc)
    disque = rho < 1.0
    somme = np.zeros((n, n, 3), np.float32)
    poids = np.zeros((n, n), np.float32)
    att_s = np.zeros((NB_BINS, 3), np.float64)
    att_n = np.zeros(NB_BINS, np.float64)
    infos = {}
    for i, phi, cen in zip(indices, phis, centres):
        can, val = image_canonique(p, i, phi)
        if can.ndim == 2:
            can = np.repeat(can[:, :, None], 3, axis=2)
        noir = _ciel_noir(can, val, rho)
        v = np.clip(can - noir[None, None, :], 0, None)
        ok = disque & (val > 0.99) & (can.max(axis=2) < 0.985)
        if cen is not None:
            d = np.hypot(X - cen[0], Y - cen[1])
            f = fraction_soleil_visible(d, rho_u, rho_p)
        else:
            d = None
            f = np.ones((n, n), np.float32)
        inf = {"noir": noir.tolist()}
        hors = ok & (f > 0.97)
        if etape == "ref":
            if hors.sum() > 300:
                g = np.array([float(np.median(v[:, :, ch][hors] / (reference[:, :, ch][hors] if reference is not None
                                                                     else 1.0))) for ch in range(3)], np.float32)
                g = np.maximum(g, 1e-6)
                inf["g"] = g.tolist()
                # Pénombre compensée par le modèle (f > 0,5) ; rejet des défauts en 2e passe
                use = ok & (f > 0.5)
                nrm = v / g[None, None, :] / np.maximum(f, 1e-3)[:, :, None]
                if reference is not None:
                    e = np.abs(nrm @ LUM - reference @ LUM)
                    use &= e < 0.15 * np.maximum(reference @ LUM, 0.05)
                wgt = (use * f).astype(np.float32)
                somme += nrm * wgt[:, :, None]
                poids += wgt
        else:   # 'att' : radiance calibrée / référence, binnée en distance au centre de l'ombre
            ent = K.get(str(i))
            if ent and d is not None:
                Ei, cb = ent
                r = v / Ei * np.array(cb, np.float32)[None, None, :]
                sel = ok & (reference @ LUM > 0.05)
                b = np.clip((d[sel] / d_max * NB_BINS).astype(int), 0, NB_BINS - 1)
                ratio = r[sel] / np.maximum(reference[sel], 1e-4)
                for ch in range(3):
                    att_s[:, ch] += np.bincount(b, weights=np.log(np.maximum(ratio[:, ch], 1e-6)), minlength=NB_BINS)
                att_n += np.bincount(b, minlength=NB_BINS)
                inf["median_ratio_lum"] = float(np.median(ratio @ LUM))
        infos[i] = inf
    return somme, poids, att_s, att_n, infos


# ---------------------------------------------------------------------
# 5. ORCHESTRATION
# ---------------------------------------------------------------------
def modeliser_lune(projet: Projet, progression, journal, annule, reprendre: bool = False):
    F = projet.donnees["forme"]
    pm = projet.donnees["params_modele"]
    ims = projet.images
    os.makedirs(projet.chemin("modele"), exist_ok=True)
    n = 2 * F["hc"] + 1
    Rc = F["A"] * F["echelle"]
    secs = projet.secondes()
    phis = angles_derotation(projet)
    for i, im in enumerate(ims):
        im["derotation"] = float(phis[i])
    utiles = [i for i, im in enumerate(ims) if im.get("statut") in STATUTS_UTILES and im.get("cache")]
    nproc = nb_processus(projet.donnees["params_analyse"].get("processus", 0))

    sig = json.dumps(["lune"] + [pm.get(c) for c in ("latitude", "longitude", "decalage_utc_h", "monture",
                                                     "sens_derotation", "trajectoire")] + [len(utiles)], default=str)
    partiel = projet.donnees.get("partiel") or {}
    if not reprendre or partiel.get("sig") != sig:
        partiel = {"sig": sig}
    projet.donnees["partiel"] = partiel
    projet.sauver()

    # ---- L1 : expositions ----
    E = {}
    for i in utiles:
        e = facteur_exposition(ims[i].get("prise") or {})
        if e:
            E[i] = e
    if len(E) < 0.8 * len(utiles):
        journal("⚠ Temps de pose absents des EXIF/FITS pour une partie des images : "
                "la luminosité réelle de la totalité ne pourra pas être reconstituée fidèlement.")

    # ---- Rayons théoriques de l'ombre (éphémérides si date connue) ----
    t0 = projet.temps_utc(ims[0])
    tm = t0 + dt.timedelta(seconds=float(np.median(secs))) if t0 else None
    if tm and ims[0].get("t_source") != "date du fichier":
        # Le rayon relatif de l'ombre varie peu dans le mois : prise au plus proche du maximum
        g = astro.geometrie_lunaire(tm)
        rho_u_th, rho_p_th = g["rho_u"], g["rho_p"]
    else:
        rho_u_th, rho_p_th = 2.70, 4.70

    # ---- L2 : bord de l'ombre (rayon libre sur un échantillon, puis fixé) ----
    progression(0.03, "Mesure du bord de l'ombre…")
    # TOUTES les photos sont mesurées en rayon libre (autour de la valeur théorique) ;
    # rayon commun = médiane pondérée, puis centres recalculés avec ce rayon à partir
    # des points de bord mémorisés.
    libres = partiel.setdefault("ombres_libres", {})
    restants = [i for i in utiles if str(i) not in libres]
    with ProcessPoolExecutor(max_workers=nproc) as ex:
        futurs = [ex.submit(_travail_ombre, (projet.dossier, i, phis[i], rho_u_th, True)) for i in restants]
        for fu in as_completed(futurs):
            i, m = fu.result()
            libres[str(i)] = m if (m and "x" in m) else None
            progression(0.05 + 0.3 * len(libres) / max(1, len(utiles)), f"Bord de l'ombre {len(libres)}/{len(utiles)}")
            if annule():
                for f2 in futurs:
                    f2.cancel()
                projet.sauver()
                raise Annulation()
    valides = [m for m in libres.values() if m and m["n"] > 40]
    if len(valides) >= 3:
        from .analyse import mediane_ponderee
        rho_u = mediane_ponderee([m["rho"] for m in valides], [m["n"] for m in valides])
    else:
        rho_u = rho_u_th
    rho_p = rho_u * rho_p_th / rho_u_th
    journal(f"Rayon de l'ombre : {rho_u:.3f} rayons lunaires (théorie {rho_u_th:.3f}, mesuré sur "
            f"{len(valides)} photos), pénombre {rho_p:.3f}")
    ombres = {}
    for k_, m in libres.items():
        if not (m and m.get("pts")):
            ombres[k_] = None
            continue
        pts = np.array(m["pts"], np.float64)
        vals, sig, rms, w = ajuster_ellipse(pts, m["x"], m["y"], Forme(rho_u, 1.0, 0.0), ("cx", "cy"), echelle=0.006)
        ombres[k_] = {"x": float(vals["cx"]), "y": float(vals["cy"]), "rho": rho_u, "n": m["n"],
                      "couverture": m["couverture"], "residu": float(rms)}
    partiel["ombres"] = ombres
    mesures = {int(k): (dict(v) if v else None) for k, v in ombres.items()}
    for i, im in enumerate(ims):
        im["lune"] = mesures.get(i)

    # ---- L3 : trajectoire (+ dérotation automatique) ----
    progression(0.38, "Trajectoire de l'ombre de la Terre…")
    traj_d = ajuster_ombre(projet, mesures, rho_u, rho_p, journal, (rho_u_th, rho_p_th))
    if traj_d and pm.get("monture", "auto") == "auto" and traj_d.get("omega_deg_h"):
        om = traj_d["omega_deg_h"]
        if abs(om) * np.ptp(secs) / 3600 > 0.3:
            dphi = -om / 3600.0 * (secs - traj_d["t_m"])
            for i, m in mesures.items():
                if m:
                    a_ = math.radians(dphi[i])
                    m["x"], m["y"] = (math.cos(a_) * m["x"] - math.sin(a_) * m["y"],
                                      math.sin(a_) * m["x"] + math.cos(a_) * m["y"])
            phis = phis + dphi
            for i, im in enumerate(ims):
                im["derotation"] = float(phis[i])
            journal(f"Rotation de champ {om:+.2f}°/h détectée : dérotation automatique appliquée")
            traj_d = ajuster_ombre(projet, mesures, rho_u, rho_p, journal, (rho_u_th, rho_p_th))
            traj_d["rotation_champ_deg_h"] = om
    centres = {}
    if traj_d:
        x, y = Trajectoire(traj_d).position(secs)
        for i in range(len(ims)):
            centres[i] = (float(x[i]), float(y[i]))
            ims[i]["ombre_modele"] = [float(x[i]), float(y[i])]
        c = traj_d["contacts"]
        if t0:
            dth = traj_d.get("dt_horloge", 0.0)
            noms = [k for k in ("P1", "U1", "U2", "max", "U3", "U4", "P4") if k in c]
            journal("Contacts (modèle) : " + ", ".join(
                f"{k} {(t0 + dt.timedelta(seconds=c[k] + dth)).strftime('%H:%M:%S')} UT" for k in noms)
                + f" — magnitude de l'ombre {c['magnitude_ombre']:.3f}")
    else:
        for i, m in mesures.items():
            if m:
                centres[i] = (m["x"], m["y"])

    # ---- L4 : Lune de référence (2 passes) ----
    paquets = [utiles[k::nproc * 2] for k in range(nproc * 2)]
    reference = None
    gains: dict = {}
    noirs: dict = {}
    for passe in (1, 2):
        if annule():
            raise Annulation()
        progression(0.45 + 0.15 * (passe - 1), f"Lune de référence — passe {passe}/2")
        somme = np.zeros((n, n, 3), np.float32)
        poids = np.zeros((n, n), np.float32)
        args = [(projet.dossier, pq, [phis[i] for i in pq], [centres.get(i) for i in pq], rho_u, rho_p,
                 "ref", reference, None, None) for pq in paquets if pq]
        with ProcessPoolExecutor(max_workers=nproc) as ex:
            for s_, w_, _, _, inf in ex.map(_travail_lune_ref, args):
                somme += s_
                poids += w_
                for i, v in inf.items():
                    noirs[i] = v["noir"]
                    if "g" in v:
                        gains[i] = v["g"]
        if poids.max() <= 0:
            raise RuntimeError("Aucune partie non éclipsée de la Lune : impossible de reconstituer la pleine Lune. "
                               "Ajoutez des photos prises avant ou après l'éclipse.")
        reference = somme / np.maximum(poids, 1e-6)[:, :, None]
    rho, _, _ = grille_rho(n, Rc)
    vu = (poids > 0.3) & (rho < 1.0)
    couv = float(vu.sum() / max(1, (rho < 1).sum()))
    manque = (~vu) & (rho < 1.02)
    if manque.any():   # zones jamais vues pleinement éclairées : remplissage par diffusion
        u8 = (manque * 255).astype(np.uint8)
        for ch in range(3):
            reference[:, :, ch] = cv2.inpaint(reference[:, :, ch].astype(np.float32), u8, 9, cv2.INPAINT_TELEA)
    reference *= np.clip((1.004 - rho) / 0.012, 0, 1)[:, :, None]
    # Normalisation : luminance du disque ≈ 0,8
    niveau = 0.8 / max(1e-6, float(np.median((reference @ LUM)[rho < 0.9])))
    reference *= niveau
    journal(f"Lune de référence reconstituée ({100 * couv:.1f} % du disque vu hors pénombre profonde)")

    # ---- Calibration photométrique : radiance = (valeur − noir) / (K · exposition) ----
    gl = {i: float(np.array(g) @ LUM) / niveau for i, g in gains.items()}   # gain image → référence
    ratios = [gl[i] / E[i] for i in gl if i in E]
    K = float(np.median(ratios)) if ratios else None
    echelle_img = {}
    for i in utiles:
        if K and i in E:
            echelle_img[str(i)] = K * E[i]
        elif i in gl:
            echelle_img[str(i)] = gl[i]
    if not K:
        journal("Pas de temps de pose exploitable : luminosités normalisées image par image (mode « compensé »)")
    # Équilibre des couleurs (rougissement près de l'horizon) : interpolé dans le temps
    cb_t, cb_v = [], []
    for i, g in sorted(gains.items()):
        g = np.array(g, np.float32)
        cb_t.append(secs[i])
        cb_v.append((g @ LUM) / np.maximum(g, 1e-6))
    couleurs = {}
    if cb_v:
        cb_v = np.array(cb_v)
        ordre = np.argsort(cb_t)
        for i in utiles:
            couleurs[i] = [float(np.interp(secs[i], np.array(cb_t)[ordre], cb_v[ordre, ch])) for ch in range(3)]

    # ---- L5 : courbe d'atténuation mesurée ----
    progression(0.8, "Courbe d'atténuation (couleur réelle de l'ombre)…")
    d_max = rho_p + 1.2
    att = None
    if K and centres:
        Kd = {str(i): (echelle_img[str(i)], couleurs.get(i, [1, 1, 1])) for i in utiles
              if str(i) in echelle_img and i in E}
        args = [(projet.dossier, pq, [phis[i] for i in pq], [centres.get(i) for i in pq], rho_u, rho_p,
                 "att", reference, Kd, d_max) for pq in paquets if pq]
        acc_s = np.zeros((NB_BINS, 3))
        acc_n = np.zeros(NB_BINS)
        with ProcessPoolExecutor(max_workers=nproc) as ex:
            for _, _, s_, n_, inf in ex.map(_travail_lune_ref, args):
                acc_s += s_
                acc_n += n_
        dd = (np.arange(NB_BINS) + 0.5) / NB_BINS * d_max
        theo = attenuation_theorique(dd, rho_u, rho_p)
        mes = np.exp(acc_s / np.maximum(acc_n, 1)[:, None])
        fiab = np.clip(acc_n / 2000.0, 0, 1)[:, None]
        # Lissage de la mesure puis mélange pondéré par le nombre de pixels
        mes_l = np.stack([np.convolve(np.log(mes[:, ch]), np.ones(5) / 5, mode="same") for ch in range(3)], 1)
        att = np.exp(fiab * mes_l + (1 - fiab) * np.log(np.maximum(theo, 1e-6)))
        att[dd > rho_p] = 1.0
        np.save(projet.chemin("modele", "attenuation.npy"), np.column_stack([dd, att]).astype(np.float32))
        frac = float((acc_n[dd < rho_u] > 2000).mean()) if (dd < rho_u).any() else 0.0
        journal(f"Atténuation mesurée sur {100 * frac:.0f} % de la profondeur de l'ombre "
                "(le reste : modèle de Danjon)")
    else:
        dd = (np.arange(NB_BINS) + 0.5) / NB_BINS * d_max
        att = attenuation_theorique(dd, rho_u, rho_p)
        np.save(projet.chemin("modele", "attenuation.npy"), np.column_stack([dd, att]).astype(np.float32))

    np.save(projet.chemin("modele", "reference.npy"), reference.astype(np.float32))
    for i, im in enumerate(ims):
        im["noir"] = noirs.get(i)
        im["gains"] = gains.get(i)
        im["echelle_radiance"] = echelle_img.get(str(i))
        im["couleur_lune"] = couleurs.get(i)
        im["photo"] = None
        if traj_d and i in centres:
            d0 = math.hypot(*centres[i])
            im["magnitude_ombre"] = (rho_u + 1 - d0) / 2
    gmed = np.median(np.array(list(gains.values())), axis=0) if gains else np.ones(3)
    teinte = (gmed / max(1e-6, float(gmed @ LUM))).tolist()
    projet.donnees["modele"] = {
        "lunaire": True, "teinte_lune": teinte, "trajectoire": traj_d, "rho_u": rho_u, "rho_p": rho_p, "rho_m": rho_u,
        "K": K, "couverture_reference": couv, "date": dt.datetime.now().isoformat(timespec="seconds"),
    }
    projet.donnees["etape"] = "modele"
    projet.sauver()
    progression(1.0, "Modélisation terminée")
