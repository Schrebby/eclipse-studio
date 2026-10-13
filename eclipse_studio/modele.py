# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jérémy BEAUFRERE — JEREMiA (https://jerem-ia.fr)
# Éclipse Studio est un logiciel libre : vous pouvez le redistribuer et/ou le
# modifier selon les termes de la GNU GPL v3 ou ultérieure (voir LICENSE).
"""
=====================================================================
 Éclipse Studio — Module MODÉLISATION (Lune, Soleil de référence,
                   uniformisation photométrique)
=====================================================================
 Tout se passe dans le REPÈRE CANONIQUE : image carrée où le Soleil
 est centré, parfaitement rond (aplatissement corrigé), de rayon Rc,
 et orienté de façon fixe sur le ciel (dérotation si monture altaz).

 D1. Mesure de la Lune sur chaque image (bord concave : sombre dedans,
     clair dehors, uniquement à l'intérieur du disque solaire).
 D2. Trajectoire de la Lune :
       - « éphémérides » (lieu GPS connu) : la course réelle Lune/Soleil
         calculée (Meeus, topocentrique) est calée sur les mesures par
         une similitude (orientation, échelle) + un DÉCALAGE D'HORLOGE
         de l'appareil, estimé automatiquement ;
       - « polynôme » : ajustement direct x(t), y(t) (degré 2).
     → contacts C1..C4, maximum, et position lunaire à tout instant
       (avant le début et après la fin des prises de vue).
 D3. SOLEIL DE RÉFÉRENCE : empilement de toutes les parties de
     photosphère non masquées (hors Lune, hors capteur, hors nuages),
     après normalisation photométrique → disque complet, taches
     solaires comprises. Sert à compléter les soleils coupés et à
     synthétiser début / fin d'éclipse.
 D4. UNIFORMISATION : pour chaque image, modèle par canal
       référence ≈ (a + cx·X + cy·Y)·valeur + b
     (exposition, couleur, contraste et gradient d'extinction
     atmosphérique près de l'horizon), lissé dans le temps.
=====================================================================
"""

from __future__ import annotations

import datetime as dt
import math
import os
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
import json

import cv2
import numpy as np

from . import astro
from .analyse import Annulation, lire_png16, nb_processus
from .detection import (Forme, ajuster_ellipse, couverture_angulaire, detecter_bords, hough_oriente,
                        normaliser, points_de_contour, profils_radiaux)
from .projet import Projet

STATUTS_UTILES = ("ok", "ok-lune", "interpole")
LUM = np.array([0.2126, 0.7152, 0.0722], np.float32)


# ---------------------------------------------------------------------
# 1. GÉOMÉTRIE DU REPÈRE CANONIQUE
# ---------------------------------------------------------------------
def rotation(phi_deg: float) -> np.ndarray:
    a = math.radians(phi_deg)
    return np.array([[math.cos(a), -math.sin(a)], [math.sin(a), math.cos(a)]])


def matrice_canon_vers_cache(F: dict, im: dict, phi_deg: float) -> np.ndarray:
    """Affine 2×3 : point canonique → point du cache (pour WARP_INVERSE_MAP)."""
    e, hc = F["echelle"], F["hc"]
    th, k = F["theta"], im.get("k_lisse", F["k"])
    Rt = rotation(math.degrees(th))
    Fm = Rt @ np.diag([1.0, k]) @ Rt.T          # aplatissement le long de θ+90°
    L = Fm @ rotation(-phi_deg)
    c = np.array([hc + (im["cx"] - im["cx0"]) * e, hc + (im["cy"] - im["cy0"]) * e])
    t = c - L @ np.array([hc, hc])
    return np.hstack([L, t[:, None]]).astype(np.float64)


def image_canonique(projet: Projet, i: int, phi_deg: float = 0.0):
    """Charge le cache de l'image i et le ré-échantillonne dans le repère
    canonique. Renvoie (image float32, masque_valide float32 0..1)."""
    F = projet.donnees["forme"]
    im = projet.images[i]
    n = 2 * F["hc"] + 1
    src = lire_png16(projet.chemin("cache", im["cache"]))
    # Effacement des poussières du capteur (carte fixe dans le repère capteur)
    from .poussieres import carte_cache, appliquer
    cp = carte_cache(projet, im, src.shape[0])
    if cp is not None:
        src = appliquer(src, cp)
    M = matrice_canon_vers_cache(F, im, phi_deg)
    can = cv2.warpAffine(src, M, (n, n), flags=cv2.INTER_CUBIC | cv2.WARP_INVERSE_MAP,
                         borderMode=cv2.BORDER_CONSTANT, borderValue=0)
    can = np.clip(can, 0, None)
    if im.get("masque"):
        m = cv2.imdecode(np.fromfile(projet.chemin("cache", im["masque"]), np.uint8), cv2.IMREAD_GRAYSCALE)
        m = m.astype(np.float32) / 255.0
    else:
        m = np.ones(src.shape[:2], np.float32)
    val = cv2.warpAffine(m, M, (n, n), flags=cv2.INTER_LINEAR | cv2.WARP_INVERSE_MAP,
                         borderMode=cv2.BORDER_CONSTANT, borderValue=0)
    return can, val


def grille_rho(n: int, Rc: float):
    """Distance normalisée au centre (1 = limbe) + coordonnées X, Y normalisées."""
    c = (n - 1) / 2.0
    y, x = np.mgrid[0:n, 0:n].astype(np.float32)
    X, Y = (x - c) / Rc, (y - c) / Rc
    return np.sqrt(X * X + Y * Y), X, Y


def assombrissement(rho: np.ndarray, u: float = 0.55) -> np.ndarray:
    mu = np.sqrt(np.clip(1 - rho * rho, 0, 1))
    return (1 - u * (1 - mu)).astype(np.float32)


def disque_lunaire(n: int, Rc: float, mx: float, my: float, rho_m: float, flou_px: float = 1.0) -> np.ndarray:
    """Masque 0..1 (1 = Lune) anti-crénelé d'un disque lunaire (unités : rayons solaires)."""
    c = (n - 1) / 2.0
    y, x = np.mgrid[0:n, 0:n].astype(np.float32)
    d = np.sqrt((x - (c + mx * Rc)) ** 2 + (y - (c + my * Rc)) ** 2)
    return np.clip((rho_m * Rc - d) / max(0.5, flou_px) + 0.5, 0, 1).astype(np.float32)


