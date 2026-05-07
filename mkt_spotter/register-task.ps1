# Registers two Windows Scheduled Tasks for Spotter:
#   1. "JJA\Spotter-Scraper" — runs main.py every Monday at 08:00
#   2. "JJA\Spotter-Web"    — starts the Flask web UI at system boot (with 60s delay)
#
# Run once as Administrator: cd C:\jja\mkt_spotter && .\register-task.ps1

$root   = "C:\jja\mkt_spotter"
$uvExe  = "C:\Users\reporting\AppData\Roaming\Python\Python312\Scripts\uv.exe"
$folder = "JJA"

# Ensure task folder exists
try {
    $svc = New-Object -ComObject Schedule.Service
    $svc.Connect()
    $rootFolder = $svc.GetFolder("\")
    try { $rootFolder.GetFolder($folder) | Out-Null }
    catch { $rootFolder.CreateFolder($folder) | Out-Null }
} catch {
    Write-Warning "Could not create task folder — continuing anyway"
}

# --- Task 1: Weekly scraper ---
$scrapeAction  = New-ScheduledTaskAction -Execute $uvExe -Argument "run python main.py" -WorkingDirectory $root
$scrapeTrigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday -At "08:00AM"
$settings      = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Hours 2) -StartWhenAvailable

Register-ScheduledTask `
    -TaskName "$folder\Spotter-Scraper" `
    -Action $scrapeAction `
    -Trigger $scrapeTrigger `
    -Settings $settings `
    -Description "Spotter: weekly competitor social media scrape" `
    -RunLevel Highest `
    -Force | Out-Null

Write-Host "[OK] Registered: $folder\Spotter-Scraper (every Monday 08:00)"

# --- Task 2: Web UI at boot ---
$webAction  = New-ScheduledTaskAction -Execute $uvExe -Argument "run python web/app.py" -WorkingDirectory $root
$webTrigger = New-ScheduledTaskTrigger -AtStartup
$webSettings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Days 365)

# Add 60-second delay after boot
$webTrigger.Delay = "PT60S"

Register-ScheduledTask `
    -TaskName "$folder\Spotter-Web" `
    -Action $webAction `
    -Trigger $webTrigger `
    -Settings $webSettings `
    -Description "Spotter: Flask web UI (starts at boot)" `
    -RunLevel Highest `
    -Force | Out-Null

Write-Host "[OK] Registered: $folder\Spotter-Web (at startup, 60s delay)"
Write-Host ""
Write-Host "Run scraper now: Start-ScheduledTask -TaskName '$folder\Spotter-Scraper'"
