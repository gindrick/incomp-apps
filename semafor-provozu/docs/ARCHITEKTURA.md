# Architektura

## Přehled

```
Prohlížeč (stránka Semafor = zdroj 2.35 + platform.js)
   │  HTTPS, cookie relace, REST JSON, Server-Sent Events
   ▼
Směrování / IIS (TLS, /semafor → 127.0.0.1:8710)
   ▼
Semafor backend (Python 3.12, FastAPI, uvicorn; Windows služba)
   ├─ přihlášení Entra ID (OIDC authorization code), role z app roles
   ├─ dokumentové úložiště (pravidla, verze, zámky, změny)
   ├─ přílohy, adresář lidí, notifikace (CLI z Plánovače úloh)
   ▼
MS SQL Server (tabulky sp_*)
```

## Proč tenký backend místo přepsání aplikace

Aplikace (3 900 řádků) je odladěná přes 13 revizí a desítky testů. Všechna její vazba na platformu jde přes
čtyři služby `window.claude.use(...)`. Backend proto implementuje přesně tuto sémantiku a stránka zůstává stejná.
Výhody: žádná regrese v pravidlech aplikace, data se přenesou beze změny tvaru, budoucí úpravy stránky
se dělají stejně jako dosud (jeden zdrojový soubor). Cena: data zůstávají dokumenty JSON, ne relační tabulky
(pro reporting viz níže).

## Platformní adaptér (`frontend/src/platform.js`)

| Služba artefaktu | Implementace |
|---|---|
| `db.doc(p).get / set / update / delete` | `GET / PUT / PATCH / DELETE /api/docs/<cesta>` |
| `update` | na serveru hluboké sloučení objektů, pole a skaláry se nahrazují, `null` nastaví null (stejně jako platforma) |
| `db.doc(p).acquire({holder, ttlMs})` | `POST /api/leases/<cesta>`: získá nebo prodlouží zámek, krátké TTL = uvolnění |
| `db.collection(c).onSnapshot` | první načtení `GET /api/collections/<c>`, dál živé změny z `/api/stream` (SSE) |
| výpadek SSE | adaptér se připojí znovu od posledního `seq`; po 3 chybách přejde na dotazování `/api/changes` každých 5 s |
| `where / orderBy / limit` | filtr na klientu (aplikace je nepoužívá, jsou pro úplnost) |
| `user.me / profiles / search` | `/api/me`, `/api/users/profiles`, `/api/users/search` |
| `assets.upload` | `POST /api/assets` (multipart), soubor se servíruje z `/_blob/<id>` |
| `downloads.save` | stažení v prohlížeči (odkaz na Blob) |

Každý zápis vrací verzi; adaptér hned po zápisu vyzvedne změny, takže vlastní úprava je vidět okamžitě
i tehdy, když proxy proud změn zdržuje.

## Datový model v SQL

| Tabulka | Účel |
|---|---|
| `sp_documents` | jeden řádek = jeden dokument: `path` (PK), `collection`, `doc_id`, `data` NVARCHAR(MAX) JSON, `version`, `seq`, `deleted` |
| `sp_counters` | globální čítač změn `seq` (řádek `docs`) |
| `sp_leases` | kooperativní zámky detailu a historie |
| `sp_users` | kdo se přihlásil (id = Entra object id, email, jméno, role) |
| `sp_assets` | přílohy VARBINARY(MAX) |
| `sp_audit_log` | kdo, kdy, jakou operaci a na jakém dokumentu (provozní audit; historie v aplikaci auditem není) |

Kolekce dokumentů jsou stejné jako v artefaktu: `projects`, `tasks`, `history`, `history_archive`, `people`,
`settings`, `notify` a soukromé `data/users/<id>/private/todos`. Popis polí: projektový dokument `claude/semafor-provozu.md`.

### Konzistence a souběh

* Každá operace je jedna transakce se zámkem řádku (`WITH (UPDLOCK, HOLDLOCK, ROWLOCK)`), takže `update`
  je atomický read modify write na serveru. Souběžné přírůstky historie se nepřepíšou (test se 40 souběžnými zápisy).
* `seq` se přiděluje zvýšením řádku čítače v téže transakci. Zámek čítače drží do potvrzení, proto se čísla
  potvrzují v pořadí a čtenář změn nic nepřeskočí (platí i při READ_COMMITTED_SNAPSHOT v Azure SQL).
* Smazání je náhrobek (`deleted = 1`), aby se o něm dozvěděli i klienti, kteří byli zrovna offline.
* Oběť deadlocku (1205) a souběžné založení téže cesty se automaticky zopakují.
* Volitelný `ifVersion` u zápisu (podmíněný zápis) používají import a obnova; aplikace sama ho nepotřebuje.

### Živé změny

Proces drží jednoho „brokera“: zápis v tomto procesu ho probudí hned, zápisy z jiných procesů (více workerů,
CLI) zachytí dotaz na čítač jednou za sekundu. Každé otevřené okno má jeden proud SSE; server mu pošle dávku
změn od jeho `seq`, filtrovanou podle práv. Proud se po 10 minutách ukončí a prohlížeč se připojí znovu
(proxy dlouhá spojení stejně ruší). Změřeno: změna od jiného uživatele se zobrazí za cca 200 ms.

## Bezpečnost

* **Přihlášení:** Entra ID, jen tenant Hranipex (kontrola `tid`), relace v podepsané cookie (HttpOnly, Secure,
  SameSite=Lax, platnost 10 h). Bez přiřazené role se dovnitř nedostane nikdo.
* **Role:** `Semafor.Admin` (dřív „vlastník artefaktu“: kurz, spárování, settings), `Semafor.User` (čte i zapisuje),
  `Semafor.Reader` (jen čte).
* **Pravidla dat:** `people` a `settings` zapisuje jen správce; `data/users/<id>` vidí a mění jen ten uživatel
  (ani správce ne, stejně jako na platformě); `notify` je přes API nepřístupné; jiné kolekce server odmítne.
* **CSRF:** zápisy vyžadují hlavičku `X-Semafor-Request: 1` a shodný `Origin`.
* **Stránka:** Content Security Policy se skripty jen s jednorázovým `nonce` (žádné `unsafe-inline` pro skripty),
  `frame-ancestors` z konfigurace, `nosniff`, `Referrer-Policy`.
* **Přílohy:** povolené typy jako v aplikaci (Office soubory dál jako odkaz na SharePoint), do 20 MB (SVG 2 MB),
  servírované s `CSP sandbox`, SVG jen ke stažení.
* **Tajemství** jen v `.env` mimo složku aplikace (NTFS práva), nikdy v kódu ani v repozitáři.

## Reporting a napojení

Data jsou JSON v `sp_documents.data`. Pro Power BI nebo SQL dotazy lze nad tabulkou postavit pohledy s `OPENJSON`
(např. `vw_semafor_tasks`), bez zásahu do aplikace. Doporučuji je přidat až podle potřeby reportingu.

## Co zůstalo ve zdroji a dál se nepoužívá

„Dočasný režim útvarů“ (členské soubory, `__MEMBER`, `testshim.js`) je ve zdroji dál, ale na serveru se nikdy
neaktivuje (nemá kdo dodat `window.__MEMBER`). Párování účtů v Tým & porada dál funguje, ale je zbytečné:
server spáruje účet s emailem automaticky při přihlášení. Odstranění obojího je vhodné jako samostatná úprava po stabilizaci.
