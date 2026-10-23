$port   = 8015
$root   = "C:\jja\feeder"
$logDir = "C:\jja\logs"

# Kill existing process on port
$p = (Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue).OwningProcess
if ($p) {
    $children = Get-CimInstance Win32_Process -Filter "ParentProcessId = $p" -ErrorAction SilentlyContinue
    foreach ($c in $children) { Stop-Process -Id $c.ProcessId -Force -ErrorAction SilentlyContinue }
    Stop-Process -Id $p -Force -ErrorAction SilentlyContinue
    Write-Host "Killed PID $p"
    Start-Sleep 2
}

if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir | Out-Null }
$log   = "$logDir\feeder.log"
$psCmd = "Set-Location '$root'; uv run python -m uvicorn main:app --host 0.0.0.0 --port $port *>> '$log'"
$proc  = Start-Process powershell.exe `
    -ArgumentList @("-NoProfile", "-NonInteractive", "-Command", $psCmd) `
    -WindowStyle Hidden `
    -PassThru
Write-Host "Started Feeder PID $($proc.Id) -> $log"

Start-Sleep 4
$check = (Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue)
if ($check) { Write-Host "Port $port LISTENING - OK" } else { Write-Host "Port $port NOT listening - check $log" }
