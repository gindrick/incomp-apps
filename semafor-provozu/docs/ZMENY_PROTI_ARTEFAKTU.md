# Změny proti verzi 2.35 v Claude artefaktu

## Zdroj stránky (`frontend/src/semafor-provozu.src.html`)

Jen sedm cílených úprav, logika aplikace je beze změny:

| Místo | Změna |
|---|---|
| `IS_TEST` | řídí se konfigurací serveru (`SEMAFOR_ENVIRONMENT=test`), ne buildem; titulek „Semafor Provozu TEST“ nastaví skript |
| `APP_VERSION` | `3.0` (v patičce, v exportech a v PDF) |
| `DB_URL` | odkaz do aplikace v předvyplněných mailech = `SEMAFOR_PUBLIC_URL` |
| `attUrl` | odkaz na přílohu respektuje base path (`/semafor/_blob/<id>`) |
| hlavička uživatele | „· správce“ místo „· vlastník“, odkaz **odhlásit** |
| texty | „Otevři stránku přes claude.ai“ → „Načti stránku znovu a přihlas se firemním účtem“ |
| značky | `<!--SP_CONFIG-->` (konfigurace ze serveru) a `<!--PLATFORM-->` (adaptér) před knihovnami PDF |

## Chování pro uživatele

| Oblast | Artefakt | Nově |
|---|---|---|
| přístup | účet Claude v organizaci + nasdílený artefakt | firemní účet M365 + role v Entra ID |
| Moje práce | jen po ručním spárování účtu správcem | hned po prvním přihlášení (spárování automaticky) |
| tisk / PDF | tlačítko „Stáhnout pro tisk“ přes platformu | totéž, stažení přímo v prohlížeči |
| souběh | poslední zápis vyhrává, atomicitu řeší klient | navíc atomické zápisy na serveru (žádné ztracené přírůstky historie) |
| soukromé To Do | skryté i před vlastníkem | stejně (ani správce ho nevidí) |
| automatické maily | blokované (chybí Mail.Send) | připravené, zapínají se konfigurací |
| dočasný režim útvarů | soubory pro vedoucí bez licence | nepotřeba, každý má přístup přímo |

## Nahrazené skripty ze složky `semafor-skripty`

| Skript | Stav |
|---|---|
| `build.py` | nahrazen `frontend/build.py` (stejné vkládání log a knihoven, navíc adaptér a CSP nonce) |
| `testshim.js` | zůstává jen pro offline sestavení a dosavadní testy (`--offline`) |
| `build_offline_v2.py` | nahrazen `frontend/build.py --offline --seed` |
| `build_member.py`, `members.json`, `merge_exports.py`, `merge_confirm.py`, `test_merge.py` | dočasný režim útvarů, v novém prostředí nepotřeba (archiv ve složce skriptů) |
| `restore_backup.py` | nahrazen `python -m semafor import` (obnova) a `export` (záloha) |
| `migrate.py`, `audit_merges.py` | historické, nepřenášejí se |
| `charter_lib.py`, `build_ceo_deck.py`, `hx.py`, šablona | přeneseny do `tools/pptx` (vstup = `export --snapshot-dir`) |
| `build_charter_pptx.py`, `charter_sample.py` | starší vzory, nepřenášejí se |