# ---------------------------------------------------------------------
# 2. ANGLE DE DÉROTATION
# ---------------------------------------------------------------------
def angles_derotation(projet: Projet) -> np.ndarray:
    pm = projet.donnees["params_modele"]
    n = len(projet.images)
    if pm.get("monture") != "altaz" or pm.get("latitude") is None or pm.get("longitude") is None:
        return np.zeros(n)
    qs = []
    for im in projet.images:
        t = projet.temps_utc(im)
        if t is None:
            return np.zeros(n)
        qs.append(astro.geometrie(t, pm["latitude"], pm["longitude"])["parallactique"])
    qs = np.array(qs)
    return float(pm.get("sens_derotation", 1)) * (qs - np.median(qs))


# ---------------------------------------------------------------------
# 3. D1 — MESURE DE LA LUNE (dans le repère canonique)
# ---------------------------------------------------------------------
def mesurer_lune(lum: np.ndarray, valide: np.ndarray, Rc: float, rho_m: float | None,
                 rho_approx: float | None = None):
    """Mesure le bord de la Lune sur le disque solaire.
    rho_m      : rayon lunaire imposé (rayons solaires) ; None = rayon libre.
    rho_approx : rayon libre mais cherché à ±6 % de cette valeur (photo pivot).
    Renvoie dict(x, y, rho, couverture, residu, n, pts) en rayons solaires, ou None."""
    n = lum.shape[0]
    c = (n - 1) / 2.0
    norm = normaliser(lum)
    f = min(1.0, 640.0 / n)
    petite = cv2.resize(norm, None, fx=f, fy=f, interpolation=cv2.INTER_AREA) if f < 1 else norm
    cont = points_de_contour(petite, sigma=1.2, frac=0.2)
    if cont is None:
        return None
    xs, ys, ux, uy, m = cont
    cc = (petite.shape[0] - 1) / 2.0
    dsol = np.hypot(xs - cc, ys - cc) / (Rc * f)
    vpet = cv2.resize(valide, (petite.shape[1], petite.shape[0]), interpolation=cv2.INTER_AREA) if f < 1 else valide
    garde = (dsol < 0.96) & (vpet[ys.astype(int), xs.astype(int)] > 0.99)
    if garde.sum() < 15:
        return None
    cont = (xs[garde], ys[garde], ux[garde], uy[garde], m[garde])
    if rho_m:
        rayons = [rho_m]
    elif rho_approx:
        rayons = list(np.linspace(0.94 * rho_approx, 1.06 * rho_approx, 9))
    else:
        rayons = list(np.linspace(0.88, 1.15, 28))
    meilleur = None
    for r in rayons:
        _, hx, hy, _, pic = hough_oriente(cont, r * Rc * f, petite.shape[:2], signe=-1, flou=1.5)
        if meilleur is None or pic > meilleur[0]:
            meilleur = (pic, hx / f, hy / f, r)
    _, lx, ly, r = meilleur
    lisse = cv2.GaussianBlur(norm, (0, 0), 1.0)
    forme = Forme(r * Rc, 1.0, 0.0)
    res = None
    for demi in (0.08 * Rc, 0.03 * Rc + 4, 0.02 * Rc + 3):
        phi, rho, prof = profils_radiaux(lisse, lx, ly, forme, demi, 360)
        rb, clair, sombre, pente, ok = detecter_bords(phi, rho, prof, -1)
        px = lx + rb * np.cos(phi)
        py = ly + rb * np.sin(phi)
        dans = np.hypot(px - c, py - c) < 0.975 * Rc
        xi, yi = np.clip(px.astype(int), 0, n - 1), np.clip(py.astype(int), 0, n - 1)
        ok = ok & dans & (valide[yi, xi] > 0.99)
        if ok.sum() < 12:
            return None
        ref = float(np.percentile(clair[ok], 90))
        bon = ok & ((clair - sombre) > 0.3 * ref)
        if bon.sum() < 12:
            return None
        pts = np.stack([px[bon], py[bon]], axis=1)
        libres = ("cx", "cy") if rho_m else ("cx", "cy", "A")
        vals, sig, rms, w = ajuster_ellipse(pts, lx, ly, forme, libres, echelle=1.5)
        lx, ly = vals["cx"], vals["cy"]
        forme = Forme(vals["A"], 1.0, 0.0)
        bons_pts = pts[w > 0.3]
        res = {"x": (lx - c) / Rc, "y": (ly - c) / Rc, "rho": forme.A / Rc,
               "couverture": couverture_angulaire(phi[bon]), "residu": rms, "n": int(bon.sum()),
               "sigma": float(math.hypot(sig["cx"], sig["cy"]) / Rc),
               "pts": np.round((bons_pts - c) / Rc, 5).tolist()}
    if res is None or res["couverture"] < 0.08 or res["residu"] > 0.01 * Rc + 2:
        return None
    return res


def _travail_lune(args):
    dossier, i, phi, rho_m, rho_approx = (tuple(args) + (None,))[:5]
    try:
        p = Projet.ouvrir(dossier)
        F = p.donnees["forme"]
        can, val = image_canonique(p, i, phi)
        lum = can if can.ndim == 2 else can @ LUM
        Rc = F["A"] * F["echelle"]
        val = cv2.erode(val, np.ones((5, 5), np.uint8))
        return i, mesurer_lune(lum, val, Rc, rho_m, rho_approx)
    except Exception as e:  # pragma: no cover
        return i, {"erreur": str(e)}


# ---------------------------------------------------------------------
# 4. D2 — TRAJECTOIRE DE LA LUNE
# ---------------------------------------------------------------------
class Trajectoire:
    """Position de la Lune (rayons solaires, repère canonique) en fonction
    du temps relatif t (s, origine = 1re image de la série)."""

    def __init__(self, d: dict):
        self.d = d

    def position(self, t: float | np.ndarray):
        d = self.d
        t = np.asarray(t, float)
        if d["mode"] == "polynome":
            return np.polyval(d["px"], t - d["t_ref"]), np.polyval(d["py"], t - d["t_ref"])
        # Éphémérides : table pré-calculée (pas fin) interpolée
        xi = np.interp(t + d["dt_horloge"], d["table_t"], d["table_xi"])
        eta = np.interp(t + d["dt_horloge"], d["table_t"], d["table_eta"])
        a, b = d["a"], d["b"]
        if d["miroir"]:
            eta = -eta
        # Ciel (ξ Est, η Nord) → image (x droite, y bas) : similitude ajustée
        # (+ petit décalage constant absorbant l'erreur résiduelle des éphémérides)
        om = d.get("omega_deg_h", 0.0)
        if om:
            ang = np.radians(om / 3600.0 * (t - d.get("t_m", 0.0)))
            c, s = np.cos(ang), np.sin(ang)
            xi, eta = c * xi - s * eta, s * xi + c * eta
        ox, oy = d.get("ox", 0.0), d.get("oy", 0.0)
        return a * xi - b * eta + ox, b * xi + a * eta + oy

    def rho(self) -> float:
        return self.d["rho_m"]


