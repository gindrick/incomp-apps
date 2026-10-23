import os

import pytest
from fastapi.testclient import TestClient

from semafor.app import create_app
from semafor.assets import AssetStore
from semafor.config import Settings
from semafor.db import init_schema, make_engine
from semafor.docstore.store import DocumentStore

W = {"X-Semafor-Request": "1"}


def make_settings(tmp_path, **kw) -> Settings:
    base = dict(environment="development", auth_mode="dev", public_url="http://testserver/semafor",
                database_url=f"sqlite:///{tmp_path / 'test.db'}", session_secret="x" * 40, change_poll_interval_s=0.2,
                sse_heartbeat_s=0.5)
    base.update(kw)
    return Settings(_env_file=None, **base)


@pytest.fixture
def settings(tmp_path):
    return make_settings(tmp_path)


# Testy úložiště jdou pustit i proti skutečnému SQL Serveru (PRÁZDNÁ testovací databáze, tabulky se vyčistí!):
#   SEMAFOR_TEST_DATABASE_URL="mssql+pyodbc://@SRV/semafor_ci?driver=ODBC+Driver+18+for+SQL+Server&trusted_connection=yes&TrustServerCertificate=yes"
TEST_DB_URL = os.environ.get("SEMAFOR_TEST_DATABASE_URL")


def _wipe(engine):
    from semafor.db import metadata
    with engine.begin() as conn:
        for t in reversed(metadata.sorted_tables):
            conn.execute(t.delete())


@pytest.fixture
def store(settings):
    engine = make_engine(TEST_DB_URL or settings.database_url)
    if TEST_DB_URL:
        init_schema(engine)
        _wipe(engine)
    init_schema(engine)
    return DocumentStore(engine, max_doc_bytes=settings.max_doc_bytes, max_lease_ttl_ms=settings.max_lease_ttl_ms)


@pytest.fixture
def assets(store, settings):
    return AssetStore(store.engine, settings)


@pytest.fixture
def app(settings):
    return create_app(settings)


def login(app, user):
    c = TestClient(app, base_url="http://testserver")
    c.__enter__()
    r = c.get(f"/semafor/auth/dev-login?u={user}", follow_redirects=False)
    assert r.status_code == 303
    return c


@pytest.fixture
def alice(app):   # správce
    c = login(app, "alice"); yield c; c.__exit__(None, None, None)


@pytest.fixture
def bob(app):     # uživatel
    c = login(app, "bob"); yield c; c.__exit__(None, None, None)


@pytest.fixture
def cyril(app):   # čtenář
    c = login(app, "cyril"); yield c; c.__exit__(None, None, None)
