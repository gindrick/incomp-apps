<#
.SYNOPSIS
  Nasazení nové verze (kód i stránka). Data v databázi se nemění.
  Postup: logická záloha -> zastavení služby -> kopie -> závislosti -> start -> kontrola.
#>
[CmdletBinding()]
param(
  [string]$Root = "C:\apps\semafor",
  [string]$Source = (Resolve-Path "$PSScriptRoot\..\..").Path
)
$ErrorActionPreference = "Stop"
$env:SEMAFOR_ENV_FILE = "$Root\.env"
$stamp = Get-Date -Format "yyyy-MM-dd_HHmm"

Write-Host "== záloha dat před nasazením" -ForegroundColor Cyan
Push-Location "$Root\app\backend"
& "$Root\venv\Scripts\python.exe" -m semafor export "$Root\backup\pred-nasazenim-$stamp.json"
if ($LASTEXITCODE) { Pop-Location; throw "záloha selhala, nasazení zastaveno" }
Pop-Location

Write-Host "== záloha kódu" -ForegroundColor Cyan
Compress-Archive -Path "$Root\app\*" -DestinationPath "$Root\backup\app-$stamp.zip" -Force

& "$Root\service\semafor-service.exe" stop
if ($LASTEXITCODE) { throw "službu se nepodařilo zastavit" }
robocopy $Source "$Root\app" /MIR /XD .git node_modules __pycache__ .pytest_cache dist /XF *.db .env /NFL /NDL /NJH /NJS | Out-Null
if ($LASTEXITCODE -ge 8) { throw "robocopy selhal ($LASTEXITCODE)" }
& "$Root\venv\Scripts\python.exe" -m pip install -r "$Root\app\backend\requirements.txt" | Out-Null
if ($LASTEXITCODE) { throw "instalace závislostí selhala; služba zůstává zastavená, návrat ze zálohy app-$stamp.zip" }
& "$Root\service\semafor-service.exe" start
if ($LASTEXITCODE) { throw "službu se nepodařilo spustit, viz $Root\logs" }
Start-Sleep -Seconds 4
$r = Invoke-RestMethod "http://127.0.0.1:8710/readyz"
Write-Host "readyz: $($r.status), seq $($r.seq). Návrat: rozbal $Root\backup\app-$stamp.zip do $Root\app a restartuj službu." -ForegroundColor Green
