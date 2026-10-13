# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jérémy BEAUFRERE — JEREMiA (https://jerem-ia.fr)
# Éclipse Studio est un logiciel libre : vous pouvez le redistribuer et/ou le
# modifier selon les termes de la GNU GPL v3 ou ultérieure (voir LICENSE).
"""
=====================================================================
 Éclipse Studio — Module ASTRONOMIE (éphémérides Soleil / Lune)
=====================================================================
 Calculs autonomes (aucune dépendance) d'après J. Meeus,
 « Astronomical Algorithms » :
   - position apparente du Soleil (ch. 25) ;
   - position de la Lune, série principale ELP (ch. 47) ;
   - passage en TOPOCENTRIQUE (lieu d'observation) par calcul vectoriel :
     indispensable, la parallaxe lunaire (~1°) fait toute l'éclipse ;
   - hauteur du Soleil, angle parallactique (dérotation de champ) ;
   - décalage Lune−Soleil sur le ciel (ξ vers l'Est, η vers le Nord)
     exprimé en RAYONS SOLAIRES, + rayon lunaire relatif.
 Précision visée : quelques secondes d'arc sur les positions RELATIVES,
 largement suffisante pour reconstituer début et fin d'éclipse.
=====================================================================
"""

from __future__ import annotations

import datetime as dt
import math

DEG = math.pi / 180.0
UA_KM = 149597870.7
R_TERRE = 6378.137
APLAT_TERRE = 1 / 298.257223563
R_LUNE_KM = 1737.4
DELTA_T_S = 69.5            # TT − UT (≈ 2025-2030)

# ---------------------------------------------------------------------
# Termes périodiques de la Lune (Meeus, tables 47.A et 47.B)
#   (D, M, M', F, Σl [1e-6 °], Σr [1e-3 km])
# ---------------------------------------------------------------------
_LR = [
    (0, 0, 1, 0, 6288774, -20905355), (2, 0, -1, 0, 1274027, -3699111),
    (2, 0, 0, 0, 658314, -2955968), (0, 0, 2, 0, 213618, -569925),
    (0, 1, 0, 0, -185116, 48888), (0, 0, 0, 2, -114332, -3149),
    (2, 0, -2, 0, 58793, 246158), (2, -1, -1, 0, 57066, -152138),
    (2, 0, 1, 0, 53322, -170733), (2, -1, 0, 0, 45758, -204586),
    (0, 1, -1, 0, -40923, -129620), (1, 0, 0, 0, -34720, 108743),
    (0, 1, 1, 0, -30383, 104755), (2, 0, 0, -2, 15327, 10321),
    (0, 0, 1, 2, -12528, 0), (0, 0, 1, -2, 10980, 79661),
    (4, 0, -1, 0, 10675, -34782), (0, 0, 3, 0, 10034, -23210),
    (4, 0, -2, 0, 8548, -21636), (2, 1, -1, 0, -7888, 24208),
    (2, 1, 0, 0, -6766, 30824), (1, 0, -1, 0, -5163, -8379),
    (1, 1, 0, 0, 4987, -16675), (2, -1, 1, 0, 4036, -12831),
    (2, 0, 2, 0, 3994, -10445), (4, 0, 0, 0, 3861, -11650),
    (2, 0, -3, 0, 3665, 14403), (0, 1, -2, 0, -2689, -7003),
    (2, 0, -1, 2, -2602, 0), (2, -1, -2, 0, 2390, 10056),
    (1, 0, 1, 0, -2348, 6322), (2, -2, 0, 0, 2236, -9884),
    (0, 1, 2, 0, -2120, 5751), (0, 2, 0, 0, -2069, 0),
    (2, -2, -1, 0, 2048, -4950), (2, 0, 1, -2, -1773, 4130),
    (2, 0, 0, 2, -1595, 0), (4, -1, -1, 0, 1215, -3958),
    (0, 0, 2, 2, -1110, 0), (3, 0, -1, 0, -892, 3258),
    (2, 1, 1, 0, -810, 2616), (4, -1, -2, 0, 759, -1897),
    (0, 2, -1, 0, -713, -2117), (2, 2, -1, 0, -700, 2354),
    (2, 1, -2, 0, 691, 0), (2, -1, 0, -2, 596, 0),
    (4, 0, 1, 0, 549, -1423), (0, 0, 4, 0, 537, -1117),
    (4, -1, 0, 0, 520, -1571), (1, 0, -2, 0, -487, -1739),
    (2, 1, 0, -2, -399, 0), (0, 0, 2, -2, -381, -4421),
    (1, 1, 1, 0, 351, 0), (3, 0, -2, 0, -340, 0),
    (4, 0, -3, 0, 330, 0), (2, -1, 2, 0, 327, 0),
    (0, 2, 1, 0, -323, 1165), (1, 1, -1, 0, 299, 0),
    (2, 0, 3, 0, 294, 0), (2, 0, -1, -2, 0, 8752),
]
_B = [
    (0, 0, 0, 1, 5128122), (0, 0, 1, 1, 280602), (0, 0, 1, -1, 277693),
    (2, 0, 0, -1, 173237), (2, 0, -1, 1, 55413), (2, 0, -1, -1, 46271),
    (2, 0, 0, 1, 32573), (0, 0, 2, 1, 17198), (2, 0, 1, -1, 9266),
    (0, 0, 2, -1, 8822), (2, -1, 0, -1, 8216), (2, 0, -2, -1, 4324),
    (2, 0, 1, 1, 4200), (2, 1, 0, -1, -3359), (2, -1, -1, 1, 2463),
    (2, -1, 0, 1, 2211), (2, -1, -1, -1, 2065), (0, 1, -1, -1, -1870),
    (4, 0, -1, -1, 1828), (0, 1, 0, 1, -1794), (0, 0, 0, 3, -1749),
    (0, 1, -1, 1, -1565), (1, 0, 0, 1, -1491), (0, 1, 1, 1, -1475),
    (0, 1, 1, -1, -1410), (0, 1, 0, -1, -1344), (1, 0, 0, -1, -1335),
    (0, 0, 3, 1, 1107), (4, 0, 0, -1, 1021), (4, 0, -1, 1, 833),
]


