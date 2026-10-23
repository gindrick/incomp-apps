# Migrace dat z Claude artefaktu

## Výchozí stav (čtení ostré 19. 10. 2026)

| Kolekce | Dokumentů |
|---|---|
| projects | 47 |
| tasks | 308 |
| history | 282 |
| history_archive | 0 |
| people | 2 (Jan Kratky, Stanislav Havel) |
| settings | 0 (firemní kurz EUR/CZK není nastaven) |
| notify | 1 (`notify/state`, notifikace nikdy neběžely) |
| **celkem** | **640** |

Zkušební import do nové databáze: **640/640 dokumentů shodných** po čtení zpět, 155 položek převedeno
ze starého id účtu na email, **0 nespárovaných identit, 0 příloh** (v datech nejsou žádné nahrané soubory, jen odkazy).

## Co se při migraci mění a co ne

| Oblast | Chování |
|---|---|
| obsah projektů, úkolů, historie | beze změny (stejné JSON dokumenty, stejná id) |
| `ownerUserId` se starým id claude.ai | nahrazen emailem v `ownerEmail` a vyprázdněn; Moje práce pak funguje podle firemního emailu |
| `byId`, `createdById`, `confirmedById` v historii a položkách | ponechány; `people/<staré id>` se přenese, takže jména se zobrazí správně |
| nové účty | při prvním přihlášení server sám založí `people/<Entra id>` (dřív ruční spárování správcem) |
| `notify/state` | přenese se; první běh notifikace přiřazení nic nerozešle (jen si zapamatuje stav) |
| **soukromé To Do** | **nepřenese se**: platforma ho neexportuje ani vlastníkovi. Uživatelé si ho musí přepsat ručně |
| verze dokumentů | začínají znovu od 1 (verze artefaktu nejsou potřeba) |
| členské soubory dočasného režimu | v novém prostředí se nepoužívají; nesloučené exporty je nutné sloučit **před** přechodem |

## Postup přechodu (den D)

**Před dnem D**

1. TEST instance na serveru, import poslední zálohy, kontrola Honzou (Jan Kratky): Moje práce, Gantt, charter PDF, Upomínky.
2. Uživatele upozornit: soukromé To Do si přepište (nebo převeďte na týmové úkoly) do dne D.
3. Vedoucí v dočasném režimu (Karel, Ondra, Kuba, Tomáš) pošlou poslední změny; sloučit do ostré artefaktu nástrojem v2.1
   (lokální ledger zmizel 15. 10., slučovat `--strict` proti základu snímku, viz `claude/slouceni-dennik-2.md`).
4. Entra ID: aplikace, role a přiřazení hotové; ostrá adresa a certifikát hotové.

**Den D (odhad 1 hodina, aplikace v artefaktu je mezitím jen ke čtení)**

1. Oznámit zmrazení: od teď nikdo nezapisuje do artefaktu.
2. Plný export ostré artefaktu: Claude v projektu „Project tracking app“ stáhne všechny kolekce
   (`projects`, `tasks`, `history`, `history_archive`, `people`, `settings`, `notify`) do složky `<kolekce>/<id>.json`
   a uloží ji vedle záloh (formát, který přímo bere import). Případné přílohy (`assetId`) stáhne do složky `assets/`.
3. Na serveru (služba zastavená, databáze prázdná):

   ```powershell
   cd C:\apps\semafor\app\backend
   $env:SEMAFOR_ENV_FILE="C:\apps\semafor\.env"
   # suchý běh: jen protokol, nic se nezapíše
   C:\apps\semafor\venv\Scripts\python.exe -m semafor import D:\migrace\export-ostra --identity-map D:\migrace\identity-map.json --assets-dir D:\migrace\export-ostra\assets --report D:\migrace\protokol-sucho.md
   # kontrola protokolu: počty, NESPÁROVANÁ id (musí být 0 nebo doplnit do identity-map.json), CHYBÍ přílohy (musí být 0)
   C:\apps\semafor\venv\Scripts\python.exe -m semafor import D:\migrace\export-ostra --identity-map D:\migrace\identity-map.json --assets-dir D:\migrace\export-ostra\assets --apply --report D:\migrace\protokol.md
   C:\apps\semafor\venv\Scripts\python.exe -m semafor export D:\migrace\po-importu.json
   ```

   Import je jedna transakce (vše, nebo nic) a končí kontrolou čtením zpět; nenulový počet rozdílů = návratový kód 1.
4. Spustit službu, kontrola dle `NASAZENI_WINDOWS_IIS.md` kap. 6 a porovnání počtů s exportem.
5. Artefakt na claude.ai přepublikovat s lištou „Aplikace se přestěhovala na https://…“ (Claude, jen změna stránky; data artefaktu zůstanou jako archiv).
6. Oznámit novou adresu.

**Návrat (rollback):** do oznámení nové adresy stačí nic neoznamovat a odmrazit artefakt; data v artefaktu se migrací nemění.
Po přechodu se změny v novém prostředí do artefaktu automaticky nevracejí (šlo by exportem a dávkou, ručně).

## Mapa identit

`tools/migrace/identity-map.json`: `{ "staré id claude.ai": "firemní email" }` pro účty, které nejsou v `people`.
Podle čtení 19. 10. není potřeba nic doplnit (jediné staré id v položkách je Honzovo a je spárované).

## Obnova ze zálohy serveru

Tentýž příkaz `import` bere i zálohu vytvořenou `python -m semafor export` (formát `{"docs": {...}}`).
Do neprázdné databáze jen s `--allow-non-empty` (přepíše shodné cesty, ostatní dokumenty nechá).
