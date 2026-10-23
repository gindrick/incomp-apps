"""Výběr položek pro e-mailové notifikace.

Pravidla odpovídají pohledu Upomínky ve frontendu (``reminderScope``,
``opsDigestMailto``) a zadání z ``notifikace-mail.md``:

* přiřazení: otevřený úkol s vlastníkem, kterému ještě nebyl ohlášen,
* termíny: po termínu / dnes / do dvou pracovních dnů (termín, jinak kontrola),
  jeden souhrnný mail na osobu,
* denní souhrn za provoz pro vybrané adresy.
"""
from __future__ import annotations

import calendar
import datetime as dt
from dataclasses import dataclass, field

DEPT_LABEL = {"vyroba": "Výroba", "kvalita": "Kvalita & BOZP/ESH", "facility": "Facility", "ie": "IE & R&D",
              "bvr": "BVR", "hq": "Ostatní / HQ", "erp": "Ostatní / HQ"}
STATUS_LABEL = {"green": "na dobré cestě", "yellow": "pozor", "red": "kritické"}
MAX_LINES_PER_MAIL = 12


def parse_date(s: str | None) -> dt.date | None:
    try:
        return dt.date.fromisoformat(str(s)[:10]) if s else None
    except ValueError:
        return None


def effective_due(it: dict) -> dt.date | None:
    """Stejně jako ``effectiveDue``: týden = neděle téhož týdne, měsíc = poslední den měsíce."""
    d = parse_date(it.get("dueDate"))
    if not d:
        return None
    prec = it.get("duePrecision")
    if prec == "week":
        return d + dt.timedelta(days=6 - d.weekday())
    if prec == "month":
        return d.replace(day=calendar.monthrange(d.year, d.month)[1])
    return d


def add_workdays(d: dt.date, k: int) -> dt.date:
    n = 0
    while n < k:
        d += dt.timedelta(days=1)
        if d.weekday() < 5:
            n += 1
    return d


def fmt_date(d: dt.date | None) -> str:
    return d.strftime("%d.%m.%Y") if d else "bez termínu"


def owner_email(it: dict) -> str:
    e = str(it.get("ownerEmail") or it.get("owner") or "").strip().lower()
    return e if "@" in e else ""


def live_tasks(tasks: list[dict]) -> list[dict]:
    return [t for t in tasks if not t.get("archived")]


def open_projects(projects: list[dict]) -> list[dict]:
    return [p for p in projects if not p.get("archived") and (p.get("lifecycle") or "active") != "done"]


@dataclass
class OwnerDigest:
    email: str
    overdue: list[tuple[str, dict, str]] = field(default_factory=list)   # (druh, položka, "termín"/"kontrola")
    today: list[tuple[str, dict, str]] = field(default_factory=list)
    soon: list[tuple[str, dict, str]] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.overdue) + len(self.today) + len(self.soon)

    def item_ids(self) -> list[str]:
        return [it["id"] for band in (self.overdue, self.today, self.soon) for _k, it, _w in band]


def due_digests(projects: list[dict], tasks: list[dict], today: dt.date) -> list[OwnerDigest]:
    horizon = add_workdays(today, 2)
    by_owner: dict[str, OwnerDigest] = {}

    def band_of(d: dt.date | None) -> str | None:
        if not d:
            return None
        if d < today:
            return "overdue"
        if d == today:
            return "today"
        return "soon" if d <= horizon else None

    def add(kind: str, it: dict) -> None:
        email = owner_email(it)
        if not email:
            return
        band, what = band_of(effective_due(it)), "termín"
        if not band:
            band, what = band_of(parse_date(it.get("nextCheckDate"))), "kontrola"
        if not band:
            return
        dg = by_owner.setdefault(email, OwnerDigest(email))
        getattr(dg, band).append((kind, it, what))

    for t in live_tasks(tasks):
        if t.get("status") != "done":
            add("task", t)
    for p in open_projects(projects):
        add("project", p)
    return sorted(by_owner.values(), key=lambda d: (-len(d.overdue), -len(d.today), d.email))


def item_line(kind: str, it: dict, what: str) -> str:
    bits = [str(it.get("title") or "(bez názvu)")]
    if kind == "project":
        bits.append("projekt, semafor " + STATUS_LABEL.get(it.get("status"), "?"))
    if it.get("department") in DEPT_LABEL:
        bits.append(DEPT_LABEL[it["department"]])
    if what == "kontrola":
        bits.append("kontrola " + fmt_date(parse_date(it.get("nextCheckDate"))))
    else:
        bits.append("termín " + fmt_date(effective_due(it)))
    if kind == "project" and str(it.get("blocker") or "").strip():
        bits.append("blokátor: " + str(it["blocker"]).strip())
    if kind == "task" and it.get("waitingReason"):
        bits.append("čeká: " + str(it["waitingReason"]))
    return ", ".join(bits)


def new_assignments(tasks: list[dict], announced: dict[str, str]) -> dict[str, list[dict]]:
    """Úkoly, jejichž vlastník se liší od naposledy ohlášeného (nový úkol i předání jinému)."""
    out: dict[str, list[dict]] = {}
    for t in live_tasks(tasks):
        email = owner_email(t)
        if not email or t.get("status") == "done":
            continue
        if announced.get(t["id"]) != email:
            out.setdefault(email, []).append(t)
    return out


def ops_summary(projects: list[dict], tasks: list[dict], today: dt.date) -> dict:
    lt = [t for t in live_tasks(tasks) if t.get("status") != "done"]
    op = open_projects(projects)
    od_t = [t for t in lt if (effective_due(t) or dt.date.max) < today]
    od_p = [p for p in op if (effective_due(p) or dt.date.max) < today]
    return {
        "overdue_projects": od_p,
        "overdue_tasks": od_t,
        "due_today": [t for t in lt if parse_date(t.get("dueDate")) == today],
        "blockers": [p for p in op if str(p.get("blocker") or "").strip()],
        "no_owner": [t for t in lt if not owner_email(t) and not t.get("ownerUserId")],
        "inbox": [t for t in lt if not t.get("department")],
    }