def _table_ephemerides(t0_utc: dt.datetime, t_min: float, t_max: float, lat: float, lon: float, pas: float = 15.0):
    ts = np.arange(t_min, t_max + pas, pas)
    xi, eta, kk = [], [], []
    for s in ts:
        g = astro.geometrie(t0_utc + dt.timedelta(seconds=float(s)), lat, lon)
        xi.append(g["xi"])
        eta.append(g["eta"])
        kk.append(g["k"])
    return ts, np.array(xi), np.array(eta), np.array(kk)


def _similitude(p_xi, p_eta, mx, my, w):
    """Résout m ≈ [[a,−b],[b,a]]·p au sens des moindres carrés pondérés."""
    # x = a ξ − b η ; y = b ξ + a η
    Am = np.zeros((2 * len(mx), 2))
    Am[0::2, 0], Am[0::2, 1] = p_xi, -p_eta
    Am[1::2, 0], Am[1::2, 1] = p_eta, p_xi
    bv = np.empty(2 * len(mx))
    bv[0::2], bv[1::2] = mx, my
    ww = np.repeat(w, 2)
    sol, *_ = np.linalg.lstsq(Am * ww[:, None], bv * ww, rcond=None)
    res = (Am @ sol - bv).reshape(-1, 2)
    return sol, np.sqrt((res ** 2).sum(axis=1))


def caler_ephemerides(t, mx, my, tt, txi, teta, plage_dt: float = 3 * 3600.0):
    """Cale une trajectoire théorique (table tt → ξ, η) sur des positions mesurées
    (mx, my) : similitude (orientation, échelle, miroir éventuel) + décalage
    d'horloge δt + rotation de champ linéaire ω (+ décalage constant si utile).
    Renvoie un dict de paramètres (clé "_r" = résidus) ou None."""
    w = np.ones(len(t))
    meilleur = None
    for miroir in (False, True):
        for dtc in np.arange(-plage_dt, plage_dt + 1, 20.0):
            xi = np.interp(t + dtc, tt, txi)
            eta = np.interp(t + dtc, tt, teta)
            if miroir:
                eta = -eta
            sol, r = _similitude(xi, eta, mx, my, w)
            echelle = math.hypot(*sol)
            if not 0.8 < echelle < 1.25:
                continue
            cout = float(np.median(r))
            if meilleur is None or cout < meilleur[0]:
                meilleur = (cout, dtc, miroir, sol)
    if meilleur is not None:
        _, dtc, miroir, sol = meilleur
        tm = float(np.median(t))
        sgn = -1.0 if miroir else 1.0

        def ajuste(d2, om, offset, w):
            """Similitude (+ rotation de champ linéaire ω, + décalage optionnel)."""
            xi = np.interp(t + d2, tt, txi)
            eta = np.interp(t + d2, tt, teta) * sgn
            ang = np.radians(om / 3600.0 * (t - tm))
            c, s_ = np.cos(ang), np.sin(ang)
            xr, yr = c * xi - s_ * eta, s_ * xi + c * eta
            Am = np.zeros((2 * len(t), 4 if offset else 2))
            Am[0::2, 0], Am[0::2, 1] = xr, -yr
            Am[1::2, 0], Am[1::2, 1] = yr, xr
            if offset:
                Am[0::2, 2], Am[1::2, 3] = 1, 1
            bv = np.empty(2 * len(t))
            bv[0::2], bv[1::2] = mx, my
            ww = np.repeat(np.sqrt(w), 2)
            so, *_ = np.linalg.lstsq(Am * ww[:, None], bv * ww, rcond=None)
            rr = np.sqrt(((Am @ so - bv).reshape(-1, 2) ** 2).sum(axis=1))
            return so, rr

        # Recherche conjointe : horloge δt + rotation de champ ω (°/h), grossière puis fine
        om = 0.0
        for (pas_t, plage_t, pas_o, plage_o) in ((10.0, 600.0, 0.5, 8.0), (2.0, 30.0, 0.05, 0.75),
                                                 (0.5, 5.0, 0.01, 0.1)):
            cands = []
            for d2 in np.arange(dtc - plage_t, dtc + plage_t + 1e-9, pas_t):
                for o2 in np.arange(om - plage_o, om + plage_o + 1e-9, pas_o):
                    so, rr = ajuste(d2, o2, False, w)
                    cands.append((float(np.sum(w * rr * rr)), d2, o2))
            _, dtc, om = min(cands)
            so, rr = ajuste(dtc, om, False, w)
            w = 1.0 / (1.0 + (rr / max(0.002, 2 * np.median(rr))) ** 2)
        sol, r = ajuste(dtc, om, False, w)
        rms = float(np.sqrt(np.average(r ** 2, weights=w)))
        # Décalage constant (erreur résiduelle d'éphémérides) s'il améliore nettement
        sol4, r4 = ajuste(dtc, om, True, w)
        rms4 = float(np.sqrt(np.average(r4 ** 2, weights=w)))
        ox = oy = 0.0
        if rms4 < 0.7 * rms:
            sol, r, rms = sol4, r4, rms4
            ox, oy = float(sol4[2]), float(sol4[3])
        return {"mode": "ephemerides", "dt_horloge": float(dtc), "miroir": bool(miroir), "ox": ox, "oy": oy,
                "omega_deg_h": float(om), "t_m": tm,
                "a": float(sol[0]), "b": float(sol[1]), "echelle": float(math.hypot(sol[0], sol[1])),
                "orientation_nord_deg": float(math.degrees(math.atan2(sol[1], sol[0]))),
                "table_t": tt.tolist(), "table_xi": txi.tolist(), "table_eta": teta.tolist(),
                "rms": rms, "_r": r}
    return None


