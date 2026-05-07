# GOAL.md — Spotter: Automated Competitor Social Media Monitor

## 1. Project Overview

**Spotter** is a Python tool that **automatically crawls competitor profiles** on Facebook, Instagram, and LinkedIn once a week and generates a structured report with key metrics and post screenshots. Reports are browsable through a **lightweight local web interface** that lets the user select any past run by date and view the full report in the browser.

---

## 2. Required Functionality

### 2.1 Input

A configurable list of competitor profile URLs, for example:

```
https://www.facebook.com/HettichCR
https://www.facebook.com/Hafele.Czech.Slovakia
https://www.instagram.com/rudolfostermann_karriere/
https://www.instagram.com/hettich_official/
https://www.linkedin.com/company/henkel/posts/?feedView=all
https://www.linkedin.com/company/moderne-kunststoff-technik-gebruder-eschbach-gmbh/posts/?feedView=all
```

URLs are stored in a configuration file (`config.yaml`) so they can be updated without touching the code.

### 2.2 What Spotter Collects Per Profile

| Metric | Description |
|---|---|
| **New posts** | Number of posts published in the last 7 days |
| **Top post** | Post with the highest engagement (topic / summary) |
| **Highest engagement** | Reactions and comments count on the best-performing post |
| **Main message** | Summary of recurring themes (e.g. fast delivery, portfolio, service) |
| **Post screenshots** | Images of each new post |

### 2.3 Output Format

Each scraper run saves its results to `reports/YYYY-MM-DD_HH-MM/` containing:

- `data.json` — structured data for all profiles (used by the web UI)
- `screenshots/` — PNG screenshots of individual posts

The **web interface** reads `data.json` files from all run folders and presents them as a browsable report. The user picks a run date from a sidebar/dropdown and sees the full report for that snapshot.

Web UI report view per profile:

```
Channel: Facebook
Profile: HettichCR
New posts: 4
Top post: trade fair / product solution / reference
Highest engagement: 184 reactions, 16 comments
Main message: fast delivery, portfolio, service
Screenshots: [thumbnails of 4 posts]
```

---

## 3. Technical Plan

### 3.1 Technology Stack

| Component | Technology |
|---|---|
| Language | Python 3.10+ |
| Scraping / browser automation | Playwright (headless Chromium) with credentials |
| Screenshots | Playwright `.screenshot()` — only possible via browser, not API |
| HTML parsing | BeautifulSoup4 |
| Configuration | PyYAML (`config.yaml`) |
| Credentials | `.env` file — all three platforms require login (FB, IG, LinkedIn) |
| Data storage | JSON files per run (`data.json`) |
| Web server | Flask (lightweight, no database needed) |
| Web UI templating | Jinja2 + plain CSS (no heavy frontend framework) |
| Scheduling | cron (Linux/macOS) or Task Scheduler (Windows); optionally APScheduler |
| Logging | Python `logging` module |

> **Why credentials for all platforms?** Facebook and Instagram block headless browsers without login — public page scraping returns nothing usable in 2025. Screenshots are a core requirement that no official API provides. Playwright with a dedicated monitoring account (2FA disabled) is the only approach that delivers both data and screenshots reliably. Weekly scraping frequency keeps account risk very low.

### 3.2 Project Structure

```
Spotter/
├── config.yaml              # URL list and settings
├── main.py                  # Scraper entry point (run weekly)
├── scraper/
│   ├── __init__.py
│   ├── base.py              # Abstract ScraperBase class
│   ├── facebook.py          # Facebook scraper
│   ├── instagram.py         # Instagram scraper
│   └── linkedin.py          # LinkedIn scraper
├── report/
│   ├── __init__.py
│   └── generator.py         # Saves data.json per run
├── web/
│   ├── app.py               # Flask web server
│   ├── templates/
│   │   ├── base.html        # Shared layout
│   │   ├── index.html       # Run list / dashboard
│   │   └── report.html      # Single run report view
│   └── static/
│       └── style.css        # Minimal styling
├── reports/                 # Auto-generated output folder
│   └── YYYY-MM-DD_HH-MM/   # One folder per scraper run
│       ├── data.json        # Structured data for this run
│       └── screenshots/     # PNG screenshots
├── requirements.txt
├── README.md
└── GOAL.md                  # This file
```

### 3.3 Scraper Architecture

Each platform has its own class inheriting from `ScraperBase`:

```python
class ScraperBase:
    def __init__(self, url: str, page: Page): ...
    def get_posts(self, days: int = 7) -> list[Post]: ...
    def get_screenshot(self, post: Post) -> bytes: ...

class FacebookScraper(ScraperBase): ...
class InstagramScraper(ScraperBase): ...
class LinkedInScraper(ScraperBase): ...
```

Post data model:

```python
@dataclass
class Post:
    platform: str          # "facebook" | "instagram" | "linkedin"
    profile: str           # profile name
    url: str               # post URL
    published_at: datetime
    text: str              # post body
    reactions: int
    comments: int
    shares: int
    screenshot_path: str   # path to saved screenshot
```

---

## 4. Step-by-Step Implementation Plan

### Step 1 — Project Initialization
- [ ] Create folder structure as per section 3.2
- [ ] Create `requirements.txt` with dependencies:
  - `playwright`, `beautifulsoup4`, `pyyaml`, `python-dateutil`, `flask`
- [ ] Create `config.yaml` with URL list and `days_back: 7` parameter
- [ ] Write `README.md` with setup and usage instructions

### Step 2 — Abstract Class and Data Model
- [ ] Create `scraper/base.py` with `ScraperBase` class and `Post` dataclass
- [ ] Define interface: `get_posts()`, `get_screenshot()`, `get_profile_name()`

### Step 3 — Facebook Scraper
- [ ] Login via `FB_USERNAME` / `FB_PASSWORD` from `.env` (headless Chromium, dedicated monitoring account, 2FA disabled)
- [ ] Login happens once per run in a shared browser context — session cookies persist across all Facebook profiles
- [ ] Page scrolls and loads posts from the last N days
- [ ] Extract: date, text, reaction count, comment count
- [ ] Take a screenshot of each post element
- [ ] **Note:** Facebook dynamically renders content — use `page.wait_for_selector()`

### Step 4 — Instagram Scraper
- [ ] Login via `IG_USERNAME` / `IG_PASSWORD` from `.env` (dedicated monitoring account, 2FA disabled)
- [ ] Login happens once per run in a shared browser context
- [ ] Load the post grid, click each post for detail view
- [ ] Extract: date, like count, comment count, caption
- [ ] Screenshot each post
- [ ] Handle "Save login info?" and "Turn on notifications?" dialogs automatically

### Step 5 — LinkedIn Scraper
- [ ] Login via `LI_USERNAME` / `LI_PASSWORD` from `.env`
- [ ] Login happens once per run in a shared browser context
- [ ] Extract posts from the `/posts/` section
- [ ] Extract: date, reactions, comments, text
- [ ] Screenshot each post

### Step 6 — Main Message Analysis (optional / bonus)
- [ ] For each profile, collect the text of all new posts
- [ ] Call a local LLM (ollama) or use simple keyword frequency analysis
- [ ] Output: 3–5 key topics/messages (e.g. "fast delivery, portfolio, service")
- [ ] Alternative without LLM: extract most frequent nouns via `spacy` or `nltk`

### Step 7 — Data Persistence (JSON per run)
- [ ] After each scraper run, save all collected data to `reports/YYYY-MM-DD_HH-MM/data.json`
- [ ] JSON structure:

```json
{
  "run_at": "2025-05-05T08:00:00",
  "profiles": [
    {
      "platform": "facebook",
      "profile": "HettichCR",
      "label": "Hettich CZ",
      "new_posts_count": 4,
      "top_post": { "text": "...", "reactions": 184, "comments": 16, "screenshot": "screenshots/fb_1.png" },
      "main_message": ["fast delivery", "portfolio", "service"],
      "posts": [ ... ]
    }
  ]
}
```

- [ ] Screenshot paths in JSON are relative to the run folder

### Step 8 — Flask Web Server (`web/app.py`)
- [ ] `GET /` — dashboard: list all available runs sorted newest first, each showing date/time and number of profiles scraped
- [ ] `GET /report/<run_id>` — full report view for a specific run, rendered from its `data.json`
- [ ] `GET /reports/<run_id>/screenshots/<filename>` — serve screenshot images statically
- [ ] Flask reads the `reports/` directory on startup and on each request (no database needed)
- [ ] Run with `python web/app.py` — accessible at `http://localhost:5000`

### Step 9 — Web UI Templates
- [ ] `index.html` — sidebar or card list of all runs; clicking a run navigates to its report
- [ ] `report.html` — displays the full report for the selected run:
  - Run date/time shown prominently at the top
  - One section per profile with: platform icon, post count, top post, engagement stats, main message tags, screenshot thumbnails (click to enlarge)
  - Navigation to go back to the run list or jump to next/previous run
- [ ] `style.css` — clean, minimal styling; no external CSS frameworks required (or use lightweight Pico CSS)

### Step 10 — Main Script `main.py`
- [ ] Load configuration from `config.yaml`
- [ ] Detect platform per URL (facebook / instagram / linkedin)
- [ ] Run the appropriate scraper
- [ ] Aggregate results
- [ ] Save `data.json` to timestamped run folder
- [ ] Log progress and errors

### Step 11 — Scheduling (cron)
- [ ] Add instructions for setting up a cron job (Linux/macOS):
  ```
  0 8 * * 1 cd /path/to/Spotter && python main.py
  ```
  (Every Monday at 8:00 AM)
