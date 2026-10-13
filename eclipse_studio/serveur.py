# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jérémy BEAUFRERE — JEREMiA (https://jerem-ia.fr)
# Éclipse Studio est un logiciel libre : vous pouvez le redistribuer et/ou le
# modifier selon les termes de la GNU GPL v3 ou ultérieure (voir LICENSE).
"""
=====================================================================
 Éclipse Studio — SERVEUR LOCAL (interface dans le navigateur)
=====================================================================
 Petit serveur HTTP 100 % local (127.0.0.1, aucune donnée ne sort de
 l'ordinateur). L'interface (ui/index.html) dialogue avec lui en JSON.
 Les traitements longs tournent dans un fil d'exécution dédié, les
 calculs lourds sur tous les cœurs (processus séparés).
=====================================================================
"""

from __future__ import annotations

import json
import math
import mimetypes
import os
import platform
import string
import subprocess
import threading
import time
import traceback
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import cv2
import numpy as np

import datetime as dt

from . import __version__, astro, lieux, palettes
from .io_images import infos_prise_de_vue
from .analyse import Annulation, analyser, consolider, coords_ellipse, lire_png16, message_inexploitable
from .export import exporter
from .io_images import RAWPY_OK, lister_images, resume_dossier
from .modele import modeliser
from .projet import PARAMS_ANALYSE, PARAMS_MODELE, PARAMS_RENDU, Projet
from .rendu import Rendu

