# JJA — Workspace

Monorepo for AI and HR applications. Shared infrastructure (MCP, LiteLLM, Router) runs as common services for all projects. Each project is accessible via a central reverse proxy on port **8000**.

---

## Root Structure

```
c:\jja\
├── 01_mcp/              Shared MCP server — all tools for AI agents
├── 02_litellm/          Shared LiteLLM proxy — unified access to LLM providers
├── 03_router/           Reverse proxy — routes URL paths to internal services (port 8000)
├── 04_scripts/          Utility scripts — start and stop all services
│
├── react_assistant/     Project: AI agents (ReAct, Plan-Execute, Workflow) + SharePoint
├── hr_hiring/           Project: HR hiring platform (backend + React frontend)
├── production_cards/    Project: Production Cards — data extraction from PDF setup cards
├── hr_demo/             Project: HR demo dashboard
├── ollama_hrx/          Project: Ollama local LLM application (standalone)
│
├── .env                 Global API keys (not in git)
└── .env.example         Global .env template
```

---

## Ports

| Port | Service | Description |
|------|---------|-------------|
| **8000** | `03_router` | Entry point — all projects through this port |
| 8001 | `react_assistant` | Web UI for AI agents |
| 8002 | `01_mcp` | MCP server |
| 8003 | `hr_demo` | HR demo dashboard |
| 4000 | `02_litellm` | LiteLLM proxy |
| 8010 | `hr_hiring` backend | HR hiring API |
| 5173 | `hr_hiring` frontend | React dev server |
| 8011 | `production_cards` backend | Production Cards API |
| 5174 | `production_cards` frontend | React dev server |

---

## Project URLs

All via the router at `http://localhost:8000`:

| URL | Project |
|-----|---------|
| `http://localhost:8000/react_assistant` | React Assistant |
| `http://localhost:8000/dashboard` | HR Demo |
| `http://localhost:8000/hr_hiring` | HR Hiring (frontend) |
| `http://localhost:8000/hr_hiring_api` | HR Hiring (API) |
| `http://localhost:8000/production_cards` | Production Cards (frontend) |
| `http://localhost:8000/production_cards_api` | Production Cards (API) |

> `ollama_hrx` is not yet routed — it starts standalone.

---

## Starting Services

```powershell
# Starts all shared services + projects in the background (no windows)
./04_scripts/start-all.ps1

# Shows the status of each service (port, uptime)
./04_scripts/status.ps1

# Stops everything and restarts
./04_scripts/restart.ps1
```

> On server boot, `start-all.ps1` runs automatically via Windows Scheduled Task `JJA\StartAll` (with a 30s delay after boot).

---

## Monitoring & Teams Notifications

A watchdog (`monitor.ps1`) runs every 2 minutes via Windows Scheduled Task. It checks each service, restarts any that are down, and sends a Teams alert if a restart fails. Spotter also posts a card when a new report is successfully generated.

### What triggers a notification

| Event | Card colour |
|-------|-------------|
| Service fails to restart after watchdog attempt | 🔴 Red alert |
| Spotter run completes — all profiles scraped OK | 🟢 Green success |

### Step 1 — Create a Teams Incoming Webhook

1. Open the target Teams channel → **···** → **Connectors** → **Incoming Webhook** → **Configure**
2. Give it a name (e.g. `JJA Monitor`) and click **Create**
3. Copy the generated webhook URL

### Step 2 — Paste the URL into monitor-config.ps1

```powershell
# C:\jja\04_scripts\monitor-config.ps1
$TeamsWebhookUrl = "https://hranipexcom.webhook.office.com/webhookb2/..."
```

This is the single source of truth — both the watchdog (`monitor.ps1`) and Spotter (`notify-spotter.ps1`) read it from here.

### Step 3 — Register the watchdog Scheduled Task

Run once as Administrator:

```powershell
cd C:\jja
.\04_scripts\register-monitor-task.ps1
```

This registers `JJA-Monitor` to fire every 2 minutes. Test immediately with:

```powershell
schtasks /run /tn JJA-Monitor
```

Logs are written to `C:\jja\logs\monitor.log`.

### Optional — Spotter "View Report" link in the card

Add `REPORT_BASE_URL` to `mkt_spotter\.env` so the Teams card includes a clickable link:

```env
# C:\jja\mkt_spotter\.env
REPORT_BASE_URL=http://SERVER_IP/spotter
```

If omitted, the card still shows run ID, platforms, and post count — just without the link.

---

## Configuration (.env)

Configuration is layered — global keys at the root, project-specific values in each project:

```
c:\jja\.env                ← global (OPENAI_API_KEY, ANTHROPIC_API_KEY, ...)
c:\jja\01_mcp\.env         ← MCP-specific (MSSQL, TAVILY, WOLFRAM)
c:\jja\02_litellm\.env     ← LiteLLM-specific (LITELLM_MASTER_KEY, OLLAMA_API_BASE)
c:\jja\<project>\.env      ← project-specific (MODEL=..., MCP_TOOLS=..., ...)
```

Every directory contains a `.env.example` as a template. Never commit `.env` files.

---

## Adding a New Project

### 1. Create the project folder

```
c:\jja\<project_name>\
├── .env.example     ← document required variables
├── .env
├── pyproject.toml   (or package.json for Node)
└── README.md
```

### 2. Choose a free port

See the port table above. The app must listen on `127.0.0.1` (or `0.0.0.0` if you need network access).

### 3. Register the project in the router

Add an entry to [03_router/apps.json](03_router/apps.json):

```json
{
  "path": "name_in_url",
  "target": "http://127.0.0.1:8020",
  "strip_prefix": false,
  "description": "Project description"
}
```

> The router loads `apps.json` dynamically — **no router restart needed**.

### 4. Add the project to start-all.ps1

In [04_scripts/start-all.ps1](04_scripts/start-all.ps1) add a block at the end of the `# --- Projects ---` section:

```powershell
Start-Service-Background `
    -Name "project-name" `
    -WorkDir "$root\project_name" `
    -Command "uv run python -m uvicorn main:app --host 127.0.0.1 --port 8020"
```

And in the port listing at the end of the file:

```powershell
Write-Host "  8020 - Project Name"
```

### 5. Add the project to status.ps1

In [04_scripts/status.ps1](04_scripts/status.ps1) add a line to the `$services` array:

```powershell
@{ Name = "project-name"; Port = 8020; Desc = "Project description" }
```

### 6. Set up .env

If the project needs shared services, add to the project's `.env`:

```env
LITELLM_BASE_URL=http://127.0.0.1:4000    # LiteLLM proxy
LITELLM_API_KEY=sk-mysecretkey
MCP_SERVER_URL=http://127.0.0.1:8002/mcp  # MCP server
```

---

## Current Projects

### react_assistant
AI agents with various reasoning patterns (ReAct, Plan-Execute, Workflow). Includes a SharePoint ingestion pipeline and Chroma vector DB for retrieval. Web UI accessible via the router.

### hr_hiring
Full HR hiring platform. FastAPI backend with LangGraph workflow for AI candidate evaluation, React + Vite frontend with Azure AD (MSAL) authentication.

### production_cards
Data extraction from PDF setup cards for extrusion lines. FastAPI backend with LiteLLM extraction (PyMuPDF + LLM structured output), React + Vite frontend with split-view (PDF preview | editing), export to XLSX. MSSQL schema `production_cards`.

### hr_demo
Simple HR demo dashboard. FastAPI backend with a static frontend.

### ollama_hrx
Standalone application built on Ollama local LLM. Has its own web UI and knowledge base. Not yet integrated into the router.