# ---------------------------------------------------------------------
# 1. TEMPS
# ---------------------------------------------------------------------
def jour_julien(t_utc: dt.datetime) -> float:
    """Jour julien (UT) d'une date naïve exprimée en UTC."""
    a = (14 - t_utc.month) // 12
    y = t_utc.year + 4800 - a
    m = t_utc.month + 12 * a - 3
    jdn = t_utc.day + (153 * m + 2) // 5 + 365 * y + y // 4 - y // 100 + y // 400 - 32045
    frac = (t_utc.hour - 12) / 24 + t_utc.minute / 1440 + (t_utc.second + t_utc.microsecond / 1e6) / 86400
    return jdn + frac


def _nutation(T: float):
    """Nutation en longitude Δψ et obliquité vraie ε (degrés), version courte."""
    om = (125.04452 - 1934.136261 * T) * DEG
    Ls = (280.4665 + 36000.7698 * T) * DEG
    Lm = (218.3165 + 481267.8813 * T) * DEG
    dpsi = (-17.20 * math.sin(om) - 1.32 * math.sin(2 * Ls) - 0.23 * math.sin(2 * Lm) + 0.21 * math.sin(2 * om)) / 3600
    deps = (9.20 * math.cos(om) + 0.57 * math.cos(2 * Ls) + 0.10 * math.cos(2 * Lm) - 0.09 * math.cos(2 * om)) / 3600
    eps0 = 23.439291111 - 0.0130041667 * T - 1.6389e-7 * T * T + 5.0361e-7 * T ** 3
    return dpsi, eps0 + deps


def _ecl_vers_eq(lam: float, bet: float, eps: float):
    """Écliptique (rad) → équatorial (rad)."""
    a = math.atan2(math.sin(lam) * math.cos(eps) - math.tan(bet) * math.sin(eps), math.cos(lam))
    d = math.asin(math.sin(bet) * math.cos(eps) + math.cos(bet) * math.sin(eps) * math.sin(lam))
    return a % (2 * math.pi), d


