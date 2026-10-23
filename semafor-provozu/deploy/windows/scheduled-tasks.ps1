<#
.SYNOPSIS
  Naplánované úlohy: noční logická záloha, úklid zámků a (vypnuté) notifikace.
  Notifikace se spouštějí vždy, ale dokud je v .env SEMAFOR_NOTIFY_ENABLED=false, jen zapisují do logu.
.PARAMETER RunAs
  Účet, pod kterým úlohy běží (stejný servisní účet jako služba, potřebuje přístup do SQL Serveru):
  "NT AUTHORITY\SYSTEM", gMSA ve tvaru "DOMENA\ucet$" (bez hesla), nebo běžný účet (skript se zeptá na heslo).
#>
[CmdletBinding()]
param(
  [string]$Root = "C:\apps\semafor",
  [string]$RunAs = "NT AUTHORITY\SYSTEM",
  [switch]$WithNotifications
)
$ErrorActionPreference = "Stop"
$py = "$Root\venv\Scripts\python.exe"
$wd = "$Root\app\backend"
$folder = "\SemaforProvozu\"

# úloha musí běžet i bez přihlášeného uživatele: principal podle typu účtu
$password = $null
if ($RunAs -match '^(NT AUTHORITY\\)?SYSTEM$') {
  $principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Limited
} elseif ($RunAs.EndsWith('$')) {
  $principal = New-ScheduledTaskPrincipal -UserId $RunAs -LogonType Password -RunLevel Limited   # gMSA
} else {
  $cred = Get-Credential -UserName $RunAs -Message "Heslo účtu pro naplánované úlohy Semafor"
  $password = $cred.GetNetworkCredential().Password
  $principal = $null
}

function New-SemaforTask([string]$Name, [string]$Arguments, $Trigger) {
  $cmd = "/c set SEMAFOR_ENV_FILE=$Root\.env&& `"$py`" -m semafor $Arguments >> `"$Root\logs\task-$Name.log`" 2>&1"
  $action = New-ScheduledTaskAction -Execute "cmd.exe" -Argument $cmd -WorkingDirectory $wd
  $settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Minutes 15) -StartWhenAvailable -MultipleInstances IgnoreNew
  if ($principal) {
    Register-ScheduledTask -TaskPath $folder -TaskName $Name -Action $action -Trigger $Trigger -Settings $settings `
      -Principal $principal -Force | Out-Null
  } else {
    Register-ScheduledTask -TaskPath $folder -TaskName $Name -Action $action -Trigger $Trigger -Settings $settings `
      -User $RunAs -Password $password -RunLevel Limited -Force | Out-Null
  }
  Write-Host "úloha $folder$Name" -ForegroundColor Green
}

$days = "Monday", "Tuesday", "Wednesday", "Thursday", "Friday"
# noční logická záloha JSON, ponechá posledních 30 (dlouhodobou historii drží záloha databáze)
New-SemaforTask "zaloha-json" "export $Root\backup\denni --keep 30" (New-ScheduledTaskTrigger -Daily -At 23:30)
New-SemaforTask "uklid-zamku" "purge-leases" (New-ScheduledTaskTrigger -Daily -At 23:45)

if ($WithNotifications) {
  # přiřazení úkolů: každou hodinu 7:00 až 18:00 v pracovní dny
  $t = New-ScheduledTaskTrigger -Weekly -DaysOfWeek $days -At 07:00
  $t.Repetition = (New-ScheduledTaskTrigger -Once -At 07:00 -RepetitionInterval (New-TimeSpan -Hours 1) -RepetitionDuration (New-TimeSpan -Hours 11)).Repetition
  New-SemaforTask "notifikace-prirazeni" "notify assigned" $t
  New-SemaforTask "notifikace-terminy" "notify due" (New-ScheduledTaskTrigger -Weekly -DaysOfWeek $days -At 06:55)
  New-SemaforTask "notifikace-souhrn" "notify daily" (New-ScheduledTaskTrigger -Weekly -DaysOfWeek $days -At 07:10)
}
