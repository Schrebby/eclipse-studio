# ☀ Éclipse Studio

*🇬🇧 English version: [README.md](README.md)*

Aligne, uniformise, reconstitue et anime des séries de photos d'éclipse solaire.
Gratuit, sans abonnement, 100 % hors-ligne. Windows, macOS et Linux.

## Ce que fait l'application

| Problème | Solution |
|---|---|
| Le Soleil n'est pas au même endroit d'une image à l'autre | Détection du **limbe solaire uniquement** (transformée de Hough orientée + ajustement d'ellipse au sous-pixel). Le bord de la Lune est ignoré : l'alignement ne « saute » plus quand la Lune passe de l'autre côté. |
| Lune qui couvre presque tout le Soleil | Le rayon solaire est mesuré une fois pour toute la série, donc un simple arc de limbe suffit. En totalité, le disque lunaire sert de repère. |
| Nuages | Les profils sont validés un par un. Une image trop voilée est recalée par interpolation de la trajectoire, ou recréée. |
| Soleil aplati près de l'horizon | L'aplatissement dû à la réfraction est mesuré, lissé dans le temps puis corrigé. |
| Soleils coupés (mauvais suivi) | La partie hors capteur est reconstituée à partir du **Soleil de référence** (empilement de toutes les zones visibles, taches solaires comprises), avec la Lune placée à sa position calculée. |
| Exposition, couleur et contraste qui varient (coucher de soleil, voiles) | Uniformisation par image : exposition, couleur, contraste et **gradient d'extinction** (bas du Soleil plus sombre et plus rouge), lissée dans le temps. |
| Début et fin de l'éclipse non photographiés | **Trajectoire de la Lune** calculée par éphémérides (Meeus, topocentrique) et calée sur vos images. Les phases manquantes sont recréées jusqu'au 1er et au dernier contact. |
| Horloge de l'appareil fausse | Le décalage est mesuré automatiquement grâce à la Lune. |
| Rotation de champ (mise en station imparfaite, monture altaz) | Mesurée grâce à la Lune et compensée automatiquement. |
| Poussières sur le capteur (anneaux sombres fixes) | Repérées parce qu'elles restent fixes sur le capteur pendant que le Soleil se déplace (les taches solaires, elles, suivent le Soleil), puis effacées. |

### Éclipses de Lune

Le type d'éclipse est reconnu automatiquement d'après la date des photos.
- **Alignement** sur le bord de la Lune, y compris en totalité.
- **Mesure du bord de l'ombre** de la Terre, puis calage de sa trajectoire sur les éphémérides (rayons de Danjon). L'app en déduit les contacts P1, U1, U2, U3, U4, P4, la magnitude, le décalage d'horloge et la rotation de champ.
- **Luminosité réelle** retrouvée grâce aux temps de pose EXIF/FITS (la totalité est environ 10 000 fois plus sombre). Trois rendus : HDR (pleine Lune et ombre rouge visibles), réel, compensé.
- **Lune de référence** reconstituée, et **couleur réelle de l'ombre mesurée** sur vos photos. Les phases non photographiées et les zones saturées sont recréées.

### Lieu d'observation

- Carte : fond OpenStreetMap si Internet est disponible, carte de repères hors-ligne sinon.
- Recherche de lieux : villes embarquées, plus OpenStreetMap si Internet est disponible.
- Lecture du GPS des photos.
- Fuseau horaire déduit du lieu.
- Tableau de visibilité : heures locales des contacts et hauteur de l'astre, avec les phases sous l'horizon signalées.

### Séries non exploitables

Une série de paysage au grand-angle, ou un Soleil photographié sans filtre (tache surexposée, croissant non enregistré), ne peut pas être alignée sur le disque. L'app le détecte et l'explique au lieu de produire un résultat faux.

