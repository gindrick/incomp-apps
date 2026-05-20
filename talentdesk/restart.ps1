$p = (Get-NetTCPConnection -LocalPort 8014 -State Listen -ErrorAction SilentlyContinue).OwningProcess
if ($p) {
    Stop-Process -Id $p -Force -ErrorAction SilentlyContinue
    Write-Host "Killed PID $p"
    Start-Sleep 2
}
$logDir = "C:\jja\logs"
if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir | Out-Null }
$log = "$logDir\talentdesk.log"
$psCmd = "Set-Location 'C:\jja\talentdesk'; uv run uvicorn main:app --host 0.0.0.0 --port 8014 *>> '$log'"
$proc = Start-Process powershell.exe `
    -ArgumentList @("-NoProfile", "-NonInteractive", "-Command", $psCmd) `
    -WindowStyle Hidden `
    -PassThru
Write-Host "Started TalentDesk PID $($proc.Id) -> $log"
Start-Sleep 3
$check = (Get-NetTCPConnection -LocalPort 8014 -State Listen -ErrorAction SilentlyContinue)
if ($check) { Write-Host "Port 8014 LISTENING - OK" } else { Write-Host "Port 8014 not listening - check $log" }