# ---------------------------------------------------------------------
# 2. SOLEIL ET LUNE GÉOCENTRIQUES
# ---------------------------------------------------------------------
def soleil_geocentrique(jd_ut: float):
    """Renvoie (α, δ en rad, distance km) apparents du Soleil."""
    T = (jd_ut + DELTA_T_S / 86400 - 2451545.0) / 36525
    L0 = 280.46646 + 36000.76983 * T + 0.0003032 * T * T
    M = (357.52911 + 35999.05029 * T - 0.0001537 * T * T) * DEG
    e = 0.016708634 - 0.000042037 * T - 0.0000001267 * T * T
    C = (1.914602 - 0.004817 * T - 0.000014 * T * T) * math.sin(M) \
        + (0.019993 - 0.000101 * T) * math.sin(2 * M) + 0.000289 * math.sin(3 * M)
    lon = L0 + C
    nu = M + C * DEG
    R = 1.000001018 * (1 - e * e) / (1 + e * math.cos(nu))
    dpsi, eps = _nutation(T)
    lam = (lon - 0.00569 + dpsi) * DEG            # aberration + nutation
    a, d = _ecl_vers_eq(lam, 0.0, eps * DEG)
    return a, d, R * UA_KM


def lune_geocentrique(jd_ut: float):
    """Renvoie (α, δ en rad, distance km) apparents de la Lune (série ELP abrégée)."""
    T = (jd_ut + DELTA_T_S / 86400 - 2451545.0) / 36525
    Lp = 218.3164477 + 481267.88123421 * T - 0.0015786 * T * T + T ** 3 / 538841 - T ** 4 / 65194000
    D = 297.8501921 + 445267.1114034 * T - 0.0018819 * T * T + T ** 3 / 545868 - T ** 4 / 113065000
    M = 357.5291092 + 35999.0502909 * T - 0.0001536 * T * T + T ** 3 / 24490000
    Mp = 134.9633964 + 477198.8675055 * T + 0.0087414 * T * T + T ** 3 / 69699 - T ** 4 / 14712000
    F = 93.2720950 + 483202.0175233 * T - 0.0036539 * T * T - T ** 3 / 3526000 + T ** 4 / 863310000
    A1 = (119.75 + 131.849 * T) * DEG
    A2 = (53.09 + 479264.290 * T) * DEG
    A3 = (313.45 + 481266.484 * T) * DEG
    E = 1 - 0.002516 * T - 0.0000074 * T * T
    d, m, mp, f, lp = D * DEG, M * DEG, Mp * DEG, F * DEG, Lp * DEG
    sl = sr = sb = 0.0
    for (cd, cm, cmp_, cf, l, r) in _LR:
        arg = cd * d + cm * m + cmp_ * mp + cf * f
        ef = E ** abs(cm)
        sl += l * ef * math.sin(arg)
        sr += r * ef * math.cos(arg)
    for (cd, cm, cmp_, cf, b) in _B:
        arg = cd * d + cm * m + cmp_ * mp + cf * f
        sb += b * (E ** abs(cm)) * math.sin(arg)
    sl += 3958 * math.sin(A1) + 1962 * math.sin(lp - f) + 318 * math.sin(A2)
    sb += -2235 * math.sin(lp) + 382 * math.sin(A3) + 175 * math.sin(A1 - f) + 175 * math.sin(A1 + f) \
        + 127 * math.sin(lp - mp) - 115 * math.sin(lp + mp)
    dpsi, eps = _nutation(T)
    lam = (Lp + sl / 1e6 + dpsi) * DEG
    bet = (sb / 1e6) * DEG
    dist = 385000.56 + sr / 1000
    a, dd = _ecl_vers_eq(lam, bet, eps * DEG)
    return a, dd, dist


# ---------------------------------------------------------------------
# 3. TOPOCENTRIQUE
# ---------------------------------------------------------------------
def temps_sideral(jd_ut: float, lon_est_deg: float) -> float:
    """Temps sidéral local (rad)."""
    T = (jd_ut - 2451545.0) / 36525
    g = 280.46061837 + 360.98564736629 * (jd_ut - 2451545.0) + 0.000387933 * T * T - T ** 3 / 38710000
    return ((g + lon_est_deg) % 360) * DEG


def _vecteur(a, d, r):
    return (r * math.cos(d) * math.cos(a), r * math.cos(d) * math.sin(a), r * math.sin(d))