**Colorisations :** naturelle, lumière blanche, film Baader, verre orangé, H-alpha, Calcium K, fausses couleurs NASA SDO/AIA (171, 193, 211, 304, 131, 335, 94, 1600 Å), feu, glace, négatif, ou une couleur personnalisée.
**Réglages :** point noir/blanc, gamma, contraste, saturation, accentuation, aplanissement du limbe, rotation, miroirs, lissage temporel.
**Exports :** vidéo MP4 (H.264), GIF, séquences PNG/TIFF 16 bits ou JPEG, planche des phases, frise, mesures CSV.
**Formats lus :** JPEG, PNG, TIFF, FITS (mono, RGB, CFA/Bayer), RAW (CR2, CR3, NEF, ARW, RAF, ORF, RW2, DNG…).

## Installation (sans Python)

Téléchargez la version de votre système dans la page **Releases** du projet :

| Système | Fichier | Premier lancement |
|---|---|---|
| **Windows** 10/11 | `EclipseStudio-…-Windows.zip` | Décompressez, puis double-cliquez sur `EclipseStudio.exe`. Si Windows affiche « Windows a protégé votre ordinateur », cliquez sur *Informations complémentaires*, puis *Exécuter quand même*. |
| **Mac** Apple Silicon (M1…M4) | `EclipseStudio-…-macOS-AppleSilicon.dmg` | Glissez l'app dans *Applications*, puis double-cliquez dessus. L'app est signée et notarisée par Apple : elle s'ouvre sans avertissement. |
| **Mac** Intel | `EclipseStudio-…-macOS-Intel.dmg` | Même procédure que pour Apple Silicon. |
| **Linux** | `EclipseStudio-…-Linux-x86_64.tar.gz` | `tar xzf …` puis `./EclipseStudio/EclipseStudio` |

L'avertissement de Windows apparaît parce que la version Windows n'est pas signée avec un certificat payant. Son code est public.
L'interface s'ouvre dans votre navigateur et fonctionne **100 % en local**. Pour fermer l'application : bouton **⏻ Quitter**.

### Version portable (un seul fichier pour les 3 systèmes)

`EclipseStudio-…-portable.zip` : décompressez-le n'importe où (disque, clé USB), puis double-cliquez sur le lanceur de votre système (`Eclipse Studio (Windows).bat`, `(Mac).command` ou `(Linux).sh`).
Au **premier lancement seulement** (connexion Internet nécessaire, 2 à 5 minutes), un Python autonome et les bibliothèques sont téléchargés **dans le dossier du kit** (`runtime/`). Rien n'est installé sur l'ordinateur.
Ensuite, le démarrage est immédiat et fonctionne hors-ligne. Pour désinstaller, supprimez le dossier. Une même clé USB peut servir sur Windows, Mac et Linux : chaque système y garde son propre `runtime`.
Sur Mac, le lanceur `.command` du kit n'est pas notarisable : macOS demande une autorisation au premier lancement. Préférez le `.dmg`, qui est signé.

### Depuis le code source (avec Python)

