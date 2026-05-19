#Requires -Version 5.1
# JJA Watchdog – spouštěn jako Scheduled Task každé 2 minuty
# Logika: kontrola → pokus o restart → notifikace jen při selhání restartu

$ErrorActionPreference = "Continue"

$root      = "C:\jja"
$logFile   = "$root\logs\monitor.log"
$stateFile = "$root\logs\monitor-state.json"

. "$PSScriptRoot\monitor-config.ps1"

# PATH: stejné jako start-all.ps1
$uvPath = "C:\Users\reporting\AppData\Roaming\Python\Python312\Scripts"
$node20 = "C:\tools\node20"
if (Test-Path $uvPath) { $env:PATH = "$uvPath;$env:PATH" }
if (Test-Path $node20) { $env:PATH = "$node20;$env:PATH" }

# ── Definice služeb ──────────────────────────────────────────────────────────

$services = @(
    @{
        Name      = "03-router"
        Port      = 8000
        HealthUrl = $null
        WorkDir   = "$root\03_router"
        Command   = "uv run python -m uvicorn main:app --host 0.0.0.0 --port 8000"
    }
    @{
        Name      = "02-litellm"
        Port      = 4000
        HealthUrl = $null
        WorkDir   = "$root\02_litellm"
        Command   = "uv run litellm --config litellm_config.yaml --port 4000"
    }
    @{
        Name      = "hr-hiring-backend"
        Port      = 8010
        HealthUrl = "http://127.0.0.1:8010/health"
        WorkDir   = "$root\hr_hiring\2_backend"
        Command   = "& '$root\hr_hiring\2_backend\.venv\Scripts\python.exe' -m uvicorn app.main:app --host 0.0.0.0 --port 8010"
    }
    @{
        Name      = "hr-hiring-frontend"
        Port      = 5173
        HealthUrl = $null
        WorkDir   = "$root\hr_hiring\3_frontend"
        Command   = "& 'C:\tools\node20\node.exe' .\node_modules\vite\bin\vite.js --host 0.0.0.0 --port 5173"
    }
    @{
        Name      = "production-cards-backend"
        Port      = 8011
        HealthUrl = "http://127.0.0.1:8011/health"
        WorkDir   = "$root\production_cards\2_backend"
        Command   = "& '$root\production_cards\2_backend\.venv\Scripts\python.exe' -m uvicorn app.main:app --host 0.0.0.0 --port 8011"
    }
    @{
        Name      = "production-cards-frontend"
        Port      = 5174
        HealthUrl = $null
        WorkDir   = "$root\production_cards\3_frontend"
        Command   = "& 'C:\tools\node20\node.exe' .\node_modules\vite\bin\vite.js --host 0.0.0.0 --port 5174"
    }
    @{
        Name      = "production-cards-2-backend"
        Port      = 8012
        HealthUrl = "http://127.0.0.1:8012/health"
        WorkDir   = "$root\production_cards_2\2_backend"
        Command   = "& '$root\production_cards_2\2_backend\.venv\Scripts\python.exe' -m uvicorn app.main:app --host 0.0.0.0 --port 8012"
    }
    @{
        Name      = "production-cards-2-frontend"
        Port      = 5175
        HealthUrl = $null
        WorkDir   = "$root\production_cards_2\3_frontend"
        Command   = "& 'C:\tools\node20\node.exe' .\node_modules\vite\bin\vite.js --host 0.0.0.0 --port 5175"
    }
)

# ── Pomocné funkce ───────────────────────────────────────────────────────────

function Write-Log {
    param([string]$Msg, [string]$Level = "INFO")
    $line = "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') [$Level] $Msg"
    Add-Content -Path $logFile -Value $line -Encoding UTF8
    Write-Host $line
}

function Test-ServiceUp {
    param([hashtable]$Svc)
    if ($Svc.HealthUrl) {
        try {
            $r = Invoke-WebRequest -Uri $Svc.HealthUrl -TimeoutSec 5 -UseBasicParsing -ErrorAction Stop
            return $r.StatusCode -lt 400
        } catch { return $false }
    }
    try {
        $tcp = New-Object System.Net.Sockets.TcpClient
        $conn = $tcp.BeginConnect("127.0.0.1", $Svc.Port, $null, $null)
        $ok = $conn.AsyncWaitHandle.WaitOne(2000, $false)
        $tcp.Close()
        return $ok
    } catch { return $false }
}

