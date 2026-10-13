# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jérémy BEAUFRERE — JEREMiA (https://jerem-ia.fr)
# Éclipse Studio est un logiciel libre : vous pouvez le redistribuer et/ou le
# modifier selon les termes de la GNU GPL v3 ou ultérieure (voir LICENSE).
"""
=====================================================================
 Éclipse Studio — Module LECTURE DES IMAGES & HORODATAGE
=====================================================================
 Formats pris en charge :
   - JPEG, PNG, TIFF (8/16/32 bits, float)       → OpenCV
   - FITS / FIT / FTS (mono, RGB, CFA Bayer)     → lecteur FITS intégré
   - RAW (CR2, CR3, NEF, ARW, RAF, ORF, RW2, DNG, PEF, SRW…)
       → rawpy (LibRaw) si installé,
       → sinon repli automatique sur l'aperçu JPEG intégré au RAW.

 Toutes les images sont renvoyées en float32 normalisé 0..1
 (0 = noir, 1 = saturation du format d'origine) afin que la
 photométrie reste comparable d'une image à l'autre.

 Les chemins contenant des accents (ex. « Août ») sont gérés sur
 Windows grâce à np.fromfile + cv2.imdecode.
=====================================================================
"""

from __future__ import annotations

import datetime as dt
import os
import re
import struct

import cv2
import numpy as np

# ---------------------------------------------------------------------
# 1. EXTENSIONS RECONNUES
# ---------------------------------------------------------------------
EXT_STANDARD = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp", ".webp"}
EXT_FITS = {".fit", ".fits", ".fts"}
EXT_RAW = {".cr2", ".cr3", ".crw", ".nef", ".nrw", ".arw", ".srf", ".sr2", ".raf", ".orf",
           ".rw2", ".dng", ".pef", ".srw", ".x3f", ".3fr", ".iiq", ".erf", ".kdc", ".mos",
           ".mrw", ".rwl", ".raw"}
EXT_TOUTES = EXT_STANDARD | EXT_FITS | EXT_RAW

try:  # rawpy est optionnel
    import rawpy  # type: ignore
    RAWPY_OK = True
except Exception:  # pragma: no cover
    rawpy = None
    RAWPY_OK = False


def famille(chemin: str) -> str:
    """Renvoie 'raw', 'fits' ou 'standard' selon l'extension."""
    ext = os.path.splitext(chemin)[1].lower()
    if ext in EXT_RAW:
        return "raw"
    if ext in EXT_FITS:
        return "fits"
    return "standard"


def tri_naturel(nom: str):
    """Clé de tri « naturel » : IMG_2.jpg avant IMG_10.jpg."""
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", nom)]


def lister_images(dossier: str, extensions: set[str] | None = None) -> list[str]:
    """Liste les images d'un dossier (non récursif), triées naturellement.
    Si plusieurs familles coexistent (ex. CR2 + FITS convertis par Siril),
    la plus nombreuse en originaux est proposée par l'interface."""
    ext_ok = extensions or EXT_TOUTES
    fichiers = []
    for nom in os.listdir(dossier):
        if nom.startswith("."):
            continue
        ch = os.path.join(dossier, nom)
        if os.path.isfile(ch) and os.path.splitext(nom)[1].lower() in ext_ok:
            fichiers.append(ch)
    fichiers.sort(key=lambda c: tri_naturel(os.path.basename(c)))
    return fichiers


def resume_dossier(dossier: str) -> dict:
    """Compte les fichiers par extension (aide au choix dans l'interface)."""
    compte: dict[str, int] = {}
    for nom in os.listdir(dossier):
        ext = os.path.splitext(nom)[1].lower()
        if ext in EXT_TOUTES and not nom.startswith("."):
            compte[ext] = compte.get(ext, 0) + 1
    return compte


