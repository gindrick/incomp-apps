from __future__ import annotations

import json
from pathlib import Path

from fastapi.templating import Jinja2Templates

from config import ROOT, settings

templates = Jinja2Templates(directory=str(ROOT / "app" / "templates"))
templates.env.filters["fromjson"] = json.loads
templates.env.globals["config"] = settings
templates.env.globals["prefix"] = settings.proxy_prefix