def ajuster_trajectoire(projet: Projet, mesures: dict, journal) -> dict | None:
    secs = projet.secondes()
    idx = sorted(i for i, m in mesures.items() if m and "x" in m)
    if len(idx) < 4:
        journal("Lune : trop peu de mesures pour modéliser la trajectoire")
        return None
    t = secs[idx]
    mx = np.array([mesures[i]["x"] for i in idx])
    my = np.array([mesures[i]["y"] for i in idx])
    rho_m = float(np.median([mesures[i]["rho"] for i in idx]))
    pm = projet.donnees["params_modele"]
    mode = pm.get("trajectoire", "auto")
    t0_utc = projet.temps_utc(projet.images[0])
    peut_eph = pm.get("latitude") is not None and pm.get("longitude") is not None and t0_utc is not None \
        and projet.images[0].get("t_source") != "date du fichier"
    res: dict | None = None
    if mode in ("auto", "ephemerides") and peut_eph:
        lat, lon = float(pm["latitude"]), float(pm["longitude"])
        marge = 4 * 3600.0
        tt, txi, teta, tk = _table_ephemerides(t0_utc, t.min() - marge, t.max() + marge, lat, lon)
        res = caler_ephemerides(t, mx, my, tt, txi, teta)
        if res is not None:
            r = res.pop("_r")
            rms, dtc, om = res["rms"], res["dt_horloge"], res["omega_deg_h"]
            res.update({"k_ephem": float(np.median(tk)), "rho_m": rho_m})
            if rms > 0.03 and mode == "auto":
                journal(f"Éphémérides peu cohérentes avec les mesures (écart {rms:.3f} R☉) → polynôme")
                res = None
            else:
                journal(f"Trajectoire lunaire calée sur les éphémérides : écart RMS {rms * 1000:.1f} ‰ du rayon, "
                        f"horloge de l'appareil décalée de {dtc:+.0f} s, rotation de champ {om:+.2f}°/h")
    if res is None:
        deg = 2 if (t.max() - t.min()) > 600 and len(t) > 10 else 1
        tr = float(np.median(t))
        w = np.ones(len(t))
        for _ in range(4):
            px = np.polyfit(t - tr, mx, deg, w=w)
            py = np.polyfit(t - tr, my, deg, w=w)
            r = np.hypot(np.polyval(px, t - tr) - mx, np.polyval(py, t - tr) - my)
            w = 1.0 / (1.0 + (r / max(0.004, 2 * np.median(r))) ** 2)
        rms = float(np.sqrt(np.average(r ** 2, weights=w)))
        res = {"mode": "polynome", "px": px.tolist(), "py": py.tolist(), "t_ref": tr, "rho_m": rho_m, "rms": rms}
        journal(f"Trajectoire lunaire (polynôme degré {deg}) : écart RMS {rms * 1000:.1f} ‰ du rayon")
    res["residus"] = {int(i): float(v) for i, v in zip(idx, r)}
    # ---- Contacts dans le repère image ----
    traj = Trajectoire(res)
    ts = np.arange(t.min() - 4 * 3600, t.max() + 4 * 3600, 2.0)
    x, y = traj.position(ts)
    dist = np.hypot(x, y)
    cont = {}
    for nom_e, nom_s, seuil in (("C1", "C4", 1 + rho_m), ("C2", "C3", abs(1 - rho_m))):
        dedans = dist < seuil
        if dedans.any():
            k0 = int(np.argmax(dedans))
            k1 = len(dedans) - 1 - int(np.argmax(dedans[::-1]))
            if k0 > 0:
                cont[nom_e] = float(ts[k0])
            if k1 < len(ts) - 1:
                cont[nom_s] = float(ts[k1])
    kmax = int(np.argmin(dist))
    cont["max"] = float(ts[kmax])
    cont["magnitude"] = float((1 + rho_m - dist[kmax]) / 2)
    cont["obscuration_max"] = float(obscuration_disques(dist[kmax], rho_m))
    res["contacts"] = cont
    return res


def obscuration_disques(d: float, r: float) -> float:
    """Fraction de la surface solaire (rayon 1) masquée par un disque de rayon r à distance d."""
    if d >= 1 + r:
        return 0.0
    if d <= abs(r - 1):
        return min(1.0, r * r)
    a1 = math.acos(max(-1, min(1, (d * d + 1 - r * r) / (2 * d))))
    a2 = math.acos(max(-1, min(1, (d * d + r * r - 1) / (2 * d * r))))
    aire = a1 + r * r * a2 - 0.5 * math.sqrt(max(0, (-d + 1 + r) * (d + 1 - r) * (d - 1 + r) * (d + 1 + r)))
    return aire / math.pi


# ---------------------------------------------------------------------
# 5. D3 — SOLEIL DE RÉFÉRENCE (empilement des zones non masquées)
# ---------------------------------------------------------------------
def _masque_eligible(can, val, rho, moon, sat_seuil=0.985):
    lum = can if can.ndim == 2 else can @ LUM
    elig = (val > 0.99) & (rho < 1.03) & (moon < 0.01)
    elig &= (lum < sat_seuil) if can.ndim == 2 else (can.max(axis=2) < sat_seuil)
    return elig, lum


def _gains_canal(can, elig, rho):
    """Niveau de photosphère par canal (valeur / assombrissement centre-bord)."""
    sel = elig & (rho < 0.92)
    if sel.sum() < 200:
        return None
    L = assombrissement(rho[sel])
    lum = (can if can.ndim == 2 else can @ LUM)[sel] / L
    p99 = float(np.percentile(lum, 99))
    ecl = lum > 0.5 * p99
    if ecl.sum() < 100:
        return None
    if can.ndim == 2:
        return np.array([float(np.median(lum[ecl]))] * 3, np.float32)
    return np.array([float(np.median(can[:, :, ch][sel][ecl] / L[ecl])) for ch in range(3)], np.float32)


def niveau_noir(can, val, rho, lune, n, Rc, rho_m):
    """Niveau du noir par canal : intérieur de la Lune (meilleure référence :
    ciel + voile + offset du capteur), sinon anneau de ciel autour du Soleil."""
    if lune is not None:
        c = (n - 1) / 2.0
        y, x = np.ogrid[0:n, 0:n]
        d = np.sqrt((x - (c + lune[0] * Rc)) ** 2 + (y - (c + lune[1] * Rc)) ** 2)
        sel = (d < (rho_m - 0.08) * Rc) & (rho < 0.95) & (val > 0.99)
        if sel.sum() > 300:
            return np.array([float(np.median(can[:, :, ch][sel])) for ch in range(3)], np.float32)
    sel = (rho > 1.2) & (rho < 1.5) & (val > 0.99)
    if sel.sum() > 300:
        return np.array([float(np.percentile(can[:, :, ch][sel], 10)) for ch in range(3)], np.float32)
    return np.zeros(3, np.float32)


