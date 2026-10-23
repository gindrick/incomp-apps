# Use WMI to spawn a truly detached process (survives parent exit)
 = 'powershell.exe -NoProfile -NonInteractive -Command "Set-Location C:\jja\talentdesk; .\.venv\Scripts\uvicorn.exe main:app --host 0.0.0.0 --port 9014 >> C:\jja\logs\talentdesk2.log 2>&1"'
 = [wmiclass]'win32_process'
 = .Create()
"Spawned PID: " + .ProcessId | Out-File C:\jja\logs\td_spawn.txt
