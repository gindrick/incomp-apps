# Semafor Provozu 3.0: z Claude artefaktu na firemní server

Semafor Provozu je interní nástroj operations Hranipexu pro sledování projektů a krátkodobých úkolů:
semafor zdraví projektu, vlastníci a termíny, návaznosti, porada týmu, přehled pro CEO, Gantt,
project charter v PDF. Tento balík obsahuje vše potřebné k tomu, aby aplikace běžela na serveru
ve firemní infrastruktuře místo na claude.ai.

## Jak aplikace vznikla

* **Září 2026:** aplikace vznikla v Claude jako *artefakt*: jedna webová stránka publikovaná na claude.ai
  s vlastní malou databází, přihlášením přes účet Claude a úložištěm příloh. Výhoda byla rychlost:
  Jan Kratky (Honza) zadával požadavky, Claude je hned zapracoval a publikoval.
* **Od 22. 9.** se v ní vedou reálná data operations. Postupně prošla 13 revizemi (v2.1 až v2.35):
  návaznosti, potvrzování stavu, koncepty a kolize při souběžné úpravě, historie změn, náklady a měny,
  Gantt, charter projektu a přehled CEO v PDF.
* **Dočasný režim útvarů:** vedoucí útvarů (Karel, Ondra, Kuba, Tomáš) neměli licenci Claude, takže dostávali
  offline soubory se snímkem dat a své změny posílali zpět exportem; ten se ručně slučoval do ostré verze.
* Stav k 19. 10. 2026: 47 projektů, 308 úkolů, 282 historií změn.

## Proč aplikaci stěhujeme

Artefakt posloužil dobře jako pilot, ale pro firemní nástroj, na kterém stojí porady a reporting pro CEO, má zásadní limity:

| Limit artefaktu | Dopad v praxi |
|---|---|
| přístup jen s účtem Claude v organizaci a nasdíleným artefaktem | vedoucí bez licence museli pracovat přes soubory a ruční slučování (pracné, riziko chyb a kolizí) |
| data v databázi artefaktu na claude.ai | mimo firemní zálohy, mimo správu IT, export jen přes Claude; strop 5 000 dokumentů |
| platforma bez transakcí a bez podmíněného zápisu | souběh se musel složitě ošetřovat na straně stránky |
| odesílání mailů blokované (konektor bez `Mail.Send`) | upomínky termínů se posílají ručně |
| tisk v sandboxu artefaktu nefunguje | PDF se muselo řešit oklikou přes stažení |
| každá úprava a publikace jde přes konverzaci s Claude | závislost na jednom kanálu, žádný běžný vývojový a nasazovací proces |
| soukromé To Do je skryté i před vlastníkem | nejde zálohovat ani obnovit |

Honza se 6. 10. ptal na rozšíření na další divize, hosting s přihlášením a přístup pro BVR. Doporučení tehdy znělo:
rozšiřovat až s vlastním hostingem a oprávněními na serveru. Tento balík je právě ten krok.

## Co jsme udělali

**Cíl:** stejná aplikace, stejná data, stejná pravidla, ale na firemní infrastruktuře:
Windows Server, IIS nebo firemní směrování aplikací, MS SQL Server, přihlášení firemním účtem přes Entra ID.

**Princip:** aplikaci jsme nepřepisovali. Stránka je odladěná přes desítky testů a revizí a celá její vazba
na platformu Claude vede přes čtyři služby (databáze, uživatel, přílohy, stahování). Napsali jsme proto:

1. **Server** (Python FastAPI), který tyto čtyři služby poskytuje nad SQL Serverem se stejným chováním,
   jaké stránka očekává, a přidává to, co platforma neuměla: atomické zápisy, verze dokumentů, provozní audit
   zápisů, podmíněný zápis pro import a obnovu.
2. **Adaptér stránky** (`platform.js`), který místo platformy Claude volá tento server; živé změny mezi uživateli
   jdou přes Server Sent Events, se záložním dotazováním, kdyby je síťové směrování nepropustilo.
3. **Přihlášení a role** přes Entra ID: správce (dřív vlastník artefaktu), uživatel, čtenář.
   Účet se s emailem spáruje sám při prvním přihlášení, odpadá ruční párování.
4. **Migraci dat** z artefaktu: import ze zálohy se suchým během, převodem identit z účtů Claude na firemní email,
   kontrolou čtením zpět a protokolem.
5. **Provoz:** Windows služba, konfigurace IIS, noční zálohy JSON, naplánované úlohy, automatické maily
   (připravené, zapínají se konfigurací), návody pro nasazení, Entra ID, migraci a provoz.
6. **Nástroje:** generátory PowerPointu (charter, přehled CEO) napojené na export ze serveru.

Ve zdroji stránky je jen sedm drobných úprav (adresa aplikace, cesta k přílohám, odhlášení, texty);
podrobnosti v [docs/ZMENY_PROTI_ARTEFAKTU.md](docs/ZMENY_PROTI_ARTEFAKTU.md).

## Co se tím změní pro uživatele

| | Dnes (artefakt) | Po přechodu (firemní server) |
|---|---|---|
| přístup | licence Claude + nasdílený artefakt | firemní účet M365 + role přidělená v Entra ID |
| vedoucí útvarů | offline soubory a slučování | pracují přímo v aplikaci, živě |
| Moje práce | až po ručním spárování účtu | hned po prvním přihlášení |
| data a zálohy | na claude.ai, zálohy přes Claude | ve firemním SQL Serveru, zálohy dle politiky IT + noční JSON |
| upomínky termínů | ručně přes předvyplněný mail | automaticky (po zapnutí) |
| úpravy aplikace | konverzace s Claude a publikace artefaktu | běžný zdrojový kód, testy, nasazení skriptem |
| soukromé To Do | jen v artefaktu | **nepřenáší se**, uživatelé si ho přepíšou před přechodem |

