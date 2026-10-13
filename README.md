# ☀ Eclipse Studio

*🇫🇷 Version française : [LISEZMOI.md](LISEZMOI.md)*

Aligns, evens out, reconstructs and animates solar eclipse photo series.
Free, no subscription, 100 % offline. Windows, macOS and Linux.

> The user interface is currently in French. This document explains each step in English.

## What the app does

| Problem | Solution |
|---|---|
| The Sun is not at the same place from one frame to the next | Detection of the **solar limb only** (oriented Hough transform + sub-pixel ellipse fit). The Moon's edge is ignored, so the alignment no longer "jumps" when the Moon crosses to the other side. |
| The Moon covers almost the whole Sun | The solar radius is measured once for the whole series, so a short arc of limb is enough. During totality, the lunar disk is used as the reference. |
| Clouds | Limb profiles are validated one by one. A frame that is too hazy is re-registered by interpolating the trajectory, or recreated. |
| Sun flattened near the horizon | The flattening caused by atmospheric refraction is measured, smoothed over time and corrected. |
| Cropped suns (poor tracking) | The part outside the sensor is rebuilt from the **reference Sun** (a stack of every visible area, sunspots included), with the Moon placed at its computed position. |
| Exposure, colour and contrast vary (sunset, haze) | Per-frame normalisation of exposure, colour, contrast and **extinction gradient** (lower part of the Sun darker and redder), smoothed over time. |
| Start and end of the eclipse not photographed | The **Moon's trajectory** is computed from ephemerides (Meeus, topocentric) and fitted to your frames. Missing phases are recreated up to first and last contact, at the same rhythm as your real shooting. |
| Wrong camera clock | The offset is measured automatically from the Moon's position. |
| Field rotation (imperfect polar alignment, alt-az mount) | Measured from the Moon and compensated automatically. |
| Dust on the sensor (fixed dark rings) | Detected because dust stays fixed on the sensor while the Sun drifts (sunspots move with the Sun), then removed. |

### Lunar eclipses

The eclipse type is recognised automatically from the photo dates.
- **Alignment** on the Moon's limb, including during totality.
- **Measurement of the edge of Earth's umbra**, then fitting of its trajectory to the ephemerides (Danjon radii). The app derives contacts P1, U1, U2, U3, U4, P4, the magnitude, the clock offset and the field rotation.
- **True brightness** recovered from EXIF/FITS exposure data (totality is about 10,000 times darker). Three renderings: HDR (full Moon and red umbra both visible), real, compensated.
- **Reference Moon** rebuilt, and the **real colour of the umbra measured** on your photos. Phases that were not photographed and saturated areas are recreated.

### Observing site

- Map: OpenStreetMap background when online, offline landmark map otherwise.
- Place search: built-in cities, plus OpenStreetMap when online.
- GPS read from the photos.
- Time zone derived from the location.
- Visibility table: local times of the contacts and altitude of the Sun or Moon, with phases below the horizon flagged.

### Unusable series

A wide-angle landscape series, or a Sun photographed without a filter (overexposed blob, no crescent recorded), cannot be aligned on the disk. The app detects it and explains why instead of producing a wrong result.

**Colourisations:** natural, white light, Baader film, orange glass, H-alpha, Calcium K, NASA SDO/AIA false colours (171, 193, 211, 304, 131, 335, 94, 1600 Å), fire, ice, negative, or a custom colour.
**Adjustments:** black/white point, gamma, contrast, saturation, sharpening, limb flattening, rotation, mirroring, temporal smoothing.
**Exports:** MP4 video (H.264), GIF, 16-bit PNG/TIFF or JPEG sequences, phase sheet, strip, CSV measurements.
**Input formats:** JPEG, PNG, TIFF, FITS (mono, RGB, CFA/Bayer), RAW (CR2, CR3, NEF, ARW, RAF, ORF, RW2, DNG…).

## Installation (no Python needed)

Download the version for your system from the project's **Releases** page:

| System | File | First launch |
|---|---|---|
| **Windows** 10/11 | `EclipseStudio-…-Windows.zip` | Unzip, then double-click `EclipseStudio.exe`. If Windows shows "Windows protected your PC", click *More info*, then *Run anyway*. |
| **Mac** Apple Silicon (M1…M4) | `EclipseStudio-…-macOS-AppleSilicon.dmg` | Drag the app into *Applications*, then double-click it. The app is signed and notarised by Apple, so it opens without any warning. |
| **Mac** Intel | `EclipseStudio-…-macOS-Intel.dmg` | Same as Apple Silicon. |
| **Linux** | `EclipseStudio-…-Linux-x86_64.tar.gz` | `tar xzf …` then `./EclipseStudio/EclipseStudio` |

The Windows warning appears because the Windows version is not signed with a paid certificate. The source code is public.
The interface opens in your web browser and runs **100 % locally**. To close the app, use the **⏻ Quitter** (Quit) button.

### Portable version (one file for all 3 systems)

