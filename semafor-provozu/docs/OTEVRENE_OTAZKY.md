# Otevřené otázky a vstupy pro nasazení

Co je potřeba doplnit nebo rozhodnout. Kde je uvedený výchozí předpoklad, kód s ním počítá a stačí potvrdit.

## Směrování a server

1. **Adresa aplikace**: přesná URL, jak ji uvidí prohlížeč (předpoklad `https://<server>/semafor`).
2. **Vaše směrování**: předává prefix `/semafor` dál, nebo ho odřízne? (aplikace zvládne obojí, jen potvrdit)
3. Končí TLS na směrování? Posílá `X-Forwarded-Proto` a `X-Forwarded-Host`? Z jaké IP adresy (kvůli `--forwarded-allow-ips`)?
4. Umí směrování **nebufferovat** `text/event-stream` a držet spojení 11 minut? (jinak aplikace funguje s dotazováním po 5 s)
5. Běží směrování na stejném serveru jako aplikace, nebo jinde? (jinde = aplikace musí naslouchat na adrese serveru, ne jen 127.0.0.1)
6. Verze Windows Serveru, smí se nainstalovat Python 3.12, ODBC Driver 18 a WinSW? Má server přístup na pypi.org?
7. Servisní účet: gMSA, nebo běžný doménový účet?

## Databáze

8. SQL Server instance a název databáze, kdo ji založí, Windows autentizace (gMSA), nebo SQL login?
9. Smí servisní účet při prvním spuštění zakládat tabulky, nebo DBA spustí `backend/sql/001_schema_mssql.sql`?
10. Zapnutý `READ_COMMITTED_SNAPSHOT`? (funguje obojí, jen pro informaci)

## Entra ID

11. Kdo založí registraci aplikace a app roles ([ENTRA_ID.md](ENTRA_ID.md))? Tenant `73b39313-1d97-4ac4-bc26-f0ba6dc67f1a` (převzato z poznámek k notifikacím, ověřit).
12. Kdo bude **správce** (`Semafor.Admin`)? Předpoklad: Jan Kratky; doplnit případně sebe jako správce za IT / data.
13. Kdo dostane roli **uživatel**, kdo **čtenář**? Skupiny v Entra ID, nebo jednotlivci?
14. Má našeptávač vlastníka hledat v celém adresáři (`User.ReadBasic.All`)?

## Notifikace

15. Odesílání přes **SMTP relay** (host, port, ověření), nebo **Graph** se sdílenou schránkou? Jaká adresa odesílatele?
16. Kdo dostává denní souhrn a kopie položek po termínu? Předpoklad: Jan Kratky.

## Data a přechod

17. **Termín přechodu** a kdo potvrdí data na TEST (předpoklad: Jan Kratky).
18. Jsou ještě nesloučené změny z dočasného režimu (Karel, Ondra, Kuba, Tomáš)? Musí se sloučit před přechodem.
19. Kdo upozorní uživatele, že **soukromé To Do se nepřenese**?
20. Chceme **TEST instanci** trvale (druhá databáze, druhá registrace nebo redirect URI)? Doporučuji ano.

## Prohlížeč

21. Smí prohlížeče stahovat písmo z Google Fonts? (jinak `SEMAFOR_ALLOW_GOOGLE_FONTS=false`, použije se Helvetica/Arial)
22. Má být aplikace jako záložka v Teams?
