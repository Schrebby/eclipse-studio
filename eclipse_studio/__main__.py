# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jérémy BEAUFRERE — JEREMiA (https://jerem-ia.fr)
# Éclipse Studio est un logiciel libre : vous pouvez le redistribuer et/ou le
# modifier selon les termes de la GNU GPL v3 ou ultérieure (voir LICENSE).
"""
Éclipse Studio — point d'entrée :  python -m eclipse_studio
  --port 8765          port local
  --sans-navigateur    ne pas ouvrir le navigateur automatiquement
  --projet DOSSIER     ouvrir directement un projet existant
"""
import argparse
import multiprocessing

from .serveur import demarrer


def main():
    ap = argparse.ArgumentParser(prog="eclipse_studio")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--sans-navigateur", action="store_true")
    ap.add_argument("--projet")
    a = ap.parse_args()
    demarrer(a.port, not a.sans_navigateur, a.projet)


if __name__ == "__main__":
    multiprocessing.freeze_support()   # nécessaire pour Windows / exécutables empaquetés
    main()