DOSSIER_UI = os.path.join(os.path.dirname(__file__), "ui")
SITE_JEREMIA = "https://jerem-ia.fr"
CONTACT = "contact@jerem-ia.fr"
# Logotype par défaut (remplaçable : déposer ui/logo.svg ou ui/logo.png)
LOGO_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 132 28" width="132" height="28">
<defs><linearGradient id="g" x1="0" x2="1"><stop offset="0" stop-color="#ffb347"/><stop offset="1" stop-color="#ff7a3d"/></linearGradient></defs>
<circle cx="13" cy="14" r="10" fill="none" stroke="url(#g)" stroke-width="2.4"/>
<circle cx="17" cy="11" r="8.2" fill="#10131a"/>
<text x="30" y="20" font-family="-apple-system,Segoe UI,Helvetica,Arial,sans-serif" font-size="16" font-weight="700"
 letter-spacing="1.2" fill="#e6e8ee">JEREM<tspan fill="url(#g)">i</tspan>A</text></svg>"""


# ---------------------------------------------------------------------
# 1. ÉTAT DE L'APPLICATION
# ---------------------------------------------------------------------
class Etat:
    def __init__(self):
        self.projet: Projet | None = None
        self.rendu: Rendu | None = None
        self.verrou_rendu = threading.Lock()
        self.tache = {"nom": "", "actif": False, "progression": 0.0, "texte": "", "erreur": "", "resultat": ""}
        self.journal: list[str] = []
        self._annuler = False
        self._fil: threading.Thread | None = None

    def log(self, txt: str):
        horo = time.strftime("%H:%M:%S")
        self.journal.append(f"[{horo}] {txt}")
        del self.journal[:-400]

    def invalider_rendu(self):
        with self.verrou_rendu:
            self.rendu = None

    def obtenir_rendu(self) -> Rendu:
        with self.verrou_rendu:
            if self.rendu is None:
                self.rendu = Rendu(self.projet)
            return self.rendu

    def lancer(self, nom: str, fonction):
        if self.tache["actif"]:
            raise RuntimeError("Un traitement est déjà en cours.")
        self._annuler = False
        self.tache = {"nom": nom, "actif": True, "progression": 0.0, "texte": "Démarrage…", "erreur": "",
                      "resultat": ""}

        def corps():
            t0 = time.time()
            try:
                res = fonction(self._progression, self.log, lambda: self._annuler)
                self.tache["resultat"] = res or ""
                self.log(f"✔ {nom} terminé en {time.time() - t0:.0f} s")
            except Annulation:
                self.tache["erreur"] = "Interrompu"
                self.log(f"✖ {nom} interrompu")
            except Exception as e:
                self.tache["erreur"] = str(e)
                self.log(f"✖ Erreur : {e}")
                traceback.print_exc()
            finally:
                self.tache["actif"] = False
                self.invalider_rendu()

        self._fil = threading.Thread(target=corps, daemon=True)
        self._fil.start()

    def _progression(self, f, txt):
        self.tache["progression"] = float(f)
        self.tache["texte"] = txt


ETAT = Etat()


# ---------------------------------------------------------------------
# 2. RÉSUMÉS POUR L'INTERFACE
# ---------------------------------------------------------------------
def resume_projet(p: Projet | None) -> dict | None:
    if p is None:
        return None
    ims = p.images
    stats: dict[str, int] = {}
    for im in ims:
        stats[im.get("statut", "?")] = stats.get(im.get("statut", "?"), 0) + 1
    mod = p.donnees.get("modele") or {}
    traj = mod.get("trajectoire") or {}
    t0 = p.temps_utc(ims[0]) if ims else None
    contacts = {}
    if traj.get("contacts") and t0:
        import datetime as dt
        dth = traj.get("dt_horloge", 0.0)
        for k, v in traj["contacts"].items():
            if k in ("C1", "C2", "C3", "C4", "max", "P1", "U1", "U2", "U3", "U4", "P4"):
                contacts[k] = (t0 + dt.timedelta(seconds=v + dth)).strftime("%H:%M:%S")
            else:
                contacts[k] = v
    F = p.donnees.get("forme") or {}
    return {
        "dossier": p.dossier, "dossier_images": p.donnees.get("dossier_images", ""),
        "etape": p.donnees.get("etape"), "nb_images": len(ims), "stats": stats,
        "forme": {k: F.get(k) for k in ("A", "k", "theta", "echelle", "demi", "methode", "blanc", "type")} if F else None,
        "params_analyse": p.donnees["params_analyse"], "params_modele": p.donnees["params_modele"],
        "params_rendu": p.donnees["params_rendu"],
        "modele": {"mode": traj.get("mode"), "rms": traj.get("rms"), "dt_horloge": traj.get("dt_horloge"),
                   "orientation_nord": traj.get("orientation_nord_deg"), "rho_m": mod.get("rho_m"),
                   "contacts": contacts, "couverture_reference": mod.get("couverture_reference"),
                   "lunaire": bool(mod.get("lunaire")), "rho_u": mod.get("rho_u"),
                   "rotation_champ": traj.get("rotation_champ_deg_h")} if mod else None,
        "exports": sorted(os.listdir(p.chemin("exports")))[::-1] if os.path.isdir(p.chemin("exports")) else [],
        "inexploitable": message_inexploitable(F) if F else None,
    }


def lignes_images(p: Projet) -> list[dict]:
    secs = p.secondes()
    out = []
    for i, im in enumerate(p.images):
        out.append({"i": i, "nom": im["nom"], "t": float(secs[i]), "heure": (im.get("t") or "")[11:19],
                    "statut": im.get("statut"), "cx": im.get("cx"), "cy": im.get("cy"), "k": im.get("k_lisse"),
                    "sigma": im.get("sigma"), "couverture": im.get("couverture"), "visible": im.get("visible"),
                    "obscuration": im.get("obscuration_modele", im.get("obscuration")),
                    "lune": bool(im.get("lune")), "exclu": bool(im.get("exclu")), "message": im.get("message", "")})
    return out


def racines() -> list[str]:
    if platform.system() == "Windows":
        return [f"{d}:\\" for d in string.ascii_uppercase if os.path.exists(f"{d}:\\")]
    r = ["/", os.path.expanduser("~")]
    if os.path.isdir("/Volumes"):
        r += [os.path.join("/Volumes", v) for v in sorted(os.listdir("/Volumes"))]
    if os.path.isdir("/media"):
        for u in os.listdir("/media"):
            d = os.path.join("/media", u)
            if os.path.isdir(d):
                r += [os.path.join(d, v) for v in os.listdir(d)]
    return r


def image_controle(p: Projet, i: int, taille: int = 900) -> np.ndarray:
    """Cache brut étiré + ellipse détectée + points de limbe : contrôle visuel."""
    F = p.donnees["forme"]
    im = p.images[i]
    src = lire_png16(p.chemin("cache", im["cache"]))
    lum = src if src.ndim == 2 else src @ np.array([0.2126, 0.7152, 0.0722], np.float32)
    hi = float(np.percentile(lum, 99.5)) or 1.0
    vis = np.clip(src / hi, 0, 1) ** 0.6
    vis = (vis * 255).astype(np.uint8)
    if vis.ndim == 2:
        vis = cv2.cvtColor(vis, cv2.COLOR_GRAY2RGB)
    vis = np.ascontiguousarray(vis)
    e, hc = F["echelle"], F["hc"]
    cx = hc + (im["cx"] - im["cx0"]) * e
    cy = hc + (im["cy"] - im["cy0"]) * e
    A = F["A"] * e
    k = im.get("k_lisse", F["k"])
    ep = max(2, int(vis.shape[0] / 400))
    cv2.ellipse(vis, (int(round(cx * 16)), int(round(cy * 16))), (int(A * 16), int(A * k * 16)),
                math.degrees(F["theta"]), 0, 360, (255, 60, 60), ep, cv2.LINE_AA, 4)
    pts = p.points.get(i)
    if pts is not None:
        for x, y in pts:
            px, py = hc + (x - im["cx0"]) * e, hc + (y - im["cy0"]) * e
            cv2.circle(vis, (int(px), int(py)), ep + 1, (60, 255, 90), -1, cv2.LINE_AA)
    cv2.drawMarker(vis, (int(cx), int(cy)), (80, 220, 255), cv2.MARKER_CROSS, int(A * 0.12), ep, cv2.LINE_AA)
    if im.get("lune_modele"):
        lx, ly = im["lune_modele"]
        rho_m = (p.donnees.get("modele") or {}).get("rho_m", 1.0)
        # Lune dessinée dans le repère canonique (approximation : rotation négligée)
        cv2.circle(vis, (int(cx + lx * A), int(cy + ly * A)), int(rho_m * A), (255, 200, 60), ep, cv2.LINE_AA)
    f = taille / vis.shape[0]
    return cv2.resize(vis, None, fx=f, fy=f, interpolation=cv2.INTER_AREA)


def date_reference() -> dt.datetime | None:
    """Date (UTC approchée) du milieu de la série du projet ouvert."""
    p = ETAT.projet
    if not p or not p.images:
        return None
    im = p.images[len(p.images) // 2]
    return p.temps_utc(im) if im.get("t_source") != "date du fichier" else None


def gps_des_photos(dossier: str | None = None) -> dict:
    """Position GPS enregistrée dans les photos (projet ouvert ou dossier choisi)."""
    chemins = []
    if ETAT.projet and ETAT.projet.images and not dossier:
        ims = ETAT.projet.images
        pos = [im["prise"]["gps"] for im in ims if (im.get("prise") or {}).get("gps")]
        if pos:
            return {"lat": float(np.median([p[0] for p in pos])), "lon": float(np.median([p[1] for p in pos])),
                    "nb": len(pos)}
        chemins = [im["chemin"] for im in ims[:: max(1, len(ims) // 20)]]
    elif dossier and os.path.isdir(dossier):
        f = lister_images(dossier)
        chemins = f[:: max(1, len(f) // 20)]
    pos = [g for g in (infos_prise_de_vue(c).get("gps") for c in chemins[:25]) if g]
    if not pos:
        return {"lat": None, "lon": None, "nb": 0}
    return {"lat": float(np.median([p[0] for p in pos])), "lon": float(np.median([p[1] for p in pos])), "nb": len(pos)}


def circonstances(lat: float, lon: float, date: str | None) -> dict:
    """Éclipse la plus proche de la date (projet ou date saisie) vue depuis le lieu :
    contacts en heure locale + hauteur de l'astre."""
    t = None
    if date:
        try:
            t = dt.datetime.fromisoformat(date)
        except ValueError:
            t = None
    t = t or date_reference() or dt.datetime.utcnow()
    r = astro.eclipse_proche(t, lat, lon, 20.0)
    if not r:
        return {"trouve": False}
    fz = lieux.fuseau(lat, lon, r["contacts"].get("max", t))
    dec = fz["decalage_h"] or 0.0
    ordre = ["C1", "P1", "U1", "C2", "U2", "max", "U3", "C3", "U4", "C4", "P4"]
    noms = {"C1": "Début (1er contact)", "C2": "Début de la totalité", "max": "Maximum",
            "C3": "Fin de la totalité", "C4": "Fin (dernier contact)", "P1": "Entrée dans la pénombre",
            "U1": "Entrée dans l'ombre", "U2": "Début de la totalité", "U3": "Fin de la totalité",
            "U4": "Sortie de l'ombre", "P4": "Sortie de la pénombre"}
    lignes = []
    for k in ordre:
        if k in r["contacts"]:
            tc = r["contacts"][k]
            h = (r.get("visibilite") or {}).get(k, {}).get("hauteur")
            lignes.append({"cle": k, "nom": noms.get(k, k), "utc": tc.strftime("%Y-%m-%d %H:%M:%S"),
                           "local": (tc + dt.timedelta(hours=dec)).strftime("%H:%M:%S"),
                           "hauteur": None if h is None else round(h, 1), "visible": h is not None and h > 0})
    return {"trouve": True, "type": r["type"], "infos": r["infos"], "fuseau": fz, "lignes": lignes,
            "date_locale": (r["contacts"]["max"] + dt.timedelta(hours=dec)).strftime("%d/%m/%Y")}


