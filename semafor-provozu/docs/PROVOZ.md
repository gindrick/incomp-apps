# Provoz

## Služba a logy

| Co | Kde |
|---|---|
| služba | `SemaforProvozu` (services.msc), `C:\apps\semafor\service\semafor-service.exe start / stop / restart` |
| konfigurace | `C:\apps\semafor\.env` (změna = restart služby) |
| logy aplikace | `C:\apps\semafor\logs\semafor.log` (denní rotace, 30 dní) a výstup služby `semafor-service.out.log` |
| logy úloh | `C:\apps\semafor\logs\task-*.log` |
| stav | `GET /semafor/healthz` (proces), `GET /semafor/readyz` (proces + databáze, vrací `seq`) |
| audit zápisů | tabulka `sp_audit_log` (kdo, kdy, operace, cesta, verze) |

Monitoring: hlídat `readyz` (HTTP 200) a velikost databáze. Přihlášení a odmítnutí jsou v logu (`přihlášení … role=…`).

## Zálohy

1. **Záloha databáze** (DBA): plná denně, log dle politiky. Pokrývá vše včetně příloh a soukromých To Do.
2. **Logická záloha JSON** (úloha `zaloha-json`, 23:30): `C:\apps\semafor\backup\denni\semafor-backup-<datum>.json`,
   posledních 30. Čitelná, porovnatelná, přenositelná; bez soukromých To Do a bez příloh.
3. Před každým nasazením nové verze dělá `update.ps1` zálohu JSON automaticky.

Ruční záloha: `python -m semafor export D:\zaloha.json`. Obnova: [MIGRACE_DAT.md](MIGRACE_DAT.md), kapitola Obnova.

## Správa uživatelů

Přístup a role výhradně v Entra ID (Enterprise application → Users and groups). Odebrání role platí
nejpozději po vypršení relace (10 h), okamžitě po restartu služby se změněným `SEMAFOR_SESSION_SECRET`.

## Zapnutí notifikací

1. Rozhodnout odesílání: SMTP relay (`SEMAFOR_SMTP_*`) nebo Graph se sdílenou schránkou ([ENTRA_ID.md](ENTRA_ID.md) kap. 5).
2. Úlohy zaregistrovat s `-WithNotifications` (bez zapnutí jen píšou, co by poslaly, do `task-notifikace-*.log`).
3. Několik dní číst logy, porovnat s pohledem Upomínky v aplikaci.
4. `.env`: `SEMAFOR_NOTIFY_ENABLED=true`, `SEMAFOR_NOTIFY_TRANSPORT=smtp|graph`, restart není nutný (úlohy čtou `.env` při každém běhu).

Pravidla: přiřazení každou hodinu 7 až 18 v pracovní dny; termíny (po termínu, dnes, do 2 pracovních dnů) jeden mail
na osobu denně; denní souhrn pro `SEMAFOR_NOTIFY_DAILY_SUMMARY_TO`; kopie mailů s položkami po termínu na
`SEMAFOR_NOTIFY_COPY_OVERDUE_TO`; nejvýše 25 mailů na běh. Stav v dokumentu `notify/state`.

## Úpravy aplikace

1. Upravit `frontend/src/semafor-provozu.src.html` (stejně jako dosud podle `claude/jak-upravovat-aplikaci.md`).
2. `python frontend/build.py`, lokálně vyzkoušet (`SEMAFOR_AUTH_MODE=dev`), `pytest`, `node tests/e2e/smoke.cjs`.
3. Nasadit na TEST, pak na ostrou (`deploy\windows\update.ps1`).

Dosavadní testy aplikace `test_t*.cjs` (v Claude projektu) běží proti offline sestavení:
`python frontend/build.py --offline --seed zaloha.json` → `frontend/dist/semafor-offline.html` jako `index.html`
na `http://localhost:8765/` (stejně jako dřív s `testshim.js`).

## Kapacita

Jeden worker zvládne desítky současných uživatelů (dokumentů je stovky, jedno okno = jeden proud SSE).
Limit dokumentu 256 KiB (`SEMAFOR_MAX_DOC_BYTES`), historie se archivuje sama po 300 událostech.
