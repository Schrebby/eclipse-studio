# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jérémy BEAUFRERE — JEREMiA (https://jerem-ia.fr)
# Éclipse Studio est un logiciel libre : vous pouvez le redistribuer et/ou le
# modifier selon les termes de la GNU GPL v3 ou ultérieure (voir LICENSE).
"""
=====================================================================
 Éclipse Studio — Module PALETTES DE COLORISATION
=====================================================================
 Chaque palette est une suite de points (position 0..1, couleur RGB
 0..255) interpolés en une table de 4096 entrées appliquée à la
 luminance de l'image. Les palettes « SDO » s'inspirent des fausses
 couleurs utilisées par la NASA (Solar Dynamics Observatory / AIA),
 « H-alpha » et « Calcium K » imitent les filtres solaires étroits.
 « naturel » conserve les couleurs réelles (uniformisées) de la série.
=====================================================================
"""

from __future__ import annotations

import numpy as np

PALETTES: dict[str, dict] = {
    "naturel": {"nom": "Couleurs naturelles (uniformisées)", "points": None},
    "blanc": {"nom": "Lumière blanche (neutre)", "points": [(0, (0, 0, 0)), (1, (255, 255, 255))]},
    "baader": {"nom": "Film Baader / lumière blanche chaude",
               "points": [(0, (0, 0, 0)), (0.5, (150, 140, 120)), (1, (255, 250, 236))]},
    "verre_orange": {"nom": "Filtre verre orangé (Thousand Oaks)",
                     "points": [(0, (0, 0, 0)), (0.45, (200, 90, 10)), (0.8, (255, 170, 60)), (1, (255, 235, 190))]},
    "halpha": {"nom": "H-alpha (656 nm)",
               "points": [(0, (0, 0, 0)), (0.25, (90, 8, 0)), (0.55, (200, 50, 5)), (0.8, (255, 135, 30)),
                          (0.95, (255, 205, 120)), (1, (255, 240, 210))]},
    "halpha_profond": {"nom": "H-alpha rouge profond",
                       "points": [(0, (0, 0, 0)), (0.35, (110, 0, 0)), (0.7, (220, 30, 10)), (1, (255, 170, 110))]},
    "cak": {"nom": "Calcium K (393 nm)",
            "points": [(0, (0, 0, 0)), (0.3, (50, 10, 110)), (0.65, (130, 60, 220)), (0.9, (205, 160, 255)),
                       (1, (245, 230, 255))]},
    "sdo_171": {"nom": "NASA SDO AIA 171 Å (or)",
                "points": [(0, (0, 0, 0)), (0.3, (80, 55, 0)), (0.6, (190, 145, 30)), (0.85, (245, 215, 110)),
                           (1, (255, 250, 230))]},
    "sdo_193": {"nom": "NASA SDO AIA 193 Å (bronze)",
                "points": [(0, (0, 0, 0)), (0.3, (75, 35, 10)), (0.6, (180, 105, 55)), (0.85, (235, 185, 140)),
                           (1, (255, 245, 235))]},
    "sdo_211": {"nom": "NASA SDO AIA 211 Å (violet)",
                "points": [(0, (0, 0, 0)), (0.3, (70, 20, 60)), (0.6, (170, 70, 150)), (0.85, (225, 160, 215)),
                           (1, (255, 240, 250))]},
    "sdo_304": {"nom": "NASA SDO AIA 304 Å (rouge-orangé)",
                "points": [(0, (0, 0, 0)), (0.3, (100, 15, 0)), (0.6, (215, 75, 10)), (0.85, (255, 160, 70)),
                           (1, (255, 235, 200))]},
    "sdo_131": {"nom": "NASA SDO AIA 131 Å (turquoise)",
                "points": [(0, (0, 0, 0)), (0.3, (0, 50, 60)), (0.6, (20, 140, 150)), (0.85, (120, 215, 220)),
                           (1, (235, 255, 255))]},
    "sdo_335": {"nom": "NASA SDO AIA 335 Å (bleu)",
                "points": [(0, (0, 0, 0)), (0.3, (10, 30, 90)), (0.6, (40, 100, 200)), (0.85, (140, 185, 245)),
                           (1, (240, 248, 255))]},
    "sdo_94": {"nom": "NASA SDO AIA 94 Å (vert)",
               "points": [(0, (0, 0, 0)), (0.3, (15, 60, 20)), (0.6, (60, 160, 60)), (0.85, (170, 230, 150)),
                          (1, (245, 255, 240))]},
    "sdo_1600": {"nom": "NASA SDO AIA 1600 Å (jaune-vert)",
                 "points": [(0, (0, 0, 0)), (0.3, (70, 70, 0)), (0.6, (175, 175, 40)), (0.85, (235, 235, 130)),
                            (1, (255, 255, 230))]},
    "feu": {"nom": "Feu", "points": [(0, (0, 0, 0)), (0.35, (180, 20, 0)), (0.65, (255, 140, 0)),
                                     (0.9, (255, 230, 80)), (1, (255, 255, 255))]},
    "glace": {"nom": "Glace", "points": [(0, (0, 0, 0)), (0.4, (10, 60, 140)), (0.75, (100, 180, 240)),
                                         (1, (255, 255, 255))]},
    "negatif": {"nom": "Négatif (relief des taches)", "points": [(0, (255, 255, 255)), (1, (0, 0, 0))]},
}


def table(nom: str, taille: int = 4096) -> np.ndarray | None:
    """Table de correspondance float32 (taille, 3) en 0..1 ; None pour « naturel »."""
    pal = PALETTES.get(nom) or PALETTES["blanc"]
    pts = pal["points"]
    if pts is None:
        return None
    pos = np.array([p for p, _ in pts], np.float32)
    col = np.array([c for _, c in pts], np.float32) / 255.0
    x = np.linspace(0, 1, taille, dtype=np.float32)
    return np.stack([np.interp(x, pos, col[:, c]) for c in range(3)], axis=1).astype(np.float32)


def table_personnalisee(couleur_hex: str, taille: int = 4096) -> np.ndarray:
    """Palette noir → couleur choisie → blanc."""
    h = couleur_hex.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    x = np.linspace(0, 1, taille, dtype=np.float32)
    pos = np.array([0, 0.6, 1], np.float32)
    cols = np.array([[0, 0, 0], [r, g, b], [255, 255, 255]], np.float32) / 255.0
    return np.stack([np.interp(x, pos, cols[:, c]) for c in range(3)], axis=1).astype(np.float32)


def appliquer(lum: np.ndarray, lut: np.ndarray) -> np.ndarray:
    idx = np.clip(lum * (len(lut) - 1), 0, len(lut) - 1).astype(np.int32)
    return lut[idx]


def liste() -> list[dict]:
    return [{"id": k, "nom": v["nom"]} for k, v in PALETTES.items()]