`EclipseStudio-…-portable.zip`: unzip it anywhere (internal drive, USB stick), then double-click the launcher for your system (`Eclipse Studio (Windows).bat`, `(Mac).command` or `(Linux).sh`).
On the **first launch only** (Internet connection required, 2 to 5 minutes), a standalone Python and the libraries are downloaded **into the kit's own folder** (`runtime/`). Nothing is installed on the computer.
After that, start-up is immediate and works offline. To uninstall, delete the folder. The same USB stick can be used on Windows, Mac and Linux: each system keeps its own `runtime` there.
On Mac, the kit's `.command` launcher cannot be notarised, so macOS asks for permission on first launch. Prefer the signed `.dmg`.

### From source (with Python)

You need **Python 3.9 or newer** (free: https://www.python.org/downloads/).

- **Mac**: double-click `Lancer Eclipse Studio (Mac).command`.
  If macOS refuses to open it: right-click the file, then **Open**.
- **Windows**: double-click `Lancer Eclipse Studio (Windows).bat`. When installing Python, tick "Add Python to PATH".
- **Linux**: `./lancer_linux.sh`

On first launch, the dependencies are installed into a private `.venv` folder (2 to 5 minutes, Internet needed only once).

### Building the installable versions yourself

- **Automatically**: on GitHub, every `vX.Y.Z` tag runs `.github/workflows/construire.yml`. It builds and tests the 4 versions and the portable kit, signs and notarises the Mac versions, then attaches everything to the Release.
- **Portable kit**: `python empaquetage/kit_portable.py` (no download needed to build it).
- **On your own machine**: double-click `empaquetage/Construire la version Mac.command` (or `… Windows.bat`), or run `python empaquetage/construire.py`.

## How to use it (5 steps)

The tab names below are given in French as they appear in the interface, with their English meaning.

1. **Images**: choose the photo folder. If it mixes RAW files and FITS files converted by Siril, choose which format to use. Click *Analyser et aligner* (Analyse and align).
2. **Alignement** (Alignment): check the result with the *Vue de contrôle* (Check view): red ellipse = detected limb, green dots = measured limb. The ← → arrow keys step through the frames, the space bar starts playback.
3. **Lune & couleurs** (Moon & colours): enter the site (latitude, longitude; West is negative) and, for JPEG or RAW photos, the offset of the camera clock from UTC (2 for French summer time). FITS files from Siril are already in UTC. Click *Calculer* (Compute).
4. **Rendu** (Rendering): palette, adjustments and overlays. The preview updates immediately.
5. **Exporter** (Export): video, GIF, image sequence, sheet…

An interrupted analysis resumes where it stopped. A project can be reopened without redoing the analysis.

## Command line (batch processing)

The command names are in French: `analyser` = analyse, `modeliser` = model, `exporter` = export.

```bash
python -m eclipse_studio.cli analyser  PHOTO_FOLDER PROJECT_FOLDER --ext .cr2
python -m eclipse_studio.cli modeliser PROJECT_FOLDER --lat 47.664 --lon -3.205 --utc 2
python -m eclipse_studio.cli exporter  PROJECT_FOLDER video --palette halpha --taille 1080
```

## Code layout

```
eclipse_studio/
  detection.py   solar disk detection (oriented Hough, profiles, robust ellipse)
  io_images.py   JPEG/PNG/TIFF/FITS/RAW reading + EXIF/FITS timestamps
  analyse.py     calibration, parallel detection, cache, Sun trajectory
  astro.py       Sun/Moon ephemerides, contacts, parallactic angle
  modele.py      Moon, reference Sun, photometric normalisation
  poussieres.py  sensor dust detection and removal
  rendu.py       rendering pipeline, timeline (real + recreated frames)
  palettes.py    colourisations
  export.py      MP4, GIF, sequences, sheets, CSV
  serveur.py     local server for the interface
  ui/index.html  interface
tests/           synthetic eclipse generator + accuracy evaluation
lanceur.py       entry point of the installable versions (+ --verifier self-test)
empaquetage/     builds without Python (PyInstaller), Apple signing, portable kit, icon
```

## Licence

Eclipse Studio is **free and open-source software**, released under the
**GNU GPL v3 or later** (full text: `LICENSE` file).

- You may use it freely, including for professional work.
- You may study, modify and redistribute it.
- Any modified version you redistribute must stay under the same licence,
  with its source code and credit to the original author.

The software comes **with no warranty** (sections 15 and 16 of the licence).

### Third-party components

Libraries installed separately, all compatible with the GPL v3:
NumPy (BSD), OpenCV (Apache 2.0), Pillow (HPND licence), imageio-ffmpeg (BSD; FFmpeg under LGPL/GPL),
rawpy (MIT; LibRaw under LGPL 2.1/CDDL), tzdata (Apache 2.0).
Map tiles © OpenStreetMap contributors (ODbL); place search: Nominatim (OpenStreetMap);
time zones: IANA tz database (public domain).

---

© 2026 Jérémy BEAUFRERE — [JEREMiA](https://jerem-ia.fr) · contact@jerem-ia.fr
