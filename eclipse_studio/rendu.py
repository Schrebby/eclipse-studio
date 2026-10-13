# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jérémy BEAUFRERE — JEREMiA (https://jerem-ia.fr)
# Éclipse Studio est un logiciel libre : vous pouvez le redistribuer et/ou le
# modifier selon les termes de la GNU GPL v3 ou ultérieure (voir LICENSE).
"""
=====================================================================
 Éclipse Studio — Module RENDU (une image finale à partir du projet)
=====================================================================
 Chaîne de rendu d'une image :
   1. Repère canonique (Soleil centré, rond, orienté sur le ciel)
   2. Uniformisation photométrique (exposition / couleur / gradient)
   3. Reconstitution des parties coupées (Soleil de référence + Lune
      à sa position calculée)
   4. Cadrage de sortie (taille, marge, rotation, miroirs)
   5. Traitements : aplanissement centre-bord, accentuation, niveaux,
      gamma, contraste, saturation
   6. Colorisation (naturel ou palette)
   7. Incrustations (heure, obscuration, titre, crédit, « reconstitué »)
 La CHRONOLOGIE assemble images réelles et images de synthèse
 (avant le 1er contact, après le dernier, trous dus aux nuages).
=====================================================================
"""

from __future__ import annotations

import datetime as dt
import math
import os

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from . import palettes
from .modele import (LUM, STATUTS_UTILES, Trajectoire, assombrissement, disque_lunaire, grille_rho,
                     image_canonique, obscuration_disques)
from .projet import Projet


# ---------------------------------------------------------------------
# 1. POLICE POUR LES INCRUSTATIONS
# ---------------------------------------------------------------------
_POLICES = ["DejaVuSans.ttf", "Arial.ttf", "arial.ttf", "Helvetica.ttc",
            "/System/Library/Fonts/Helvetica.ttc", "/System/Library/Fonts/SFNS.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "C:/Windows/Fonts/arial.ttf",
            "C:/Windows/Fonts/segoeui.ttf"]
_cache_polices: dict[int, ImageFont.ImageFont] = {}


def police(taille: int):
    if taille in _cache_polices:
        return _cache_polices[taille]
    f = None
    for nom in _POLICES:
        try:
            f = ImageFont.truetype(nom, taille)
            break
        except Exception:
            continue
    if f is None:
        try:
            f = ImageFont.load_default(size=taille)
        except TypeError:
            f = ImageFont.load_default()
    _cache_polices[taille] = f
    return f


