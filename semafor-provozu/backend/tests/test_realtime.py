"""Proud změn (SSE) doručí změnu jiného uživatele."""
import json
import threading
import time

from conftest import W, login, make_settings
from semafor.app import create_app


def test_stream_delivers_change(tmp_path):
    app = create_app(make_settings(tmp_path, sse_max_duration_s=3, sse_heartbeat_s=0.3))
    alice, bob = login(app, "alice"), login(app, "bob")
    since = alice.get("/semafor/api/changes?since=0").json()["seq"]
    got = {}

    def reader():
        with alice.stream("GET", f"/semafor/api/stream?since={since}") as r:
            for line in r.iter_lines():
                if line.startswith("data:") and any(c["path"] == "tasks/live" for c in json.loads(line[5:])["changes"]):
                    got["ok"] = time.monotonic()

    t = threading.Thread(target=reader, daemon=True)
    t.start()
    time.sleep(0.3)
    bob.put("/semafor/api/docs/tasks/live", json={"data": {"title": "živě"}}, headers=W)
    t.join(timeout=6)
    assert got.get("ok"), "změna nepřišla proudem"
    # latenci TestClient neměří (tělo odpovědi bufferuje); v prohlížeči ji měří tests/e2e/smoke.cjs