def _degrade_image(norm, elig, rho, X, Y, profil, avec_niveau=False):
    """Dégradé d'éclairage propre à UNE image (extinction au coucher du soleil,
    voile…) : plan a + b·X + c·Y ajusté de façon robuste sur le rapport
    image / profil attendu. Renvoie le facteur multiplicatif normalisé à 1 au
    centre, ou None si l'image n'offre pas assez de surface exploitable."""
    lum = norm @ LUM
    sel = elig & (rho < 0.85) & (profil > 0.05)
    if sel.sum() < 2000:
        return None
    r = lum[sel] / profil[sel]
    xs, ys = X[sel], Y[sel]
    garde = np.ones(r.size, bool)
    coef = None
    for _ in range(3):                                   # robuste : taches solaires et défauts écartés
        A = np.stack([np.ones(garde.sum()), xs[garde], ys[garde]], axis=1)
        coef, *_ = np.linalg.lstsq(A, r[garde], rcond=None)
        res = r - (coef[0] + coef[1] * xs + coef[2] * ys)
        mad = float(np.median(np.abs(res[garde]))) + 1e-6
        garde = np.abs(res) < 4 * 1.4826 * mad
    if coef is None or coef[0] <= 0:
        return None
    pente = np.hypot(coef[1], coef[2]) / coef[0]
    if pente > 0.5:                                      # ajustement aberrant : on s'abstient
        return None
    if avec_niveau:                                      # calage complet (niveau + dégradé)
        return (coef[0] + coef[1] * X + coef[2] * Y).astype(np.float32)
    return (1.0 + (coef[1] / coef[0]) * X + (coef[2] / coef[0]) * Y).astype(np.float32)


# Version de la méthode d'empilement : l'incrémenter invalide les calculs
# partiels d'anciens projets (2 = calage type panorama + raccords progressifs)
VERSION_REFERENCE = 2


def _profil_radial(lum: np.ndarray, rho: np.ndarray) -> np.ndarray:
    """Profil centre-bord MESURÉ (médiane par anneau) : référence parfaitement
    symétrique, sans aucun dégradé d'éclairage."""
    bins = np.clip((rho * 200).astype(int), 0, 299)
    ok = (lum > 0.02) & (rho < 1.0)
    somme = np.bincount(bins[ok], weights=lum[ok], minlength=300)
    nb = np.bincount(bins[ok], minlength=300)
    table = np.where(nb > 20, somme / np.maximum(nb, 1), 0.0).astype(np.float32)
    return table[bins]


def _travail_empilement(args):
    """Accumule une partie de la série (exécuté en parallèle).
    Chaque image est ramenée à un Soleil « neutre » (dégradé d'éclairage retiré)
    et sa contribution s'estompe progressivement à l'approche du bord de la
    Lune : aucune frontière nette (empreinte du bord lunaire) dans la moyenne."""
    dossier, indices, phis, lunes, rho_m, reference = args
    p = Projet.ouvrir(dossier)
    F = p.donnees["forme"]
    n = 2 * F["hc"] + 1
    Rc = F["A"] * F["echelle"]
    rho, X, Y = grille_rho(n, Rc)
    # 1re passe : dégradé retiré par rapport au modèle centre-bord théorique.
    # 2e passe : chaque image est calée (niveau + dégradé) sur la moyenne de la
    # 1re passe, là où elles se recouvrent — comme l'assemblage d'un panorama :
    # toutes les images deviennent cohérentes entre elles, sans raccord visible.
    profil = assombrissement(rho) if reference is None else (reference @ LUM)
    somme = np.zeros((n, n, 3), np.float32)
    poids = np.zeros((n, n), np.float32)
    gains = {}
    for i, phi, lune in zip(indices, phis, lunes):
        can, val = image_canonique(p, i, phi)
        if can.ndim == 2:
            can = np.repeat(can[:, :, None], 3, axis=2)
        if lune is not None:
            moon = disque_lunaire(n, Rc, lune[0], lune[1], rho_m + 0.015, 1.0)
            # Distance au bord lunaire (rayons solaires) → poids 0 au bord, 1 à 0,06 R☉
            d_bord = np.sqrt((X - lune[0]) ** 2 + (Y - lune[1]) ** 2) - rho_m
            fondu = np.clip((d_bord - 0.015) / 0.045, 0, 1)
        else:
            moon = np.zeros((n, n), np.float32)
            fondu = np.ones((n, n), np.float32)
        elig, lum = _masque_eligible(can, val, rho, moon)
        noir = niveau_noir(can, val, rho, lune, n, Rc, rho_m)
        can = np.clip(can - noir[None, None, :], 0, None)
        g = _gains_canal(can, elig, rho)
        if g is None:
            continue
        norm = can / g[None, None, :]
        deg = _degrade_image(norm, elig & (fondu > 0.5), rho, X, Y, profil, avec_niveau=reference is not None)
        if deg is not None:
            norm = norm / np.maximum(deg, 0.2)[:, :, None]
        gains[i] = {"g": g.tolist(), "noir": noir.tolist()}
        if reference is not None:   # rejet des nuages / défauts (2e passe)
            ecart = np.abs(norm @ LUM - reference @ LUM)
            elig &= ecart < 0.12 * np.maximum(reference @ LUM, 0.05)
        e = elig.astype(np.float32) * fondu
        somme += norm * e[:, :, None]
        poids += e
    return somme, poids, gains