function Stop-Port {
    param([int]$Port)
    $lines = netstat -ano | Select-String ":$Port\s"
    foreach ($line in $lines) {
        $pidVal = ($line.ToString() -replace '.*\s+(\d+)\s*$', '$1').Trim()
        $pidInt = [int]$pidVal
        if ($pidInt -gt 4) {
            $children = Get-CimInstance Win32_Process -Filter "ParentProcessId = $pidInt" -ErrorAction SilentlyContinue
            foreach ($c in $children) { Stop-Process -Id $c.ProcessId -Force -ErrorAction SilentlyContinue }
            Stop-Process -Id $pidInt -Force -ErrorAction SilentlyContinue
        }
    }
}

function Start-Svc {
    param([hashtable]$Svc)
    $svcLog = "$root\logs\$($Svc.Name).log"
    $psCmd  = "Set-Location '$($Svc.WorkDir)'; $($Svc.Command) *>> '$svcLog'"
    Start-Process powershell.exe -ArgumentList @("-NoProfile", "-NonInteractive", "-Command", $psCmd) -WindowStyle Hidden
}

function Load-State {
    if (-not (Test-Path $stateFile)) { return @{} }
    try {
        $obj = Get-Content $stateFile -Raw -Encoding UTF8 | ConvertFrom-Json
        $d = @{}
        $obj.PSObject.Properties | ForEach-Object { $d[$_.Name] = $_.Value }
        return $d
    } catch { return @{} }
}

function Save-State { param([hashtable]$s); $s | ConvertTo-Json | Set-Content $stateFile -Encoding UTF8 }

function In-Cooldown {
    param([string]$Key, [hashtable]$State)
    if (-not $State.ContainsKey($Key)) { return $false }
    return ((Get-Date) - [datetime]::Parse($State[$Key])).TotalMinutes -lt $AlertCooldownMinutes
}

function Send-Alert {
    param([string]$Name, [string]$Msg)
    if (-not $TeamsWebhookUrl) {
        Write-Log "Teams webhook není nakonfigurován — alert přeskočen" "WARNING"
        return
    }
    $title = "🚨 JJA: $Name nefunguje"
    $text  = "**Server:** $env:COMPUTERNAME  **Čas:** $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')<br>$Msg"
    $card  = @{
        "@type"    = "MessageCard"
        "@context" = "https://schema.org/extensions"
        themeColor = "FF0000"
        summary    = $title
        sections   = @(@{ activityTitle = $title; activityText = $text })
    } | ConvertTo-Json -Depth 5
    try {
        Invoke-RestMethod -Uri $TeamsWebhookUrl -Method Post -Body $card -ContentType "application/json" -ErrorAction Stop
        Write-Log "Teams alert odeslán: $Name"
    } catch {
        Write-Log "Teams alert selhal: $_" "ERROR"
    }
}

# ── Hlavní smyčka ────────────────────────────────────────────────────────────

if (-not (Test-Path "$root\logs")) { New-Item -ItemType Directory -Path "$root\logs" | Out-Null }

Write-Log "--- monitor start ---"
$state = Load-State

foreach ($svc in $services) {
    if (Test-ServiceUp -Svc $svc) { continue }

    Write-Log "$($svc.Name) (port $($svc.Port)) neodpovídá — restartuji" "WARNING"
    Stop-Port -Port $svc.Port
    Start-Sleep -Seconds 2
    Start-Svc -Svc $svc
    Start-Sleep -Seconds $RestartWaitSec

    if (Test-ServiceUp -Svc $svc) {
        Write-Log "$($svc.Name) úspěšně restartován" "INFO"
        $state.Remove("ALERT_$($svc.Name)")
    } else {
        Write-Log "$($svc.Name) RESTART SELHAL" "ERROR"
        $alertKey = "ALERT_$($svc.Name)"
        if (-not (In-Cooldown -Key $alertKey -State $state)) {
            Send-Alert -Name $svc.Name -Message "Služba $($svc.Name) (port $($svc.Port)) nereaguje ani po restartu. Nutný ruční zásah."
            $state[$alertKey] = (Get-Date).ToString("o")
        } else {
            Write-Log "$($svc.Name) — cooldown, alert nevysílám"
        }
    }
}

Save-State -State $state
Write-Log "--- monitor end ---"