## Stav a další kroky

**Hotovo (19. 10. 2026):** kompletní codebase, 49 automatických testů serveru, testy v prohlížeči, zkušební
import aktuálních ostrých dat (640 dokumentů, 640 shodných po kontrole), nezávislá kontrola kódu a opravy nálezů.

**Zbývá:**

1. Odpovědi na otevřené otázky (směrování, SQL Server, Entra ID, maily, termín): [docs/OTEVRENE_OTAZKY.md](docs/OTEVRENE_OTAZKY.md).
2. TEST instance na serveru: ověřit běh na Windows a proti SQL Serveru (tady to ověřit nešlo), Honza projde data.
3. Před přechodem sloučit poslední exporty z dočasného režimu, uživatelé přepíšou soukromé To Do.
4. Den přechodu: zmrazení artefaktu, plný export, import, kontrola, nová adresa ([docs/MIGRACE_DAT.md](docs/MIGRACE_DAT.md)).
   Artefakt zůstává jako archiv a záložní cesta zpět.

# Technická část

## Co je v balíku

| Složka | Obsah |
|---|---|
| `backend/semafor/` | server: dokumentové úložiště nad SQL, pravidla přístupu, zámky, živé změny (SSE), přílohy, Entra ID, CLI |
| `backend/semafor/static/index.html` | sestavená stránka aplikace (vzniká `python frontend/build.py`) |
| `backend/sql/001_schema_mssql.sql` | DDL pro DBA (aplikace umí tabulky založit i sama) |
| `backend/tests/` | automatické testy serveru (pytest, 49 testů) |
| `frontend/src/semafor-provozu.src.html` | zdroj aplikace (jediný soubor, upravuje se jen tento) |
| `frontend/src/platform.js` | platformní adaptér: API artefaktu nad REST a SSE |
| `frontend/build.py` | sestavení stránky (loga, knihovny PDF, adaptér, CSP nonce) |
| `deploy/` | vzor konfigurace, Windows služba, IIS web.config, naplánované úlohy |
| `tools/pptx/` | charter a přehled CEO jako PowerPoint (mimo aplikaci) |
| `tools/migrace/` | mapa identit pro import |
| `tests/e2e/` | testy v prohlížeči proti běžícímu serveru (Playwright) |
| `docs/` | architektura, nasazení, Entra ID, migrace dat, provoz, změny proti artefaktu, otevřené otázky |

## Rychlý start na vývojářském PC (bez SQL Serveru a bez Entra ID)

```powershell
cd backend
py -3.12 -m venv .venv; .\.venv\Scripts\activate
pip install -r requirements-dev.txt
$env:SEMAFOR_AUTH_MODE="dev"; $env:SEMAFOR_DATABASE_URL="sqlite:///./semafor.db"
python -m semafor import ..\cesta\semafor-backup-plna.json --identity-map ..\tools\migrace\identity-map.example.json --apply
python -m semafor serve --port 8000
# prohlížeč: http://localhost:8000/  (vývojové přihlášení: Alice správce, Bob uživatel, Cyril čtenář)
pytest
```

## Nasazení

Postup krok za krokem: [docs/NASAZENI_WINDOWS_IIS.md](docs/NASAZENI_WINDOWS_IIS.md).
Registrace v Entra ID: [docs/ENTRA_ID.md](docs/ENTRA_ID.md).
Přenos ostrých dat z artefaktu: [docs/MIGRACE_DAT.md](docs/MIGRACE_DAT.md).
Co ještě potřebuji znát: [docs/OTEVRENE_OTAZKY.md](docs/OTEVRENE_OTAZKY.md).

## Ověřeno (19. 10. 2026)

* `pytest`: 49 testů úložiště, pravidel, zámků, API, CSRF, příloh, migrace, notifikací a proudu změn.
* Import aktuálních ostrých dat z artefaktu (čtení 19. 10.): 640 dokumentů, kontrola čtením zpět 640/640 shodných,
  0 nespárovaných identit, 0 příloh k přenosu.
* `tests/e2e/smoke.cjs` 20/20 a `tests/e2e/ui.cjs` 12/12 v Chromiu, s jedním i dvěma workery, pod base path `/semafor`:
  přihlášení, živá změna mezi dvěma uživateli (do 200 ms), záložní dotazování bez SSE, pravidla, zámek detailu, rychlé zadání a historie,
  nahrání a stažení přílohy, charter jako PDF pod přísnou CSP, Moje práce podle emailu.
* Notifikace na ostrých datech (jen do logu): stejní lidé a stejné počty jako pohled Upomínky v aplikaci.
* PPTX nástroje nad exportem ze serveru: charter i přehled CEO se vygenerují.

**Neověřeno:** běh proti skutečnému SQL Serveru a na Windows (v testovacím prostředí nebyl dostupný).
Testy úložiště jdou pustit proti prázdné testovací databázi SQL Serveru, viz `backend/tests/conftest.py`
(`SEMAFOR_TEST_DATABASE_URL`). Udělat to jako první krok na TEST serveru.
