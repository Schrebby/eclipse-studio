# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jérémy BEAUFRERE — JEREMiA (https://jerem-ia.fr)
# Éclipse Studio est un logiciel libre : vous pouvez le redistribuer et/ou le
# modifier selon les termes de la GNU GPL v3 ou ultérieure (voir LICENSE).
"""
=====================================================================
 Éclipse Studio — Module LIEUX (hors-ligne)
=====================================================================
 - Liste de villes embarquée (France détaillée + grandes villes du monde)
   complétée par les ~400 villes de référence des fuseaux horaires (tzdb)
   → recherche par nom sans Internet.
 - Fuseau horaire d'un point : fuseau de la ville de référence la plus
   proche (approximation suffisante, sauf tout près d'une frontière),
   décalage exact à la date voulue (heure d'été comprise) via zoneinfo.
=====================================================================
"""

from __future__ import annotations

import datetime as dt
import json
import math
import os
import unicodedata

FICHIER = os.path.join(os.path.dirname(__file__), "donnees", "lieux.json")

# (nom, latitude, longitude, pays, fuseau)
VILLES = [
    # ---- France : Bretagne et côte atlantique ----
    ("Étel", 47.656, -3.205, "France", "Europe/Paris"), ("Lorient", 47.748, -3.370, "France", "Europe/Paris"),
    ("Vannes", 47.658, -2.760, "France", "Europe/Paris"), ("Quiberon", 47.484, -3.120, "France", "Europe/Paris"),
    ("Carnac", 47.584, -3.078, "France", "Europe/Paris"), ("Auray", 47.668, -2.982, "France", "Europe/Paris"),
    ("Belle-Île-en-Mer (Le Palais)", 47.347, -3.155, "France", "Europe/Paris"),
    ("Hennebont", 47.805, -3.277, "France", "Europe/Paris"), ("Pontivy", 48.068, -2.963, "France", "Europe/Paris"),
    ("Quimper", 47.996, -4.102, "France", "Europe/Paris"), ("Concarneau", 47.875, -3.919, "France", "Europe/Paris"),
    ("Brest", 48.390, -4.486, "France", "Europe/Paris"), ("Pointe du Raz", 48.040, -4.739, "France", "Europe/Paris"),
    ("Morlaix", 48.578, -3.828, "France", "Europe/Paris"), ("Saint-Brieuc", 48.514, -2.765, "France", "Europe/Paris"),
    ("Saint-Malo", 48.649, -2.026, "France", "Europe/Paris"), ("Rennes", 48.117, -1.678, "France", "Europe/Paris"),
    ("Nantes", 47.218, -1.554, "France", "Europe/Paris"), ("Saint-Nazaire", 47.273, -2.214, "France", "Europe/Paris"),
    ("La Baule", 47.286, -2.391, "France", "Europe/Paris"), ("Lannion", 48.732, -3.456, "France", "Europe/Paris"),
    ("Perros-Guirec", 48.815, -3.443, "France", "Europe/Paris"), ("Douarnenez", 48.093, -4.329, "France", "Europe/Paris"),
    ("Crozon", 48.246, -4.490, "France", "Europe/Paris"), ("Ouessant", 48.457, -5.095, "France", "Europe/Paris"),
    ("La Rochelle", 46.160, -1.151, "France", "Europe/Paris"), ("Les Sables-d'Olonne", 46.496, -1.784, "France", "Europe/Paris"),
    ("Biarritz", 43.483, -1.559, "France", "Europe/Paris"), ("Arcachon", 44.658, -1.168, "France", "Europe/Paris"),
    # ---- France : grandes villes et sites astro ----
    ("Paris", 48.857, 2.352, "France", "Europe/Paris"), ("Lyon", 45.764, 4.836, "France", "Europe/Paris"),
    ("Marseille", 43.296, 5.370, "France", "Europe/Paris"), ("Toulouse", 43.605, 1.444, "France", "Europe/Paris"),
    ("Bordeaux", 44.838, -0.579, "France", "Europe/Paris"), ("Lille", 50.629, 3.057, "France", "Europe/Paris"),
    ("Strasbourg", 48.573, 7.752, "France", "Europe/Paris"), ("Nice", 43.710, 7.262, "France", "Europe/Paris"),
    ("Montpellier", 43.611, 3.877, "France", "Europe/Paris"), ("Grenoble", 45.188, 5.724, "France", "Europe/Paris"),
    ("Clermont-Ferrand", 45.778, 3.087, "France", "Europe/Paris"), ("Limoges", 45.834, 1.261, "France", "Europe/Paris"),
    ("Tours", 47.394, 0.685, "France", "Europe/Paris"), ("Orléans", 47.903, 1.909, "France", "Europe/Paris"),
    ("Le Mans", 48.006, 0.199, "France", "Europe/Paris"), ("Angers", 47.478, -0.563, "France", "Europe/Paris"),
    ("Caen", 49.183, -0.371, "France", "Europe/Paris"), ("Rouen", 49.443, 1.100, "France", "Europe/Paris"),
    ("Le Havre", 49.494, 0.108, "France", "Europe/Paris"), ("Cherbourg", 49.640, -1.616, "France", "Europe/Paris"),
    ("Amiens", 49.894, 2.296, "France", "Europe/Paris"), ("Reims", 49.258, 4.032, "France", "Europe/Paris"),
    ("Metz", 49.120, 6.176, "France", "Europe/Paris"), ("Nancy", 48.692, 6.184, "France", "Europe/Paris"),
    ("Dijon", 47.322, 5.041, "France", "Europe/Paris"), ("Besançon", 47.238, 6.024, "France", "Europe/Paris"),
    ("Poitiers", 46.580, 0.340, "France", "Europe/Paris"), ("Pau", 43.295, -0.371, "France", "Europe/Paris"),
    ("Perpignan", 42.699, 2.895, "France", "Europe/Paris"), ("Ajaccio", 41.919, 8.738, "France", "Europe/Paris"),
    ("Bastia", 42.697, 9.451, "France", "Europe/Paris"), ("Avignon", 43.949, 4.806, "France", "Europe/Paris"),
    ("Pic du Midi de Bigorre", 42.936, 0.142, "France", "Europe/Paris"),
    ("Saint-Véran", 44.701, 6.868, "France", "Europe/Paris"),
    ("Observatoire de Haute-Provence", 43.932, 5.713, "France", "Europe/Paris"),
    ("Mont Aigoual", 44.121, 3.581, "France", "Europe/Paris"),
    # ---- Europe ----
    ("Bruxelles", 50.850, 4.352, "Belgique", "Europe/Brussels"), ("Genève", 46.204, 6.143, "Suisse", "Europe/Zurich"),
    ("Zurich", 47.377, 8.541, "Suisse", "Europe/Zurich"), ("Luxembourg", 49.612, 6.130, "Luxembourg", "Europe/Luxembourg"),
    ("Londres", 51.507, -0.128, "Royaume-Uni", "Europe/London"), ("Édimbourg", 55.953, -3.188, "Royaume-Uni", "Europe/London"),
    ("Dublin", 53.350, -6.260, "Irlande", "Europe/Dublin"), ("Madrid", 40.417, -3.704, "Espagne", "Europe/Madrid"),
    ("Barcelone", 41.385, 2.173, "Espagne", "Europe/Madrid"), ("Burgos", 42.344, -3.697, "Espagne", "Europe/Madrid"),
    ("León", 42.599, -5.567, "Espagne", "Europe/Madrid"), ("Oviedo", 43.362, -5.849, "Espagne", "Europe/Madrid"),
    ("Valence", 39.470, -0.376, "Espagne", "Europe/Madrid"), ("Saragosse", 41.649, -0.889, "Espagne", "Europe/Madrid"),
    ("Palma de Majorque", 39.570, 2.650, "Espagne", "Europe/Madrid"), ("Bilbao", 43.263, -2.935, "Espagne", "Europe/Madrid"),
    ("Lisbonne", 38.722, -9.139, "Portugal", "Europe/Lisbon"), ("Porto", 41.158, -8.629, "Portugal", "Europe/Lisbon"),
    ("Rome", 41.903, 12.496, "Italie", "Europe/Rome"), ("Milan", 45.464, 9.190, "Italie", "Europe/Rome"),
    ("Berlin", 52.520, 13.405, "Allemagne", "Europe/Berlin"), ("Munich", 48.137, 11.576, "Allemagne", "Europe/Berlin"),
    ("Amsterdam", 52.370, 4.895, "Pays-Bas", "Europe/Amsterdam"), ("Vienne", 48.208, 16.373, "Autriche", "Europe/Vienna"),
    ("Prague", 50.075, 14.438, "Tchéquie", "Europe/Prague"), ("Varsovie", 52.230, 21.012, "Pologne", "Europe/Warsaw"),
    ("Copenhague", 55.676, 12.568, "Danemark", "Europe/Copenhagen"), ("Oslo", 59.914, 10.752, "Norvège", "Europe/Oslo"),
    ("Stockholm", 59.329, 18.069, "Suède", "Europe/Stockholm"), ("Helsinki", 60.170, 24.938, "Finlande", "Europe/Helsinki"),
    ("Reykjavik", 64.147, -21.942, "Islande", "Atlantic/Reykjavik"), ("Athènes", 37.984, 23.728, "Grèce", "Europe/Athens"),
    ("Istanbul", 41.008, 28.978, "Turquie", "Europe/Istanbul"), ("Moscou", 55.756, 37.617, "Russie", "Europe/Moscow"),
    # ---- Afrique, Amériques, Asie, Océanie ----
    ("Casablanca", 33.573, -7.590, "Maroc", "Africa/Casablanca"), ("Marrakech", 31.629, -7.981, "Maroc", "Africa/Casablanca"),
    ("Alger", 36.754, 3.059, "Algérie", "Africa/Algiers"), ("Tunis", 36.806, 10.181, "Tunisie", "Africa/Tunis"),
    ("Le Caire", 30.044, 31.236, "Égypte", "Africa/Cairo"), ("Louxor", 25.687, 32.640, "Égypte", "Africa/Cairo"),
    ("Dakar", 14.716, -17.467, "Sénégal", "Africa/Dakar"), ("Abidjan", 5.360, -4.008, "Côte d'Ivoire", "Africa/Abidjan"),
    ("Le Cap", -33.925, 18.424, "Afrique du Sud", "Africa/Johannesburg"),
    ("New York", 40.713, -74.006, "États-Unis", "America/New_York"), ("Dallas", 32.777, -96.797, "États-Unis", "America/Chicago"),
    ("Los Angeles", 34.052, -118.244, "États-Unis", "America/Los_Angeles"), ("Montréal", 45.502, -73.567, "Canada", "America/Toronto"),
    ("Québec", 46.814, -71.208, "Canada", "America/Toronto"), ("Mexico", 19.433, -99.133, "Mexique", "America/Mexico_City"),
    ("Mazatlán", 23.249, -106.411, "Mexique", "America/Mazatlan"), ("Buenos Aires", -34.604, -58.382, "Argentine", "America/Argentina/Buenos_Aires"),
    ("Santiago du Chili", -33.449, -70.669, "Chili", "America/Santiago"), ("La Serena", -29.904, -71.249, "Chili", "America/Santiago"),
    ("San Pedro de Atacama", -22.911, -68.200, "Chili", "America/Santiago"), ("Rio de Janeiro", -22.907, -43.173, "Brésil", "America/Sao_Paulo"),
    ("Fort-de-France", 14.616, -61.059, "Martinique", "America/Martinique"), ("Pointe-à-Pitre", 16.241, -61.533, "Guadeloupe", "America/Guadeloupe"),
    ("Cayenne", 4.922, -52.313, "Guyane", "America/Cayenne"), ("Saint-Denis (La Réunion)", -20.882, 55.450, "La Réunion", "Indian/Reunion"),
    ("Nouméa", -22.276, 166.458, "Nouvelle-Calédonie", "Pacific/Noumea"), ("Papeete", -17.535, -149.570, "Polynésie française", "Pacific/Tahiti"),
    ("Tokyo", 35.676, 139.650, "Japon", "Asia/Tokyo"), ("Pékin", 39.904, 116.407, "Chine", "Asia/Shanghai"),
    ("Delhi", 28.614, 77.209, "Inde", "Asia/Kolkata"), ("Dubaï", 25.205, 55.271, "Émirats arabes unis", "Asia/Dubai"),
    ("Sydney", -33.869, 151.209, "Australie", "Australia/Sydney"), ("Perth", -31.951, 115.861, "Australie", "Australia/Perth"),
    ("Exmouth", -21.932, 114.128, "Australie", "Australia/Perth"), ("Auckland", -36.849, 174.763, "Nouvelle-Zélande", "Pacific/Auckland"),
]


