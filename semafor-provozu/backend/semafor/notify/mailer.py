"""Odesílání e-mailů: log (nic neposílá), SMTP relay, nebo Microsoft Graph sendMail."""
from __future__ import annotations

import logging
import smtplib
from dataclasses import dataclass
from email.message import EmailMessage

import httpx

from ..config import Settings

log = logging.getLogger(__name__)


@dataclass
class Mail:
    to: list[str]
    subject: str
    body: str
    cc: tuple[str, ...] = ()


class Mailer:
    def __init__(self, settings: Settings):
        self.s = settings
        self._graph_token: str | None = None

    def send(self, mail: Mail) -> None:
        transport = self.s.notify_transport if self.s.notify_enabled else "log"
        if transport == "log":
            log.info("MAIL (neodesláno) komu=%s kopie=%s předmět=%s\n%s", mail.to, list(mail.cc), mail.subject, mail.body)
        elif transport == "smtp":
            self._send_smtp(mail)
        elif transport == "graph":
            self._send_graph(mail)
        else:  # pragma: no cover - validace konfigurace to nepustí
            raise ValueError(transport)

    def _send_smtp(self, mail: Mail) -> None:
        msg = EmailMessage()
        msg["From"] = self.s.notify_from
        msg["To"] = ", ".join(mail.to)
        if mail.cc:
            msg["Cc"] = ", ".join(mail.cc)
        msg["Subject"] = mail.subject
        msg.set_content(mail.body)
        with smtplib.SMTP(self.s.smtp_host, self.s.smtp_port, timeout=30) as smtp:
            if self.s.smtp_starttls:
                smtp.starttls()
            if self.s.smtp_user:
                smtp.login(self.s.smtp_user, self.s.smtp_password)
            smtp.send_message(msg)

    def _token(self) -> str:
        if not self._graph_token:
            r = httpx.post(
                f"https://login.microsoftonline.com/{self.s.oidc_tenant_id}/oauth2/v2.0/token",
                data={"client_id": self.s.oidc_client_id, "client_secret": self.s.oidc_client_secret,
                      "scope": "https://graph.microsoft.com/.default", "grant_type": "client_credentials"}, timeout=15)
            r.raise_for_status()
            self._graph_token = r.json()["access_token"]
        return self._graph_token

    def _send_graph(self, mail: Mail) -> None:
        """Aplikační oprávnění Mail.Send, omezené Application Access Policy jen na schránku odesílatele."""
        body = {"message": {"subject": mail.subject, "body": {"contentType": "Text", "content": mail.body},
                            "toRecipients": [{"emailAddress": {"address": a}} for a in mail.to],
                            "ccRecipients": [{"emailAddress": {"address": a}} for a in mail.cc]},
                "saveToSentItems": True}
        r = httpx.post(f"https://graph.microsoft.com/v1.0/users/{self.s.notify_from}/sendMail", json=body,
                       headers={"Authorization": f"Bearer {self._token()}"}, timeout=30)
        r.raise_for_status()
