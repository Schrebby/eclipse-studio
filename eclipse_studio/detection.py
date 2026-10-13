# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jérémy BEAUFRERE — JEREMiA (https://jerem-ia.fr)
# Éclipse Studio est un logiciel libre : vous pouvez le redistribuer et/ou le
# modifier selon les termes de la GNU GPL v3 ou ultérieure (voir LICENSE).
"""
=====================================================================
 Éclipse Studio — Module DÉTECTION DU DISQUE SOLAIRE
=====================================================================
 Objectif : retrouver, dans chaque image, le centre exact du disque
 solaire (au sous-pixel), même lorsque la Lune en masque l'essentiel,
 que des nuages passent ou que le Soleil est aplati près de l'horizon.

 Principe (robuste par construction) :
   1. TRANSFORMÉE DE HOUGH ORIENTÉE (grossière, image réduite)
      Chaque point de contour vote pour un centre situé à la distance
      R dans le sens du gradient (du sombre vers le clair).
        - Bord du Soleil  : le clair est À L'INTÉRIEUR du cercle
          → tous les votes convergent vers le centre du Soleil.
        - Bord de la Lune : le clair est À L'EXTÉRIEUR
          → les votes s'éparpillent et ne forment pas de pic.
      La Lune ne peut donc pas « attirer » l'alignement, quel que soit
      le côté où elle se trouve.
   2. AFFINAGE PAR RAYONS (pleine résolution, sous-pixel)
      360 profils radiaux autour du centre estimé ; sur chacun on
      repère la chute clair→sombre du limbe. Un rayon n'est retenu que
      si l'intérieur est lumineux (photosphère) et l'extérieur sombre
      (ciel) : les rayons qui tombent sur la Lune ou sur un nuage
      épais sont rejetés.
   3. AJUSTEMENT ROBUSTE D'UNE ELLIPSE DE TAILLE CONNUE
      Le rayon R est connu (estimé une fois pour toute la série), donc
      un simple arc de limbe suffit à positionner le centre. Une
      ellipse (aplatissement k, angle θ) est permise pour absorber la
      réfraction atmosphérique près de l'horizon. Les points aberrants
      sont neutralisés par une pondération de Cauchy (IRLS).
   4. MODE LUNE (totalité)
      Si aucun limbe solaire n'est visible, on cherche le disque sombre
      de la Lune entouré de la couronne (gradient inversé).
=====================================================================
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import cv2
import numpy as np


# ---------------------------------------------------------------------
# 1. STRUCTURES DE DONNÉES
# ---------------------------------------------------------------------
@dataclass
class Forme:
    """Forme du disque : demi-grand axe A (px), aplatissement k = B/A
    (1 = cercle) et angle θ (radians) de l'axe A dans l'image."""
    A: float
    k: float = 1.0
    theta: float = 0.0


@dataclass
class ResultatDetection:
    """Résultat de la détection pour une image (coordonnées pleine résolution)."""
    ok: bool = False
    mode: str = "echec"            # "soleil", "lune" ou "echec"
    cx: float = float("nan")
    cy: float = float("nan")
    forme: Forme | None = None
    sigma_centre: float = float("inf")   # incertitude estimée du centre (px)
    sigma_k: float = float("inf")        # incertitude de l'aplatissement
    couverture: float = 0.0              # fraction du limbe effectivement vue (0-1)
    nettete: float = 0.0                 # raideur moyenne du bord (qualité)
    largeur_bord: float = 0.0            # largeur du bord (px) : petite = limbe net (filtre solaire)
    fond_relatif: float = 0.0            # ciel juste hors du disque / disque : ~0 avec filtre, élevé = halo
    residu: float = float("inf")         # RMS des écarts au modèle (px)
    points: np.ndarray = field(default_factory=lambda: np.zeros((0, 2), np.float32))
    message: str = ""


# ---------------------------------------------------------------------
# 2. OUTILS DE BASE
# ---------------------------------------------------------------------
def normaliser(img: np.ndarray) -> np.ndarray:
    """Ramène l'image entre ~0 (ciel) et ~1 (photosphère) de façon robuste."""
    img = img.astype(np.float32, copy=False)
    echant = img[:: max(1, img.shape[0] // 400), :: max(1, img.shape[1] // 400)]
    bas = float(np.percentile(echant, 1.0))
    haut = float(np.percentile(echant, 99.9))
    if haut - bas < 1e-6:
        haut = bas + 1.0
    return (img - bas) / (haut - bas)


def reduire(img: np.ndarray, dim_max: int = 1024) -> tuple[np.ndarray, float]:
    """Réduit l'image (dimension max = dim_max). Renvoie (image, facteur)."""
    h, w = img.shape[:2]
    f = min(1.0, dim_max / float(max(h, w)))
    if f >= 1.0:
        return img, 1.0
    petite = cv2.resize(img, (int(round(w * f)), int(round(h * f))), interpolation=cv2.INTER_AREA)
    return petite, f


def points_de_contour(img: np.ndarray, sigma: float = 1.5, frac: float = 0.15,
                      max_points: int = 40000, graine: int = 0):
    """Extrait les points de fort gradient + leur direction unitaire
    (orientée du sombre vers le clair) et leur poids (= amplitude)."""
    lisse = cv2.GaussianBlur(img, (0, 0), sigma)
    gx = cv2.Sobel(lisse, cv2.CV_32F, 1, 0, ksize=3) / 8.0
    gy = cv2.Sobel(lisse, cv2.CV_32F, 0, 1, ksize=3) / 8.0
    mag = np.hypot(gx, gy)
    seuil = frac * float(np.percentile(mag, 99.95))
    if seuil <= 0:
        return None
    ys, xs = np.nonzero(mag > seuil)
    if xs.size < 20:
        return None
    if xs.size > max_points:  # sous-échantillonnage aléatoire reproductible
        sel = np.random.default_rng(graine).choice(xs.size, max_points, replace=False)
        xs, ys = xs[sel], ys[sel]
    m = mag[ys, xs]
    ux, uy = gx[ys, xs] / m, gy[ys, xs] / m
    return xs.astype(np.float32), ys.astype(np.float32), ux, uy, m


def hough_oriente(contour, rayon: float, forme_img: tuple[int, int], signe: int = +1,
                  flou: float = 1.5):
    """Accumulateur de Hough orienté pour UN rayon donné.
    signe=+1 : disque clair (Soleil) ; signe=-1 : disque sombre (Lune).
    Renvoie (score, cx, cy, accumulateur)."""
    xs, ys, ux, uy, m = contour
    h, w = forme_img
    vx = np.rint(xs + signe * rayon * ux).astype(np.int64)
    vy = np.rint(ys + signe * rayon * uy).astype(np.int64)
    ok = (vx >= 0) & (vx < w) & (vy >= 0) & (vy < h)
    acc = np.bincount(vy[ok] * w + vx[ok], weights=m[ok], minlength=h * w).astype(np.float32)
    acc = cv2.GaussianBlur(acc.reshape(h, w), (0, 0), flou)
    idx = int(np.argmax(acc))
    cy, cx = divmod(idx, w)
    # Raffinement du pic par barycentre local 5x5
    y0, y1 = max(0, cy - 2), min(h, cy + 3)
    x0, x1 = max(0, cx - 2), min(w, cx + 3)
    bloc = acc[y0:y1, x0:x1]
    s = float(bloc.sum())
    if s > 0:
        yy, xx = np.mgrid[y0:y1, x0:x1]
        cx, cy = float((bloc * xx).sum() / s), float((bloc * yy).sum() / s)
    # Score normalisé : poids concentré au pic / poids attendu pour un limbe complet
    pic = float(acc.max())
    score = pic * (2 * math.pi * flou ** 2) / max(1e-6, 2 * math.pi * rayon * float(np.median(m)))
    return score, float(cx), float(cy), acc, pic


def rayon_ellipse(phi: np.ndarray, forme: Forme) -> np.ndarray:
    """Distance centre→bord de l'ellipse dans la direction phi."""
    B = forme.A * forme.k
    d = phi - forme.theta
    return 1.0 / np.sqrt((np.cos(d) / forme.A) ** 2 + (np.sin(d) / B) ** 2)


# ---------------------------------------------------------------------
# 3. RECHERCHE GROSSIÈRE (Hough sur image réduite)
# ---------------------------------------------------------------------
def recherche_grossiere(img_norm: np.ndarray, rayon_connu: float | None = None,
                        dim_max: int = 1024, signe: int = +1, rayon_approx: float | None = None):
    """Trouve un centre approximatif. Si le rayon est inconnu, balaye une
    gamme de rayons et garde celui qui concentre le mieux les votes.
    Renvoie (cx, cy, rayon, score) en coordonnées pleine résolution."""
    petite, f = reduire(img_norm, dim_max)
    contour = points_de_contour(petite)
    if contour is None:
        return None
    h, w = petite.shape[:2]
    if rayon_connu is not None:
        rayons = [rayon_connu * f * c for c in (0.96, 1.0, 1.04)]
    elif rayon_approx is not None:
        # Rayon déjà connu à ±15 % (photo pivot) : recherche restreinte, plus sûre
        rayons = list(np.geomspace(0.85 * rayon_approx * f, 1.15 * rayon_approx * f, 25))
    else:
        rmin, rmax = 8.0, 0.75 * min(h, w)
        rayons = list(np.geomspace(rmin, rmax, 70))
    # Sélection par PIC BRUT : seul le vrai rayon fait converger tout un
    # arc de limbe vers un point unique (les petits rayons ne donnent que
    # des courbes diffuses, ex. axe médian d'un croissant).
    meilleurs = []
    for r in rayons:
        score, cx, cy, _, pic = hough_oriente(contour, r, (h, w), signe)
        meilleurs.append((pic, score, cx, cy, r))
    meilleurs.sort(key=lambda t: t[0], reverse=True)
    pic, score, cx, cy, r = meilleurs[0]
    if rayon_connu is None:
        # Affinage local du rayon autour du meilleur
        for r2 in np.linspace(r * 0.94, r * 1.06, 13):
            p2, s2, cx2, cy2, _ = (lambda t: (t[4], t[0], t[1], t[2], t))(hough_oriente(contour, r2, (h, w), signe))
            if p2 > pic:
                pic, score, cx, cy, r = p2, s2, cx2, cy2, r2
    return cx / f, cy / f, r / f, score


# ---------------------------------------------------------------------
# 4. AFFINAGE PAR PROFILS RADIAUX (pleine résolution)
# ---------------------------------------------------------------------
def profils_radiaux(img: np.ndarray, cx: float, cy: float, forme: Forme,
                    demi_fenetre: float, n_rayons: int = 360, pas: float = 0.5):
    """Échantillonne n_rayons profils radiaux de part et d'autre du bord
    attendu. Renvoie (phi, rho, profils) ; profils = NaN hors image."""
    phi = np.linspace(0, 2 * math.pi, n_rayons, endpoint=False).astype(np.float32)
    rho0 = rayon_ellipse(phi, forme).astype(np.float32)
    n_ech = int(min(800, max(16, 2 * demi_fenetre / pas)))
    decal = np.linspace(-demi_fenetre, demi_fenetre, n_ech, dtype=np.float32)
    rho = rho0[:, None] + decal[None, :]
    mx = (cx + rho * np.cos(phi)[:, None]).astype(np.float32)
    my = (cy + rho * np.sin(phi)[:, None]).astype(np.float32)
    prof = cv2.remap(img, mx, my, cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=np.nan)
    h, w = img.shape[:2]
    hors = (mx < 1) | (my < 1) | (mx > w - 2) | (my > h - 2)
    prof[hors] = np.nan
    return phi, rho, prof


def detecter_bords(phi, rho, prof, signe: int = +1, lissage: float = 2.0):
    """Sur chaque profil, localise au sous-pixel le saut d'intensité.
    signe=+1 : clair dedans → sombre dehors (limbe solaire)
    signe=-1 : sombre dedans → clair dehors (limbe lunaire en totalité)
    Renvoie (rho_bord, interieur, exterieur, pente, valide)."""
    n, m = prof.shape
    p = np.nan_to_num(prof, nan=0.0)
    if lissage > 0:
        p = cv2.GaussianBlur(p, (0, 0), sigmaX=lissage, sigmaY=0.01)
    d = -np.gradient(p, axis=1) * signe         # chute positive au bord recherché
    marge = 4
    d[:, :marge] = -np.inf
    d[:, -marge:] = -np.inf
    j = np.argmax(d, axis=1)
    lignes = np.arange(n)
    # Parabole sous-pixel
    j0 = np.clip(j, 1, m - 2)
    a, b, c = d[lignes, j0 - 1], d[lignes, j0], d[lignes, j0 + 1]
    den = (a - 2 * b + c)
    with np.errstate(all="ignore"):
        off = np.where(np.abs(den) > 1e-12, 0.5 * (a - c) / den, 0.0)
    off = np.clip(np.nan_to_num(off), -1, 1)
    pas = (rho[0, 1] - rho[0, 0])
    rho_bord = rho[lignes, j0] + off * pas
    # Niveaux intérieur / extérieur (fenêtres de part et d'autre du bord)
    ecart, larg = 8, 14
    idx_in = np.clip(j0[:, None] - ecart - np.arange(larg)[None, :], 0, m - 1)
    idx_out = np.clip(j0[:, None] + ecart + np.arange(larg)[None, :], 0, m - 1)
    with np.errstate(all="ignore"):
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            v_in = np.nanmedian(np.take_along_axis(prof, idx_in, axis=1), axis=1)
            v_out = np.nanmedian(np.take_along_axis(prof, idx_out, axis=1), axis=1)
    # Un rayon touchant le bord de l'image est invalide
    nan_seg = np.isnan(prof[lignes[:, None], np.clip(j0[:, None] + np.arange(-ecart - larg, ecart + larg)[None, :], 0, m - 1)]).any(axis=1)
    pente = d[lignes, j0]
    if signe > 0:
        clair, sombre = v_in, v_out
    else:
        clair, sombre = v_out, v_in
    valide = (~nan_seg) & np.isfinite(clair) & np.isfinite(sombre) & (j0 > marge) & (j0 < m - marge - 1)
    return rho_bord, clair, sombre, pente, valide


# ---------------------------------------------------------------------
# 5. AJUSTEMENT ROBUSTE D'ELLIPSE (Gauss-Newton + pondération de Cauchy)
# ---------------------------------------------------------------------
def _residus(params, pts, libres, fixes):
    v = dict(fixes)
    v.update(zip(libres, params))
    cx, cy, A, k, th = v["cx"], v["cy"], v["A"], v["k"], v["theta"]
    dx, dy = pts[:, 0] - cx, pts[:, 1] - cy
    c, s = math.cos(th), math.sin(th)
    xp = (dx * c + dy * s) / A
    yp = (-dx * s + dy * c) / (A * k)
    rn = np.sqrt(xp * xp + yp * yp)
    # Résidu ≈ distance radiale au bord, en pixels
    return (rn - 1.0) * np.hypot(dx, dy) / np.maximum(rn, 1e-9)


def ajuster_ellipse(pts: np.ndarray, cx: float, cy: float, forme: Forme,
                    libres=("cx", "cy"), echelle: float = 2.0, iterations: int = 30):
    """Ajuste les paramètres 'libres' parmi cx, cy, A, k, theta.
    Renvoie (valeurs, sigmas, rms, poids)."""
    fixes = {"cx": cx, "cy": cy, "A": forme.A, "k": forme.k, "theta": forme.theta}
    x = np.array([fixes[n] for n in libres], dtype=np.float64)
    pts = pts.astype(np.float64)
    pas_num = {"cx": 0.05, "cy": 0.05, "A": 0.05, "k": 1e-4, "theta": 1e-4}
    w = np.ones(len(pts))
    J = None
    for _ in range(iterations):
        r = _residus(x, pts, libres, fixes)
        # Pondération de Cauchy (IRLS) : neutralise les points aberrants
        w = 1.0 / (1.0 + (r / echelle) ** 2)
        J = np.empty((len(pts), len(libres)))
        for i, n in enumerate(libres):
            xd = x.copy()
            xd[i] += pas_num[n]
            J[:, i] = (_residus(xd, pts, libres, fixes) - r) / pas_num[n]
        JW = J * w[:, None]
        H = J.T @ JW + 1e-9 * np.eye(len(libres))
        g = JW.T @ r
        try:
            dx = -np.linalg.solve(H, g)
        except np.linalg.LinAlgError:
            break
        x += dx
        if "k" in libres:
            i = libres.index("k")
            x[i] = float(np.clip(x[i], 0.6, 1.05))
        if np.all(np.abs(dx) < 1e-4):
            break
    r = _residus(x, pts, libres, fixes)
    w = 1.0 / (1.0 + (r / echelle) ** 2)
    neff = max(1.0, float(w.sum()))
    rms = float(np.sqrt((w * r * r).sum() / neff))
    sig = np.full(len(libres), np.inf)
    try:
        cov = np.linalg.inv(J.T @ (J * w[:, None])) * max(rms, 0.2) ** 2
        sig = np.sqrt(np.abs(np.diag(cov)))
    except Exception:
        pass
    vals = dict(fixes)
    vals.update(zip(libres, x))
    return vals, dict(zip(libres, sig)), rms, w


def couverture_angulaire(phi_valides: np.ndarray, n_secteurs: int = 72) -> float:
    """Fraction des secteurs angulaires (5°) contenant au moins un point de limbe."""
    if phi_valides.size == 0:
        return 0.0
    sect = np.floor((phi_valides % (2 * math.pi)) / (2 * math.pi) * n_secteurs).astype(int)
    return len(np.unique(sect)) / float(n_secteurs)


# ---------------------------------------------------------------------
# 6. AJUSTEMENT D'ELLIPSE LIBRE (étalonnage de la forme)
# ---------------------------------------------------------------------
def ajuster_ellipse_libre(pts: np.ndarray, iterations: int = 4):
    """Ellipse entièrement libre (centre, axes, angle) par moindres carrés
    directs d'OpenCV, rendue robuste par rejets successifs des points
    aberrants. Utilisé seulement sur des images où le limbe est bien
    couvert, pour mesurer le rayon et l'aplatissement de la série.
    Renvoie (cx, cy, Forme, rms) ou None."""
    garde = np.ones(len(pts), bool)
    resultat = None
    for _ in range(iterations):
        if garde.sum() < 12:
            return resultat
        (cx, cy), (w, h), ang = cv2.fitEllipseDirect(pts[garde].astype(np.float32))
        if w <= 0 or h <= 0:
            return resultat
        if w >= h:
            A, B, th = w / 2, h / 2, math.radians(ang)
        else:
            A, B, th = h / 2, w / 2, math.radians(ang + 90)
        th = (th + math.pi / 2) % math.pi - math.pi / 2   # angle ramené dans [-90°, 90°[
        f = Forme(A, B / A, th)
        r = _residus(np.array([cx, cy]), pts, ("cx", "cy"), {"A": A, "k": f.k, "theta": th})
        mad = float(np.median(np.abs(r[garde]))) * 1.4826 + 0.3
        rms = float(np.sqrt(np.mean(r[garde] ** 2)))
        resultat = (cx, cy, f, rms)
        garde = np.abs(r) < max(1.5, 3 * mad)
    return resultat


# ---------------------------------------------------------------------
# 7. DÉTECTION COMPLÈTE D'UNE IMAGE
# ---------------------------------------------------------------------
def detecter_disque(img: np.ndarray, forme: Forme | None = None, k_libre: bool = True,
                    etalonnage: bool = False, mode_lune: bool = True,
                    n_rayons: int = 360, rayon_approx: float | None = None) -> ResultatDetection:
    """Pipeline complet sur une image en niveaux de gris (pleine résolution).

    forme      : forme du disque connue pour la série (A, k, θ).
                 None → le rayon est recherché (balayage de Hough).
    k_libre    : ajuste l'aplatissement k image par image (θ reste fixe),
                 uniquement si le limbe visible le permet.
    etalonnage : ajuste une ellipse entièrement libre (rayon, k, θ) —
                 sert à mesurer la forme sur des images bien couvertes.
    """
    res = ResultatDetection()
    norm = normaliser(img)
    rayon = forme.A if forme is not None else None
    gros = recherche_grossiere(norm, rayon, rayon_approx=rayon_approx)
    if gros is None:
        res.message = "aucun contour exploitable"
        return res
    cx, cy, r_est, _ = gros
    if rayon is None:
        rayon = r_est
    f = Forme(forme.A, forme.k, forme.theta) if forme is not None else Forme(rayon, 1.0, 0.0)

    # Image légèrement lissée pour des profils propres (bruit, turbulence)
    lisse = cv2.GaussianBlur(norm, (0, 0), 1.0)

    # Affinage itératif : fenêtres de recherche de plus en plus serrées
    fenetres = [0.16 * rayon, 0.06 * rayon + 6, 0.025 * rayon + 4, 0.025 * rayon + 4]
    pts = None
    for it, demi in enumerate(fenetres):
        phi, rho, prof = profils_radiaux(lisse, cx, cy, f, demi, n_rayons)
        rb, clair, sombre, pente, valide = detecter_bords(phi, rho, prof, +1)
        if valide.sum() < 8:
            pts = None
            break
        ref = float(np.percentile(clair[valide], 90))
        contraste = clair - sombre
        # Rayon retenu = vrai limbe : photosphère dedans, ciel noir dehors
        bon = valide & (clair > 0.35 * ref) & (contraste > 0.25 * ref) & (sombre < 0.6 * ref)
        if bon.sum() < 8:
            pts = None
            break
        pts = np.stack([cx + rb[bon] * np.cos(phi[bon]), cy + rb[bon] * np.sin(phi[bon])], axis=1)
        cov = couverture_angulaire(phi[bon])
        echelle = max(1.5, 0.004 * rayon)
        if etalonnage and it >= 1 and cov > 0.35:
            lib = ajuster_ellipse_libre(pts)
            if lib is not None:
                cx, cy, f, _ = lib
            libres = ("cx", "cy")
        else:
            libres = ("cx", "cy", "k") if (k_libre and it >= 1 and cov > 0.3) else ("cx", "cy")
        vals, sig, rms, w = ajuster_ellipse(pts, cx, cy, f, libres, echelle=echelle)
        cx, cy = vals["cx"], vals["cy"]
        f = Forme(vals["A"], vals["k"], vals["theta"])
        res.sigma_centre = float(math.hypot(sig.get("cx", np.inf), sig.get("cy", np.inf)))
        res.sigma_k = float(sig.get("k", np.inf))
        res.residu = rms
        res.couverture = cov
        res.nettete = float(np.median(pente[bon]) / max(ref, 1e-6))
        pas_r = float(rho[0, 1] - rho[0, 0])
        res.largeur_bord = float(np.median((clair[bon] - sombre[bon]) / np.maximum(pente[bon], 1e-6)) * pas_r)
        res.fond_relatif = float(np.median(sombre[bon] / np.maximum(clair[bon], 1e-6)))
        res.points = pts[w > 0.3].astype(np.float32)

    if pts is not None and res.couverture >= 0.06 and res.residu < 0.02 * rayon + 3 \
            and res.sigma_centre < 0.05 * rayon:
        res.ok, res.mode = True, "soleil"
        res.cx, res.cy, res.forme = cx, cy, f
        return res

    # ---- Mode LUNE (totalité) : disque sombre cerclé de lumière ----
    if mode_lune:
        rl = recherche_grossiere(norm, rayon, signe=-1)
        if rl is not None:
            lx, ly, _, _ = rl
            fl = Forme(rayon * 1.02, 1.0, 0.0)
            for demi in (0.12 * rayon, 0.04 * rayon + 5, 0.03 * rayon + 4):
                phi, rho, prof = profils_radiaux(lisse, lx, ly, fl, demi, n_rayons)
                rb, clair, sombre, pente, valide = detecter_bords(phi, rho, prof, -1)
                if valide.sum() < 8:
                    break
                ref = float(np.percentile(clair[valide], 90))
                bon = valide & ((clair - sombre) > 0.3 * ref)
                if bon.sum() < 20:
                    break
                ptsl = np.stack([lx + rb[bon] * np.cos(phi[bon]), ly + rb[bon] * np.sin(phi[bon])], axis=1)
                vals, sig, rms, w = ajuster_ellipse(ptsl, lx, ly, fl, ("cx", "cy", "A"), echelle=2.0)
                lx, ly = vals["cx"], vals["cy"]
                fl = Forme(vals["A"], 1.0, 0.0)
                cov = couverture_angulaire(phi[bon])
                if cov > 0.5 and rms < 0.02 * rayon + 3 and 0.85 < fl.A / rayon < 1.15:
                    res.ok, res.mode = True, "lune"
                    res.cx, res.cy = lx, ly
                    res.forme = Forme(f.A, f.k, f.theta)
                    res.couverture, res.residu = cov, rms
                    res.sigma_centre = float(math.hypot(sig["cx"], sig["cy"]))
                    res.points = ptsl[w > 0.3].astype(np.float32)
                    res.message = f"centre de la Lune (rayon lunaire {fl.A:.1f}px)"
    if not res.ok:
        res.message = res.message or "limbe insuffisant (nuage épais ?)"
        res.cx, res.cy = cx, cy   # position approximative conservée
        res.forme = f
    return res