def _observateur(lat_deg, lst, alt_m=0.0):
    phi = lat_deg * DEG
    b = 1 - APLAT_TERRE
    C = 1 / math.sqrt(math.cos(phi) ** 2 + (b * math.sin(phi)) ** 2)
    S = b * b * C
    h = alt_m / 1000
    return ((R_TERRE * C + h) * math.cos(phi) * math.cos(lst),
            (R_TERRE * C + h) * math.cos(phi) * math.sin(lst),
            (R_TERRE * S + h) * math.sin(phi))


def topocentrique(a, d, r, lat, lst, alt_m=0.0):
    """Corrige (α, δ, distance) de la parallaxe pour un lieu donné."""
    x, y, z = _vecteur(a, d, r)
    ox, oy, oz = _observateur(lat, lst, alt_m)
    x, y, z = x - ox, y - oy, z - oz
    rr = math.sqrt(x * x + y * y + z * z)
    return math.atan2(y, x) % (2 * math.pi), math.asin(z / rr), rr


def hauteur_et_parallactique(a, d, lat, lst):
    """Hauteur (°) et angle parallactique q (°) d'un astre."""
    H = lst - a
    phi = lat * DEG
    sin_h = math.sin(phi) * math.sin(d) + math.cos(phi) * math.cos(d) * math.cos(H)
    q = math.atan2(math.sin(H), math.tan(phi) * math.cos(d) - math.sin(d) * math.cos(H))
    return math.degrees(math.asin(max(-1, min(1, sin_h)))), math.degrees(q)


# ---------------------------------------------------------------------
# 4. GÉOMÉTRIE DE L'ÉCLIPSE POUR UN INSTANT
# ---------------------------------------------------------------------
def geometrie(t_utc: dt.datetime, lat: float, lon_est: float, alt_m: float = 0.0) -> dict:
    """Décalage Lune−Soleil vu du lieu :
       xi  : vers l'Est céleste, eta : vers le Nord céleste (rayons solaires)
       k   : rayon lunaire / rayon solaire
       hauteur_soleil (°), parallactique (°)."""
    jd = jour_julien(t_utc)
    lst = temps_sideral(jd, lon_est)
    sa, sd, sr = topocentrique(*soleil_geocentrique(jd), lat, lst, alt_m)
    ma, md, mr = topocentrique(*lune_geocentrique(jd), lat, lst, alt_m)
    rs = math.asin(696000.0 / sr)              # demi-diamètre solaire (rad)
    rm = math.asin(R_LUNE_KM / mr)             # demi-diamètre lunaire topocentrique (rad)
    da = ma - sa
    xi = math.cos(md) * math.sin(da)
    eta = math.sin(md) * math.cos(sd) - math.cos(md) * math.sin(sd) * math.cos(da)
    h, q = hauteur_et_parallactique(sa, sd, lat, lst)
    return {"xi": xi / rs, "eta": eta / rs, "k": rm / rs, "hauteur_soleil": h, "parallactique": q,
            "rayon_soleil_arcsec": math.degrees(rs) * 3600}


def contacts(t0: dt.datetime, t1: dt.datetime, lat: float, lon_est: float, pas_s: float = 20.0) -> dict:
    """Recherche les contacts C1..C4 et le maximum entre t0 et t1 (UTC)."""
    res: dict = {}
    t = t0
    prec = None
    dmin = (1e9, None)
    while t <= t1:
        g = geometrie(t, lat, lon_est)
        dist = math.hypot(g["xi"], g["eta"])
        if dist < dmin[0]:
            dmin = (dist, t, g)
        if prec is not None:
            for nom, seuil in (("C1/C4", 1 + g["k"]), ("C2/C3", abs(1 - g["k"]))):
                if (prec[0] - seuil) * (dist - seuil) < 0:
                    frac = (prec[0] - seuil) / (prec[0] - dist)
                    tc = prec[1] + (t - prec[1]) * frac
                    entree = dist < prec[0]
                    cle = {"C1/C4": ("C1", "C4"), "C2/C3": ("C2", "C3")}[nom][0 if entree else 1]
                    res[cle] = tc
        prec = (dist, t)
        t += dt.timedelta(seconds=pas_s)
    if dmin[1] is not None:
        g = dmin[2]
        res["max"] = dmin[1]
        res["magnitude"] = (1 + g["k"] - dmin[0]) / 2
    return res


