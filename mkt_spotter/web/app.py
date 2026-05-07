from __future__ import annotations

import json
import os
import sys

from flask import Flask, abort, render_template, send_from_directory

# Allow imports from project root when run as `python web/app.py`
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

REPORTS_DIR = os.path.join(os.path.dirname(__file__), "..", "reports")

app = Flask(__name__, template_folder="templates", static_folder="static")


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
            runs.append({
                "run_id": entry,
                "run_at": data.get("run_at", entry),
                "profile_count": len(data.get("profiles", [])),
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
    all_runs = _list_runs()
    run_ids = [r["run_id"] for r in all_runs]
    idx = run_ids.index(run_id) if run_id in run_ids else -1
    prev_run = run_ids[idx + 1] if idx >= 0 and idx + 1 < len(run_ids) else None
    next_run = run_ids[idx - 1] if idx > 0 else None
    return render_template("report.html", data=data, run_id=run_id, prev_run=prev_run, next_run=next_run)


@app.route("/reports/<run_id>/screenshots/<filename>")
def screenshot(run_id: str, filename: str):
    screenshots_dir = os.path.join(REPORTS_DIR, run_id, "screenshots")
    return send_from_directory(screenshots_dir, filename)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8013))
    app.run(host="127.0.0.1", port=port, debug=False)
