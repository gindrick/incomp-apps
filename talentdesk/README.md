# TalentDesk

Internal HR tool for managing recruitment campaigns and AI-assisted candidate evaluation.

**URL:** http://192.168.41.43:8000/talentdesk/

---

## Login

Sign in with your company Windows (Active Directory) account — the same username and password you use to log into your computer. No separate registration is needed; your account is created automatically on first login.

---

## Roles

| Role | What they can do |
|------|-----------------|
| **Admin** | Full access — create job descriptions, create recruitments, manage user access, see salary data |
| **User** | View and work with recruitments they have been granted access to; salary fields are hidden |

---

## Workflow overview

```
Job Description → Recruitment → Candidates → Documents → AI Evaluation
```

---

## 1. Job Descriptions (admin only)

Job descriptions are the templates that define a role. They are reused across multiple recruitment campaigns.

**Navigate to:** Pozice (top navigation)

**To create a new JD:**
1. Click **+ Nová pozice**
2. Fill in the title, department, salary range, and the full job description text
3. Click **Uložit**

The JD text is passed verbatim to the AI when evaluating candidates, so the more detailed it is, the better the evaluation quality.

---

## 2. Recruitments

A recruitment campaign ties a job description to a pool of candidates.

**Navigate to:** Nábory (top navigation)

**To create a recruitment (admin only):**
1. Click **+ Nový nábor**
2. Enter a campaign name and select a job description
3. Click **Vytvořit**

**Statuses:**
- `Aktivní` — open campaign
- `Pozastaveno` — paused
- `Uzavřeno` — closed

---

## 3. Candidates

Candidates belong to a recruitment campaign.

**To add a candidate:**
1. Open a recruitment
2. Click **+ Přidat kandidáta**
3. Fill in name, email, phone, and age (name is the only required field)
4. Click **Přidat**

**Candidate statuses** (change via the candidate detail modal):

| Status | Meaning |
|--------|---------|
| Nový | Just added |
| V procesu | Actively considered |
| Pohovor | Interview scheduled/done |
| Nabídka | Offer extended |
| Přijat | Hired |
| Odmítnut | Rejected |

**Sorting and filtering** — use the dropdowns above the candidate list to sort by name, rating, or status, or filter to show only one status.

---

## 4. Candidate detail modal

Click on a candidate's name or the **Detail** button to open the modal. It has four tabs:

### Přehled (Overview)
- Change the candidate's status
- View the AI-generated summary, strengths, weaknesses, match analysis with the JD, and recommended interview questions (available after evaluation)

### Dokumenty (Documents)
- Drag and drop files onto the upload zone, or click to browse
- Supported formats: **PDF, DOCX, TXT, MD** — max 20 MB per file
- Text is extracted automatically in the background
- Duplicate files are detected by content hash and rejected (you will see "Soubor již byl nahrán")
- Click **Zobrazit** to open a document in a new tab
- Click **Smazat** to soft-delete a document (triggers re-evaluation flag)

### AI hodnocení (AI Evaluation)
- Shows the overall AI rating (0–10 scale) and a per-skill breakdown
- To run an evaluation: upload at least one document first, then click **Spustit hodnocení** (or **Přehodnotit** if one already exists)
- Evaluation runs in the background — the page polls every 2 seconds and refreshes automatically when done
- The **🔄 Hodnotit** button appears on the candidate card in the list whenever documents have changed since the last evaluation
- Admins also see AI-detected salary figures (current and expected)

### Moje hodnocení (My overrides)
- Shows all manual adjustments made to skill ratings
- To adjust a skill rating: go to the **AI hodnocení** tab, change the value in the **Moje** column, and the change saves automatically on blur

---

## 5. AI evaluation details

The AI reads all uploaded documents and the job description, then produces:

- **Overall rating** — 0 to 10
- **Summary** — 2–3 sentence narrative
- **Strengths / Weaknesses** — bullet lists
- **JD match analysis** — how well the candidate fits the role
- **Skill ratings** — per-skill scores with evidence snippets
- **Skill tags** — matched skills (shown as green tags on the candidate card)
- **Missing skill tags** — required skills not found (shown as red tags)
- **Recommended interview questions** — tailored to the candidate's profile
- **Salary estimate** — current and expected (admin only)

Re-evaluation is triggered automatically when new documents are uploaded. Previous manual overrides carry forward to the new evaluation.

---

## 6. Access management (admin only)

By default only admins see all recruitments. To give a regular user access to a specific campaign:

1. Open the recruitment detail page
2. Scroll to **Přístupy ke kampani** at the bottom
3. Select a user from the dropdown and click **Přidat přístup**
4. To remove access, click **Odebrat** next to the user's name

---

## Administration

### Starting / restarting the service

```powershell
# From C:\jja
.\04_scripts\start-all.ps1   # start all services including TalentDesk
.\04_scripts\status.ps1      # check which services are running
```

Logs: `C:\jja\logs\talentdesk.log`

### Environment configuration

All settings live in `C:\jja\talentdesk\.env`. Key variables:

| Variable | Description |
|----------|-------------|
| `ENV` | `prod` or `dev` |
| `DEV_AUTH_BYPASS` | Set to `true` to skip LDAP (dev only, ignored when `ENV=prod`) |
| `LDAP_ALLOWED_USERS` | Comma-separated whitelist of usernames; empty = all AD users allowed |
| `LITELLM_MODEL` | AI model used for evaluation (default: `gpt-4o-mini`) |
| `LITELLM_MAX_TOKENS` | Max tokens for evaluation response (default: 2000) |
| `MAX_UPLOAD_SIZE_MB` | Upload size limit (default: 20) |

### Database

MSSQL at `192.168.41.43`, database `talentdesk`. Tables are created automatically on first startup (`AUTO_CREATE_SCHEMA=true`).

### Tech stack

- **Backend:** FastAPI + SQLAlchemy (Python 3.12, managed by `uv`)
- **Frontend:** Jinja2 templates, Tailwind CSS (CDN), HTMX, Alpine.js
- **Auth:** LDAP via `ldap3`
- **AI:** LiteLLM proxy on port 4000 → configured model
- **Port:** 8014 (direct) / `/talentdesk/` via router on port 8000
