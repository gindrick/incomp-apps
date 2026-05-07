# Spotter — Competitor Social Media Monitor

Automatically scrapes competitor profiles on Facebook, Instagram, and LinkedIn once a week and presents the results in a local web UI.

## Requirements

- Python 3.10+
- [uv](https://github.com/astral-sh/uv) package manager
- Dedicated monitoring accounts for **all three platforms** with **2FA disabled** (see Credentials below)

## Setup

### 1. Install dependencies

```powershell
cd C:\jja\mkt_spotter
uv sync
```

### 2. Install Playwright browser

```powershell
uv run playwright install chromium
```

### 3. Set credentials

All three platforms require login. Spotter logs in once per platform per run using a real Chromium browser — session cookies are reused across all profiles of the same platform.

Copy `.env.example` to `.env` and fill in all credentials:

```powershell
copy .env.example .env
```

Edit `.env`:

```env
# Facebook — dedicated monitoring account, 2FA disabled
FB_USERNAME=your_facebook_email@example.com
FB_PASSWORD=your_facebook_password

# Instagram — dedicated monitoring account, 2FA disabled
IG_USERNAME=your_instagram_username
IG_PASSWORD=your_instagram_password

# LinkedIn — dedicated monitoring account, 2FA disabled
LI_USERNAME=your_linkedin_email@example.com
LI_PASSWORD=your_linkedin_password

# LiteLLM proxy (shared JJA service — main message analysis)
LITELLM_BASE_URL=http://127.0.0.1:4000
LITELLM_API_KEY=sk-mysecretkey
LITELLM_MODEL=gpt-4o-mini
```

> **Why dedicated accounts?** Using a personal account risks triggering security alerts from automated activity. A throwaway account created specifically for Spotter keeps your personal account safe. Create one Facebook account, one Instagram account, and one LinkedIn account — all with 2FA disabled and no other activity.

> **Why not the official API?** Screenshots are a core output of Spotter. No official API (Facebook Graph API, Instagram Graph API, LinkedIn API) provides screenshots. Browser automation with credentials is the only approach that delivers both structured data and post screenshots.

If credentials for a platform are missing or incorrect, Spotter skips all profiles for that platform, logs a warning, and continues with the remaining platforms.

### 4. Configure profiles

Edit `config.yaml` — add or remove competitor profile URLs under `profiles:`:

```yaml
profiles:
  - url: https://www.facebook.com/CompanyPage
    label: Company Name
  - url: https://www.instagram.com/company_handle/
    label: Company Name
  - url: https://www.linkedin.com/company/company-slug/posts/?feedView=all
    label: Company Name
```

## Running the scraper

```powershell
uv run python main.py
```

Results are saved to `reports/YYYY-MM-DD_HH-MM/`:
- `data.json` — all collected data (used by the web UI)
- `screenshots/` — PNG screenshots per post

## Starting the web UI

```powershell
uv run python web/app.py
```

Open: http://localhost:8013  
Via JJA router: http://localhost:8000/spotter

## Scheduling (Windows Task Scheduler)

Run once as Administrator to register both scheduled tasks:

```powershell
.\register-task.ps1
```

This registers:
- `JJA\Spotter-Scraper` — runs `main.py` every Monday at 08:00
- `JJA\Spotter-Web` — starts the web UI at system boot (60s delay)

To trigger the scraper immediately without waiting for Monday:

```powershell
Start-ScheduledTask -TaskName "JJA\Spotter-Scraper"
```

## Debugging

Set `headless: false` in `config.yaml` to watch the browser navigate in real time — useful for diagnosing login issues or blocked pages.

Check logs in `C:\jja\logs\spotter-web.log` (web UI) when started via `start-all.ps1`.

If a platform consistently returns zero posts after successful login, run with `headless: false` and observe what the browser sees — it may be a CAPTCHA, a changed DOM structure, or a temporary block.

## Notes

- `.env` is gitignored — never commit credentials.
- Reports persist as files on disk and survive server restarts.
- Each scraper run is independent — a failure on one platform does not stop the others.
- Weekly scraping frequency is low enough that account flags are unlikely, but avoid running more than once per day.
