# Entra ID: registrace aplikace

Provádí správce s rolí *Application Administrator* (nebo *Cloud Application Administrator*).

## 1. App registration

Entra admin center → Identity → Applications → App registrations → New registration

| Pole | Hodnota |
|---|---|
| Name | `Semafor Provozu` (pro TEST zvlášť `Semafor Provozu TEST`) |
| Supported account types | *Accounts in this organizational directory only* (jen tenant Hranipex) |
| Redirect URI | platforma **Web**: `https://<adresa>/semafor/auth/callback` (přesně `SEMAFOR_PUBLIC_URL` + `/auth/callback`) |

Po vytvoření:

* **Overview**: zkopírovat *Application (client) ID* → `SEMAFOR_OIDC_CLIENT_ID`, *Directory (tenant) ID* → `SEMAFOR_OIDC_TENANT_ID`.
* **Authentication**: přidat druhé redirect URI `https://<adresa>/semafor/` (návrat po odhlášení);
  *Front channel logout URL* nevyplňovat; *ID tokens* zaškrtávat netřeba (aplikace používá authorization code flow).
* **Certificates & secrets** → New client secret (platnost např. 24 měsíců) → hodnota do `SEMAFOR_OIDC_CLIENT_SECRET`.
  Termín expirace si dát do kalendáře; po výměně stačí přepsat `.env` a restartovat službu.
* **Token configuration** → Add optional claim → ID → `email` (pro jistotu; jinak se bere `preferred_username`).
* **API permissions**: `openid`, `profile`, `email` (Microsoft Graph, delegované) jsou výchozí, admin consent pro tenant.

## 2. App roles

App registration → **App roles** → Create app role (Allowed member types: *Users/Groups*):

| Display name | Value | Popis |
|---|---|---|
| Semafor správce | `Semafor.Admin` | kurz EUR/CZK, spárování účtů, nastavení (dřív vlastník artefaktu) |
| Semafor uživatel | `Semafor.User` | čte a zapisuje projekty a úkoly |
| Semafor čtenář | `Semafor.Reader` | jen čte |

Názvy lze změnit, pak upravit `SEMAFOR_ROLE_*` v `.env`.

## 3. Přiřazení lidí

Enterprise applications → Semafor Provozu:

* **Properties** → *Assignment required?* = **Yes** (bez přiřazení se nikdo nepřihlásí; aplikace to navíc kontroluje sama).
* **Users and groups** → Add user/group → vybrat roli. Doporučeno přes skupiny, např.
  `SG-Semafor-Admins` (Jan Kratky, správce aplikace), `SG-Semafor-Users` (vedoucí útvarů Operations), případně `SG-Semafor-Readers`.

## 4. Volitelné: hledání lidí v adresáři

Aby šlo v poli Vlastník najít i kolegu, který se ještě nepřihlásil:

* API permissions → Microsoft Graph → **Application** → `User.ReadBasic.All` → *Grant admin consent*.
* `.env`: `SEMAFOR_GRAPH_DIRECTORY_SEARCH=true`.

Bez toho našeptávač nabízí lidi, kteří se do aplikace už přihlásili, a emaily, které jsou v datech.

## 5. Volitelné: automatické maily přes Graph

Místo SMTP relay lze posílat přes Graph:

* Microsoft Graph → **Application** → `Mail.Send` → admin consent.
* **Nutně** omezit na jednu schránku odesílatele (Exchange Online PowerShell):

```powershell
New-ApplicationAccessPolicy -AppId <client id> -PolicyScopeGroupId semafor-odesilatel@hranipex.com `
  -AccessRight RestrictAccess -Description "Semafor Provozu smí posílat jen ze sdílené schránky"
```

* `.env`: `SEMAFOR_NOTIFY_TRANSPORT=graph`, `SEMAFOR_NOTIFY_FROM=semafor-odesilatel@hranipex.com`.

Poznámka: dřívější blokace (`Mail.Send` u konektoru Claude, viz `notifikace-mail.md`) se týkala delegovaného
přístupu Claude; tady jde o vlastní aplikaci firmy a sdílenou schránku, takže maily nechodí z osobní schránky.

## 6. Teams (volitelné)

Aplikaci lze připnout do kanálu jako záložku *Website*. Přihlašovací stránka Microsoftu se ale v rámu nezobrazí;
pokud by záložka nefungovala, otevře se aplikace v prohlížeči. Pro vkládání do Teams nastavit `SEMAFOR_FRAME_ANCESTORS`
(vzor v `deploy/env.example`) a `SEMAFOR_SESSION_SAME_SITE=none` (cookie relace se jinak v rámu neposílá). Nezkoušeno.