def _sans_accents(t: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", t.lower()) if unicodedata.category(c) != "Mn")


_DONNEES: list[dict] | None = None


def donnees() -> list[dict]:
    """Villes embarquées + villes de référence des fuseaux (fichier généré à
    l'installation depuis la base tzdb, fourni avec l'application)."""
    global _DONNEES
    if _DONNEES is None:
        base = [{"nom": n, "lat": la, "lon": lo, "pays": p, "tz": tz} for n, la, lo, p, tz in VILLES]
        try:
            with open(FICHIER, encoding="utf-8") as f:
                base += json.load(f)
        except Exception:
            pass
        _DONNEES = base
    return _DONNEES


def chercher(texte: str, n: int = 12) -> list[dict]:
    """Recherche par nom (sans accents ; début de mot prioritaire)."""
    q = _sans_accents(texte.strip())
    if not q:
        return []
    res = []
    for v in donnees():
        nom = _sans_accents(v["nom"])
        if q in nom:
            res.append((0 if nom.startswith(q) else 1, len(nom), v))
    res.sort(key=lambda r: (r[0], r[1]))
    vus, out = set(), []
    for _, _, v in res:
        cle = (round(v["lat"], 2), round(v["lon"], 2))
        if cle not in vus:
            vus.add(cle)
            out.append(v)
        if len(out) >= n:
            break
    return out


def fuseau(lat: float, lon: float, date: dt.datetime | None = None) -> dict:
    """Fuseau horaire le plus probable et décalage UTC (h) à la date donnée."""
    meilleur = None
    for v in donnees():
        if not v.get("tz"):
            continue
        # distance angulaire approchée (suffisante pour un plus proche voisin)
        d = math.hypot(lat - v["lat"], (lon - v["lon"]) * math.cos(math.radians(lat)))
        if meilleur is None or d < meilleur[0]:
            meilleur = (d, v)
    tz = meilleur[1]["tz"] if meilleur else None
    date = date or dt.datetime.utcnow()
    dec = None
    try:
        from zoneinfo import ZoneInfo
        dec = ZoneInfo(tz).utcoffset(date).total_seconds() / 3600.0
    except Exception:
        dec = round(lon / 15.0)   # repli : fuseau théorique
    return {"tz": tz, "decalage_h": dec, "reference": meilleur[1]["nom"] if meilleur else None,
            "distance_km": round(meilleur[0] * 111.2) if meilleur else None}


def generer_fichier(zone_tab: str = "/usr/share/zoneinfo/zone.tab"):
    """Construit donnees/lieux.json depuis zone.tab (outil de développement)."""
    out = []
    with open(zone_tab, encoding="utf-8") as f:
        for ligne in f:
            if ligne.startswith("#") or not ligne.strip():
                continue
            parts = ligne.rstrip("\n").split("\t")
            pays, coord, tz = parts[0], parts[1], parts[2]
            i = max(coord.rfind("+"), coord.rfind("-"))
            la, lo = coord[:i], coord[i:]

            def deg(t):
                s = -1 if t[0] == "-" else 1
                t = t[1:]
                if len(t) in (4, 5):
                    return s * (int(t[:-2]) + int(t[-2:]) / 60)
                return s * (int(t[:-4]) + int(t[-4:-2]) / 60 + int(t[-2:]) / 3600)
            nom = tz.split("/")[-1].replace("_", " ")
            out.append({"nom": nom, "lat": round(deg(la), 4), "lon": round(deg(lo), 4), "pays": pays, "tz": tz})
    os.makedirs(os.path.dirname(FICHIER), exist_ok=True)
    with open(FICHIER, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False)
    return len(out)


if __name__ == "__main__":
    print(generer_fichier())
