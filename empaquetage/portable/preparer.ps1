# =====================================================================
#  Éclipse Studio PORTABLE — préparation du Python autonome (Windows)
#  Appelé par le lanceur au 1er démarrage. Tout est écrit DANS le dossier
#  du kit (runtime\<système>\) : rien n'est installé sur l'ordinateur.
# =====================================================================
param([Parameter(Mandatory = $true)][string]$Kit, [Parameter(Mandatory = $true)][string]$T)
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'          # téléchargement bien plus rapide
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$Kit = (Resolve-Path $Kit).Path
$RT = Join-Path $Kit "runtime\$T"
$PY = Join-Path $RT 'python\python.exe'
$secours = "https://github.com/astral-sh/python-build-standalone/releases/download/20241016/cpython-3.12.7%2B20241016-$T-install_only.tar.gz"

Write-Host ""
Write-Host "  Éclipse Studio portable — première préparation pour ce système ($T)"
Write-Host "  Téléchargement d'un Python autonome (~30 Mo) et des bibliothèques (~80 Mo)."
Write-Host "  Connexion Internet nécessaire UNE SEULE FOIS. Rien n'est installé sur"
Write-Host "  l'ordinateur : tout reste dans le dossier « runtime » du kit."
Write-Host ""
try {
    # ---- 1. Python autonome ----
    if (-not (Test-Path $PY)) {
        New-Item -ItemType Directory -Force -Path $RT | Out-Null
        $url = $null
        try {
            $rel = Invoke-RestMethod 'https://api.github.com/repos/astral-sh/python-build-standalone/releases/latest' -Headers @{ 'User-Agent' = 'EclipseStudio' } -TimeoutSec 30
            foreach ($v in 12, 13) {
                $a = $rel.assets | Where-Object { $_.name -match "^cpython-3\.$v\.\d+\+\d+-$([regex]::Escape($T))-install_only\.tar\.gz$" } | Select-Object -First 1
                if ($a) { $url = $a.browser_download_url; break }
            }
        } catch { }
        if (-not $url) { $url = $secours }
        Write-Host "-> $url"
        $tgz = Join-Path $RT 'python.tar.gz'
        Invoke-WebRequest $url -OutFile $tgz -UseBasicParsing
        tar -xzf $tgz -C $RT                        # tar.exe est inclus dans Windows 10/11
        if ($LASTEXITCODE -ne 0) { throw "Archive Python illisible" }
        Remove-Item $tgz -Force
    }
    & $PY -c "import sys; print('  Python', sys.version.split()[0], 'prêt')"
    if ($LASTEXITCODE -ne 0) { throw "Python autonome inutilisable" }

    # ---- 2. Bibliothèques ----
    $env:PIP_DISABLE_PIP_VERSION_CHECK = '1'
    & $PY -m pip install --no-warn-script-location -q numpy opencv-python-headless pillow imageio-ffmpeg tzdata
    if ($LASTEXITCODE -ne 0) { throw "Installation des bibliothèques impossible (connexion ?)" }
    & $PY -m pip install --no-warn-script-location -q rawpy
    if ($LASTEXITCODE -ne 0) { Write-Host "Attention : rawpy indisponible, les RAW seront lus via leur aperçu JPEG intégré." }

    # ---- 3. Auto-test puis marqueur « prêt » ----
    & $PY (Join-Path $Kit 'app\lanceur.py') --verifier
    if ($LASTEXITCODE -ne 0) { throw "L'auto-test a échoué" }
    Get-Date | Out-File (Join-Path $RT '.pret')
    Write-Host "OK - Préparation terminée. Les prochains lancements seront immédiats et hors-ligne."
    exit 0
} catch {
    Write-Host "ERREUR : $($_.Exception.Message)"
    exit 1
}
