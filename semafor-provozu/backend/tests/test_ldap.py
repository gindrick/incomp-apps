"""Přihlášení přes LDAP (Active Directory) proti podvrženému serveru."""
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from ldap3.core.exceptions import LDAPSocketOpenError

from conftest import make_settings
from semafor import ldap_auth
from semafor.app import create_app

# uživatelské jméno → (heslo, mail, displayName)
AD = {
    "jan.kratky": ("tajne", "Jan.Kratky@hranipex.com", "Jan Krátký"),
    "petr.user": ("heslo2", "petr.user@hranipex.com", "Petr Uživatel"),
    "bez.mailu": ("heslo3", None, "Bez Mailu"),
    "nikdo": ("heslo4", "nikdo@hranipex.com", "Nikdo"),
}


class FakeConnection:
    def __init__(self, upn, password):
        self.upn, self.password, self.bound, self.entries, self.filter = upn, password, False, [], None

    def bind(self):
        sam, _, domain = self.upn.partition("@")
        self.bound = domain == "hranipex.net" and sam in AD and AD[sam][0] == self.password
        return self.bound

    def search(self, base, search_filter, *_a, **_k):
        assert base == "DC=hranipex,DC=net"
        self.filter = search_filter
        sam = search_filter[len("(sAMAccountName="):-1]
        if sam in AD:
            _, mail, name = AD[sam]
            attrs = {"displayName": [name], **({"mail": [mail]} if mail else {})}
            self.entries = [SimpleNamespace(entry_attributes_as_dict=attrs)]

    def unbind(self):
        self.bound = False


@pytest.fixture
def fake_ad(monkeypatch):
    calls = []

    def connect(_settings, upn, password):
        conn = FakeConnection(upn, password)
        calls.append(conn)
        return conn

    monkeypatch.setattr(ldap_auth, "connect", connect)
    return calls


@pytest.fixture
def ldap_settings(tmp_path):
    return make_settings(tmp_path, auth_mode="ldap", ldap_server="hranipex.net", ldap_domain="hranipex.net",
                         ldap_admins=["jan.kratky"], ldap_users=["petr.user@hranipex.com"], ldap_readers=[])


@pytest.fixture
def client(ldap_settings, fake_ad):
    with TestClient(create_app(ldap_settings), base_url="http://testserver") as c:
        yield c


def post_login(c, username, password, **headers):
    return c.post("/semafor/auth/login", data={"username": username, "password": password, "next": "/semafor/"},
                  headers=headers, follow_redirects=False)


def test_normalize_username():
    for raw in ("jan.kratky", " Jan.Kratky ", "HRANIPEX\\jan.kratky", "jan.kratky@hranipex.net"):
        assert ldap_auth.normalize_username(raw) == "jan.kratky"


def test_login_page_is_form(client):
    r = client.get("/semafor/auth/login")
    assert r.status_code == 200 and "name='password'" in r.text and "/semafor/auth/login" in r.text
    assert "/semafor/favicon.svg" in r.text


def test_admin_login_uses_email_from_ad(client):
    r = post_login(client, "HRANIPEX\\Jan.Kratky", "tajne")
    assert r.status_code == 303 and r.headers["location"] == "/semafor/"
    me = client.get("/semafor/api/me").json()
    assert me["id"] == me["email"] == "jan.kratky@hranipex.com"
    assert me["name"] == "Jan Krátký" and me["isOwner"] is True


def test_role_by_email(client):
    post_login(client, "petr.user", "heslo2")
    me = client.get("/semafor/api/me").json()
    assert me["canEdit"] is True and me["isOwner"] is False


def test_wrong_password(client):
    r = post_login(client, "jan.kratky", "spatne")
    assert r.status_code == 401 and "Neplatné" in r.text
    assert client.get("/semafor/api/me").status_code == 401


def test_empty_password_never_reaches_ad(client, fake_ad):
    assert post_login(client, "jan.kratky", "").status_code == 401
    assert fake_ad == []


def test_account_without_mail_rejected(client):
    assert post_login(client, "bez.mailu", "heslo3").status_code == 401


def test_user_without_role_has_no_access(client):
    assert post_login(client, "nikdo", "heslo4").status_code == 303
    assert client.get("/semafor/api/me").status_code == 403


def test_role_revoked_without_relogin(client, ldap_settings):
    post_login(client, "jan.kratky", "tajne")
    ldap_settings.ldap_admins = []
    assert client.get("/semafor/api/me").status_code == 403


def test_search_filter_is_escaped(client, fake_ad, monkeypatch):
    monkeypatch.setitem(AD, "a*)(cn=*", ("x", "a@hranipex.com", "A"))
    assert post_login(client, "a*)(cn=*", "x").status_code == 401  # účet se nenašel, filtr se nerozšířil
    assert fake_ad[-1].filter == "(sAMAccountName=a\\2a\\29\\28cn=\\2a)"


def test_ldap_unavailable(client, monkeypatch):
    def down(*_a):
        raise LDAPSocketOpenError("unreachable")
    monkeypatch.setattr(ldap_auth, "connect", down)
    r = post_login(client, "jan.kratky", "tajne")
    assert r.status_code == 503 and "nedostupný" in r.text


def test_foreign_origin_rejected(client):
    r = post_login(client, "jan.kratky", "tajne", origin="http://evil.example")
    assert r.status_code == 403
    assert client.get("/semafor/api/me").status_code == 401


def test_open_redirect_blocked(client):
    r = client.post("/semafor/auth/login", data={"username": "jan.kratky", "password": "tajne", "next": "//evil.example/x"},
                    follow_redirects=False)
    assert r.headers["location"] == "/semafor/"


def test_post_login_disabled_outside_ldap(app):
    with TestClient(app) as c:
        assert c.post("/semafor/auth/login", data={"username": "a", "password": "b"}).status_code == 404


def test_config_guards(tmp_path):
    with pytest.raises(ValueError, match="LDAP"):
        make_settings(tmp_path, auth_mode="ldap")
    prod = dict(environment="production", auth_mode="ldap", public_url="http://erp.hranipex.net:8000/semafor",
                ldap_server="hranipex.net", ldap_domain="hranipex.net")
    with pytest.raises(ValueError, match="https"):
        make_settings(tmp_path, **prod)
    assert make_settings(tmp_path, allow_insecure_http=True, **prod).secure_cookies is False


def test_shared_entra_values_and_override(tmp_path):
    from semafor.config import Settings
    shared, own = tmp_path / "shared.env", tmp_path / "own.env"
    shared.write_text("ENTRA_TENANT_ID=tenant\nENTRA_CLIENT_ID=shared-client\nOPENAI_API_KEY=ignored\n", encoding="utf-8")
    own.write_text("SEMAFOR_OIDC_CLIENT_ID=own-client\n", encoding="utf-8")
    s = Settings(_env_file=(shared, own))
    assert s.oidc_tenant_id == "tenant" and s.oidc_client_id == "own-client"
