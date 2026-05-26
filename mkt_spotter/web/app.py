from __future__ import annotations

import json
import os
import sys

from dotenv import load_dotenv
from flask import Flask, abort, render_template, send_from_directory

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

# Allow imports from project root when run as `python web/app.py`
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

REPORTS_DIR = os.path.join(os.path.dirname(__file__), "..", "reports")

app = Flask(__name__, template_folder="templates", static_folder="static")

_PLATFORM_ABBR = {"facebook": "FB", "instagram": "IG", "linkedin": "LI"}
_PLATFORM_ORDER = ["FB", "IG", "LI"]


def _list_runs() -> list[dict]:
    runs = []
    if not os.path.isdir(REPORTS_DIR):
        return runs
    for entry in sorted(os.listdir(REPORTS_DIR), reverse=True):
        run_dir = os.path.join(REPORTS_DIR, entry)
        data_file = os.path.join(run_dir, "data.json")
        if not os.path.isfile(data_file):
            continue
        try:
            with open(data_file, encoding="utf-8") as f:
                data = json.load(f)
            profiles = data.get("profiles", [])
            counts: dict[str, int] = {}
            total_posts = 0
            for p in profiles:
                abbr = _PLATFORM_ABBR.get(p.get("platform", ""), "?")
                counts[abbr] = counts.get(abbr, 0) + 1
                total_posts += p.get("new_posts_count", 0)
            parts = [f"{counts[a]} {a}" for a in _PLATFORM_ORDER if a in counts]
            parts += [f"{n} {a}" for a, n in counts.items() if a not in _PLATFORM_ORDER]
            status = data.get("status") or (
                "partial" if any(p.get("error") for p in profiles) else "success"
            )
            runs.append({
                "run_id": entry,
                "run_at": data.get("run_at", entry),
                "profile_count": len(profiles),
                "total_posts": total_posts,
                "platform_summary": " · ".join(parts),
                "status": status,
            })
        except Exception:
            continue
    return runs


def _load_run(run_id: str) -> dict:
    data_file = os.path.join(REPORTS_DIR, run_id, "data.json")
    if not os.path.isfile(data_file):
        abort(404)
    with open(data_file, encoding="utf-8") as f:
        return json.load(f)


@app.route("/")
def index():
    runs = _list_runs()
    return render_template("index.html", runs=runs)


@app.route("/report/<run_id>")
def report(run_id: str):
    data = _load_run(run_id)
    for profile in data.get("profiles", []):
        profile["total_engagement"] = sum(
            p.get("reactions", 0) + p.get("comments", 0) + p.get("shares", 0)
            for p in profile.get("posts", [])
        )
    all_runs = _list_runs()
    run_ids = [r["run_id"] for r in all_runs]
    idx = run_ids.index(run_id) if run_id in run_ids else -1
    prev_run = run_ids[idx + 1] if idx >= 0 and idx + 1 < len(run_ids) else None
    next_run = run_ids[idx - 1] if idx > 0 else None
    return render_template("report.html", data=data, run_id=run_id, prev_run=prev_run, next_run=next_run)


@app.route("/report/<run_id>/profile/<platform>/<profile_name>")
def profile_detail(run_id: str, platform: str, profile_name: str):
    data = _load_run(run_id)
    profile = next(
        (p for p in data.get("profiles", [])
         if p["platform"] == platform and p["profile"] == profile_name),
        None,
    )
    if profile is None:
        abort(404)
    posts = sorted(profile.get("posts", []), key=lambda p: p["published_at"], reverse=True)
    return render_template("profile.html", profile=profile, posts=posts, run_id=run_id)


@app.route("/reports/<run_id>/screenshots/<filename>")
def screenshot(run_id: str, filename: str):
    screenshots_dir = os.path.join(REPORTS_DIR, run_id, "screenshots")
    return send_from_directory(screenshots_dir, filename)


class _ScriptNameMiddleware:
    """Mounts the app under a prefix path.

    Sets SCRIPT_NAME so url_for() generates prefix-correct paths, and also strips
    the prefix from PATH_INFO when present — so both direct access (localhost:8013/spotter/)
    and proxy access (router strips prefix, forwards / to localhost:8013/) work correctly.
    """

    def __init__(self, wsgi_app: object, script_name: str) -> None:
        self._wsgi_app = wsgi_app
        self._script_name = script_name.rstrip("/")

    def __call__(self, environ: dict, start_response: object) -> object:
        environ["SCRIPT_NAME"] = self._script_name
        path = environ.get("PATH_INFO", "")
        if path.startswith(self._script_name + "/"):
            environ["PATH_INFO"] = path[len(self._script_name):]
        elif path == self._script_name:
            environ["PATH_INFO"] = "/"
        return self._wsgi_app(environ, start_response)


script_name = os.environ.get("SCRIPT_NAME", "")
if script_name:
    app.wsgi_app = _ScriptNameMiddleware(app.wsgi_app, script_name)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8013))
    app.run(host="0.0.0.0", port=port, debug=False)
