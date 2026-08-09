# Exécuté à chaque déclenchement de la tâche planifiée "CollectCryptoData"
# (toutes les 15 min, voir register_task_windows.ps1) : met à jour le
# dépôt (git pull) puis lance les 5 scripts de collecte avec `py` (le
# lanceur Python standard sur Windows -- pas `python`, absent du PATH
# sur cette machine).
#
# Chaque étape est indépendante : un git pull ou un script en échec
# n'empêche pas les suivants de tourner, même logique que le workflow
# GitHub Actions équivalent (.github/workflows/collect_data.yml).
#
# Peut aussi être lancé à la main pour tester un cycle complet :
#   powershell -ExecutionPolicy Bypass -File data_collection\vps_deploy\run_collection.ps1

$ErrorActionPreference = "Continue"

$RepoDir = (Resolve-Path "$PSScriptRoot\..\..").Path
Set-Location $RepoDir

$LogPath = Join-Path $PSScriptRoot "collect.log"

function Write-Log {
    param([string]$Message)
    "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') [run_collection] $Message" | Add-Content -Path $LogPath
}

Write-Log "=== Cycle demarre ==="

# git pull -- une tache planifiee n'a pas de terminal interactif pour
# resoudre un conflit ou ressaisir des identifiants : en cas d'echec on
# logge et on continue avec le code deja present localement, plutot que
# de bloquer tout le cycle de collecte pour un probleme de synchro git.
try {
    $pullOutput = git pull 2>&1 | Out-String
    Write-Log "git pull :`n$pullOutput"
} catch {
    Write-Log "ERREUR git pull (on continue avec le code actuel) : $_"
}

# Les 5 collecteurs, dans le meme ordre que collect_data.yml.
$Scripts = @(
    "data_collection\collect_funding_oi.py",
    "data_collection\collect_liquidations.py",
    "data_collection\collect_long_short_ratio.py",
    "data_collection\collect_ohlcv_indicators.py",
    "data_collection\collect_whale_trades.py"
)

foreach ($script in $Scripts) {
    Write-Log "-- Lancement de $script --"
    try {
        $output = & py $script 2>&1 | Out-String
        Write-Log $output
    } catch {
        Write-Log "ERREUR sur $script (on continue avec les scripts suivants) : $_"
    }
}

Write-Log "=== Cycle termine ==="
