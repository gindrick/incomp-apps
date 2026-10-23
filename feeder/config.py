from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


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
    session_secret: str
    session_timeout_hours: int
    dev_auth_bypass: bool
    dev_auth_user: str
    ldap_server: str
    ldap_domain: str
    ldap_allowed_users: str
    proxy_prefix: str
    data_dir: str
    backend_port: int


settings = Settings(
    env=os.getenv("ENV", "dev"),
    session_secret=os.getenv("SESSION_SECRET", "feeder-change-this-in-production"),
    session_timeout_hours=int(os.getenv("SESSION_TIMEOUT_HOURS", "8")),
    dev_auth_bypass=os.getenv("DEV_AUTH_BYPASS", "true").lower() == "true",
    dev_auth_user=os.getenv("DEV_AUTH_USER", "dev"),
    ldap_server=os.getenv("LDAP_SERVER", ""),
    ldap_domain=os.getenv("LDAP_DOMAIN", ""),
    ldap_allowed_users=os.getenv("LDAP_ALLOWED_USERS", ""),
    proxy_prefix=os.getenv("PROXY_PREFIX", "").rstrip("/"),
    data_dir=os.getenv("DATA_DIR", str(ROOT / "data")),
    backend_port=int(os.getenv("BACKEND_PORT", "8015")),
)