# ---------------------------------------------------------------------
# 2. MOTEUR DE RENDU
# ---------------------------------------------------------------------
class Rendu:
    def __init__(self, projet: Projet):
        self.p = projet
        self.F = projet.donnees["forme"]
        self.n = 2 * self.F["hc"] + 1
        self.Rc = self.F["A"] * self.F["echelle"]
        self.secs = projet.secondes()
        mod = projet.donnees.get("modele") or {}
        self.mod = mod
        self.traj = Trajectoire(mod["trajectoire"]) if mod.get("trajectoire") else None
        self.rho_m = mod.get("rho_m", 1.0)
        ch = projet.chemin("modele", "reference.npy")
        self.reference = np.load(ch) if os.path.exists(ch) else None
        self.rho, self.X, self.Y = grille_rho(self.n, self.Rc)
        self._cache_can: dict = {}
        # Éclipse de Lune : table d'atténuation (distance au centre de l'ombre → RGB)
        self.lunaire = bool(mod.get("lunaire")) or self.F.get("type") == "lunaire"
        self.attenuation = None
        cha = projet.chemin("modele", "attenuation.npy")
        if self.lunaire and os.path.exists(cha):
            self.attenuation = np.load(cha)
        self.teinte = np.array(mod.get("teinte_lune", [1, 1, 1]), np.float32)

    # ---- Chronologie ----
    def chronologie(self, pr: dict) -> list[dict]:
        """Liste ordonnée des images à produire : réelles et de synthèse."""
        ims = self.p.images
        reelles = [i for i, im in enumerate(ims) if im.get("statut") in STATUTS_UTILES and im.get("cache")
                   and not im.get("exclu")]
        if not reelles:
            return []
        t_reel = self.secs[reelles]
        cad, seuil = self.cadence(t_reel)
        if pr.get("cadence_synthese_s"):
            cad = max(0.2, float(pr["cadence_synthese_s"]))   # rythme imposé par l'utilisateur
            seuil = max(seuil, 1.8 * cad)
        synth_ok = self.reference is not None and self.traj is not None
        liste = []
        contacts = (self.mod.get("trajectoire") or {}).get("contacts", {}) if synth_ok else {}
        marge = float(pr.get("marge_synthese_s", 120))
        # Début recréé : images placées À REBOURS depuis la 1re photo, exactement au
        # rythme réel de la prise de vue → aucune saccade à la jonction.
        if synth_ok and pr.get("synthese_debut_fin") and contacts.get("C1") is not None:
            debut = contacts["C1"] - marge
            ts, k = [], 1
            while t_reel[0] - k * cad >= debut:
                ts.append(t_reel[0] - k * cad)
                k += 1
            liste += [{"type": "synth", "t": float(t)} for t in reversed(ts)]
        # Images réelles ; un trou (nuage, pause) est comblé par des images
        # régulièrement espacées au même rythme
        precedent = None
        for i in reelles:
            t = float(self.secs[i])
            if synth_ok and pr.get("combler_trous") and precedent is not None and t - precedent > seuil:
                m = int(round((t - precedent) / cad)) - 1
                for j in range(1, m + 1):
                    liste.append({"type": "synth", "t": precedent + j * (t - precedent) / (m + 1)})
            if synth_ok and pr.get("remplacer_interpolees", True) and ims[i].get("statut") == "interpole":
                # Image dont le disque n'a pas pu être mesuré (nuage épais) : sa position n'est
                # qu'estimée → on la remplace par la reconstitution, sans à-coup.
                liste.append({"type": "synth", "t": t, "remplace": i})
            else:
                liste.append({"type": "reel", "i": i, "t": t})
            precedent = t
        # Fin recréée : même rythme, à partir de la dernière photo
        if synth_ok and pr.get("synthese_debut_fin") and contacts.get("C4") is not None:
            fin = contacts["C4"] + marge
            k = 1
            while t_reel[-1] + k * cad <= fin:
                liste.append({"type": "synth", "t": float(t_reel[-1] + k * cad)})
                k += 1
        return liste

    @staticmethod
    def cadence(t_reel: np.ndarray) -> tuple[float, float]:
        """Rythme réel de la prise de vue, propre à CHAQUE série (intervalle fixe,
        intervallomètre irrégulier, rafales entrecoupées de pauses…).
        Renvoie (cadence, seuil) :
          cadence = durée moyenne représentée par une photo (pauses habituelles
                    comprises : une série en rafales garde son rythme moyen) ;
          seuil   = au-delà, l'intervalle est une interruption exceptionnelle
                    (nuage, changement de batterie…) comblée par la reconstitution."""
        if len(t_reel) < 2:
            return 10.0, 30.0
        d = np.diff(np.asarray(t_reel, float))
        d = d[d > 0]
        if not len(d):
            return 10.0, 30.0
        p90 = float(np.percentile(d, 90))
        seuil = max(3.0 * p90, 2.5 * float(np.median(d)))
        normaux = d[d <= seuil]
        cad = float(normaux.mean()) if len(normaux) else float(np.median(d))
        return max(0.2, cad), seuil

    # ---- Heure affichée ----
    def heure(self, t_rel: float, pr: dict) -> str:
        t0 = self.p.temps_utc(self.p.images[0])
        if t0 is None:
            return ""
        dth = (self.mod.get("trajectoire") or {}).get("dt_horloge", 0.0) if pr.get("corriger_horloge", True) else 0.0
        t = t0 + dt.timedelta(seconds=float(t_rel + dth))
        fz = pr.get("fuseau_affichage_h")
        if fz is None or fz == "":
            return t.strftime("%H:%M:%S") + " UT"
        t += dt.timedelta(hours=float(fz))
        return t.strftime("%H:%M:%S") + f" (UTC{float(fz):+g})"

    # ---- Étape 1-3 : image canonique corrigée (float RGB) ----
    def canonique_corrigee(self, entree: dict, pr: dict) -> np.ndarray:
        n = self.n
        if entree["type"] == "synth":
            return self.synthese(entree["t"], entree.get("remplace"))
        i = entree["i"]
        im = self.p.images[i]
        can, val = image_canonique(self.p, i, im.get("derotation", 0.0))
        if can.ndim == 2:
            can = np.repeat(can[:, :, None], 3, axis=2)
        if self.lunaire:
            # Pixels saturés : leur vraie luminosité est inconnue → reconstitués
            sat = (can.max(axis=2) > 0.975).astype(np.uint8)
            if sat.any():
                sat = cv2.dilate(sat, np.ones((5, 5), np.uint8))
                val = val * (1 - sat.astype(np.float32))
        out = self.corriger_lune(can, im) if self.lunaire else self.corriger(can, im, pr)
        if self._ciel_noir(pr):
            out *= np.clip((1.03 - self.rho) / 0.025, 0, 1)[:, :, None]
        if pr.get("reconstituer_coupes", True) and self.reference is not None and \
                float(val[self.rho < 1.02].min(initial=1.0)) < 0.99:
            plein = self.synthese(entree["t"], i)
            if plein is not None:
                # Fondu progressif sur ~8 px pour une jonction invisible réel / reconstitué
                v = cv2.erode(val, np.ones((9, 9), np.uint8))
                v = cv2.GaussianBlur(v, (0, 0), 3.5)[:, :, None]
                out = out * v + plein * (1 - v)
        return out

    def corriger_lune(self, can: np.ndarray, im: dict) -> np.ndarray:
        """Éclipse de Lune : passage en LUMINANCE RÉELLE (même échelle pour toutes
        les images grâce aux temps de pose) et neutralisation du rougissement
        atmosphérique propre à chaque image."""
        noir = np.array(im.get("noir") or [0, 0, 0], np.float32)
        v = np.clip(can - noir[None, None, :], 0, None)
        e = im.get("echelle_radiance") or 1.0
        cb = np.array(im.get("couleur_lune") or [1, 1, 1], np.float32)
        return v / float(e) * (cb * self.teinte)[None, None, :]

    def _ciel_noir(self, pr: dict) -> bool:
        """Ciel noir autour du disque (auto : sauf si une totalité est présente,
        pour préserver la couronne)."""
        v = pr.get("ciel_noir", "auto")
        if v == "auto":
            return not any(im.get("statut") == "ok-lune" for im in self.p.images)
        return bool(v)

    def corriger(self, can: np.ndarray, im: dict, pr: dict) -> np.ndarray:
        """Uniformisation photométrique selon le niveau choisi."""
        pm = self.p.donnees["params_modele"]
        mode = pm.get("uniformisation", "complete")
        if pm.get("teinte_cible") == "origine" and mode in ("couleur", "complete"):
            mode = "exposition"
        cible = np.array(self.mod.get("gain_cible", [1, 1, 1]), np.float32)
        g = np.array(im.get("gains") or [0, 0, 0], np.float32)
        if mode != "complete" or not im.get("photo"):
            noir = np.array(im.get("noir") or [0, 0, 0], np.float32)
            can = np.clip(can - noir[None, None, :], 0, None)
        if mode == "complete" and im.get("photo"):
            c = np.array(im["photo"], np.float32)   # (3, 4) : a, cx, cy, b
            out = np.empty_like(can)
            for ch in range(3):
                a, cx, cy, b = c[ch]
                out[:, :, ch] = (a + cx * self.X + cy * self.Y) * can[:, :, ch] + b
            return out
        if g.min() <= 0:
            # Pas de mesure : on applique un gain global moyen
            gm = [x.get("gains") for x in self.p.images if x.get("gains")]
            g = np.median(np.array(gm), axis=0).astype(np.float32) if gm else np.ones(3, np.float32)
            mode = "couleur" if mode == "complete" else mode
        if mode == "aucune":
            gm = [x.get("gains") for x in self.p.images if x.get("gains")]
            gref = np.median(np.array(gm), axis=0) if gm else np.ones(3)
            return can * float((cible @ LUM) / max(1e-6, gref @ LUM))
        if mode == "exposition":
            return can * float((cible @ LUM) / max(1e-6, g @ LUM))
        return can * (cible / np.maximum(g, 1e-6))[None, None, :]

    def synthese(self, t_rel: float, i: int | None = None) -> np.ndarray | None:
        """Éclipse de Soleil : Soleil de référence + Lune à sa position à l'instant t.
        Éclipse de Lune : Lune de référence × atténuation par l'ombre de la Terre.
        Renvoie None si la position de l'objet masquant est inconnue."""
        ref = self.reference
        if ref is None:
            return None
        im = self.p.images[i] if i is not None else {}
        if self.lunaire:
            if im.get("ombre_modele"):
                ox, oy = im["ombre_modele"]
            elif self.traj is not None:
                ox, oy = self.traj.position(t_rel)
            else:
                return None
            d = np.hypot(self.X - float(ox), self.Y - float(oy))
            tab = self.attenuation
            att = np.stack([np.interp(d, tab[:, 0], tab[:, 1 + ch], right=1.0) for ch in range(3)], axis=2)
            return ref * att.astype(np.float32) * self.teinte[None, None, :]
        if im.get("lune_modele"):
            mx, my = im["lune_modele"]
        elif self.traj is not None:
            mx, my = self.traj.position(t_rel)
        elif im.get("lune"):
            mx, my = im["lune"]["x"], im["lune"]["y"]
        else:
            return None
        lune = disque_lunaire(self.n, self.Rc, float(mx), float(my), self.rho_m, 1.2)
        return ref * (1 - lune)[:, :, None]

    def obscuration(self, entree: dict) -> float | None:
        if self.lunaire:
            return None
        if self.traj is not None:
            if entree["type"] == "reel" and self.p.images[entree["i"]].get("obscuration_modele") is not None:
                return self.p.images[entree["i"]]["obscuration_modele"]
            mx, my = self.traj.position(entree["t"])
            return obscuration_disques(math.hypot(float(mx), float(my)), self.rho_m)
        if entree["type"] == "reel":
            return self.p.images[entree["i"]].get("obscuration")
        return None

    # ---- Étape 4 : cadrage de sortie ----
    def cadrer(self, can: np.ndarray, pr: dict, taille: int | None = None) -> np.ndarray:
        S = int(taille or pr.get("taille", 1080))
        Rout = S / 2.0 / (1.0 + float(pr.get("marge", 0.35)))
        f = Rout / self.Rc
        if f < 0.8:
            can = cv2.GaussianBlur(can, (0, 0), 0.42 / f)
        c = (self.n - 1) / 2.0
        a = math.radians(float(pr.get("rotation", 0.0)))
        R = np.array([[math.cos(a), -math.sin(a)], [math.sin(a), math.cos(a)]])
        Fl = np.diag([-1.0 if pr.get("miroir_h") else 1.0, -1.0 if pr.get("miroir_v") else 1.0])
        L = Fl @ R * f
        t = np.array([(S - 1) / 2.0, (S - 1) / 2.0]) - L @ np.array([c, c])
        M = np.hstack([L, t[:, None]])
        return cv2.warpAffine(can, M, (S, S), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_CONSTANT, borderValue=0)

    # ---- Étapes 5-6 : traitements et couleurs ----
    def magnitude_ombre(self, entree: dict) -> float | None:
        """Éclipse de Lune : magnitude de l'ombre (> 1 = totalité)."""
        if not self.lunaire or self.traj is None:
            return None
        x, y = self.traj.position(entree["t"])
        return (self.mod["rho_u"] + 1 - math.hypot(float(x), float(y))) / 2

    def lumiere_lune(self, img: np.ndarray, pr: dict) -> np.ndarray:
        """Éclipse de Lune : la totalité est ~10 000× plus sombre que la pleine Lune.
        hdr       : compression asinh → pleine Lune ET ombre rouge visibles
        reelle    : luminosités réelles (la totalité devient presque noire)
        compensee : chaque image ramenée à la même luminosité moyenne."""
        mode = pr.get("lumiere_lune", "hdr")
        lum = img @ LUM
        S = img.shape[0]
        Rout = S / 2.0 / (1.0 + float(pr.get("marge", 0.35)))
        if mode == "reelle":
            return img / 0.8
        if mode == "compensee":
            rho, _, _ = grille_rho(S, Rout)
            m = float(np.median(lum[rho < 0.9])) if (rho < 0.9).any() else 1.0
            return img * (0.6 / max(m, 1e-7))
        sig = max(1e-6, float(pr.get("compression_hdr", 2e-4)))
        l2 = 0.8 * np.arcsinh(lum / sig) / np.arcsinh(0.8 / sig)
        return img * (l2 / np.maximum(lum, 1e-9))[:, :, None]

    def developper(self, img: np.ndarray, pr: dict) -> np.ndarray:
        S = img.shape[0]
        img = np.clip(img, 0, None)
        if self.lunaire:
            img = self.lumiere_lune(img, pr)
        # Aplanissement de l'assombrissement centre-bord (fait ressortir les facules)
        ap = float(pr.get("aplanir_limbe", 0.0)) if not self.lunaire else 0.0
        if ap > 0:
            Rout = S / 2.0 / (1.0 + float(pr.get("marge", 0.35)))
            rho, _, _ = grille_rho(S, Rout)
            L = assombrissement(np.minimum(rho, 0.995))
            corr = np.where(rho < 1.0, (1.0 / L) ** ap, 1.0).astype(np.float32)
            img = img * corr[:, :, None]
        # Accentuation (masque flou)
        acc = float(pr.get("accentuation", 0.0))
        if acc > 0:
            r = max(0.5, float(pr.get("rayon_accentuation", 2.0)) * S / 1080.0)
            flou = cv2.GaussianBlur(img, (0, 0), r)
            img = np.clip(img + acc * (img - flou), 0, None)
        # Niveaux + gamma + contraste
        noir, blanc = float(pr.get("point_noir", 0.02)), float(pr.get("point_blanc", 1.0))
        gam = max(0.05, float(pr.get("gamma", 1.0)))
        con = float(pr.get("contraste", 0.0))

        def ton(v):
            v = np.clip((v - noir) / max(1e-6, blanc - noir), 0, 1)
            if gam != 1.0:
                v = v ** (1.0 / gam)
            if con:
                s = v * v * (3 - 2 * v)
                v = np.clip(v + con * (s - v), 0, 1)
            return v

        lum = img @ LUM
        pal = pr.get("palette", "naturel")
        if pal == "naturel":
            l2 = ton(lum)
            rapport = np.where(lum > 1e-5, l2 / np.maximum(lum, 1e-5), 0.0)
            out = img * rapport[:, :, None]
            sat = float(pr.get("saturation", 1.0))
            if sat != 1.0:
                out = l2[:, :, None] + sat * (out - l2[:, :, None])
            return np.clip(out, 0, 1).astype(np.float32)
        if pal.startswith("#"):
            lut = palettes.table_personnalisee(pal)
        else:
            lut = palettes.table(pal)
        return palettes.appliquer(ton(lum), lut)

    # ---- Étape 7 : incrustations ----
    def incruster(self, rgb8: np.ndarray, entree: dict, pr: dict) -> np.ndarray:
        """Textes : titre (haut gauche), « reconstitution » (haut droite),
        heure + obscuration (bas gauche), crédit (bas droite)."""
        S = rgb8.shape[0]
        bas_g = []
        if pr.get("inc_heure"):
            h = self.heure(entree["t"], pr)
            if h:
                bas_g.append(h)
        if pr.get("inc_obscuration"):
            o = self.obscuration(entree)
            if o is not None:
                bas_g.append(f"Obscuration {100 * o:.1f} %")
            mo = self.magnitude_ombre(entree)
            if mo is not None:
                rp = self.mod.get("rho_p", 4.7)
                x, y = self.traj.position(entree["t"])
                d = math.hypot(float(x), float(y))
                phase = ("totalité" if mo >= 1 else "phase partielle" if mo > 0
                         else "pénombre" if d < rp + 1 else "pleine Lune")
                bas_g.append(f"{phase.capitalize()} · magnitude {max(mo, 0):.2f}" if mo > 0 else phase.capitalize())
        blocs = []
        if pr.get("inc_titre"):
            blocs.append(("hg", [str(pr["inc_titre"])], (225, 225, 225)))
        if pr.get("inc_reconstitue", True) and entree["type"] == "synth":
            blocs.append(("hd", ["reconstitution"], (255, 190, 90)))
        if bas_g:
            blocs.append(("bg", bas_g, (205, 205, 205)))
        if pr.get("inc_credit"):
            blocs.append(("bd", [str(pr["inc_credit"])], (170, 170, 170)))
        if not blocs:
            return rgb8
        img = Image.fromarray(rgb8)
        d = ImageDraw.Draw(img)
        fp = police(max(11, int(S * 0.026)))
        m = int(S * 0.025)
        inter = int(S * 0.036)
        for pos, lignes, coul in blocs:
            hauteur = inter * len(lignes)
            for j, t in enumerate(lignes):
                bb = d.textbbox((0, 0), t, font=fp)
                w = bb[2] - bb[0]
                x = m if pos[1] == "g" else S - m - w
                y = (m + j * inter) if pos[0] == "h" else (S - m - hauteur + j * inter)
                d.text((x, y), t, font=fp, fill=coul)
        return np.asarray(img)

    # ---- Image finale ----
    def image(self, entree: dict, pr: dict, taille: int | None = None, seize_bits: bool = False):
        can = self.canonique_corrigee(entree, pr)
        cad = self.cadrer(can, pr, taille)
        dev = self.developper(cad, pr)
        if seize_bits:
            return dev
        rgb8 = (dev * 255 + 0.5).astype(np.uint8)
        return self.incruster(rgb8, entree, pr)

    def flux(self, pr: dict, taille: int | None = None, seize_bits: bool = False, annule=None,
             debut: int = 0, fin: int | None = None):
        """Générateur d'images finales (gère le lissage temporel).
        debut / fin : plage d'indices de la chronologie (export partiel)."""
        chrono = self.chronologie(pr)
        n_lis = max(1, int(pr.get("lissage_temporel", 1)))
        tampon: list[np.ndarray] = []
        fin = len(chrono) if fin is None else min(len(chrono), fin)
        for k, e in enumerate(chrono):
            if k < debut - (n_lis - 1) or k >= fin:
                continue
            if annule and annule():
                return
            cad = self.cadrer(self.canonique_corrigee(e, pr), pr, taille)
            tampon.append(cad)
            if len(tampon) > n_lis:
                tampon.pop(0)
            if k < debut:
                continue
            moy = tampon[0] if len(tampon) == 1 else np.mean(tampon, axis=0)
            dev = self.developper(moy, pr)
            if seize_bits:
                yield k, len(chrono), e, dev
            else:
                yield k, len(chrono), e, self.incruster((dev * 255 + 0.5).astype(np.uint8), e, pr)
