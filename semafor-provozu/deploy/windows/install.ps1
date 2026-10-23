<#
.SYNOPSIS
  První instalace Semafor Provozu na Windows Server (spouštět jako administrátor).
.DESCRIPTION
  1. vytvoří adresářovou strukturu C:\apps\semafor
  2. zkopíruje aplikaci, vytvoří virtuální prostředí Pythonu a nainstaluje závislosti
  3. založí schéma v databázi (pokud má účet právo; jinak DBA spustí backend\sql\001_schema_mssql.sql)
  4. zaregistruje Windows službu (WinSW) a spustí ji
  Předpoklady: Python 3.12 x64 (pro všechny uživatele), Microsoft ODBC Driver 18 for SQL Server,
  vyplněný C:\apps\semafor\.env (vzor deploy\env.example), WinSW-x64.exe stažený jako semafor-service.exe.
#>
[CmdletBinding()]
param(
  [string]$Root = "C:\apps\semafor",
  [string]$Python = "py -3.12",
  [string]$Source = (Resolve-Path "$PSScriptRoot\..\..").Path,
  # účet služby (stejný jako v semafor-service.xml), dostane právo číst .env a zapisovat logy
  [string]$ServiceAccount = "NT AUTHORITY\SYSTEM"
)
$ErrorActionPreference = "Stop"

Write-Host "== adresáře" -ForegroundColor Cyan
New-Item -ItemType Directory -Force -Path "$Root\app", "$Root\logs", "$Root\backup", "$Root\service" | Out-Null

Write-Host "== kopie aplikace z $Source" -ForegroundColor Cyan
robocopy $Source "$Root\app" /MIR /XD .git node_modules __pycache__ .pytest_cache dist /XF *.db .env /NFL /NDL /NJH /NJS | Out-Null
if ($LASTEXITCODE -ge 8) { throw "robocopy selhal ($LASTEXITCODE)" }

if (-not (Test-Path "$Root\.env")) {
  Copy-Item "$Root\app\deploy\env.example" "$Root\.env"
  throw "Vyplň $Root\.env (vzor zkopírován) a spusť skript znovu."
}

Write-Host "== virtuální prostředí" -ForegroundColor Cyan
if (-not (Test-Path "$Root\venv\Scripts\python.exe")) { Invoke-Expression "$Python -m venv `"$Root\venv`"" }
& "$Root\venv\Scripts\python.exe" -m pip install --upgrade pip | Out-Null
& "$Root\venv\Scripts\python.exe" -m pip install -r "$Root\app\backend\requirements.txt"
if ($LASTEXITCODE) { throw "instalace závislostí selhala" }

Write-Host "== schéma databáze" -ForegroundColor Cyan
$env:SEMAFOR_ENV_FILE = "$Root\.env"
Push-Location "$Root\app\backend"
& "$Root\venv\Scripts\python.exe" -m semafor db-init
$dbInit = $LASTEXITCODE
Pop-Location
if ($dbInit) { Write-Warning "db-init selhal: ověř připojení k SQL Serveru, případně ať DBA spustí backend\sql\001_schema_mssql.sql" }

Write-Host "== Windows služba" -ForegroundColor Cyan
Copy-Item "$Root\app\deploy\windows\semafor-service.xml" "$Root\service\semafor-service.xml" -Force
if (-not (Test-Path "$Root\service\semafor-service.exe")) { throw "Chybí $Root\service\semafor-service.exe (WinSW-x64.exe 2.12.0)" }
& "$Root\service\semafor-service.exe" status | Out-Null
if ($LASTEXITCODE -ne 0 -or -not (Get-Service SemaforProvozu -ErrorAction SilentlyContinue)) { & "$Root\service\semafor-service.exe" install }
# práva: .env jen pro administrátory, SYSTEM a servisní účet; logy a zálohy zapisuje servisní účet
icacls "$Root\.env" /inheritance:r /grant:r "Administrators:F" "SYSTEM:R" "${ServiceAccount}:R" | Out-Null
icacls "$Root\logs" /grant "${ServiceAccount}:(OI)(CI)M" | Out-Null
icacls "$Root\backup" /grant "${ServiceAccount}:(OI)(CI)M" | Out-Null
& "$Root\service\semafor-service.exe" restart

Start-Sleep -Seconds 4
try { $r = Invoke-RestMethod "http://127.0.0.1:8710/readyz"; Write-Host "readyz: $($r.status), seq $($r.seq)" -ForegroundColor Green }
catch { Write-Warning "Služba neodpovídá na http://127.0.0.1:8710/readyz, viz $Root\logs" }
