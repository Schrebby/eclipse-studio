# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jérémy BEAUFRERE — JEREMiA (https://jerem-ia.fr)
# Éclipse Studio est un logiciel libre : vous pouvez le redistribuer et/ou le
# modifier selon les termes de la GNU GPL v3 ou ultérieure (voir LICENSE).
"""
=====================================================================
 Éclipse Studio — SIGNATURE ET NOTARISATION APPLE (macOS)
=====================================================================
 Avec un compte Apple Developer, l'app s'ouvre par simple double-clic,
 sans avertissement « Apple n'a pas pu confirmer… ».

 1. Signature « Developer ID Application » de CHAQUE binaire de l'app
    (de l'intérieur vers l'extérieur), avec le « runtime renforcé »
    exigé par Apple, puis de l'app elle-même.
 2. Signature du .dmg.
 3. Notarisation : envoi du .dmg à Apple (notarytool), attente du verdict.
 4. Agrafage (stapler) du ticket dans le .dmg : vérifiable hors-ligne.

 Réglages (variables d'environnement, toutes facultatives) :
   MAC_SIGNATURE   identité, ex. « Developer ID Application: Nom (TEAMID) »
                   (sinon : détectée automatiquement dans le trousseau)
   Notarisation, au choix :
   NOTARY_PROFIL   profil enregistré par « xcrun notarytool store-credentials »
                   (par défaut : eclipse-studio)
   APPLE_ID + APPLE_TEAM_ID + APPLE_MDP_APP   (mot de passe pour app,
                   créé sur account.apple.com) — utilisé sur GitHub
 Sans identité : signature « ad hoc » (l'app fonctionne, avec avertissement).
=====================================================================
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import unicodedata

DROITS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "droits_mac.plist")
MAGIQUES = {b"\xfe\xed\xfa\xce", b"\xfe\xed\xfa\xcf", b"\xce\xfa\xed\xfe",
            b"\xcf\xfa\xed\xfe", b"\xca\xfe\xba\xbe", b"\xbe\xba\xfe\xca"}


# ---------------------------------------------------------------------
# 1. Outils
# ---------------------------------------------------------------------
def _cmd(cmd: list[str], secret: str | None = None, verifier: bool = True) -> subprocess.CompletedProcess:
    # Affichage court : les longues listes de binaires sont résumées
    vis = [c if c != secret else "••••" for c in cmd]
    fichiers = [c for c in vis if c.startswith("/")]
    aff = " ".join(vis) if len(fichiers) <= 2 else \
        " ".join(c for c in vis if not c.startswith("/")) + f"  [{len(fichiers)} fichiers]"
    print("→", aff, flush=True)
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.stdout.strip():
        print(r.stdout.strip())
    if verifier and r.returncode != 0:
        print("--- message de l'outil ---")
        print(r.stderr.strip())
        print("--------------------------", flush=True)
        sys.exit(f"✗ Échec : {aff}")
    return r


def identite() -> str | None:
    """Identité « Developer ID Application », renvoyée sous forme d'EMPREINTE SHA-1
    (40 caractères hexadécimaux) : un nom avec accents (« Jérémy Beaufrère »)
    peut ne pas être reconnu par codesign selon la normalisation Unicode.
    Source : variable MAC_SIGNATURE (nom ou empreinte), sinon le trousseau."""
    voulu = os.environ.get("MAC_SIGNATURE", "")
    if re.fullmatch(r"[0-9A-Fa-f]{40}", voulu):
        return voulu
    r = subprocess.run(["security", "find-identity", "-v", "-p", "codesigning"], capture_output=True, text=True)
    for empreinte, nom in re.findall(r'([0-9A-F]{40}) "(Developer ID Application: [^"]+)"', r.stdout):
        if not voulu or unicodedata.normalize("NFC", voulu) == unicodedata.normalize("NFC", nom):
            print(f"  Certificat : {nom} [{empreinte[:8]}…]")
            return empreinte
    return voulu or None


def _est_macho(ch: str) -> bool:
    try:
        with open(ch, "rb") as f:
            return f.read(4) in MAGIQUES
    except OSError:
        return False


# ---------------------------------------------------------------------
# 2. Signature de l'application
# ---------------------------------------------------------------------
def signer_app(app: str, ident: str | None):
    """Signe tous les binaires (bibliothèques .so/.dylib, FFmpeg, Python…)
    puis le paquet .app. Sans identité : signature ad hoc."""
    if not ident:
        print("⚠ Aucun certificat « Developer ID Application » : signature ad hoc "
              "(les utilisateurs verront un avertissement au 1er lancement).")
        _cmd(["codesign", "--force", "--deep", "--sign", "-", app])
        return
    print(f"✍ Signature avec : {ident}")
    # Attributs étendus (Finder, provenance…) : refusés par codesign (« detritus not allowed »)
    _cmd(["xattr", "-cr", app], verifier=False)
    binaires, paquets = [], []
    for rac, dossiers, fichiers in os.walk(app):
        for d in dossiers:                               # paquets imbriqués (Python.framework…)
            if d.endswith((".framework", ".app", ".bundle")) and not os.path.islink(os.path.join(rac, d)):
                paquets.append(os.path.join(rac, d))
        for f in fichiers:
            ch = os.path.join(rac, f)
            if not os.path.islink(ch) and _est_macho(ch):
                binaires.append(ch)
    base = ["codesign", "--force", "--timestamp", "--options", "runtime",
            "--entitlements", DROITS, "--sign", ident]
    # 1) binaires, du plus profond au moins profond (un conteneur se signe après son contenu)
    binaires.sort(key=lambda c: c.count(os.sep), reverse=True)
    for i in range(0, len(binaires), 40):             # par lots (ligne de commande raisonnable)
        _cmd(base + binaires[i:i + 40])
    # 2) paquets imbriqués, puis 3) l'application elle-même
    for p in sorted(paquets, key=lambda c: c.count(os.sep), reverse=True):
        _cmd(base + [p])
    _cmd(base + [app])
    _cmd(["codesign", "--verify", "--strict", "--verbose=2", app])
    print(f"✓ {len(binaires)} binaires + l'application signés")


# ---------------------------------------------------------------------
# 3. Signature + notarisation + agrafage du .dmg
# ---------------------------------------------------------------------
def _identifiants_notarisation() -> tuple[list[str], str | None] | None:
    if os.environ.get("APPLE_ID") and os.environ.get("APPLE_TEAM_ID") and os.environ.get("APPLE_MDP_APP"):
        mdp = os.environ["APPLE_MDP_APP"]
        return ["--apple-id", os.environ["APPLE_ID"], "--team-id", os.environ["APPLE_TEAM_ID"],
                "--password", mdp], mdp
    profil = os.environ.get("NOTARY_PROFIL", "eclipse-studio")
    r = subprocess.run(["xcrun", "notarytool", "history", "--keychain-profile", profil],
                       capture_output=True, text=True)
    if r.returncode == 0:
        return ["--keychain-profile", profil], None
    return None


def notariser_dmg(dmg: str, ident: str | None):
    if not ident:
        return
    _cmd(["codesign", "--force", "--timestamp", "--sign", ident, dmg])
    ids = _identifiants_notarisation()
    if not ids:
        print("⚠ Notarisation non configurée : le .dmg est signé mais pas notarisé.\n"
              "  Une seule fois, dans le Terminal :\n"
              "  xcrun notarytool store-credentials eclipse-studio --apple-id VOTRE@MAIL "
              "--team-id VOTRE_TEAM_ID --password MOT-DE-PASSE-POUR-APP")
        return
    args, secret = ids
    print("⏳ Notarisation par Apple (souvent 2 à 15 minutes)…", flush=True)
    r = _cmd(["xcrun", "notarytool", "submit", dmg, "--wait", "--output-format", "json"] + args,
             secret=secret, verifier=False)
    try:
        res = json.loads(r.stdout)
    except ValueError:
        res = {}
    if res.get("status") != "Accepted":
        if res.get("id"):
            _cmd(["xcrun", "notarytool", "log", res["id"]] + args, secret=secret, verifier=False)
        print(r.stderr.strip())
        sys.exit(f"✗ Notarisation refusée ({res.get('status', 'erreur')}) — le journal Apple ci-dessus indique quel fichier pose problème")
    _cmd(["xcrun", "stapler", "staple", dmg])
    _cmd(["spctl", "--assess", "--type", "open", "--context", "context:primary-signature", "--verbose", dmg],
         verifier=False)
    print("✓ Notarisé et agrafé : aucun avertissement à l'ouverture")
