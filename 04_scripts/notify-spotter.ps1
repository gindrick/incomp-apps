param(
    [string]$RunId,
    [string]$PlatformSummary,
    [int]$TotalPosts,
    [string]$ReportUrl = ""
)

. "$PSScriptRoot\monitor-config.ps1"

if (-not $TeamsWebhookUrl) { exit 0 }

$title = "✓ Spotter — New Report Ready"
$facts = @(
    @{ name = "Run";             value = $RunId }
    @{ name = "Platforms";       value = $PlatformSummary }
    @{ name = "Posts collected"; value = "$TotalPosts" }
)

$card = @{
    "@type"    = "MessageCard"
    "@context" = "https://schema.org/extensions"
    themeColor = "22c55e"
    summary    = $title
    sections   = @(@{
        activityTitle    = $title
        activitySubtitle = (Get-Date -Format "yyyy-MM-dd HH:mm")
        facts            = $facts
    })
}

if ($ReportUrl) {
    $card["potentialAction"] = @(@{
        "@type"  = "OpenUri"
        name     = "View Report"
        targets  = @(@{ os = "default"; uri = $ReportUrl })
    })
}

$body = $card | ConvertTo-Json -Depth 6
try {
    Invoke-RestMethod -Uri $TeamsWebhookUrl -Method Post -Body $body -ContentType "application/json" -ErrorAction Stop
} catch {
    Write-Host "Teams notification failed: $_"
    exit 1
}