def nettoyer(o):
    """JSON strict pour le navigateur : NaN / Infini → null, types NumPy → Python."""
    if isinstance(o, float) or isinstance(o, np.floating):
        return float(o) if math.isfinite(o) else None
    if isinstance(o, np.integer):
        return int(o)
    if isinstance(o, dict):
        return {k: nettoyer(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [nettoyer(v) for v in o]
    return o


def jpeg(rgb: np.ndarray, q: int = 88) -> bytes:
    ok, buf = cv2.imencode(".jpg", cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR), [cv2.IMWRITE_JPEG_QUALITY, q])
    return buf.tobytes()


# ---------------------------------------------------------------------
# 3. ROUTES
# ---------------------------------------------------------------------
class Gestionnaire(BaseHTTPRequestHandler):
    server_version = "EclipseStudio/" + __version__

    def log_message(self, *args):  # silence
        pass

    # ---- réponses ----
    def _envoyer(self, code: int, corps: bytes, type_mime: str):
        self.send_response(code)
        self.send_header("Content-Type", type_mime)
        self.send_header("Content-Length", str(len(corps)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(corps)

    def _json(self, obj, code: int = 200):
        self._envoyer(code, json.dumps(nettoyer(obj), ensure_ascii=False, default=str).encode("utf-8"),
                      "application/json; charset=utf-8")

    def _corps(self) -> dict:
        n = int(self.headers.get("Content-Length", 0) or 0)
        return json.loads(self.rfile.read(n).decode("utf-8")) if n else {}

    # ---- GET ----
    def do_GET(self):
        try:
            u = urlparse(self.path)
            q = {k: v[0] for k, v in parse_qs(u.query).items()}
            if u.path in ("/", "/index.html"):
                with open(os.path.join(DOSSIER_UI, "index.html"), "rb") as f:
                    return self._envoyer(200, f.read(), "text/html; charset=utf-8")
            if u.path == "/logo":
                for nom, mime in (("logo.svg", "image/svg+xml"), ("logo.png", "image/png"), ("logo.webp", "image/webp")):
                    ch = os.path.join(DOSSIER_UI, nom)
                    if os.path.exists(ch):
                        with open(ch, "rb") as f:
                            return self._envoyer(200, f.read(), mime)
                return self._envoyer(200, LOGO_SVG.encode("utf-8"), "image/svg+xml")
            if u.path == "/licence":
                # Texte intégral de la licence (fichier LICENSE à la racine du projet)
                ch = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "LICENSE")
                if os.path.exists(ch):
                    with open(ch, "rb") as f:
                        return self._envoyer(200, f.read(), "text/plain; charset=utf-8")
                self.send_response(302)
                self.send_header("Location", "https://www.gnu.org/licenses/gpl-3.0.html")
                self.end_headers()
                return
            if u.path == "/api/etat":
                return self._json({"version": __version__, "rawpy": RAWPY_OK, "tache": ETAT.tache,
                                   "site": SITE_JEREMIA, "contact": CONTACT,
                                   "journal": ETAT.journal[-200:], "projet": resume_projet(ETAT.projet),
                                   "defauts": {"analyse": PARAMS_ANALYSE, "modele": PARAMS_MODELE,
                                               "rendu": PARAMS_RENDU},
                                   "palettes": palettes.liste()})
            if u.path == "/api/images":
                return self._json(lignes_images(ETAT.projet) if ETAT.projet else [])
            if u.path == "/api/chronologie":
                pr = json.loads(q.get("p", "{}")) or ETAT.projet.donnees["params_rendu"]
                r = ETAT.obtenir_rendu()
                ch = r.chronologie(pr)
                cad, _ = r.cadence(r.secs[[i for i, im in enumerate(ETAT.projet.images)
                                           if im.get("statut") in ("ok", "ok-lune", "interpole")]])
                return self._json({"cadence": cad, "images": [{"type": e["type"], "i": e.get("i"), "t": e["t"],
                                    "heure": r.heure(e["t"], pr)} for e in ch]})
            if u.path in ("/api/apercu", "/api/chronologie") and ETAT.projet and \
                    message_inexploitable(ETAT.projet.donnees.get("forme")):
                return self._json({"erreur": message_inexploitable(ETAT.projet.donnees.get("forme"))}, 409)
            if u.path == "/api/apercu":
                pr = dict(ETAT.projet.donnees["params_rendu"])
                pr.update(json.loads(q.get("p", "{}")))
                r = ETAT.obtenir_rendu()
                ch = r.chronologie(pr)
                if not ch:
                    return self._json({"erreur": "aucune image"}, 404)
                k = max(0, min(len(ch) - 1, int(q.get("k", 0))))
                taille = int(q.get("taille", 640))
                img = r.image(ch[k], pr, taille)
                return self._envoyer(200, jpeg(img), "image/jpeg")
            # ---- Localisation : recherche de lieux, fuseau, GPS, circonstances ----
            if u.path == "/api/lieux":
                return self._json(lieux.chercher(q.get("q", ""), 12))
            if u.path == "/api/lieux_carte":
                return self._json([[round(v["lat"], 3), round(v["lon"], 3), v["nom"]] for v in lieux.donnees()])
            if u.path == "/api/fuseau":
                return self._json(lieux.fuseau(float(q["lat"]), float(q["lon"]), date_reference()))
            if u.path == "/api/gps":
                return self._json(gps_des_photos(q.get("dossier")))
            if u.path == "/api/circonstances":
                return self._json(circonstances(float(q["lat"]), float(q["lon"]), q.get("date")))
            if u.path == "/api/controle":
                img = image_controle(ETAT.projet, int(q.get("i", 0)), int(q.get("taille", 800)))
                return self._envoyer(200, jpeg(img), "image/jpeg")
            if u.path == "/api/fichier":
                ch = os.path.realpath(q.get("chemin", ""))
                base = os.path.realpath(ETAT.projet.chemin("exports")) if ETAT.projet else None
                if not base or not ch.startswith(base) or not os.path.isfile(ch):
                    return self._json({"erreur": "fichier non autorisé"}, 403)
                with open(ch, "rb") as f:
                    data = f.read()
                return self._envoyer(200, data, mimetypes.guess_type(ch)[0] or "application/octet-stream")
            return self._json({"erreur": "introuvable"}, 404)
        except Exception as e:
            traceback.print_exc()
            return self._json({"erreur": str(e)}, 500)

    # ---- POST ----
    def do_POST(self):
        try:
            u = urlparse(self.path)
            d = self._corps()
            if u.path == "/api/parcourir":
                ch = d.get("chemin") or os.path.expanduser("~")
                ch = os.path.abspath(os.path.expanduser(ch))
                if not os.path.isdir(ch):
                    ch = os.path.dirname(ch)
                dossiers = []
                try:
                    for n in sorted(os.listdir(ch), key=str.lower):
                        if not n.startswith(".") and os.path.isdir(os.path.join(ch, n)):
                            dossiers.append(n)
                except PermissionError:
                    pass
                try:
                    res = resume_dossier(ch)
                except Exception:
                    res = {}
                return self._json({"chemin": ch, "parent": os.path.dirname(ch), "dossiers": dossiers,
                                   "images": res, "racines": racines(),
                                   "projet": os.path.exists(os.path.join(ch, "projet.json"))})
            if u.path == "/api/analyser":
                images = d["dossier_images"]
                fichiers = lister_images(images)
                if d.get("extension"):
                    fichiers = [f for f in fichiers if f.lower().endswith(d["extension"].lower())]
                if d.get("filtre"):
                    fichiers = [f for f in fichiers if d["filtre"] in os.path.basename(f)]
                if not fichiers:
                    return self._json({"erreur": "Aucune image correspondante dans ce dossier."}, 400)
                p = Projet(d["dossier_projet"])
                p.donnees["dossier_images"] = images
                p.donnees["params_analyse"].update(d.get("params_analyse", {}))
                if ETAT.projet:   # on garde les réglages de rendu précédents
                    p.donnees["params_rendu"].update(ETAT.projet.donnees["params_rendu"])
                ETAT.projet = p
                ETAT.lancer("Analyse", lambda pg, lg, an: analyser(p, fichiers, pg, lg, an))
                return self._json({"ok": True, "nb": len(fichiers)})
            if u.path == "/api/ouvrir":
                ETAT.projet = Projet.ouvrir(d["dossier_projet"])
                ETAT.invalider_rendu()
                ETAT.log(f"Projet ouvert : {ETAT.projet.dossier}")
                return self._json({"ok": True})
            if u.path == "/api/modeliser":
                p = ETAT.projet
                p.donnees["params_modele"].update(d.get("params_modele", {}))
                ETAT.lancer("Modélisation", lambda pg, lg, an: modeliser(p, pg, lg, an))
                return self._json({"ok": True})
            if u.path == "/api/params_rendu":
                ETAT.projet.donnees["params_rendu"].update(d)
                ETAT.projet.sauver()
                return self._json({"ok": True})
            if u.path == "/api/exclure":
                p = ETAT.projet
                p.images[int(d["i"])]["exclu"] = bool(d.get("exclu", True))
                consolider(p, ETAT.log)
                p.sauver()
                ETAT.invalider_rendu()
                return self._json({"ok": True})
            if u.path == "/api/exporter":
                p = ETAT.projet
                pr = dict(p.donnees["params_rendu"])
                pr.update(d.get("params_rendu", {}))
                p.donnees["params_rendu"].update(d.get("params_rendu", {}))
                p.sauver()
                typ = d["type"]
                ETAT.lancer(f"Export {typ}", lambda pg, lg, an: exporter(p, typ, pr, pg, lg, an, d.get("options")))
                return self._json({"ok": True})
            if u.path == "/api/annuler":
                ETAT._annuler = True
                return self._json({"ok": True})
            if u.path == "/api/quitter":
                # Arrêt de l'application (indispensable pour les versions sans fenêtre de terminal)
                ETAT._annuler = True
                self._json({"ok": True})
                threading.Timer(0.3, lambda: os._exit(0)).start()
                return
            if u.path == "/api/ouvrir_dossier":
                ch = d.get("chemin") or (ETAT.projet.chemin("exports") if ETAT.projet else "")
                if os.path.exists(ch):
                    if platform.system() == "Windows":
                        os.startfile(ch)  # type: ignore[attr-defined]
                    elif platform.system() == "Darwin":
                        subprocess.Popen(["open", ch])
                    else:
                        subprocess.Popen(["xdg-open", ch])
                return self._json({"ok": True})
            return self._json({"erreur": "introuvable"}, 404)
        except Exception as e:
            traceback.print_exc()
            return self._json({"erreur": str(e)}, 500)


# ---------------------------------------------------------------------
# 4. DÉMARRAGE
# ---------------------------------------------------------------------
def instance_existante(port: int) -> str | None:
    """Si Éclipse Studio tourne déjà sur ce port, renvoie son adresse
    (un 2e double-clic rouvre simplement l'interface au lieu d'un 2e serveur)."""
    import urllib.request
    url = f"http://127.0.0.1:{port}/"
    try:
        ouvreur = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with ouvreur.open(url + "api/etat", timeout=1.5) as r:
            if r.headers.get("Server", "").startswith("EclipseStudio"):
                return url
    except Exception:
        return None
    return None


def demarrer(port: int = 8765, ouvrir_navigateur: bool = True, projet: str | None = None):
    deja = None if projet else instance_existante(port)
    if deja:
        print(f"Éclipse Studio est déjà ouvert : {deja}", flush=True)
        if ouvrir_navigateur:
            webbrowser.open(deja)
        return
    if projet:
        ETAT.projet = Projet.ouvrir(projet)
    for essai in range(20):
        try:
            serveur = ThreadingHTTPServer(("127.0.0.1", port + essai), Gestionnaire)
            break
        except OSError:
            continue
    else:
        raise RuntimeError("Aucun port disponible")
    url = f"http://127.0.0.1:{serveur.server_address[1]}/"
    print(f"\n  Éclipse Studio {__version__} — interface : {url}\n  (bouton « Quitter » de l'interface, ou fermez cette fenêtre)\n", flush=True)
    if ouvrir_navigateur:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        serveur.serve_forever()
    except KeyboardInterrupt:
        pass
