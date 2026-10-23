<#
.SYNOPSIS
  Jednorázové nastavení IIS pro variantu A (reverse proxy přes ARR). Spouštět jako administrátor.
  Předpoklad: nainstalované URL Rewrite 2.1 a Application Request Routing 3.0.
#>
$ErrorActionPreference = "Stop"
$appcmd = "$env:windir\system32\inetsrv\appcmd.exe"
# zapnout proxy, bez bufferování odpovědí (Server-Sent Events) a s timeoutem delším než 10 min proudu
& $appcmd set config -section:system.webServer/proxy /enabled:"True" /responseBufferLimit:"0" /timeout:"00:11:00" /preserveHostHeader:"True" /reverseRewriteHostInResponseHeaders:"False" /commit:apphost
# povolit nastavování hlaviček X-Forwarded-* z pravidla
foreach ($v in "HTTP_X_FORWARDED_PROTO", "HTTP_X_FORWARDED_HOST") {
  & $appcmd set config -section:system.webServer/rewrite/allowedServerVariables /+"[name='$v']" /commit:apphost 2>$null
}
Write-Host "ARR nastaveno. Teď vytvoř IIS aplikaci /semafor a do její složky dej web.config z web.config.reverse-proxy.xml." -ForegroundColor Green
