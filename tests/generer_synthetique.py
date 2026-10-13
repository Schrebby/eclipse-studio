# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jérémy BEAUFRERE — JEREMiA (https://jerem-ia.fr)
# Éclipse Studio est un logiciel libre : vous pouvez le redistribuer et/ou le
# modifier selon les termes de la GNU GPL v3 ou ultérieure (voir LICENSE).
"""
Générateur d'une éclipse SYNTHÉTIQUE avec vérité terrain, pour valider
Éclipse Studio : dérive + recentrage brutal, Soleil coupé par le bord,
aplatissement croissant (réfraction), coucher de soleil (exposition,
couleur, gradient d'extinction), nuages fins, un nuage épais, Lune qui
traverse le disque de part en part.
Usage : python tests/generer_synthetique.py DOSSIER [nb_images]
"""
import json, math, os, sys
import cv2
import numpy as np

def main(dossier, N=60):
    os.makedirs(dossier, exist_ok=True)
    rng = np.random.default_rng(42)
    H, W, A, theta, rho_m = 1400, 2000, 280.0, 0.4, 1.035
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    # Taches solaires (coordonnées ciel, unités de rayon)
    taches = [(0.3, -0.2, 0.025), (-0.45, 0.35, 0.018), (0.1, 0.55, 0.012)]
    verite = []
    t0 = 1786559736  # epoch arbitraire
    for i in range(N):
        u = i / (N - 1)
        # Trajectoire du centre : dérive + recentrage à mi-parcours + passages près du bord
        cx = 700 + 500 * u + (0 if u < 0.5 else -450) + 40 * math.sin(7 * u)
        cy = 600 + 300 * u + (0 if u < 0.5 else -200)
        if 0.40 < u < 0.48:
            cx += 700 + 250 * (u - 0.40) / 0.08   # Soleil sorti du champ à droite (coupé)
        if u > 0.85:
            cy += 650 * (u - 0.85) / 0.15          # coupé en bas en fin de série
        k = 1 - 0.08 * u ** 3
        mxs, mys = -1.25 + 2.5 * u, 0.55 - 0.9 * u    # Lune (rayons solaires, ciel)
        # Image → ciel (désaplatissement)
        c, s = math.cos(theta), math.sin(theta)
        dx, dy = xx - cx, yy - cy
        a1 = dx * c + dy * s
        a2 = (-dx * s + dy * c) / k
        qx, qy = (a1 * c - a2 * s) / A, (a1 * s + a2 * c) / A
        r = np.sqrt(qx * qx + qy * qy)
        mu = np.sqrt(np.clip(1 - r * r, 0, 1))
        soleil = (1 - 0.6 * (1 - mu)) * np.clip((1 - r) * A / 1.2 + 0.5, 0, 1)
        for (tx, ty, tr) in taches:
            soleil *= 1 - 0.7 * np.exp(-((qx - tx) ** 2 + (qy - ty) ** 2) / (2 * tr * tr))
        dl = np.sqrt((qx - mxs) ** 2 + (qy - mys) ** 2)
        soleil *= np.clip((dl - rho_m) * A / 1.2 + 0.5, 0, 1)
        # Coucher de soleil : exposition, couleur, gradient d'extinction
        gain = 0.85 - 0.35 * u + 0.1 * math.sin(11 * u)
        coul = np.array([1.0, 0.95 - 0.35 * u, 0.85 - 0.55 * u])
        grad = 1 + 0.35 * u * (yy - cy) / A * 0.5
        img = soleil[:, :, None] * coul[None, None, :] * (gain * grad)[:, :, None]
        # Nuages
        if 18 <= i <= 23:
            champ = cv2.GaussianBlur(rng.random((H // 20, W // 20)).astype(np.float32), (0, 0), 2)
            champ = cv2.resize(champ, (W, H))
            att = 0.45 + 0.55 * (champ - champ.min()) / (np.ptp(champ) + 1e-6)
            img = img * att[:, :, None] + 0.04 * cv2.GaussianBlur(img, (0, 0), 25)
        if i == 34:
            img = 0.06 * cv2.GaussianBlur(img, (0, 0), 30) + 0.02
        img = img + 0.008 + rng.normal(0, 0.004, img.shape)
        img = np.clip(img, 0, 1)
        u16 = (img * 65535).astype(np.uint16)
        nom = os.path.join(dossier, f"synth_{i + 1:04d}.png")
        cv2.imwrite(nom, cv2.cvtColor(u16, cv2.COLOR_RGB2BGR))
        os.utime(nom, (t0 + 20 * i, t0 + 20 * i))
        verite.append({"nom": os.path.basename(nom), "cx": cx, "cy": cy, "k": k, "lune": [mxs, mys]})
    json.dump({"A": A, "theta": theta, "rho_m": rho_m, "images": verite}, open(os.path.join(dossier, "verite.json"), "w"), indent=1)

if __name__ == "__main__":
    main(sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else 60)
