"""HTTP vrstva: přihlášení, CSRF, base path, přílohy, stránka a CSP."""
from conftest import W


def test_requires_login(app):
    from fastapi.testclient import TestClient
    with TestClient(app) as c:
        assert c.get("/semafor/api/me").status_code == 401
        assert c.get("/semafor/api/me").json()["code"] == "upstream_auth"
        r = c.get("/semafor/", follow_redirects=False)
        assert r.status_code == 303 and "/semafor/auth/login" in r.headers["location"]


def test_me_roles(alice, bob, cyril):
    assert alice.get("/semafor/api/me").json()["isOwner"] is True
    b = bob.get("/semafor/api/me").json()
    assert b["isOwner"] is False and b["canEdit"] is True
    assert cyril.get("/semafor/api/me").json()["canEdit"] is False


def test_base_path_optional(bob):
    """Směrování může prefix předat i odříznout (prohlížeč ale vždy vidí cestu s prefixem, proto cookie)."""
    assert bob.get("/semafor/api/me").status_code == 200
    cookie = bob.cookies.get("semafor_session")
    assert bob.get("/api/me", headers={"Cookie": f"semafor_session={cookie}"}).status_code == 200


def test_csrf_header_required(bob):
    r = bob.put("/semafor/api/docs/tasks/t1", json={"data": {"a": 1}})
    assert r.status_code == 403
    r = bob.put("/semafor/api/docs/tasks/t1", json={"data": {"a": 1}}, headers={**W, "Origin": "https://evil.example"})
    assert r.status_code == 403
    assert bob.put("/semafor/api/docs/tasks/t1", json={"data": {"a": 1}}, headers=W).status_code == 200


def test_crud_and_changes(bob, alice):
    assert bob.put("/semafor/api/docs/projects/p1", json={"data": {"title": "X"}}, headers=W).json()["version"] == 1
    assert bob.patch("/semafor/api/docs/projects/p1", json={"patch": {"s": 1}}, headers=W).json()["version"] == 2
    assert bob.patch("/semafor/api/docs/projects/nope", json={"patch": {"s": 1}}, headers=W).json()["code"] == "not_found"
    col = alice.get("/semafor/api/collections/projects").json()
    assert col["docs"][0]["data"] == {"title": "X", "s": 1}
    ch = alice.get("/semafor/api/changes?since=0").json()
    assert any(c["path"] == "projects/p1" for c in ch["changes"])
    assert bob.delete("/semafor/api/docs/projects/p1", headers=W).json() == {"ok": True}
    assert alice.get("/semafor/api/docs/projects/p1").json()["exists"] is False


def test_people_upserted_on_login(alice, bob):
    people = alice.get("/semafor/api/collections/people").json()["docs"]
    assert {d["data"]["email"] for d in people} >= {"alice@hranipex.com", "bob@hranipex.com"}
    prof = bob.post("/semafor/api/users/profiles", json={"ids": ["dev-alice", "neznamy"]}).json()
    assert prof["dev-alice"]["name"] == "Alice Testová" and prof["neznamy"]["name"] == ""
    hits = bob.get("/semafor/api/users/search?q=ali").json()
    assert [h["email"] for h in hits] == ["alice@hranipex.com"]


def test_legacy_profile_via_people(alice):
    alice.put("/semafor/api/docs/people/u_old", json={"data": {"email": "alice@hranipex.com"}}, headers=W)
    prof = alice.post("/semafor/api/users/profiles", json={"ids": ["u_old"]}).json()
    assert prof["u_old"]["email"] == "alice@hranipex.com" and prof["u_old"]["name"] == "Alice Testová"


def test_assets(bob, cyril):
    r = bob.post("/semafor/api/assets", files={"file": ("a.png", b"\x89PNG....", "image/png")}, data={"type": "image/png"}, headers=W)
    assert r.status_code == 200, r.text
    aid = r.json()["id"]
    g = cyril.get(f"/semafor/_blob/{aid}")
    assert g.status_code == 200 and g.content == b"\x89PNG...." and "sandbox" in g.headers["content-security-policy"]
    bad = bob.post("/semafor/api/assets", files={"file": ("a.docx", b"x", "application/msword")}, data={"type": "application/msword"}, headers=W)
    assert bad.json()["code"] == "unsupported_type"
    svg = bob.post("/semafor/api/assets", files={"file": ("a.svg", b"<svg/>", "image/svg+xml")}, data={"type": "image/svg+xml"}, headers=W).json()
    assert cyril.get(f"/semafor/_blob/{svg['id']}").headers["content-disposition"].startswith("attachment")
    ro = cyril.post("/semafor/api/assets", files={"file": ("a.png", b"x", "image/png")}, data={"type": "image/png"}, headers=W)
    assert ro.status_code == 403