# ---------------------------------------------------------------------
# 5. ÉCLIPSES DE LUNE : OMBRE ET PÉNOMBRE DE LA TERRE
# ---------------------------------------------------------------------
DANJON = 1.0 + 1.0 / 85.0      # agrandissement de l'ombre par l'atmosphère terrestre


def geometrie_lunaire(t_utc: dt.datetime, lat: float | None = None, lon_est: float | None = None) -> dict:
    """Position du CENTRE DE L'OMBRE par rapport au centre de la Lune
    (ξ vers l'Est, η vers le Nord), en RAYONS LUNAIRES géocentriques, et
    rayons de l'ombre (rho_u) et de la pénombre (rho_p) dans la même unité.
    L'ombre est posée SUR la Lune : la géométrie ombre/Lune est géocentrique
    (le lieu ne fait que décaler l'ensemble, il ne change pas la figure).
    Si lat/lon sont donnés : hauteur de la Lune et angle parallactique."""
    jd = jour_julien(t_utc)
    sa, sd, sr = soleil_geocentrique(jd)
    ma, md, mr = lune_geocentrique(jd)
    aa, ad = (sa + math.pi) % (2 * math.pi), -sd          # point antisolaire
    s_m = math.asin(R_LUNE_KM / mr)                         # demi-diamètre lunaire (rad)
    pi_m = math.asin(R_TERRE / mr)                          # parallaxe horizontale de la Lune
    pi_s = math.asin(R_TERRE / sr)
    s_s = math.asin(696000.0 / sr)
    rho_u = DANJON * 0.998340 * pi_m - s_s + pi_s
    rho_p = DANJON * 0.998340 * pi_m + s_s + pi_s
    da = aa - ma
    xi = math.cos(ad) * math.sin(da)
    eta = math.sin(ad) * math.cos(md) - math.cos(ad) * math.sin(md) * math.cos(da)
    res = {"xi": xi / s_m, "eta": eta / s_m, "rho_u": rho_u / s_m, "rho_p": rho_p / s_m,
           "rayon_lune_arcsec": math.degrees(s_m) * 3600}
    if lat is not None and lon_est is not None:
        lst = temps_sideral(jd, lon_est)
        ta, td, _ = topocentrique(ma, md, mr, lat, lst)
        h, q = hauteur_et_parallactique(ta, td, lat, lst)
        res.update({"hauteur_lune": h, "parallactique": q})
    return res


def _recherche_seuils(fonction, t0: dt.datetime, t1: dt.datetime, pas_s: float, seuils: dict):
    """Instants où la distance renvoyée par fonction(t) franchit chaque seuil
    (entrée et sortie), + minimum. seuils : {(nom_entree, nom_sortie): valeur}."""
    res: dict = {}
    t, prec, dmin = t0, None, (1e9, None)
    while t <= t1:
        d, extra = fonction(t)
        if d < dmin[0]:
            dmin = (d, t)
        if prec is not None:
            for (ne, ns), s in seuils.items():
                if (prec[0] - s) * (d - s) < 0:
                    frac = (prec[0] - s) / (prec[0] - d)
                    tc = prec[1] + (t - prec[1]) * frac
                    res[ne if d < prec[0] else ns] = tc
        prec = (d, t)
        t += dt.timedelta(seconds=pas_s)
    return res, dmin


def contacts_lunaires(t0: dt.datetime, t1: dt.datetime, pas_s: float = 20.0) -> dict:
    """Contacts P1, U1, U2, maximum, U3, U4, P4 (UTC) et magnitudes."""
    g = geometrie_lunaire(t0 + (t1 - t0) / 2)
    ru, rp = g["rho_u"], g["rho_p"]
    seuils = {("P1", "P4"): rp + 1, ("U1", "U4"): ru + 1, ("U2", "U3"): ru - 1}
    res, (dmin, tmax) = _recherche_seuils(
        lambda t: (math.hypot(*(lambda q: (q["xi"], q["eta"]))(geometrie_lunaire(t))), None), t0, t1, pas_s, seuils)
    if tmax is not None:
        res["max"] = tmax
        res["magnitude_ombre"] = (ru + 1 - dmin) / 2
        res["magnitude_penombre"] = (rp + 1 - dmin) / 2
        res["type"] = ("totale" if dmin < ru - 1 else "partielle" if dmin < ru + 1
                       else "pénombrale" if dmin < rp + 1 else "aucune")
    return res


