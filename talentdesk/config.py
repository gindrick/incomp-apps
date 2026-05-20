from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote_plus


def _load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            os.environ[key] = value


ROOT = Path(__file__).resolve().parent
_load_dotenv(ROOT / ".env")
_load_dotenv(ROOT.parent / ".env")


@dataclass(frozen=True)
class Settings:
    env: str
    log_level: str
    backend_host: str
    backend_port: int
    session_secret: str
    session_timeout_hours: int
    auth_mode: str
    dev_auth_bypass: bool
    dev_auth_user_name: str
    dev_auth_user_email: str
    dev_auth_role: str
    ldap_server: str
    ldap_domain: str
    ldap_allowed_users: str
    mssql_host: str
    mssql_port: int
    mssql_db: str
    mssql_user: str
    mssql_password: str
    mssql_driver: str
    auto_create_schema: bool
    litellm_base_url: str
    litellm_api_key: str
    litellm_model: str
    litellm_max_tokens: int
    upload_dir: str
    max_upload_size_mb: int
    proxy_prefix: str

    @property
    def sqlalchemy_url(self) -> str:
        driver = quote_plus(self.mssql_driver)
        return (
            f"mssql+pyodbc://{self.mssql_user}:{quote_plus(self.mssql_password)}"
            f"@{self.mssql_host}:{self.mssql_port}/{self.mssql_db}"
            f"?driver={driver}&TrustServerCertificate=yes"
        )


settings = Settings(
    env=os.getenv("ENV", "dev"),
    log_level=os.getenv("LOG_LEVEL", "INFO"),
    backend_host=os.getenv("BACKEND_HOST", "127.0.0.1"),
    backend_port=int(os.getenv("BACKEND_PORT", "8014")),
    session_secret=os.getenv("SESSION_SECRET", "talentdesk-change-this-key"),
    session_timeout_hours=int(os.getenv("SESSION_TIMEOUT_HOURS", "8")),
    auth_mode=os.getenv("AUTH_MODE", "ldap").lower(),
    dev_auth_bypass=os.getenv("DEV_AUTH_BYPASS", "true").lower() == "true",
    dev_auth_user_name=os.getenv("DEV_AUTH_USER_NAME", "Admin Dev"),
    dev_auth_user_email=os.getenv("DEV_AUTH_USER_EMAIL", "admin@company.local"),
    dev_auth_role=os.getenv("DEV_AUTH_ROLE", "admin"),
    ldap_server=os.getenv("LDAP_SERVER", ""),
    ldap_domain=os.getenv("LDAP_DOMAIN", ""),
    ldap_allowed_users=os.getenv("LDAP_ALLOWED_USERS", ""),
    mssql_host=os.getenv("MSSQL_HOST", "localhost"),
    mssql_port=int(os.getenv("MSSQL_PORT", "1433")),
    mssql_db=os.getenv("MSSQL_DB", "talentdesk"),
    mssql_user=os.getenv("MSSQL_USER", "sa"),
    mssql_password=os.getenv("MSSQL_PASSWORD", ""),
    mssql_driver=os.getenv("MSSQL_DRIVER", "ODBC Driver 17 for SQL Server"),
    auto_create_schema=os.getenv("AUTO_CREATE_SCHEMA", "true").lower() == "true",
    litellm_base_url=os.getenv("LITELLM_BASE_URL", "http://127.0.0.1:4000"),
    litellm_api_key=os.getenv("LITELLM_API_KEY", "sk-local"),
    litellm_model=os.getenv("LITELLM_MODEL", "gpt-4o-mini"),
    litellm_max_tokens=int(os.getenv("LITELLM_MAX_TOKENS", "2000")),
    upload_dir=os.getenv("UPLOAD_DIR", "./data/uploads"),
    max_upload_size_mb=int(os.getenv("MAX_UPLOAD_SIZE_MB", "20")),
    proxy_prefix=os.getenv("PROXY_PREFIX", "").rstrip("/"),
)