def test_index_has_config_and_nonce(bob):
    r = bob.get("/semafor/")
    assert r.status_code == 200
    csp = r.headers["content-security-policy"]
    nonce = csp.split("'nonce-")[1].split("'")[0]
    assert f'nonce="{nonce}"' in r.text and "__CSP_NONCE__" not in r.text
    assert 'window.SP_CONFIG={"basePath": "/semafor"' in r.text
    assert "unsafe-inline" not in csp.split("script-src")[1].split(";")[0]


def test_no_role_rejected(tmp_path):
    from conftest import make_settings, login
    from semafor.app import create_app
    s = make_settings(tmp_path, dev_users={"nobody": {"id": "n", "email": "n@x.cz", "name": "N", "roles": []}})
    c = login(create_app(s), "nobody")
    assert c.get("/semafor/api/me").status_code == 403
    assert c.get("/semafor/").status_code == 403


def test_production_guards(tmp_path):
    import pytest
    from conftest import make_settings
    with pytest.raises(ValueError):
        make_settings(tmp_path, environment="production", auth_mode="dev")
    with pytest.raises(ValueError):
        make_settings(tmp_path, environment="production", auth_mode="oidc", public_url="http://x",
                      oidc_tenant_id="t", oidc_client_id="c", oidc_client_secret="s")


def test_open_redirect_blocked(app):
    c = __import__("conftest").login(app, "bob")
    r = c.get("/semafor/auth/dev-login?u=bob&next=//evil.example/x", follow_redirects=False)
    assert r.headers["location"] == "/semafor/"


def test_no_is_comparison_in_sql():
    """SQL Server neumí `IS 0`: booleovské sloupce porovnávat přes == false()/true()."""
    import pathlib
    import re
    src = pathlib.Path(__file__).resolve().parents[1] / "semafor"
    offenders = [str(p) for p in src.rglob("*.py") if re.search(r"\.is_\((True|False)\)", p.read_text(encoding="utf-8"))]
    assert offenders == []


def test_mssql_compiles_locking_and_booleans():
    from sqlalchemy import false, select
    from sqlalchemy.dialects import mssql
    from semafor.db import documents
    from semafor.docstore.store import _locking
    sql = str(_locking(select(documents).where(documents.c.path == "x", documents.c.deleted == false()), documents)
              .compile(dialect=mssql.dialect()))
    assert "WITH (UPDLOCK, HOLDLOCK, ROWLOCK)" in sql and "deleted = 0" in sql and " IS " not in sql


def test_dev_mode_only_in_development(tmp_path):
    import pytest
    from conftest import make_settings
    with pytest.raises(ValueError):
        make_settings(tmp_path, environment="test", auth_mode="dev")


def test_blob_pdf_and_role(tmp_path, bob):
    r = bob.post("/semafor/api/assets", files={"file": ("a.pdf", b"%PDF-1.4", "application/pdf")}, data={"type": "application/pdf"}, headers=W).json()
    g = bob.get(f"/semafor/_blob/{r['id']}")
    assert g.status_code == 200 and "content-security-policy" not in g.headers and g.headers["x-content-type-options"] == "nosniff"
    from conftest import login, make_settings
    from semafor.app import create_app
    s = make_settings(tmp_path, database_url=bob.app.state.settings.database_url,
                      dev_users={"nobody": {"id": "n", "email": "n@x.cz", "name": "N", "roles": []}})
    c = login(create_app(s), "nobody")
    assert c.get(f"/semafor/_blob/{r['id']}").status_code == 403


def test_asset_id_with_dash_roundtrip(assets):
    assets.import_asset("ab-12_x", "x.pdf", "application/pdf", b"%PDF", "migrace")
    assert assets.load("ab-12_x").data == b"%PDF"


def test_favicon_on_every_page(bob, app):
    from fastapi.testclient import TestClient
    r = bob.get("/semafor/favicon.svg")
    assert r.status_code == 200 and r.headers["content-type"].startswith("image/svg+xml") and b"<svg" in r.content
    link = '<link rel="icon" type="image/svg+xml" href="/semafor/favicon.svg">'
    page = bob.get("/semafor/").text
    assert link in page and "<!--SP_ICON-->" not in page
    with TestClient(app) as anon:
        assert anon.get("/semafor/favicon.svg").status_code == 200  # i bez přihlášení (přihlašovací stránka)
        assert link in anon.get("/semafor/auth/login").text
