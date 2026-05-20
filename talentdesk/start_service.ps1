Set-Location "C:\jja\talentdesk"

Get-Content ".env" | ForEach-Object {
    $line = $_.Trim()
    if (-not $line -or $line.StartsWith('#')) { return }
    $parts = $line -split '=', 2
    if ($parts.Count -eq 2) {
        $key = $parts[0].Trim()
        $val = $parts[1].Trim().Trim('"').Trim("'")
        if ($key) { [System.Environment]::SetEnvironmentVariable($key, $val, 'Process') }
    }
}

& "C:\jja\talentdesk\.venv\Scripts\uvicorn.exe" main:app --host 0.0.0.0 --port 9014 >> "C:\jja\logs\talentdesk2.log" 2>&1