# ---------------------------------------------------------------------
# 6. CIRCONSTANCES LOCALES ET RECHERCHE DE L'ÉCLIPSE LA PLUS PROCHE
# ---------------------------------------------------------------------
def hauteurs(t_utc: dt.datetime, lat: float, lon_est: float) -> tuple[float, float]:
    """Hauteurs topocentriques (°) du Soleil et de la Lune."""
    jd = jour_julien(t_utc)
    lst = temps_sideral(jd, lon_est)
    sa, sd, _ = topocentrique(*soleil_geocentrique(jd), lat, lst)
    ma, md, _ = topocentrique(*lune_geocentrique(jd), lat, lst)
    return hauteur_et_parallactique(sa, sd, lat, lst)[0], hauteur_et_parallactique(ma, md, lat, lst)[0]


def _syzygies(t_centre: dt.datetime, jours: float = 20.0):
    """Nouvelles et pleines lunes (instants approchés, UTC) autour d'une date."""
    out = []
    t = t_centre - dt.timedelta(days=jours)
    fin = t_centre + dt.timedelta(days=jours)
    prec = None
    pas = dt.timedelta(hours=3)
    while t <= fin:
        jd = jour_julien(t)
        sa, sd, _ = soleil_geocentrique(jd)
        ma, md, _ = lune_geocentrique(jd)
        # élongation écliptique approchée : différence d'ascension droite ramenée
        dl = (ma - sa + math.pi) % (2 * math.pi) - math.pi
        if prec is not None:
            if prec[0] < 0 <= dl:
                out.append(("solaire", prec[1] + pas * (-prec[0] / (dl - prec[0]))))
            if prec[0] > 0 and dl < 0 and prec[0] - dl > math.pi:   # passage par ±180°
                out.append(("lunaire", prec[1] + pas * ((math.pi - prec[0]) / (dl + 2 * math.pi - prec[0]))))
        prec = (dl, t)
        t += pas
    return out


def eclipse_proche(t_utc: dt.datetime, lat: float | None = None, lon_est: float | None = None,
                   jours: float = 20.0) -> dict | None:
    """Cherche l'éclipse (solaire visible du lieu, ou lunaire) la plus proche
    de la date donnée. Renvoie type, contacts (UTC) et visibilité."""
    candidats = []
    for genre, ts in _syzygies(t_utc, jours):
        a, b = ts - dt.timedelta(hours=6), ts + dt.timedelta(hours=6)
        if genre == "lunaire":
            c = contacts_lunaires(a, b, 60.0)
            if c.get("type", "aucune") != "aucune":
                c = contacts_lunaires(c.get("P1", a) - dt.timedelta(minutes=5),
                                      c.get("P4", b) + dt.timedelta(minutes=5), 10.0)
                candidats.append(("lunaire", c))
        elif lat is not None and lon_est is not None:
            c = contacts(a, b, lat, lon_est, 60.0)
            if c.get("magnitude", 0) > 0 and ("C1" in c or "C4" in c):
                c = contacts(c.get("C1", a) - dt.timedelta(minutes=5), c.get("C4", b) + dt.timedelta(minutes=5),
                             lat, lon_est, 5.0)
                candidats.append(("solaire", c))
    if not candidats:
        return None
    genre, c = min(candidats, key=lambda gc: abs((gc[1]["max"] - t_utc).total_seconds()))
    res = {"type": genre, "contacts": {k: v for k, v in c.items() if isinstance(v, dt.datetime)},
           "infos": {k: v for k, v in c.items() if not isinstance(v, dt.datetime)}}
    if lat is not None and lon_est is not None:
        vis = {}
        for k, t in res["contacts"].items():
            hs, hl = hauteurs(t, lat, lon_est)
            vis[k] = {"hauteur": hs if genre == "solaire" else hl, "hauteur_soleil": hs}
        res["visibilite"] = vis
    return res
