# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jérémy BEAUFRERE — JEREMiA (https://jerem-ia.fr)
# Éclipse Studio est un logiciel libre : vous pouvez le redistribuer et/ou le
# modifier selon les termes de la GNU GPL v3 ou ultérieure (voir LICENSE).
"""
=====================================================================
 Éclipse Studio — Module EXPORTS
=====================================================================
   - Vidéo MP4 H.264 (imageio-ffmpeg, ou ffmpeg du système,
     ou à défaut OpenCV mp4v)
   - GIF animé
   - Séquences d'images : PNG 16 bits, TIFF 16 bits, JPEG
   - Planche des phases (grille) et frise chronologique
   - Rapport CSV des mesures (centre, aplatissement, Lune, photométrie)
=====================================================================
"""

from __future__ import annotations

import csv
import math
import os
import shutil
import subprocess
import datetime as dt

import cv2
import numpy as np
from PIL import Image, ImageDraw

from .rendu import Rendu, police


def _horodater(nom: str) -> str:
    return f"{nom}_{dt.datetime.now().strftime('%Y%m%d_%H%M%S')}"


def _ecrire_image(chemin: str, rgb: np.ndarray, seize: bool):
    ext = os.path.splitext(chemin)[1].lower()
    if seize:
        u = np.clip(rgb * 65535 + 0.5, 0, 65535).astype(np.uint16)
    else:
        u = rgb
    bgr = cv2.cvtColor(u, cv2.COLOR_RGB2BGR)
    params = [cv2.IMWRITE_JPEG_QUALITY, 95] if ext in (".jpg", ".jpeg") else []
    ok, buf = cv2.imencode(ext, bgr, params)
    if not ok:
        raise IOError(f"écriture impossible : {chemin}")
    buf.tofile(chemin)


# ---------------------------------------------------------------------
# 1. ÉCRIVAINS VIDÉO
# ---------------------------------------------------------------------
class EcrivainVideo:
    """Choisit automatiquement le meilleur encodeur disponible."""

    def __init__(self, chemin: str, taille: int, fps: float, qualite: int = 18):
        self.chemin, self.taille, self.fps = chemin, taille, fps
        self.mode = None
        self._gen = None
        self._proc = None
        self._cv = None
        try:
            import imageio_ffmpeg  # type: ignore
            self._gen = imageio_ffmpeg.write_frames(chemin, (taille, taille), fps=fps, codec="libx264",
                                                    pix_fmt_out="yuv420p", quality=None,
                                                    output_params=["-crf", str(qualite), "-preset", "slow",
                                                                   "-movflags", "+faststart"],
                                                    macro_block_size=2)
            self._gen.send(None)
            self.mode = "imageio-ffmpeg (H.264)"
            return
        except Exception:
            self._gen = None
        ff = shutil.which("ffmpeg")
        if ff:
            cmd = [ff, "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{taille}x{taille}",
                   "-r", str(fps), "-i", "-", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", str(qualite),
                   "-preset", "slow", "-movflags", "+faststart", chemin]
            self._proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
            self.mode = "ffmpeg système (H.264)"
            return
        self._cv = cv2.VideoWriter(chemin, cv2.VideoWriter_fourcc(*"mp4v"), fps, (taille, taille))
        self.mode = "OpenCV (MPEG-4)"

    def ecrire(self, rgb8: np.ndarray):
        if self._gen is not None:
            self._gen.send(np.ascontiguousarray(rgb8))
        elif self._proc is not None:
            self._proc.stdin.write(np.ascontiguousarray(rgb8).tobytes())
        else:
            self._cv.write(cv2.cvtColor(rgb8, cv2.COLOR_RGB2BGR))

    def fermer(self):
        if self._gen is not None:
            self._gen.close()
        elif self._proc is not None:
            self._proc.stdin.close()
            self._proc.wait()
        elif self._cv is not None:
            self._cv.release()


