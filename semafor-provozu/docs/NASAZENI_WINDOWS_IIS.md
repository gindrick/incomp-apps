# Nasazení na Windows Server

Doporučené uspořádání: aplikace běží jako Windows služba na `127.0.0.1:8710`, ven ji publikuje IIS
nebo vaše směrování aplikací přes HTTPS. Stejný postup použijte nejdřív pro TEST instanci
(vlastní databáze, `SEMAFOR_ENVIRONMENT=test`, vlastní registrace nebo redirect URI v Entra ID).

## 1. Předpoklady na serveru

| Co | Verze / poznámka |
|---|---|
| Windows Server | 2019 nebo 2022 |
| Python | 3.12 x64, instalace „pro všechny uživatele“ (spouštěč `py`) |
| Microsoft ODBC Driver for SQL Server | 18 |
| WinSW | 2.12.0 (`WinSW-x64.exe` přejmenovat na `semafor-service.exe`) |
| IIS (varianta A) | URL Rewrite 2.1 + Application Request Routing 3.0 |
| Síť | server → SQL Server (1433), server → `login.microsoftonline.com` (443), případně `graph.microsoft.com` |
| pip | přístup na pypi.org, nebo předem stažené balíčky (`pip download -r requirements.txt -d wheels`) |

## 2. Databáze (DBA)

1. Založit databázi `SemaforProvozu` (collation `Czech_100_CI_AS` nebo výchozí; data jsou NVARCHAR).
2. Servisní účet aplikace (ideálně gMSA `HRANIPEX\svc-semafor$`) jako uživatel databáze:
   * první spuštění zakládá tabulky sám (`db_ddladmin` jen dočasně), **nebo** DBA spustí `backend/sql/001_schema_mssql.sql`,
   * běžný provoz: `db_datareader` + `db_datawriter`.
3. Záloha databáze dle firemní politiky (aplikace navíc dělá noční logickou zálohu JSON).

## 3. Entra ID

Registrace aplikace a role: [ENTRA_ID.md](ENTRA_ID.md). Výstup: client ID, client secret, redirect URI.

## 4. Instalace aplikace

```powershell
# jako administrátor, ze složky rozbaleného balíku
mkdir C:\apps\semafor\service
copy WinSW-x64.exe C:\apps\semafor\service\semafor-service.exe
copy deploy\env.example C:\apps\semafor\.env      # vyplnit!
notepad C:\apps\semafor\.env
powershell -ExecutionPolicy Bypass -File deploy\windows\install.ps1
```

Skript zkopíruje aplikaci do `C:\apps\semafor\app`, vytvoří `C:\apps\semafor\venv`, nainstaluje závislosti,
založí schéma, zaregistruje službu `SemaforProvozu` a ověří `http://127.0.0.1:8710/readyz`.
Služba poběží pod účtem z `semafor-service.xml` (odkomentovat `serviceaccount` pro gMSA).

## 5. Publikace přes HTTPS

### Varianta A: IIS jako reverse proxy (doporučeno)

```powershell
powershell -ExecutionPolicy Bypass -File deploy\iis\iis-arr-setup.ps1
```

Pak v IIS vytvořit aplikaci `/semafor` (pool *No Managed Code*, fyzická složka např. `C:\inetpub\semafor`)
a do ní dát `deploy\iis\web.config.reverse-proxy.xml` přejmenovaný na `web.config`. HTTPS certifikát je na webu IIS.

### Varianta B: IIS spouští proces sám (HttpPlatformHandler)

Bez Windows služby; `deploy\iis\web.config.httpplatform.xml` jako `web.config`. Jednodušší, ale jen jeden proces
a restart při recyklaci poolu. Pro tuto variantu nainstalovat HttpPlatformHandler 1.2.

### Vaše vlastní směrování aplikací

Pokud aplikace půjde přes vaše firemní směrování, musí splňovat tohle:

| Požadavek | Proč |
|---|---|
| TLS končí na směrování, dál může jít HTTP na 127.0.0.1:8710 nebo na adresu serveru | aplikace naslouchá jen lokálně; při jiném serveru změnit `--host` a `--forwarded-allow-ips` |
| předává `X-Forwarded-Proto: https` a `X-Forwarded-Host` | správné adresy a bezpečné cookie |
| prefix `/semafor` může předat i odříznout | aplikace funguje v obou případech; v prohlížeči musí zůstat `SEMAFOR_PUBLIC_URL` |
| **nebufferuje** odpovědi `text/event-stream` (`/semafor/api/stream`) a nekomprimuje je | živé změny; jinak aplikace spadne na dotazování po 5 s (funkční, ale pomalejší) |
| timeout spojení alespoň 11 minut pro `/api/stream` | proud se sám ukončuje po 10 minutách |
| tělo požadavku až 21 MB | přílohy |
| `SEMAFOR_PUBLIC_URL` = přesně adresa, kterou vidí prohlížeč | redirect URI pro Entra ID, odkazy v mailech |

## 6. Kontrola po nasazení

1. `https://<adresa>/semafor/healthz` vrací `{"status":"ok"}` (bez přihlášení).
2. Otevřít `https://<adresa>/semafor/`: přesměruje na Microsoft přihlášení a zpět, vpravo nahoře jméno a role.
3. Indikátor „připojeno“ vlevo nahoře je zelený; ve dvou oknech (dva uživatelé) se změna propíše do sekundy.
4. Vývojářské nástroje prohlížeče: žádné chyby CSP v konzoli.
5. Automatické testy v prohlížeči (`tests/e2e`) běží jen proti vývojové instanci (`SEMAFOR_ENVIRONMENT=development`); na TEST a ostré se ověřuje ručně s firemními účty.

## 7. Naplánované úlohy

```powershell
# noční záloha JSON + úklid zámků
powershell -ExecutionPolicy Bypass -File deploy\windows\scheduled-tasks.ps1 -RunAs "HRANIPEX\svc-semafor$"
# a s notifikacemi (dokud SEMAFOR_NOTIFY_ENABLED=false, jen zapisují do logu)
powershell -ExecutionPolicy Bypass -File deploy\windows\scheduled-tasks.ps1 -RunAs "HRANIPEX\svc-semafor$" -WithNotifications
```

## 8. Nová verze

```powershell
powershell -ExecutionPolicy Bypass -File deploy\windows\update.ps1
```

Před nasazením udělá logickou zálohu dat a zip dosavadního kódu (návrat = rozbalit zip a restartovat službu).
Změna stránky: upravit `frontend/src/semafor-provozu.src.html`, spustit `python frontend/build.py`, nasadit.
