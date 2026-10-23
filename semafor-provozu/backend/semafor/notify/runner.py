"""Běh notifikací (spouští Plánovač úloh Windows, viz deploy/windows/notify-tasks.ps1).

  python -m semafor notify assigned   každou hodinu v pracovní dny 7 až 18
  python -m semafor notify due        v pracovní dny v 7:00 (upomínky po lidech)
  python -m semafor notify daily      v pracovní dny v 7:00 (souhrn za provoz)

Dokud ``SEMAFOR_NOTIFY_ENABLED`` není ``true``, maily se jen zapíšou do logu
a stav ``notify/state`` se nemění (bezpečné zkoušení na ostrých datech).
"""
from __future__ import annotations

import datetime as dt
import logging

from ..config import Settings
from ..docstore.store import DocumentStore, now_ms
from ..principal import SYSTEM
from . import rules
from .mailer import Mail, Mailer

log = logging.getLogger(__name__)
STATE_PATH = "notify/state"


class NotifyRunner:
    def __init__(self, store: DocumentStore, settings: Settings, mailer: Mailer | None = None,
                 today: dt.date | None = None):
        self.store = store
        self.s = settings
        self.mailer = mailer or Mailer(settings)
        self.today = today or dt.date.today()
        self.sent = 0

    # ---- data ----
    def _items(self) -> tuple[list[dict], list[dict]]:
        projects, _ = self.store.list_collection(SYSTEM, "projects")
        tasks, _ = self.store.list_collection(SYSTEM, "tasks")
        return ([{"id": d.id, **d.data} for d in projects], [{"id": d.id, **d.data} for d in tasks])

    def _state(self) -> tuple[dict, bool]:
        doc = self.store.get(SYSTEM, STATE_PATH)
        return (dict(doc.data) if doc.exists else {}), doc.exists

    def _save_state(self, patch: dict) -> None:
        """Sloučí ``patch`` do stavu (atomicky na serveru). Volá se po KAŽDÉM odeslaném mailu,
        aby chyba u dalšího příjemce nezpůsobila opakované rozeslání těm předchozím."""
        if not self.s.notify_enabled:
            log.info("notifikace vypnuté: stav %s se nemění", STATE_PATH)
            return
        if self.store.get(SYSTEM, STATE_PATH).exists:
            self.store.update(SYSTEM, STATE_PATH, patch)
        else:
            self.store.set(SYSTEM, STATE_PATH, patch)

    def _prune_state(self, live_task_ids: set[str]) -> None:
        """Udrží stav malý: ohlášení jen u živých úkolů, upomínky jen z dneška."""
        if not self.s.notify_enabled:
            return
        doc = self.store.get(SYSTEM, STATE_PATH)
        if not doc.exists:
            return
        state = dict(doc.data)
        today_s = self.today.isoformat()
        state["assigned"] = {k: v for k, v in (state.get("assigned") or {}).items() if k in live_task_ids}
        state["reminded"] = {k: v for k, v in (state.get("reminded") or {}).items() if v == today_s}
        self.store.set(SYSTEM, STATE_PATH, state)

    def _can_send(self) -> bool:
        return self.sent < self.s.notify_max_mails_per_run

    def _send(self, mail: Mail) -> bool:
        if not self._can_send():
            log.warning("dosažen limit %d mailů na běh, zbytek příště", self.s.notify_max_mails_per_run)
            return False
        self.mailer.send(mail)
        self.sent += 1
        return True

    def _footer(self) -> str:
        return f"\n\nAplikace: {self.s.public_url}/\n(automatická zpráva Semafor Provozu)"

    # ---- úlohy ----
    def run_assigned(self) -> int:
        _projects, tasks = self._items()
        state, exists = self._state()
        announced: dict[str, str] = dict(state.get("assigned") or {})
        if not exists or not state.get("lastAssignRun"):
            # první běh (i po migraci z artefaktu, kde je stav založený, ale úloha nikdy neběžela):
            # zapamatovat současný stav, nic nerozesílat (žádná lavina mailů ke starým úkolům)
            snapshot = {t["id"]: rules.owner_email(t) for t in rules.live_tasks(tasks) if rules.owner_email(t)}
            self._save_state({"assigned": snapshot, "reminded": state.get("reminded") or {}, "lastAssignRun": now_ms()})
            log.info("první běh přiřazení: zapamatováno %d úkolů, nic neodesláno", len(snapshot))
            return 0
        for email, items in rules.new_assignments(tasks, announced).items():
            lines = [f"* {t.get('title')} ({rules.DEPT_LABEL.get(t.get('department'), 'Inbox')}, "
                     f"termín {rules.fmt_date(rules.effective_due(t))})" for t in items[:rules.MAX_LINES_PER_MAIL]]
            if len(items) > rules.MAX_LINES_PER_MAIL:
                lines.append(f"... a další {len(items) - rules.MAX_LINES_PER_MAIL} v aplikaci.")
            subject = "Semafor Provozu: nový úkol" if len(items) == 1 else f"Semafor Provozu: {len(items)} nové úkoly"
            body = "Ahoj,\n\nv Semaforu Provozu ti byl přiřazen:\n\n" + "\n".join(lines) + self._footer()
            if not self._send(Mail([email], subject, body)):
                break
            self._save_state({"assigned": {t["id"]: email for t in items}})
        self._save_state({"lastAssignRun": now_ms()})
        self._prune_state({t["id"] for t in rules.live_tasks(tasks)})
        return self.sent

    def run_due(self) -> int:
        projects, tasks = self._items()
        state, _ = self._state()
        reminded: dict[str, str] = dict(state.get("reminded") or {})
        today_s = self.today.isoformat()
        for dg in rules.due_digests(projects, tasks, self.today):
            if reminded.get(dg.email) == today_s:
                continue
            groups = [("PO TERMÍNU", dg.overdue), ("DNES", dg.today), ("DO DVOU PRACOVNÍCH DNŮ", dg.soon)]
            lines, shown = ["Ahoj,", "", "přehled tvých termínů ze Semaforu Provozu:"], 0
            for title, band in groups:
                if not band:
                    continue
                lines += ["", title]
                for kind, it, what in band:
                    if shown < rules.MAX_LINES_PER_MAIL:
                        lines.append("* " + rules.item_line(kind, it, what))
                        shown += 1
            if dg.total > rules.MAX_LINES_PER_MAIL:
                lines += ["", f"... a další {dg.total - rules.MAX_LINES_PER_MAIL} v aplikaci."]
            parts = [f"{len(dg.overdue)} po termínu" if dg.overdue else "", f"{len(dg.today)} dnes" if dg.today else "",
                     f"{len(dg.soon)} do dvou dnů" if dg.soon else ""]
            subject = "Semafor Provozu: tvé termíny (" + ", ".join(x for x in parts if x) + ")"
            cc = tuple(a for a in self.s.notify_copy_overdue_to if a != dg.email) if dg.overdue else ()
            if not self._send(Mail([dg.email], subject, "\n".join(lines) + self._footer(), cc=cc)):
                break
            self._save_state({"reminded": {dg.email: today_s}})
        self._save_state({"lastDueRun": now_ms()})
        self._prune_state({t["id"] for t in rules.live_tasks(tasks)})
        return self.sent

    def run_daily(self) -> int:
        if not self.s.notify_daily_summary_to:
            log.info("denní souhrn: není nastaven žádný příjemce (SEMAFOR_NOTIFY_DAILY_SUMMARY_TO)")
            return 0
        state, _ = self._state()
        if state.get("lastDailyDate") == self.today.isoformat():
            log.info("denní souhrn už dnes odešel")
            return 0
        projects, tasks = self._items()
        sm = rules.ops_summary(projects, tasks, self.today)
        L = [f"Semafor Provozu: souhrn {rules.fmt_date(self.today)}", "",
             f"Po termínu: {len(sm['overdue_projects']) + len(sm['overdue_tasks'])} "
             f"(projekty {len(sm['overdue_projects'])}, úkoly {len(sm['overdue_tasks'])})",
             f"Termín dnes: {len(sm['due_today'])}", f"Otevřené blokátory: {len(sm['blockers'])}",
             f"Úkoly bez vlastníka: {len(sm['no_owner'])}, v Inboxu: {len(sm['inbox'])}"]
        if sm["overdue_projects"]:
            L += ["", "PROJEKTY PO TERMÍNU"] + [f"* {p.get('title')} ({rules.owner_email(p) or 'bez vlastníka'}), "
                                               f"termín {rules.fmt_date(rules.effective_due(p))}" for p in sm["overdue_projects"]]
        if sm["overdue_tasks"]:
            L += ["", "ÚKOLY PO TERMÍNU"] + [f"* {t.get('title')} ({rules.owner_email(t) or 'bez vlastníka'}), "
                                            f"termín {rules.fmt_date(rules.effective_due(t))}"
                                            for t in sm["overdue_tasks"][:rules.MAX_LINES_PER_MAIL]]
            if len(sm["overdue_tasks"]) > rules.MAX_LINES_PER_MAIL:
                L.append(f"  ... a další {len(sm['overdue_tasks']) - rules.MAX_LINES_PER_MAIL}")
        mail = Mail(list(self.s.notify_daily_summary_to), f"Semafor Provozu: souhrn {rules.fmt_date(self.today)}",
                    "\n".join(L) + self._footer())
        if self._send(mail):
            self._save_state({"lastDailyDate": self.today.isoformat(), "lastDailyRun": now_ms()})
        return self.sent