def construire_reference(projet: Projet, phis, lune_pos, rho_m, journal, progression, annule, partiel=None):
    """Construit le Soleil de référence normalisé (≈1 au centre, par canal).
    partiel : dict de reprise (passes déjà calculées sauvegardées dans modele/)."""
    F = projet.donnees["forme"]
    n = 2 * F["hc"] + 1
    Rc = F["A"] * F["echelle"]
    ims = projet.images
    utiles = [i for i, im in enumerate(ims) if im.get("statut") in STATUTS_UTILES and im.get("cache")]
    nproc = nb_processus(projet.donnees["params_analyse"].get("processus", 0))
    paquets = [utiles[k::nproc * 2] for k in range(nproc * 2)]
    reference = None
    gains: dict = {}
    partiel = partiel if partiel is not None else {}
    for passe in (1, 2):
        if annule():
            raise Annulation()
        fich = projet.chemin("modele", f"passe{passe}.npz")
        if partiel.get(f"passe{passe}") and os.path.exists(fich):
            with np.load(fich) as z:
                reference, poids = z["moy"], z["poids"]
            gains = {int(k): v for k, v in partiel.get("gains", {}).items()}
            continue
        progression(0.45 + 0.2 * (passe - 1), f"Soleil de référence — passe {passe}/2")
        somme = np.zeros((n, n, 3), np.float32)
        poids = np.zeros((n, n), np.float32)
        args = [(projet.dossier, pq, [phis[i] for i in pq], [lune_pos.get(i) for i in pq], rho_m, reference)
                for pq in paquets if pq]
        with ProcessPoolExecutor(max_workers=nproc) as ex:
            for s, w, g in ex.map(_travail_empilement, args):
                somme += s
                poids += w
                gains.update(g)
        moy = somme / np.maximum(poids, 1e-6)[:, :, None]
        reference = moy
        np.savez(fich, moy=moy.astype(np.float32), poids=poids)
        partiel[f"passe{passe}"] = True
        partiel["gains"] = {str(k): v for k, v in gains.items()}
        projet.sauver()
    rho, _, _ = grille_rho(n, Rc)
    # Zones jamais vues (sous la Lune sur TOUTES les photos : série commencée
    # après le 1er contact et finie avant le dernier) ou vues par très peu
    # d'images : fondu progressif avec le profil centre-bord médian, pour
    # qu'aucun contour (empreinte du bord lunaire) ne subsiste.
    disque = rho < 1.03
    bins = np.clip((rho * 200).astype(int), 0, 299)
    vu = (poids > 2.0) & disque
    prof = np.zeros((n, n, 3), np.float32)
    for ch in range(3):
        table = np.zeros(300, np.float32)
        for b_ in np.unique(bins[vu]):
            table[b_] = np.median(reference[:, :, ch][vu & (bins == b_)])
        prof[:, :, ch] = table[bins]
    confiance = np.clip(poids / 6.0, 0, 1)                    # ≥ 6 images pleinement vues : donnée seule
    confiance = cv2.GaussianBlur(confiance, (0, 0), max(2.0, 0.01 * Rc))
    confiance = np.where(poids < 0.05, 0.0, confiance).astype(np.float32)
    # Modèle de remplissage = profil centre-bord × luminosité LOCALE environnante
    # (rapport donnée/profil lissé à grande échelle) : la zone comblée prend
    # exactement le niveau et la teinte de ce qui l'entoure.
    rapport = np.where(vu[:, :, None], reference / np.maximum(prof, 1e-4), 0.0).astype(np.float32)
    w = (confiance * vu).astype(np.float32)
    sig = max(4.0, 0.08 * Rc)
    den = cv2.GaussianBlur(w, (0, 0), sig)
    modele_loc = np.empty_like(reference)
    for ch in range(3):
        num = cv2.GaussianBlur(rapport[:, :, ch] * w, (0, 0), sig)
        modele_loc[:, :, ch] = prof[:, :, ch] * np.where(den > 1e-3, num / np.maximum(den, 1e-3), 1.0)
    cf = confiance[:, :, None]
    reference = np.where(disque[:, :, None], cf * reference + (1 - cf) * modele_loc, reference)
    manque = (poids < 0.5) & (rho < 1)
    if manque.any():
        journal(f"Soleil de référence : {100 * manque.sum() / max(1, (rho < 1).sum()):.1f} % du disque "
                "jamais visible, complété par le profil centre-bord (raccord progressif)")
    # Ciel noir au-delà du limbe (adoucissement 1 %)
    fondu = np.clip((1.03 - rho) / 0.02, 0, 1)
    reference *= fondu[:, :, None]
    couverture = float(((poids > 0.5) & (rho < 1)).sum() / max(1, (rho < 1).sum()))
    return reference.astype(np.float32), gains, couverture


# ---------------------------------------------------------------------
# 6. D4 — UNIFORMISATION PHOTOMÉTRIQUE (coefficients par image)
# ---------------------------------------------------------------------
def _travail_photometrie(args):
    dossier, indices, phis, lunes, rho_m, ref_cible = args
    p = Projet.ouvrir(dossier)
    F = p.donnees["forme"]
    n = 2 * F["hc"] + 1
    Rc = F["A"] * F["echelle"]
    rho, X, Y = grille_rho(n, Rc)
    out = {}
    rng = np.random.default_rng(1)
    for i, phi, lune in zip(indices, phis, lunes):
        can, val = image_canonique(p, i, phi)
        if can.ndim == 2:
            can = np.repeat(can[:, :, None], 3, axis=2)
        moon = disque_lunaire(n, Rc, lune[0], lune[1], rho_m + 0.02, 1.0) if lune is not None \
            else np.zeros((n, n), np.float32)
        elig, _ = _masque_eligible(can, val, rho, moon)
        elig &= rho < 0.97
        yy, xx = np.nonzero(elig)
        if len(xx) < 400:
            continue
        if len(xx) > 30000:
            s = rng.choice(len(xx), 30000, replace=False)
            yy, xx = yy[s], xx[s]
        # Ancrages sombres : intérieur de la Lune et ciel → doivent devenir noirs
        sombre = np.zeros((n, n), bool)
        if lune is not None:
            sombre |= (disque_lunaire(n, Rc, lune[0], lune[1], rho_m - 0.06, 1.0) > 0.99) & (rho < 0.95)
        sombre |= (rho > 1.15) & (rho < 1.45)
        sombre &= val > 0.99
        ys, xs = np.nonzero(sombre)
        if len(xs) > 6000:
            s = rng.choice(len(xs), 6000, replace=False)
            ys, xs = ys[s], xs[s]
        poids_sombre = 0.25 * len(xx) / max(1, len(xs))
        coefs = []
        for ch in range(3):
            v = np.concatenate([can[yy, xx, ch], can[ys, xs, ch]])
            r = np.concatenate([ref_cible[yy, xx, ch], np.zeros(len(xs), np.float32)])
            Xs = np.concatenate([X[yy, xx], X[ys, xs]])
            Ys = np.concatenate([Y[yy, xx], Y[ys, xs]])
            w0 = np.concatenate([np.ones(len(xx)), np.full(len(xs), poids_sombre)])
            Am = np.stack([v, v * Xs, v * Ys, np.ones_like(v)], axis=1)
            w = w0.copy()
            sol = None
            for _ in range(3):  # IRLS (rejette nuages résiduels, taches mal placées)
                sol, *_ = np.linalg.lstsq(Am * np.sqrt(w)[:, None], r * np.sqrt(w), rcond=None)
                res = Am @ sol - r
                w = w0 / (1.0 + (res / max(1e-4, 2.5 * np.median(np.abs(res)))) ** 2)
            coefs.append([float(c) for c in sol])
        out[i] = coefs
    return out


def calculer_photometrie(projet: Projet, phis, lune_pos, rho_m, ref_cible, progression, annule, partiel=None):
    ims = projet.images
    partiel = partiel if partiel is not None else {}
    res = {int(k): v for k, v in partiel.get("coefs", {}).items()}
    utiles = [i for i, im in enumerate(ims) if im.get("statut") in STATUTS_UTILES and im.get("cache")
              and i not in res and str(i) not in partiel.get("sans_coef", {})]
    nproc = nb_processus(projet.donnees["params_analyse"].get("processus", 0))
    paquets = [utiles[k:k + 6] for k in range(0, len(utiles), 6)]
    args = [(projet.dossier, pq, [phis[i] for i in pq], [lune_pos.get(i) for i in pq], rho_m, ref_cible)
            for pq in paquets if pq]
    progression(0.85, "Uniformisation des expositions et des couleurs…")
    with ProcessPoolExecutor(max_workers=nproc) as ex:
        futurs = {ex.submit(_travail_photometrie, a): a[1] for a in args}
        for fu in as_completed(futurs):
            o = fu.result()
            res.update(o)
            for i in futurs[fu]:
                if i not in o:
                    partiel.setdefault("sans_coef", {})[str(i)] = True
            partiel["coefs"] = {str(k): v for k, v in res.items()}
            progression(0.85 + 0.13 * len(res) / max(1, len(res) + len(utiles)), "Uniformisation…")
            if annule():
                for f2 in futurs:
                    f2.cancel()
                projet.sauver()
                raise Annulation()
    return res


