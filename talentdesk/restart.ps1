$port = 9014
$p = (Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue).OwningProcess
if ($p) {
    Stop-Process -Id $p -Force -ErrorAction SilentlyContinue
    Write-Host "Killed PID $p"
    Start-Sleep 2
}
$logDir = "C:\jja\logs"
if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir | Out-Null }
$log = "$logDir\talentdesk.log"
$psCmd = "Set-Location 'C:\jja\talentdesk'; uv run uvicorn main:app --host 0.0.0.0 --port $port *>> '$log'"
$proc = Start-Process powershell.exe `
    -ArgumentList @("-NoProfile", "-NonInteractive", "-Command", $psCmd) `
    -WindowStyle Hidden `
    -PassThru
Write-Host "Started TalentDesk PID $($proc.Id) -> $log"
Start-Sleep 4
$check = (Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue)
if ($check) { Write-Host "Port $port LISTENING - OK" } else { Write-Host "Port $port not listening - check $log" }