- [ ] Web server runs separately and continuously: `python web/app.py`
- [ ] Optionally: use `systemd` service or `screen`/`tmux` to keep the web server running in background

### Step 12 — Error Handling and Robustness
- [ ] Wrap each scraper in try/except — one failing profile must not stop the entire run
- [ ] Rate limiting — add random delays between requests (2–5 seconds)
- [ ] Retry logic (3 attempts) for unstable page loads
- [ ] Headless mode with option to switch to visible browser for debugging (`HEADLESS=false`)

---

## 5. Configuration File (`config.yaml`)

```yaml
days_back: 7           # How many days back to collect posts
headless: true         # true = no GUI, false = visible browser (debug)
output_dir: reports    # Output folder for reports
screenshot_width: 1280 # Browser viewport width for screenshots

profiles:
  - url: https://www.facebook.com/HettichCR
    label: Hettich CZ
  - url: https://www.facebook.com/Hafele.Czech.Slovakia
    label: Hafele CZ/SK
  - url: https://www.instagram.com/rudolfostermann_karriere/
    label: Rudolf Ostermann Karriere
  - url: https://www.instagram.com/hettich_official/
    label: Hettich Official
  - url: https://www.linkedin.com/company/henkel/posts/?feedView=all
    label: Henkel
  - url: https://www.linkedin.com/company/moderne-kunststoff-technik-gebruder-eschbach-gmbh/posts/?feedView=all
    label: MKT Eschbach

facebook:
  username_env: FB_USERNAME   # Env variable name for Facebook login
  password_env: FB_PASSWORD   # Env variable name for Facebook password

instagram:
  username_env: IG_USERNAME   # Env variable name for Instagram login
  password_env: IG_PASSWORD   # Env variable name for Instagram password

linkedin:
  username_env: LI_USERNAME   # Env variable name for LinkedIn login
  password_env: LI_PASSWORD   # Env variable name for LinkedIn password

# Use dedicated monitoring accounts with 2FA disabled for all platforms.
```

---

## 6. Security and Limitations

- **Credentials** (LinkedIn login) must be stored exclusively in a `.env` file — never in code or `config.yaml`
- Add `.env` to `.gitignore`
- Respect `robots.txt` — Spotter is intended for internal monitoring, not mass scraping
- Facebook and Instagram may block headless browsers — log a warning and skip the profile if anti-bot protection is detected
- Screenshots are stored locally and never sent to external servers

---

## 7. Web UI — Key Screens

### Dashboard (`/`)
Lists all past scraper runs, newest first:

```
┌─────────────────────────────────────────────────┐
│  Spotter                                          │
├─────────────────────────────────────────────────┤
│  All Reports                                    │
│                                                 │
│  ▶ Mon 05 May 2025, 08:00   6 profiles  [View] │
│  ▶ Mon 28 Apr 2025, 08:03   6 profiles  [View] │
│  ▶ Mon 21 Apr 2025, 08:01   5 profiles  [View] │
└─────────────────────────────────────────────────┘
```

### Report View (`/report/<run_id>`)
Full report for the selected run:

```
┌─────────────────────────────────────────────────┐
│  Spotter  ← Back   Report: Mon 05 May 2025 08:00 │
├─────────────────────────────────────────────────┤
│  📘 Facebook — HettichCR                        │
│  New posts: 4   Top engagement: 184 👍  16 💬  │
│  Main message: fast delivery · portfolio · svc  │
│  [📷][📷][📷][📷]  ← clickable thumbnails       │
├─────────────────────────────────────────────────┤
│  📷 Instagram — hettich_official                │
│  New posts: 3   Top engagement: 312 👍  8 💬   │
│  Main message: design · innovation              │
│  [📷][📷][📷]                                   │
├─────────────────────────────────────────────────┤
│  💼 LinkedIn — Henkel                           │
│  New posts: 5   Top engagement: 97 👍  22 💬   │
│  Main message: culture · sustainability         │
│  [📷][📷][📷][📷][📷]                           │
└─────────────────────────────────────────────────┘
```

---

## 8. Definition of Done

The project is considered complete when:

1. ✅ `python main.py` runs through all profiles in `config.yaml` without errors
2. ✅ Each profile entry includes: post count, top post, engagement, main message
3. ✅ Each new post has a screenshot saved under `reports/YYYY-MM-DD_HH-MM/screenshots/`
4. ✅ Each run produces a valid `data.json` with all collected data
5. ✅ `python web/app.py` starts a local server at `http://localhost:5000`
6. ✅ The dashboard lists all past runs sorted newest first
7. ✅ Clicking a run opens the full report with screenshots visible in the browser
8. ✅ A failure on one profile does not stop processing of the remaining profiles
9. ✅ LinkedIn login works via environment variables
10. ✅ `README.md` includes instructions for installation, running the scraper, and starting the web UI