def lisser_coefficients(projet: Projet, coefs: dict, fen: int) -> dict:
    """Médiane glissante des coefficients (évite le scintillement)."""
    if fen <= 1 or not coefs:
        return coefs
    cles = sorted(coefs)
    arr = np.array([coefs[k] for k in cles])        # (N, 3, 4)
    h = fen // 2
    lis = np.array([np.median(arr[max(0, j - h): j + h + 1], axis=0) for j in range(len(cles))])
    return {k: lis[j].tolist() for j, k in enumerate(cles)}


# ---------------------------------------------------------------------
# 7. ORCHESTRATION
# ---------------------------------------------------------------------
def modeliser(projet: Projet, progression, journal, annule, reprendre: bool = False):
    """Étapes D1 à D4 ; résultats dans projet.donnees['modele'] et modele/.
    reprendre=True : réutilise les calculs déjà faits si les réglages n'ont pas changé."""
    F = projet.donnees["forme"]
    if not F:
        raise RuntimeError("Lancez d'abord l'analyse.")
    from .analyse import message_inexploitable
    msg = message_inexploitable(F)
    if msg:
        raise RuntimeError(msg)
    # D0 : poussières du capteur (avant toute mesure, pour qu'elles ne faussent rien)
    os.makedirs(projet.chemin("modele"), exist_ok=True)
    pm0 = projet.donnees["params_modele"]
    partiel0 = projet.donnees.get("partiel") or {}
    if pm0.get("effacer_poussieres", True) and not (reprendre and partiel0.get("poussieres_faites")):
        from .poussieres import calculer_carte
        projet.donnees["poussieres"] = calculer_carte(projet, journal, progression,
                                                      nb_processus(projet.donnees["params_analyse"].get("processus", 0)))
        projet.sauver()
    elif not pm0.get("effacer_poussieres", True):
        projet.donnees["poussieres"] = None
    if F.get("type") == "lunaire":
        from .modele_lunaire import modeliser_lune
        return modeliser_lune(projet, progression, journal, annule, reprendre)
    pm = projet.donnees["params_modele"]
    ims = projet.images
    os.makedirs(projet.chemin("modele"), exist_ok=True)
    n = 2 * F["hc"] + 1
    Rc = F["A"] * F["echelle"]
    phis = angles_derotation(projet)
    for i, im in enumerate(ims):
        im["derotation"] = float(phis[i])
    utiles = [i for i, im in enumerate(ims) if im.get("statut") in STATUTS_UTILES and im.get("cache")]
    nproc = nb_processus(projet.donnees["params_analyse"].get("processus", 0))

    # Signature des réglages : toute modification invalide les calculs partiels
    sig = json.dumps([pm.get(c) for c in ("latitude", "longitude", "decalage_utc_h", "monture", "sens_derotation",
                                          "trajectoire", "uniformisation", "teinte_cible", "effacer_poussieres")]
                     + [len(utiles), F.get("hc"), VERSION_REFERENCE], default=str)
    partiel = projet.donnees.get("partiel") or {}
    if not reprendre or partiel.get("sig") != sig:
        partiel = {"sig": sig}
    partiel["poussieres_faites"] = True
    projet.donnees["partiel"] = partiel
    projet.sauver()   # les travailleurs relisent le projet

    # ---- D1 : mesure de la Lune (rayon libre, puis rayon fixé) ----
    progression(0.02, "Mesure de la Lune…")
    # 1) PHOTO PIVOT : l'image du milieu de la série (la plus proche où la Lune
    #    est mesurable) donne un premier rayon lunaire.
    # 2) TOUTES LES PHOTOS sont mesurées en rayon libre (±6 % du pivot).
    # 3) Rayon final = médiane pondérée (longueur d'arc visible) de toutes les
    #    mesures ; chaque centre est ensuite recalculé avec ce rayon commun
    #    à partir des points de bord déjà mesurés (sans relire les images).
    if "rho_pivot" not in partiel:
        milieu = len(utiles) // 2
        ordre = sorted(utiles, key=lambda i: abs(utiles.index(i) - milieu))[:15]
        with ProcessPoolExecutor(max_workers=nproc) as ex:
            essais = list(ex.map(_travail_lune, [(projet.dossier, i, phis[i], None, None) for i in ordre]))
        pivot = next(((i, m) for i, m in essais if m and "rho" in m and m["couverture"] > 0.15
                      and 0.9 <= m["rho"] <= 1.12), None)
        partiel["rho_pivot"] = pivot[1]["rho"] if pivot else None
        partiel["pivot_lune"] = ims[pivot[0]]["nom"] if pivot else None
        partiel["lunes_libres"] = {}
        projet.sauver()
    rho_pivot = partiel["rho_pivot"]
    if rho_pivot:
        journal(f"Photo pivot pour la Lune : {partiel['pivot_lune']} — rayon {rho_pivot:.4f} × Soleil")
    libres = partiel.setdefault("lunes_libres", {})
    if rho_pivot:
        restants = [i for i in utiles if str(i) not in libres]
        derniere = time.time()
        with ProcessPoolExecutor(max_workers=nproc) as ex:
            futurs = [ex.submit(_travail_lune, (projet.dossier, i, phis[i], None, rho_pivot)) for i in restants]
            for fu in as_completed(futurs):
                i, m = fu.result()
                libres[str(i)] = m if (m and "x" in m) else None
                progression(0.05 + 0.3 * len(libres) / max(1, len(utiles)),
                            f"Mesure de la Lune {len(libres)}/{len(utiles)}")
                if time.time() - derniere > 20:
                    projet.sauver()
                    derniere = time.time()
                if annule():
                    for f2 in futurs:
                        f2.cancel()
                    projet.sauver()
                    raise Annulation()
    valides = [m for m in libres.values() if m and m.get("couverture", 0) > 0.1 and 0.9 <= m["rho"] <= 1.12]
    rho_m = None
    if len(valides) >= 3:
        from .analyse import mediane_ponderee
        rho_m = mediane_ponderee([m["rho"] for m in valides], [m["n"] * m["couverture"] for m in valides])
        disp = float(np.std([m["rho"] for m in valides]))
        journal(f"Rayon apparent de la Lune : {rho_m:.4f} × rayon solaire "
                f"(mesuré sur {len(valides)} photos, dispersion {disp:.4f})")
    else:
        journal("Lune non détectée de façon fiable (éclipse non commencée sur les images ?)")
    partiel["rho_m"] = rho_m
    # Centres recalculés avec le rayon commun (à partir des points de bord mémorisés)
    lunes = {}
    for k_, m in libres.items():
        if not (rho_m and m and m.get("pts")):
            lunes[k_] = None
            continue
        pts = np.array(m["pts"], np.float64)
        vals, sig, rms, w = ajuster_ellipse(pts, m["x"], m["y"], Forme(rho_m, 1.0, 0.0), ("cx", "cy"), echelle=0.004)
        lunes[k_] = {"x": float(vals["cx"]), "y": float(vals["cy"]), "rho": rho_m, "couverture": m["couverture"],
                     "residu": float(rms), "n": m["n"], "sigma": float(math.hypot(sig["cx"], sig["cy"]))}
    partiel["lunes"] = lunes
    mesures = {int(k): (dict(v) if v else None) for k, v in lunes.items()}
    for i, im in enumerate(ims):
        im["lune"] = mesures.get(i)

    # ---- D2 : trajectoire ----
    progression(0.38, "Calcul de la trajectoire lunaire…")
    traj_d = ajuster_trajectoire(projet, mesures, journal) if rho_m else None
    if traj_d and traj_d.get("rms", 1) > 0.05:
        journal(f"⚠ Trajectoire de la Lune peu fiable (écart {1000 * traj_d['rms']:.0f} ‰ du rayon) : "
                "pas de reconstitution du début / de la fin")
        traj_d = None
    # Dérotation AUTOMATIQUE : la rotation de champ mesurée grâce à la Lune
    # (mise en station imparfaite, monture altazimutale…) est compensée.
    secs = projet.secondes()
    if traj_d and pm.get("monture", "auto") == "auto" and traj_d.get("omega_deg_h"):
        om = traj_d["omega_deg_h"]
        duree_h = (secs.max() - secs.min()) / 3600.0
        if abs(om) * duree_h > 0.15:
            dphi = -om / 3600.0 * (secs - traj_d["t_m"])
            for i, m in mesures.items():
                if m:
                    a_ = math.radians(dphi[i])
                    x, y = m["x"], m["y"]
                    m["x"], m["y"] = math.cos(a_) * x - math.sin(a_) * y, math.sin(a_) * x + math.cos(a_) * y
            phis = phis + dphi
            for i, im in enumerate(ims):
                im["derotation"] = float(phis[i])
                im["lune"] = mesures.get(i)
            journal(f"Rotation de champ de {om:+.2f}°/h détectée ({om * duree_h:+.2f}° sur la série) : "
                    "dérotation automatique appliquée")
            traj_d = ajuster_trajectoire(projet, mesures, journal)
            traj_d["rotation_champ_deg_h"] = om
    secs = projet.secondes()
    lune_pos = {}
    if traj_d:
        traj = Trajectoire(traj_d)
        x, y = traj.position(secs)
        for i in range(len(ims)):
            lune_pos[i] = (float(x[i]), float(y[i]))
            ims[i]["lune_modele"] = [float(x[i]), float(y[i])]
            ims[i]["obscuration_modele"] = obscuration_disques(math.hypot(x[i], y[i]), traj_d["rho_m"])
        c = traj_d["contacts"]
        t0 = projet.temps_utc(ims[0])
        if t0:
            dth = traj_d.get("dt_horloge", 0.0)
            desc = ", ".join(f"{k} {(t0 + dt.timedelta(seconds=v + dth)).strftime('%H:%M:%S')} UT"
                             for k, v in c.items() if k in ("C1", "C2", "max", "C3", "C4"))
            journal(f"Contacts (modèle) : {desc} — magnitude {c['magnitude']:.3f}, "
                    f"obscuration max {100 * c['obscuration_max']:.1f} %")
    else:
        # Pas de modèle : masque lunaire mesuré image par image si disponible
        for i, m in mesures.items():
            if m:
                lune_pos[i] = (m["x"], m["y"])
    rho_eff = traj_d["rho_m"] if traj_d else (rho_m or 1.0)

    # ---- D3 : Soleil de référence ----
    reference, gains, couv = construire_reference(projet, phis, lune_pos, rho_eff, journal, progression, annule,
                                                  partiel)
    journal(f"Soleil de référence reconstitué ({100 * couv:.1f} % du disque observé)")
    # Couleur cible
    G = np.array([gains[i]["g"] for i in sorted(gains)]) if gains else np.ones((1, 3))
    teinte = pm.get("teinte_cible", "naturelle")
    cible = np.median(G, axis=0)
    if teinte == "naturelle" and str(F.get("methode", "")).startswith("fits-cfa"):
        journal("Données brutes CFA sans balance des blancs : teinte cible « neutre » utilisée")
        teinte = "neutre"
    if teinte == "chaude":
        cible = np.array([1.0, 0.80, 0.58]) * float(cible @ LUM)
    if teinte == "neutre":
        cible = np.full(3, float(cible @ LUM))
    # Le niveau cible est ramené pour que le centre du disque atteigne ~0.9
    niveau = 0.9 / max(1e-6, float((reference[n // 2 - 3:n // 2 + 4, n // 2 - 3:n // 2 + 4] @ LUM).mean()))
    cible_norm = cible / max(1e-6, float(cible @ LUM))
    ref_cible = reference * (cible_norm * niveau)[None, None, :]
    np.save(projet.chemin("modele", "reference.npy"), ref_cible.astype(np.float32))
    np.save(projet.chemin("modele", "reference_norm.npy"), reference.astype(np.float32))

    # ---- D4 : uniformisation ----
    coefs = calculer_photometrie(projet, phis, lune_pos, rho_eff, ref_cible, progression, annule, partiel) \
        if pm.get("uniformisation", "complete") != "aucune" else {}
    coefs = lisser_coefficients(projet, coefs, int(pm.get("lissage_photometrique", 5)))
    for i, im in enumerate(ims):
        im["gains"] = gains[i]["g"] if i in gains else None
        im["noir"] = gains[i]["noir"] if i in gains else None
        im["photo"] = coefs.get(i)
    projet.donnees["modele"] = {
        "trajectoire": traj_d, "rho_m": rho_eff, "couverture_reference": couv,
        "teinte_cible": cible_norm.tolist(), "niveau": niveau,
        "gain_cible": (cible_norm * niveau).tolist(),
        "date": dt.datetime.now().isoformat(timespec="seconds"),
    }
    projet.donnees["etape"] = "modele"
    projet.sauver()
    progression(1.0, "Modélisation terminée")