# ---------------------------------------------------------------------
# 2. LECTEUR FITS INTÉGRÉ (aucune dépendance)
# ---------------------------------------------------------------------
def lire_entete_fits(f) -> dict:
    """Lit l'en-tête FITS primaire (blocs de 2880 octets)."""
    entete: dict = {}
    while True:
        bloc = f.read(2880)
        if len(bloc) < 2880:
            raise ValueError("FITS tronqué")
        for i in range(0, 2880, 80):
            carte = bloc[i:i + 80].decode("ascii", errors="replace")
            cle = carte[:8].strip()
            if cle == "END":
                return entete
            if carte[8:10] == "= ":
                val = carte[10:].split("/")[0].strip() if not carte[10:].strip().startswith("'") \
                    else carte[10:].strip()[1:].split("'")[0].strip()
                if val in ("T", "F"):
                    val = (val == "T")
                else:
                    try:
                        val = int(val)
                    except ValueError:
                        try:
                            val = float(val)
                        except ValueError:
                            pass
                entete[cle] = val


def lire_fits(chemin: str):
    """Renvoie (donnees float32 normalisées 0..1, entête).
    Formes possibles : (H, W) mono/CFA ou (H, W, 3) couleur."""
    with open(chemin, "rb") as f:
        ent = lire_entete_fits(f)
        bitpix = int(ent["BITPIX"])
        naxis = int(ent.get("NAXIS", 2))
        dims = [int(ent[f"NAXIS{i}"]) for i in range(1, naxis + 1)]
        types = {8: ">u1", 16: ">i2", 32: ">i4", 64: ">i8", -32: ">f4", -64: ">f8"}
        n = int(np.prod(dims))
        brut = np.frombuffer(f.read(n * abs(bitpix) // 8), dtype=types[bitpix], count=n)
    bzero = float(ent.get("BZERO", 0.0))
    bscale = float(ent.get("BSCALE", 1.0))
    data = brut.astype(np.float32) * bscale + bzero
    data = data.reshape(dims[::-1])           # (plans, H, W) ou (H, W)
    if data.ndim == 3:
        data = np.moveaxis(data, 0, -1)       # (H, W, plans)
        if data.shape[2] == 1:
            data = data[:, :, 0]
    # Normalisation selon le type d'origine
    if bitpix == 8:
        data /= 255.0
    elif bitpix == 16:
        data /= 65535.0
    elif bitpix == 32:
        data /= 4294967295.0 if bzero else 2147483647.0
    else:  # flottant : déjà 0..1 (Siril) ou 0..65535 (autres logiciels)
        mx = float(np.nanmax(data)) if data.size else 1.0
        if mx > 1.5:
            data /= 65535.0 if mx <= 65535.0 else mx
    data = np.nan_to_num(data, nan=0.0)
    # Convention FITS : 1re ligne = BAS de l'image → on remet à l'endroit
    ordre = str(ent.get("ROWORDER", "BOTTOM-UP")).upper()
    retourne = ordre != "TOP-DOWN"
    if retourne:
        data = data[::-1].copy()
    ent["_RETOURNE"] = retourne
    return data, ent


def motif_bayer(motif: str) -> str:
    """Motif Bayer normalisé. Convention Siril / NINA / ASIAIR : le motif est
    exprimé pour l'image affichée à l'endroit (vérifié sur Canon EOS : RGGB)."""
    motif = (motif or "").strip().upper()[:4]
    return motif if len(motif) == 4 and set(motif) <= set("RGB") else ""


def niveau_blanc_probable(maximum: float) -> float:
    """Les capteurs 12/14 bits enregistrés en FITS 16 bits n'atteignent pas 1.0
    (ex. Canon : saturation vers 15 300 / 65 535). Le maximum observé sur la
    série sert de niveau de saturation (constante commune à toutes les images)."""
    return float(maximum) if 0.01 < maximum < 0.98 else 1.0


def debayeriser(cfa: np.ndarray, motif: str) -> np.ndarray:
    """Dématriçage bilinéaire OpenCV → RGB float32."""
    # Correspondance motif capteur → constante OpenCV (convention OpenCV décalée)
    codes = {"RGGB": cv2.COLOR_BayerBG2RGB, "BGGR": cv2.COLOR_BayerRG2RGB,
             "GRBG": cv2.COLOR_BayerGB2RGB, "GBRG": cv2.COLOR_BayerGR2RGB}
    code = codes.get(motif)
    if code is None:
        return np.repeat(cfa[:, :, None], 3, axis=2)
    u16 = np.clip(cfa * 65535.0, 0, 65535).astype(np.uint16)
    return cv2.cvtColor(u16, code).astype(np.float32) / 65535.0


def binning_cfa(cfa: np.ndarray) -> np.ndarray:
    """Super-pixel 2×2 : luminance d'une matrice de Bayer sans connaître
    le motif (moyenne R+G+G+B). Image résultante à demi-résolution."""
    h, w = cfa.shape[0] // 2 * 2, cfa.shape[1] // 2 * 2
    c = cfa[:h, :w]
    return 0.25 * (c[0::2, 0::2] + c[0::2, 1::2] + c[1::2, 0::2] + c[1::2, 1::2])


# ---------------------------------------------------------------------
# 3. APERÇU JPEG INTÉGRÉ AUX RAW (repli sans rawpy)
# ---------------------------------------------------------------------
def extraire_jpeg_integre(chemin: str) -> bytes | None:
    """Plus grand aperçu JPEG intégré au RAW qui se décode correctement
    (certains RAW — CR3 notamment — contiennent des flux tronqués)."""
    with open(chemin, "rb") as f:
        b = f.read()
    candidats = []
    pos = 0
    while True:
        debut = b.find(b"\xff\xd8\xff", pos)
        if debut < 0:
            break
        prochain = b.find(b"\xff\xd8\xff", debut + 3)
        lim = prochain if prochain > 0 else len(b)
        fin = b.rfind(b"\xff\xd9", debut, lim)
        if fin < 0:
            fin = b.find(b"\xff\xd9", debut + 3)
        if fin > 0 and fin + 2 - debut > 20000:
            candidats.append((fin + 2 - debut, debut))
        pos = debut + 3
    for taille, debut in sorted(candidats, reverse=True):
        flux = b[debut:debut + taille]
        if cv2.imdecode(np.frombuffer(flux, np.uint8), cv2.IMREAD_REDUCED_COLOR_8) is not None:
            return flux
    return None


# ---------------------------------------------------------------------
# 4. CHARGEMENT UNIFIÉ
# ---------------------------------------------------------------------
def _imread_unicode(chemin: str):
    data = np.fromfile(chemin, dtype=np.uint8)
    return cv2.imdecode(data, cv2.IMREAD_UNCHANGED | cv2.IMREAD_ANYDEPTH | cv2.IMREAD_ANYCOLOR)


def _vers_float(img: np.ndarray) -> np.ndarray:
    if img.dtype == np.uint8:
        return img.astype(np.float32) / 255.0
    if img.dtype == np.uint16:
        return img.astype(np.float32) / 65535.0
    img = img.astype(np.float32)
    mx = float(img.max()) if img.size else 1.0
    return img / mx if mx > 1.5 else img


def charger_image(chemin: str, couleur: bool = False, raw_demi: bool = False,
                  blanc: float | None = None) -> tuple[np.ndarray, dict]:
    """Charge une image en float32 0..1.
    couleur=False → (H, W) luminance ; couleur=True → (H, W, 3) RGB.
    raw_demi       → RAW décodé à demi-résolution (4× plus rapide).
    blanc          → niveau de saturation des FITS entiers (12/14 bits), ramené à 1.
    Renvoie (image, infos) ; infos['methode'] décrit la voie utilisée."""
    fam = famille(chemin)
    infos: dict = {"methode": fam}
    if fam == "fits":
        data, ent = lire_fits(chemin)
        infos["maximum"] = float(data.max()) if data.size else 1.0
        if blanc and blanc < 1.0 and int(ent.get("BITPIX", 16)) > 0:
            data = data / blanc
        infos["entete"] = {k: v for k, v in ent.items() if not k.startswith("_")}
        if data.ndim == 2 and ent.get("BAYERPAT"):
            motif = motif_bayer(str(ent["BAYERPAT"]))
            infos["methode"] = f"fits-cfa-{motif}"
            if couleur:
                rgb = debayeriser(data, motif)
                if raw_demi:
                    rgb = cv2.resize(rgb, (rgb.shape[1] // 2, rgb.shape[0] // 2), interpolation=cv2.INTER_AREA)
                return rgb, infos
            lum = binning_cfa(data)
            if not raw_demi:
                lum = cv2.resize(lum, (data.shape[1], data.shape[0]), interpolation=cv2.INTER_LINEAR)
            infos["demi"] = raw_demi
            return lum, infos
        img = data
    elif fam == "raw":
        if RAWPY_OK:
            with rawpy.imread(chemin) as raw:
                rgb16 = raw.postprocess(use_camera_wb=True, no_auto_bright=True, output_bps=16,
                                        gamma=(1, 1), half_size=raw_demi, user_flip=0)
            img = rgb16.astype(np.float32) / 65535.0
            infos["methode"] = "rawpy" + ("-demi" if raw_demi else "")
        else:
            jpg = extraire_jpeg_integre(chemin)
            if jpg is None:
                raise IOError("RAW illisible : installez rawpy (pip install rawpy)")
            bgr = cv2.imdecode(np.frombuffer(jpg, np.uint8), cv2.IMREAD_COLOR)
            if bgr is None:
                raise IOError("aperçu intégré illisible : installez rawpy pour lire ce RAW")
            img = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
            if raw_demi:
                img = cv2.resize(img, (img.shape[1] // 2, img.shape[0] // 2), interpolation=cv2.INTER_AREA)
            infos["methode"] = "apercu-jpeg-integre"
    else:
        brut = _imread_unicode(chemin)
        if brut is None:
            raise IOError(f"Image illisible : {os.path.basename(chemin)}")
        if brut.ndim == 3:
            if brut.shape[2] == 4:
                brut = brut[:, :, :3]
            brut = cv2.cvtColor(brut, cv2.COLOR_BGR2RGB)
        img = _vers_float(brut)

    if couleur:
        if img.ndim == 2:
            img = np.repeat(img[:, :, None], 3, axis=2)
        return img, infos
    if img.ndim == 3:
        img = 0.2126 * img[:, :, 0] + 0.7152 * img[:, :, 1] + 0.0722 * img[:, :, 2]
    return img.astype(np.float32, copy=False), infos


# ---------------------------------------------------------------------
# 5. HORODATAGE (EXIF / FITS / date du fichier)
# ---------------------------------------------------------------------
def _tiff_lire_ifd(b: bytes, off: int, e: str):
    """Lit un IFD TIFF ; renvoie {tag: (type, nb, offset_valeur, octets_bruts)}."""
    if off <= 0 or off + 2 > len(b):
        return {}
    n = struct.unpack(e + "H", b[off:off + 2])[0]
    if n > 1000:
        return {}
    res = {}
    for i in range(n):
        p = off + 2 + 12 * i
        if p + 12 > len(b):
            break
        tag, typ, cnt = struct.unpack(e + "HHI", b[p:p + 8])
        res[tag] = (typ, cnt, p + 8)
    return res


def _tiff_ascii(b: bytes, ent, e: str) -> str | None:
    typ, cnt, p = ent
    if typ != 2:
        return None
    if cnt <= 4:
        brut = b[p:p + cnt]
    else:
        off = struct.unpack(e + "I", b[p:p + 4])[0]
        brut = b[off:off + cnt]
    return brut.split(b"\x00")[0].decode("ascii", errors="ignore").strip()


def _tiff_rationnels(b: bytes, ent, e: str) -> list[float]:
    """Valeurs RATIONAL (type 5) / SRATIONAL (10) d'une entrée TIFF."""
    typ, cnt, p = ent
    if typ in (11, 12):   # FLOAT / DOUBLE (certains logiciels)
        taille = 4 if typ == 11 else 8
        off = p if cnt * taille <= 4 else struct.unpack(e + "I", b[p:p + 4])[0]
        return list(struct.unpack(e + ("f" if typ == 11 else "d") * cnt, b[off:off + taille * cnt]))
    if typ not in (5, 10):
        return []
    off = struct.unpack(e + "I", b[p:p + 4])[0]
    fmt = e + ("II" if typ == 5 else "ii")
    vals = []
    for k in range(cnt):
        num, den = struct.unpack(fmt, b[off + 8 * k: off + 8 * k + 8])
        vals.append(num / den if den else 0.0)
    return vals


def _tiff_entier(b: bytes, ent, e: str) -> int | None:
    typ, cnt, p = ent
    if typ == 3:
        return struct.unpack(e + "H", b[p:p + 2])[0]
    if typ == 4:
        return struct.unpack(e + "I", b[p:p + 4])[0]
    return None


def _exif_depuis_tiff(b: bytes) -> dict:
    """Extrait d'un bloc TIFF/EXIF : date de prise de vue (+ sous-secondes,
    décalage horaire), exposition, ouverture, ISO et position GPS."""
    if b[:2] == b"II":
        e = "<"
    elif b[:2] == b"MM":
        e = ">"
    else:
        return {}
    off0 = struct.unpack(e + "I", b[4:8])[0]
    ifd0 = _tiff_lire_ifd(b, off0, e)
    out = {}
    if 0x0132 in ifd0:
        out["DateTime"] = _tiff_ascii(b, ifd0[0x0132], e)
    if 0x8769 in ifd0:
        off_exif = struct.unpack(e + "I", b[ifd0[0x8769][2]:ifd0[0x8769][2] + 4])[0]
        ex = _tiff_lire_ifd(b, off_exif, e)
        for tag, nom in ((0x9003, "DateTimeOriginal"), (0x9291, "SubSecTimeOriginal"),
                         (0x9011, "OffsetTimeOriginal")):
            if tag in ex:
                out[nom] = _tiff_ascii(b, ex[tag], e)
        try:
            if 0x829A in ex:
                out["ExposureTime"] = (_tiff_rationnels(b, ex[0x829A], e) or [None])[0]
            if 0x829D in ex:
                out["FNumber"] = (_tiff_rationnels(b, ex[0x829D], e) or [None])[0]
            if 0x8827 in ex:
                out["ISO"] = _tiff_entier(b, ex[0x8827], e)
        except Exception:
            pass
    if 0x8825 in ifd0:   # bloc GPS
        try:
            off_gps = struct.unpack(e + "I", b[ifd0[0x8825][2]:ifd0[0x8825][2] + 4])[0]
            g = _tiff_lire_ifd(b, off_gps, e)
            if 2 in g and 4 in g:
                la = _tiff_rationnels(b, g[2], e)
                lo = _tiff_rationnels(b, g[4], e)
                lat = la[0] + la[1] / 60 + la[2] / 3600
                lon = lo[0] + lo[1] / 60 + lo[2] / 3600
                if 1 in g and (_tiff_ascii(b, g[1], e) or "N").upper().startswith("S"):
                    lat = -lat
                if 3 in g and (_tiff_ascii(b, g[3], e) or "E").upper().startswith("W"):
                    lon = -lon
                if abs(lat) > 1e-6 or abs(lon) > 1e-6:
                    out["GPS"] = (lat, lon)
        except Exception:
            pass
    return out


def _exif_brut(chemin: str) -> dict:
    """Lit les EXIF d'un JPEG (segment APP1) ou d'un fichier de type TIFF (TIFF, CR2, NEF, ARW, DNG…)."""
    with open(chemin, "rb") as f:
        tete = f.read(4 * 1024 * 1024)
    try:
        if tete[:2] == b"\xff\xd8":
            pos = 2
            while pos + 4 < len(tete):
                if tete[pos] != 0xFF:
                    break
                marq = tete[pos + 1]
                long = struct.unpack(">H", tete[pos + 2:pos + 4])[0]
                if marq == 0xE1 and tete[pos + 4:pos + 10] == b"Exif\x00\x00":
                    return _exif_depuis_tiff(tete[pos + 10:pos + 2 + long])
                pos += 2 + long
            return {}
        if tete[:2] in (b"II", b"MM"):
            return _exif_depuis_tiff(tete)
    except Exception:
        return {}
    return {}


_RE_DATE = re.compile(rb"(19|20)\d\d:[01]\d:[0-3]\d [0-2]\d:[0-5]\d:[0-5]\d")


def horodatage(chemin: str) -> tuple[dt.datetime | None, str, bool]:
    """Renvoie (date, source, est_UTC).
    Priorité : FITS DATE-OBS (UTC) > EXIF DateTimeOriginal (+SubSec)
    > recherche d'une date EXIF dans les 4 premiers Mo (CR3, ORF…) > date du fichier."""
    fam = famille(chemin)
    try:
        if fam == "fits":
            with open(chemin, "rb") as f:
                ent = lire_entete_fits(f)
            d = ent.get("DATE-OBS") or ent.get("DATE_OBS")
            if d:
                d = str(d).replace("Z", "")
                fmt = "%Y-%m-%dT%H:%M:%S.%f" if "." in d else "%Y-%m-%dT%H:%M:%S"
                return dt.datetime.strptime(d, fmt), "FITS DATE-OBS (UT)", True
        else:
            ex = _exif_brut(chemin)
            d = ex.get("DateTimeOriginal") or ex.get("DateTime")
            if d:
                t = dt.datetime.strptime(d[:19], "%Y:%m:%d %H:%M:%S")
                ss = (ex.get("SubSecTimeOriginal") or "").strip()
                if ss.isdigit():
                    t += dt.timedelta(seconds=float("0." + ss))
                return t, "EXIF (heure de l'appareil)", False
            with open(chemin, "rb") as f:
                m = _RE_DATE.search(f.read(4 * 1024 * 1024))
            if m:
                return dt.datetime.strptime(m.group(0).decode(), "%Y:%m:%d %H:%M:%S"), \
                    "EXIF (recherche)", False
    except Exception:
        pass
    t = dt.datetime.fromtimestamp(os.path.getmtime(chemin))
    return t, "date du fichier", False


# ---------------------------------------------------------------------
# 6. PARAMÈTRES DE PRISE DE VUE (exposition, GPS, fuseau)
# ---------------------------------------------------------------------
def _degres(v) -> float | None:
    """Convertit 47.66, '47.66', '47 39 50', '47:39:50' ou '-3d12m' en degrés."""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    t = re.findall(r"[-+]?\d+(?:\.\d+)?", str(v))
    if not t:
        return None
    vals = [float(x) for x in t[:3]]
    signe = -1.0 if str(v).strip().startswith("-") or str(v).strip().upper()[-1:] in ("S", "W", "O") else 1.0
    d = abs(vals[0]) + (vals[1] / 60 if len(vals) > 1 else 0) + (vals[2] / 3600 if len(vals) > 2 else 0)
    return signe * d


def infos_prise_de_vue(chemin: str) -> dict:
    """Exposition (s), ouverture, ISO, position GPS et décalage horaire
    d'une image (EXIF ou en-tête FITS). Les champs absents valent None."""
    out = {"exposition": None, "ouverture": None, "iso": None, "gps": None, "decalage_utc_h": None}
    try:
        if famille(chemin) == "fits":
            with open(chemin, "rb") as f:
                ent = lire_entete_fits(f)
            out["exposition"] = ent.get("EXPTIME") or ent.get("EXPOSURE")
            out["iso"] = ent.get("ISOSPEED") or ent.get("GAIN")
            lat = _degres(ent.get("SITELAT") or ent.get("OBSLAT") or ent.get("LAT-OBS"))
            lon = _degres(ent.get("SITELONG") or ent.get("OBSLONG") or ent.get("LONG-OBS"))
            if lat is not None and lon is not None:
                out["gps"] = (lat, lon)
            return out
        ex = _exif_brut(chemin)
        out["exposition"] = ex.get("ExposureTime")
        out["ouverture"] = ex.get("FNumber")
        out["iso"] = ex.get("ISO")
        out["gps"] = ex.get("GPS")
        o = ex.get("OffsetTimeOriginal")
        if o and re.match(r"^[+-]\d\d:\d\d$", o):
            out["decalage_utc_h"] = (1 if o[0] == "+" else -1) * (int(o[1:3]) + int(o[4:6]) / 60)
    except Exception:
        pass
    return out


def facteur_exposition(info: dict) -> float | None:
    """Quantité de lumière captée, relative : temps × ISO / ouverture²."""
    t = info.get("exposition")
    if not t or t <= 0:
        return None
    iso = info.get("iso") or 100
    n = info.get("ouverture")
    return float(t) * float(iso) / 100.0 / (float(n) ** 2 if n else 1.0)