# ---------------------------------------------------------------------
# 2. EXPORTS
# ---------------------------------------------------------------------
def exporter(projet, type_export: str, pr: dict, progression, journal, annule, options: dict | None = None) -> str:
    """type_export : video | gif | png16 | tiff16 | jpeg | planche | frise | csv"""
    options = options or {}
    from .analyse import message_inexploitable
    msg = message_inexploitable(projet.donnees.get("forme"))
    if msg and type_export != "csv":
        raise RuntimeError(msg)
    dossier = projet.chemin("exports")
    os.makedirs(dossier, exist_ok=True)
    r = Rendu(projet)

    if type_export == "csv":
        return exporter_csv(projet, os.path.join(dossier, _horodater("mesures") + ".csv"))

    if type_export in ("planche", "frise"):
        return exporter_planche(r, pr, os.path.join(dossier, _horodater(type_export) + ".png"),
                                type_export, int(options.get("nombre", 12)), progression)

    if type_export == "video":
        chemin = os.path.join(dossier, _horodater("eclipse") + ".mp4")
        taille = int(pr.get("taille", 1080)) // 2 * 2
        ecr = EcrivainVideo(chemin, taille, float(pr.get("fps", 25)), int(options.get("crf", 18)))
        journal(f"Encodeur vidéo : {ecr.mode}")
        try:
            for k, n, e, img in r.flux(pr, taille, annule=annule):
                ecr.ecrire(img)
                progression((k + 1) / n, f"Vidéo : image {k + 1}/{n}")
        finally:
            ecr.fermer()
        return chemin

    if type_export == "gif":
        chemin = os.path.join(dossier, _horodater("eclipse") + ".gif")
        taille = min(int(pr.get("taille", 1080)), int(options.get("taille_gif", 600)))
        pas = max(1, int(options.get("pas_gif", 2)))
        images = []
        for k, n, e, img in r.flux(pr, taille, annule=annule):
            if k % pas == 0:
                images.append(Image.fromarray(img).quantize(colors=255, method=Image.Quantize.MEDIANCUT))
            progression((k + 1) / n, f"GIF : image {k + 1}/{n}")
        if images:
            duree = int(1000 * pas / float(pr.get("fps", 25)))
            images[0].save(chemin, save_all=True, append_images=images[1:], duration=duree, loop=0, optimize=False)
        return chemin

    if type_export in ("png16", "tiff16", "jpeg"):
        # options["dossier"] permet de compléter une séquence existante (export par tranches)
        sous = options.get("dossier") or os.path.join(dossier, _horodater("sequence_" + type_export))
        os.makedirs(sous, exist_ok=True)
        ext = {"png16": ".png", "tiff16": ".tif", "jpeg": ".jpg"}[type_export]
        seize = type_export != "jpeg"
        for k, n, e, img in r.flux(pr, None, seize_bits=seize, annule=annule,
                                   debut=int(options.get("debut", 0)), fin=options.get("fin")):
            _ecrire_image(os.path.join(sous, f"eclipse_{k + 1:05d}{ext}"), img, seize)
            progression((k + 1) / n, f"Séquence : image {k + 1}/{n}")
        return sous

    raise ValueError(f"Type d'export inconnu : {type_export}")


def exporter_planche(r: Rendu, pr: dict, chemin: str, style: str, nombre: int, progression) -> str:
    """Planche des phases : sélection d'images régulièrement espacées dans le temps."""
    chrono = r.chronologie(pr)
    if not chrono:
        raise RuntimeError("Aucune image disponible.")
    ts = np.array([e["t"] for e in chrono])
    cibles = np.linspace(ts.min(), ts.max(), max(2, nombre))
    choix = [chrono[int(np.argmin(np.abs(ts - c)))] for c in cibles]
    cell = 360
    pr2 = dict(pr)
    pr2.update({"inc_heure": False, "inc_obscuration": False, "inc_titre": "", "inc_credit": "",
                "inc_reconstitue": False})
    vignettes = []
    for k, e in enumerate(choix):
        vignettes.append(r.image(e, pr2, cell))
        progression((k + 1) / len(choix), f"Planche : {k + 1}/{len(choix)}")
    fp = police(18)
    if style == "frise":
        cols, lignes = len(vignettes), 1
    else:
        cols = int(math.ceil(math.sqrt(len(vignettes) * 1.5)))
        lignes = int(math.ceil(len(vignettes) / cols))
    leg = 34
    W, H = cols * cell, lignes * (cell + leg)
    toile = Image.new("RGB", (W, H), (0, 0, 0))
    d = ImageDraw.Draw(toile)
    for k, (e, v) in enumerate(zip(choix, vignettes)):
        x, y = (k % cols) * cell, (k // cols) * (cell + leg)
        toile.paste(Image.fromarray(v), (x, y))
        t = r.heure(e["t"], pr) + (" *" if e["type"] == "synth" else "")
        bb = d.textbbox((0, 0), t, font=fp)
        d.text((x + (cell - (bb[2] - bb[0])) // 2, y + cell + 6), t, font=fp, fill=(190, 190, 190))
    toile.save(chemin)
    return chemin


def exporter_csv(projet, chemin: str) -> str:
    cols = ["nom", "t", "t_source", "statut", "mode", "cx", "cy", "k_lisse", "sigma", "couverture", "residu",
            "nettete", "visible", "obscuration", "obscuration_modele", "derotation"]
    with open(chemin, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(cols + ["lune_x", "lune_y", "lune_modele_x", "lune_modele_y", "gain_R", "gain_V", "gain_B"])
        for im in projet.images:
            l = im.get("lune") or {}
            lm = im.get("lune_modele") or [None, None]
            g = im.get("gains") or [None, None, None]
            w.writerow([im.get(c) for c in cols] + [l.get("x"), l.get("y"), lm[0], lm[1]] + list(g))
    return chemin
