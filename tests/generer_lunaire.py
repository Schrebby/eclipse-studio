# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jérémy BEAUFRERE — JEREMiA (https://jerem-ia.fr)
# Éclipse Studio est un logiciel libre : vous pouvez le redistribuer et/ou le
# modifier selon les termes de la GNU GPL v3 ou ultérieure (voir LICENSE).
"""
Générateur d'une ÉCLIPSE DE LUNE synthétique (vérité terrain) : géométrie réelle
de l'éclipse totale du 14 mars 2025 (éphémérides), Lune texturée, pénombre et
ombre rouge, expositions automatiques très variables (EXIF), dérive du suivi,
Lune coupée par le bord, horloge de l'appareil décalée de +120 s.
Usage : python tests/generer_lunaire.py DOSSIER [nb_images]
"""
import datetime as dt, json, math, os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import cv2
import numpy as np
from PIL import Image
from PIL.TiffImagePlugin import IFDRational
from eclipse_studio import astro
from eclipse_studio.modele_lunaire import attenuation_theorique

def main(dossier, N=70):
    os.makedirs(dossier, exist_ok=True)
    rng = np.random.default_rng(7)
    H, W, R = 1300, 1900, 300.0
    alpha = math.radians(30)                      # orientation du Nord céleste dans l'image
    # Texture lunaire (albédo) : mers sombres + cratères
    yy, xx = np.mgrid[-1:1:601j, -1:1:601j]
    alb = np.ones((601, 601), np.float32)
    for _ in range(9):
        cx, cy, r = rng.uniform(-0.7, 0.7), rng.uniform(-0.7, 0.7), rng.uniform(0.1, 0.35)
        alb -= 0.35 * np.exp(-((xx - cx) ** 2 + (yy - cy) ** 2) / (2 * r * r))
    for _ in range(60):
        cx, cy, r = rng.uniform(-0.9, 0.9), rng.uniform(-0.9, 0.9), rng.uniform(0.01, 0.04)
        alb += 0.25 * np.exp(-((xx - cx) ** 2 + (yy - cy) ** 2) / (2 * r * r))
    alb = np.clip(alb, 0.3, 1.4)
    t_debut = dt.datetime(2025, 3, 14, 4, 50)     # entre P1 et U1 (UTC)
    t_fin = dt.datetime(2025, 3, 14, 9, 10)       # entre U4 et P4
    verite = []
    gy, gx = np.mgrid[0:H, 0:W].astype(np.float32)
    for i in range(N):
        u = i / (N - 1)
        t = t_debut + (t_fin - t_debut) * u
        g = astro.geometrie_lunaire(t)
        xi, eta = g["xi"], g["eta"]
        ox = math.cos(alpha) * xi - math.sin(alpha) * (-eta)     # image : x droite, y bas (Nord en haut)
        oy = math.sin(alpha) * xi + math.cos(alpha) * (-eta)
        cx = 900 + 380 * math.sin(3 * u) + 120 * u
        cy = 640 + 200 * math.cos(2 * u)
        if 0.30 < u < 0.36:
            cx += 520                                            # Lune coupée à droite
        X, Y = (gx - cx) / R, (gy - cy) / R
        r = np.sqrt(X * X + Y * Y)
        d = np.hypot(X - ox, Y - oy)
        att = attenuation_theorique(d.ravel(), g["rho_u"], g["rho_p"]).reshape(H, W, 3)
        tex = cv2.remap(alb, ((X + 1) * 300).astype(np.float32), ((Y + 1) * 300).astype(np.float32),
                        cv2.INTER_LINEAR, borderValue=1.0)
        disque = np.clip((1 - r) * R / 1.2 + 0.5, 0, 1)
        radiance = (disque * tex)[:, :, None] * att * np.array([1.0, 0.97, 0.9])[None, None, :]
        # Exposition automatique : médiane du disque → 45 % du blanc
        med = float(np.median((radiance @ np.array([0.2126, 0.7152, 0.0722]))[r < 0.9]))
        expo = min(8.0, max(1 / 4000, 0.45 / max(med, 1e-6) / 400.0))
        img = radiance * expo * 400.0 + 0.01 + rng.normal(0, 0.003, radiance.shape)
        img8 = (np.clip(img, 0, 1) ** (1 / 1.0) * 255).astype(np.uint8)
        im = Image.fromarray(img8)
        ex = Image.Exif()
        t_cam = t + dt.timedelta(seconds=120)
        ex[0x0132] = t_cam.strftime("%Y:%m:%d %H:%M:%S")
        sub = ex.get_ifd(0x8769)
        sub[0x9003] = t_cam.strftime("%Y:%m:%d %H:%M:%S")
        sub[0x829A] = IFDRational(int(round(expo * 1e6)), 1000000)
        sub[0x8827] = 400
        nom = os.path.join(dossier, f"lune_{i + 1:04d}.jpg")
        im.save(nom, quality=95, exif=ex)
        verite.append({"nom": os.path.basename(nom), "cx": cx, "cy": cy, "ombre": [ox, oy], "expo": expo,
                       "t": t.isoformat()})
    json.dump({"R": R, "alpha": alpha, "images": verite}, open(os.path.join(dossier, "verite.json"), "w"), indent=1)

if __name__ == "__main__":
    main(sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else 70)
