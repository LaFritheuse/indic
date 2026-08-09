# Installe la collecte crypto (5 scripts, voir run_collection.ps1) en
# tache planifiee Windows, toutes les 15 min. Utilise le lanceur `py`
# (pas `python`, ni un venv dedie) sur l'installation Python par
# defaut de la machine.
#
# A lancer depuis PowerShell EN TANT QU'ADMINISTRATEUR, depuis la
# racine du repo :
#   powershell -ExecutionPolicy Bypass -File data_collection\vps_deploy\register_task_windows.ps1

$ErrorActionPreference = "Stop"

# Register-ScheduledTask echoue avec un "Acces refuse" (HRESULT
# 0x80070005) si ce PowerShell n'est pas ouvert en tant
# qu'administrateur -- verifie et arrete tout de suite avec un message
# clair plutot que d'echouer au bout du script.
$IsAdmin = ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $IsAdmin) {
    Write-Host "ERREUR : ce script doit etre lance depuis un PowerShell ouvert EN TANT QU'ADMINISTRATEUR."
    Write-Host "  -> Fermer cette fenetre, clic droit sur PowerShell > 'Executer en tant qu'administrateur',"
    Write-Host "     puis relancer la commande depuis ce nouveau terminal (se replacer dans le dossier du repo)."
    exit 1
}

$RepoDir = (Resolve-Path "$PSScriptRoot\..\..").Path
Set-Location $RepoDir

Write-Host "1/3 - Installation des dependances (py -m pip)..."
py -m pip install --upgrade pip -q
py -m pip install -r data_collection\requirements.txt -q

$EnvFile = "data_collection\vps_deploy\.env"
if (-not (Test-Path $EnvFile)) {
    Copy-Item "data_collection\vps_deploy\.env.example" $EnvFile
    Write-Host ""
    Write-Host "2/3 - Fichier .env cree depuis le modele."
    Write-Host "  -> Edite data_collection\vps_deploy\.env avec tes vraies valeurs"
    Write-Host "     (SUPABASE_URL, SUPABASE_KEY, COINALIZE_API_KEY), puis relance ce script."
    exit 1
}
Write-Host "2/3 - Fichier .env deja present, OK."

Write-Host "3/3 - Creation de la tache planifiee (toutes les 15 min)..."
$RunScript = Join-Path $PSScriptRoot "run_collection.ps1"

$Action = New-ScheduledTaskAction -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$RunScript`"" `
    -WorkingDirectory $RepoDir
# [TimeSpan]::MaxValue casse la conversion XML du Planificateur de
# taches ("valeur incorrectement formatee ou hors limites") -- le
# format de duree accepte a une limite bien plus basse. 10 ans est une
# duree finie largement suffisante pour un "tourne indefiniment" en
# pratique.
$Trigger = New-ScheduledTaskTrigger -Once -At (Get-Date) `
    -RepetitionInterval (New-TimeSpan -Minutes 15) `
    -RepetitionDuration (New-TimeSpan -Days 3650)
$Settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -DontStopOnIdleEnd `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 10) `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -MultipleInstances IgnoreNew

# Compte utilisateur courant (PAS SYSTEM) : le git pull a besoin de tes
# identifiants git (credential manager / cle SSH), qui ne sont
# generalement pas accessibles au compte SYSTEM. -LogonType S4U evite
# de stocker un mot de passe -- fonctionne tant que ta session Windows
# a ete ouverte au moins une fois depuis le demarrage (suffisant pour
# un PC perso laisse allume avec une session ouverte). Si le git pull
# echoue silencieusement dans les logs avec S4U (droits/identifiants
# non trouves), remplacer par -LogonType Password (PowerShell demande
# alors le mot de passe une fois, a l'enregistrement).
$Principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType S4U -RunLevel Highest

Register-ScheduledTask -TaskName "CollectCryptoData" -Action $Action -Trigger $Trigger `
    -Settings $Settings -Principal $Principal -Force | Out-Null

Write-Host "Termine."
Write-Host ""
Write-Host "Verifier l'etat :      Get-ScheduledTask -TaskName CollectCryptoData"
Write-Host "Voir le dernier run :  Get-ScheduledTaskInfo -TaskName CollectCryptoData"
Write-Host "Lancer un cycle test : Start-ScheduledTask -TaskName CollectCryptoData"
Write-Host "Logs :                 Get-Content -Wait data_collection\vps_deploy\collect.log"
Write-Host "Desactiver :           Disable-ScheduledTask -TaskName CollectCryptoData"
Write-Host "Supprimer :            Unregister-ScheduledTask -TaskName CollectCryptoData -Confirm:`$false"
