"""Databázové schéma a připojení (SQLAlchemy Core).

Cílová databáze je MS SQL Server / Azure SQL; testy běží nad SQLite.
Typy jsou zvolené tak, aby na SQL Serveru vznikly NVARCHAR / NVARCHAR(MAX) /
VARBINARY(MAX) / BIGINT / BIT. Ruční DDL pro DBA je v ``sql/001_schema_mssql.sql``.
"""
from __future__ import annotations

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    Index,
    Integer,
    LargeBinary,
    MetaData,
    Table,
    Unicode,
    UnicodeText,
    create_engine,
    event,
    insert,
    select,
)
from sqlalchemy.dialects import mssql
from sqlalchemy.engine import Engine

metadata = MetaData()

# Na SQL Serveru výslovně NVARCHAR(MAX) / VARBINARY(MAX) (ne zastaralé NTEXT / IMAGE).
JsonText = UnicodeText().with_variant(mssql.NVARCHAR(None), "mssql")
Blob = LargeBinary().with_variant(mssql.VARBINARY(None), "mssql")

# Cesty a id dokumentů se porovnávají přesně (velká/malá písmena), nezávisle na výchozí collation databáze.
def PathText(length: int):
    return Unicode(length).with_variant(mssql.NVARCHAR(length, collation="Latin1_General_100_BIN2"), "mssql")


# Zámek čteného řádku do konce transakce. SQL Server ignoruje FOR UPDATE, proto tabulková nápověda;
# HOLDLOCK zamkne i dosud neexistující klíč (souběžné založení téže cesty se seřadí).
MSSQL_LOCK_HINT = "WITH (UPDLOCK, HOLDLOCK, ROWLOCK)"

# Jeden řádek = jeden dokument (JSON). Cesta má tvar <kolekce>/<id>[/<podkolekce>/<id>...].
documents = Table(
    "sp_documents",
    metadata,
    Column("path", PathText(450), primary_key=True),
    Column("collection", PathText(400), nullable=False),
    Column("doc_id", PathText(200), nullable=False),
    Column("data", JsonText, nullable=False),
    Column("version", Integer, nullable=False),
    Column("seq", BigInteger, nullable=False),          # globální pořadí změn (živé změny, export)
    Column("deleted", Boolean, nullable=False, default=False),
    Column("created_at", BigInteger, nullable=False),
    Column("updated_at", BigInteger, nullable=False),
    Column("updated_by", Unicode(320), nullable=False, default=""),
)
Index("ix_sp_documents_collection", documents.c.collection, documents.c.deleted)
Index("ix_sp_documents_seq", documents.c.seq)

# Čítač změn. Zvýšení řádku drží zámek do konce transakce, takže čísla seq se
# potvrzují ve stejném pořadí, v jakém vznikla (čtenář živých změn nic nepřeskočí).
counters = Table(
    "sp_counters",
    metadata,
    Column("name", Unicode(50), primary_key=True),
    Column("value", BigInteger, nullable=False),
)

# Kooperativní zámky (lease) na dokumenty: kdo drží, do kdy.
leases = Table(
    "sp_leases",
    metadata,
    Column("path", PathText(450), primary_key=True),
    Column("holder", Unicode(200), nullable=False),
    Column("expires_at", BigInteger, nullable=False),
)

# Lidé, kteří se přihlásili (adresář pro našeptávač a jména).
users = Table(
    "sp_users",
    metadata,
    Column("id", Unicode(64), primary_key=True),        # Entra ID object id (oid)
    Column("email", Unicode(320), nullable=False, index=True),
    Column("name", Unicode(200), nullable=False, default=""),
    Column("roles", Unicode(400), nullable=False, default=""),
    Column("first_seen", BigInteger, nullable=False),
    Column("last_seen", BigInteger, nullable=False),
)

# Přílohy (dříve schopnost "assets" platformy).
assets = Table(
    "sp_assets",
    metadata,
    Column("id", PathText(64), primary_key=True),
    Column("filename", Unicode(260), nullable=False),
    Column("content_type", Unicode(100), nullable=False),
    Column("size_bytes", BigInteger, nullable=False),
    Column("sha256", Unicode(64), nullable=False),
    Column("data", Blob, nullable=False),
    Column("created_at", BigInteger, nullable=False),
    Column("created_by", Unicode(320), nullable=False),
)

# Provozní záznam zápisů (kdo, kdy, co). Historie v aplikaci není audit, tohle ano.
audit_log = Table(
    "sp_audit_log",
    metadata,
    Column("id", BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True),
    Column("at", BigInteger, nullable=False, index=True),
    Column("user_id", Unicode(64), nullable=False),
    Column("user_email", Unicode(320), nullable=False),
    Column("op", Unicode(20), nullable=False),
    Column("path", Unicode(450), nullable=False, index=True),
    Column("version", Integer, nullable=True),
    Column("bytes", Integer, nullable=True),
)

COUNTER_DOCS = "docs"


def make_engine(url: str, *, pool_size: int = 10, echo: bool = False) -> Engine:
    kwargs: dict = {"echo": echo, "future": True}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False, "timeout": 30}
    else:
        kwargs.update(pool_size=pool_size, max_overflow=pool_size, pool_pre_ping=True, pool_recycle=1800)
        if url.startswith("mssql"):
            kwargs["fast_executemany"] = True
    engine = create_engine(url, **kwargs)
    if url.startswith("sqlite"):
        _sqlite_serializable_writes(engine)
    return engine


def _sqlite_serializable_writes(engine: Engine) -> None:
    """SQLite: každá transakce začíná BEGIN IMMEDIATE (zápisy se řadí, žádné ztracené update)."""

    @event.listens_for(engine, "connect")
    def _on_connect(dbapi_conn, _record):
        dbapi_conn.isolation_level = None
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()

    @event.listens_for(engine, "begin")
    def _on_begin(conn):
        conn.exec_driver_sql("BEGIN IMMEDIATE")


def init_schema(engine: Engine) -> None:
    """Založí chybějící tabulky a čítač. Idempotentní."""
    metadata.create_all(engine)
    with engine.begin() as conn:
        exists = conn.execute(select(counters.c.value).where(counters.c.name == COUNTER_DOCS)).first()
        if not exists:
            conn.execute(insert(counters).values(name=COUNTER_DOCS, value=0))