Il faut **Python 3.9 ou plus récent** (gratuit : https://www.python.org/downloads/).

- **Mac** : double-clic sur `Lancer Eclipse Studio (Mac).command`.
  Si macOS refuse de l'ouvrir : clic droit sur le fichier, puis **Ouvrir**.
- **Windows** : double-clic sur `Lancer Eclipse Studio (Windows).bat`. À l'installation de Python, cochez « Add Python to PATH ».
- **Linux** : `./lancer_linux.sh`

Au premier lancement, les dépendances s'installent dans un dossier privé `.venv` (2 à 5 minutes, connexion nécessaire une seule fois).

### Construire soi-même les versions installables

- **Automatiquement** : sur GitHub, chaque étiquette `vX.Y.Z` lance `.github/workflows/construire.yml`. Ce script construit et teste les 4 versions et le kit portable, signe et notarise les versions Mac, puis attache le tout à la Release.
- **Kit portable** : `python empaquetage/kit_portable.py` (aucun téléchargement nécessaire pour le fabriquer).
- **Sur sa machine** : double-clic sur `empaquetage/Construire la version Mac.command` (ou `… Windows.bat`), ou `python empaquetage/construire.py`.

## Utilisation (5 étapes)

1. **Images** : choisissez le dossier des photos. Si le dossier mélange des RAW et des FITS convertis par Siril, choisissez le format à utiliser. Cliquez sur *Analyser et aligner*.
2. **Alignement** : vérifiez le résultat avec la *Vue de contrôle* (ellipse rouge = limbe détecté, points verts = limbe mesuré). Les flèches ← → font défiler les images, la barre d'espace lance la lecture.
3. **Lune & couleurs** : indiquez le lieu (latitude, longitude ; l'Ouest est négatif) et, pour des photos JPEG ou RAW, le décalage de l'heure de l'appareil par rapport à UTC (2 en heure d'été française). Les FITS de Siril sont déjà en UTC. Cliquez sur *Calculer*.
4. **Rendu** : palette, réglages et incrustations. L'aperçu se met à jour immédiatement.
5. **Exporter** : vidéo, GIF, séquence, planche…

Une analyse interrompue reprend là où elle s'était arrêtée. Un projet se rouvre sans refaire l'analyse.

## Ligne de commande (traitement par lots)

```bash
python -m eclipse_studio.cli analyser  DOSSIER_PHOTOS DOSSIER_PROJET --ext .cr2
python -m eclipse_studio.cli modeliser DOSSIER_PROJET --lat 47.664 --lon -3.205 --utc 2
python -m eclipse_studio.cli exporter  DOSSIER_PROJET video --palette halpha --taille 1080
```

## Organisation du code

```
eclipse_studio/
  detection.py   détection du disque solaire (Hough orienté, profils, ellipse robuste)
  io_images.py   lecture JPEG/PNG/TIFF/FITS/RAW + horodatage EXIF/FITS
  analyse.py     étalonnage, détection parallèle, cache, trajectoire du Soleil
  astro.py       éphémérides Soleil/Lune, contacts, angle parallactique
  modele.py      Lune, Soleil de référence, uniformisation photométrique
  poussieres.py  détection et effacement des poussières du capteur
  rendu.py       chaîne de rendu, chronologie (images réelles + recréées)
  palettes.py    colorisations
  export.py      MP4, GIF, séquences, planches, CSV
  serveur.py     serveur local de l'interface
  ui/index.html  interface
tests/           générateur d'éclipse synthétique + évaluation de la précision
lanceur.py       point d'entrée des versions installables (+ auto-test --verifier)
empaquetage/     construction des versions sans Python (PyInstaller), signature Apple, kit portable, icône
```

## Licence

Éclipse Studio est un **logiciel libre et gratuit**, distribué sous licence
**GNU GPL v3 ou ultérieure** (texte complet : fichier `LICENSE`).

- Vous pouvez l'utiliser librement, y compris pour un usage professionnel.
- Vous pouvez l'étudier, le modifier et le redistribuer.
- Toute version modifiée et redistribuée doit rester sous la même licence,
  avec son code source et la mention de l'auteur d'origine.

Le logiciel est fourni **sans aucune garantie** (articles 15 et 16 de la licence).

### Composants tiers

Bibliothèques installées séparément, toutes compatibles avec la GPL v3 :
NumPy (BSD), OpenCV (Apache 2.0), Pillow (licence HPND), imageio-ffmpeg (BSD ; FFmpeg sous LGPL/GPL),
rawpy (MIT ; LibRaw sous LGPL 2.1/CDDL), tzdata (Apache 2.0).
Fond de carte © contributeurs OpenStreetMap (ODbL) ; recherche de lieux : Nominatim (OpenStreetMap) ;
fuseaux horaires : base IANA tz (domaine public).

---

© 2026 Jérémy BEAUFRERE — [JEREMiA](https://jerem-ia.fr) · contact@jerem-ia.fr
