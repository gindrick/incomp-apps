# Registruje Windows Scheduled Task pro JJA Monitor (watchdog)
# SPUSTIT JAKO ADMINISTRÁTOR
# Použití: cd c:\jja && .\04_scripts\register-monitor-task.ps1

$taskName   = "JJA-Monitor"
$scriptPath = "C:\jja\04_scripts\monitor.ps1"

Write-Host ""
Write-Host "Registruji Scheduled Task '$taskName'..." -ForegroundColor Cyan
Write-Host ""

$action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NonInteractive -NoProfile -WindowStyle Hidden -File `"$scriptPath`"" `
    -WorkingDirectory "C:\jja"

# Trigger: jednou za 2 minuty, indefinitely
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date) `
    -RepetitionInterval  (New-TimeSpan -Minutes 2) `
    -RepetitionDuration  (New-TimeSpan -Days 3650)

$settings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit  (New-TimeSpan -Minutes 3) `
    -MultipleInstances   IgnoreNew `
    -StartWhenAvailable  `
    -RunOnlyIfNetworkAvailable:$false

$currentUser = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
Write-Host "Uživatel pro task: $currentUser"

$principal = New-ScheduledTaskPrincipal `
    -UserId    $currentUser `
    -LogonType S4U `
    -RunLevel  Highest

try {
    Register-ScheduledTask `
        -TaskName    $taskName `
        -Action      $action `
        -Trigger     $trigger `
        -Settings    $settings `
        -Principal   $principal `
        -Description "JJA Watchdog — každé 2 min kontroluje zdraví služeb, restartuje padlé, notifikuje při selhání" `
        -Force | Out-Null

    Write-Host ""
    Write-Host "OK: '$taskName' zaregistrován." -ForegroundColor Green
    Write-Host "    Kontrola každé 2 minuty, bez nutnosti přihlášeného uživatele."
    Write-Host ""
    Write-Host "Další kroky:" -ForegroundColor Yellow
    Write-Host "  1. Vyplň SMTP + Teams webhook v: C:\jja\04_scripts\monitor-config.ps1"
    Write-Host "  2. Test:  schtasks /run /tn $taskName"
    Write-Host "  3. Logy:  C:\jja\logs\monitor.log"
    Write-Host ""
    Write-Host "Pro odstranění tasku:"
    Write-Host "  Unregister-ScheduledTask -TaskName '$taskName' -Confirm:`$false"
} catch {
    Write-Error "Chyba při registraci: $_"
    Write-Host ""
    Write-Host "Ujistěte se, že PowerShell běží jako Administrátor!" -ForegroundColor Red
}
