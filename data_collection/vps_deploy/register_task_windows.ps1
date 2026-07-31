# Installe la collecte funding/OI en tâche planifiée Windows (toutes les
# 15 min, tourne que l'utilisateur soit connecté ou non -- compte SYSTEM).
# A lancer depuis PowerShell EN TANT QU'ADMINISTRATEUR, depuis la racine
# du repo :
#   powershell -ExecutionPolicy Bypass -File data_collection\vps_deploy\register_task_windows.ps1

$ErrorActionPreference = "Stop"

$RepoDir = (Resolve-Path "$PSScriptRoot\..\..").Path
Set-Location $RepoDir

Write-Host "1/4 - Environnement virtuel Python..."
python -m venv data_collection\vps_deploy\venv
& data_collection\vps_deploy\venv\Scripts\pip.exe install --upgrade pip -q
& data_collection\vps_deploy\venv\Scripts\pip.exe install -r data_collection\requirements.txt -q

$EnvFile = "data_collection\vps_deploy\.env"
if (-not (Test-Path $EnvFile)) {
    Copy-Item "data_collection\vps_deploy\.env.example" $EnvFile
    Write-Host ""
    Write-Host "2/4 - Fichier .env cree depuis le modele."
    Write-Host "  -> Edite data_collection\vps_deploy\.env avec tes vraies valeurs"
    Write-Host "     SUPABASE_URL / SUPABASE_KEY, puis relance ce script."
    exit 1
}
Write-Host "2/4 - Fichier .env deja present, OK."

Write-Host "3/4 - Creation de la tache planifiee (toutes les 15 min, compte SYSTEM)..."
$PythonExe = Join-Path $RepoDir "data_collection\vps_deploy\venv\Scripts\python.exe"
$ScriptPath = Join-Path $RepoDir "data_collection\collect_funding_oi.py"
$LogPath = Join-Path $RepoDir "data_collection\vps_deploy\collect.log"

# Passe par cmd.exe pour rediriger stdout/stderr vers un fichier de log --
# une tache planifiee n'a pas de console, donc les print()/logging du
# script seraient sinon perdus.
$CmdArgument = "/c `"`"$PythonExe`" `"$ScriptPath`" >> `"$LogPath`" 2>&1`""

$Action = New-ScheduledTaskAction -Execute "cmd.exe" -Argument $CmdArgument -WorkingDirectory $RepoDir
$Trigger = New-ScheduledTaskTrigger -Once -At (Get-Date) `
    -RepetitionInterval (New-TimeSpan -Minutes 15) `
    -RepetitionDuration ([TimeSpan]::MaxValue)
$Settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -DontStopOnIdleEnd `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 5) `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -MultipleInstances IgnoreNew
$Principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest

Register-ScheduledTask -TaskName "CollectFundingOI" -Action $Action -Trigger $Trigger `
    -Settings $Settings -Principal $Principal -Force | Out-Null

Write-Host "4/4 - Termine."
Write-Host ""
Write-Host "Verifier l'etat :      Get-ScheduledTask -TaskName CollectFundingOI"
Write-Host "Voir le dernier run :  Get-ScheduledTaskInfo -TaskName CollectFundingOI"
Write-Host "Lancer maintenant :    Start-ScheduledTask -TaskName CollectFundingOI"
Write-Host "Logs :                 Get-Content -Wait $LogPath"
Write-Host "Desactiver :           Disable-ScheduledTask -TaskName CollectFundingOI"
Write-Host "Supprimer :            Unregister-ScheduledTask -TaskName CollectFundingOI -Confirm:`$false"
