"""Výběr položek a průběh notifikací (bez skutečného odesílání)."""
import datetime as dt

from semafor.notify import rules
from semafor.notify.mailer import Mail
from semafor.notify.runner import NotifyRunner
from semafor.principal import SYSTEM

TODAY = dt.date(2026, 10, 19)   # pondělí


class FakeMailer:
    def __init__(self): self.sent: list[Mail] = []
    def send(self, m): self.sent.append(m)


def test_effective_due_precision():
    assert rules.effective_due({"dueDate": "2026-10-14", "duePrecision": "week"}) == dt.date(2026, 10, 18)
    assert rules.effective_due({"dueDate": "2026-02-03", "duePrecision": "month"}) == dt.date(2026, 2, 28)
    assert rules.effective_due({"dueDate": ""}) is None


def test_workdays():
    assert rules.add_workdays(dt.date(2026, 10, 23), 2) == dt.date(2026, 10, 27)   # pátek + 2 = úterý


def test_due_digests_bands():
    tasks = [
        {"id": "a", "title": "A", "ownerEmail": "x@h.cz", "dueDate": "2026-10-10", "status": "todo"},
        {"id": "b", "title": "B", "ownerEmail": "x@h.cz", "dueDate": "2026-10-19", "status": "todo"},
        {"id": "c", "title": "C", "ownerEmail": "x@h.cz", "dueDate": "2026-10-21", "status": "todo"},
        {"id": "d", "title": "D", "ownerEmail": "x@h.cz", "dueDate": "2026-10-30", "status": "todo"},
        {"id": "e", "title": "E", "ownerEmail": "x@h.cz", "dueDate": "2026-10-10", "status": "done"},
        {"id": "f", "title": "F", "ownerEmail": "x@h.cz", "nextCheckDate": "2026-10-19", "status": "todo"},
        {"id": "g", "title": "G", "ownerEmail": "x@h.cz", "dueDate": "2026-10-10", "status": "todo", "archived": True},
    ]
    projects = [{"id": "p", "title": "P", "ownerEmail": "y@h.cz", "dueDate": "2026-10-01", "lifecycle": "done"}]
    [dg] = rules.due_digests(projects, tasks, TODAY)
    assert [i["id"] for _k, i, _w in dg.overdue] == ["a"]
    assert sorted(i["id"] for _k, i, _w in dg.today) == ["b", "f"]
    assert [i["id"] for _k, i, _w in dg.soon] == ["c"]


def _seed(store):
    store.set(SYSTEM, "tasks/t1", {"title": "Úkol 1", "ownerEmail": "x@h.cz", "status": "todo", "dueDate": "2026-10-10"})


def test_assigned_first_run_is_silent_then_announces(store, settings):
    settings.notify_enabled = True
    _seed(store)
    m = FakeMailer()
    assert NotifyRunner(store, settings, m, TODAY).run_assigned() == 0 and m.sent == []
    store.set(SYSTEM, "tasks/t2", {"title": "Úkol 2", "ownerEmail": "z@h.cz", "status": "todo"})
    NotifyRunner(store, settings, m, TODAY).run_assigned()
    assert [x.to for x in m.sent] == [["z@h.cz"]]
    NotifyRunner(store, settings, m, TODAY).run_assigned()
    assert len(m.sent) == 1   # podruhé už ne


def test_due_once_per_day_and_disabled_keeps_state(store, settings):
    _seed(store)
    m = FakeMailer()
    settings.notify_enabled = False
    NotifyRunner(store, settings, m, TODAY).run_due()
    assert not store.get(SYSTEM, "notify/state").exists       # vypnuté: stav se nemění
    settings.notify_enabled = True
    settings.notify_copy_overdue_to = ["sef@h.cz"]
    NotifyRunner(store, settings, m, TODAY).run_due()
    NotifyRunner(store, settings, m, TODAY).run_due()
    assert len(m.sent) == 2 and m.sent[1].cc == ("sef@h.cz",) and "PO TERMÍNU" in m.sent[1].body


def test_daily_summary(store, settings):
    _seed(store)
    settings.notify_enabled = True
    settings.notify_daily_summary_to = ["sef@h.cz"]
    m = FakeMailer()
    NotifyRunner(store, settings, m, TODAY).run_daily()
    NotifyRunner(store, settings, m, TODAY).run_daily()
    assert len(m.sent) == 1 and "Po termínu: 1" in m.sent[0].body


def test_mail_limit(store, settings):
    settings.notify_enabled = True
    settings.notify_max_mails_per_run = 2
    for i in range(5):
        store.set(SYSTEM, f"tasks/x{i}", {"title": f"T{i}", "ownerEmail": f"o{i}@h.cz", "status": "todo", "dueDate": "2026-10-19"})
    m = FakeMailer()
    NotifyRunner(store, settings, m, TODAY).run_due()
    assert len(m.sent) == 2


def test_migrated_empty_state_does_not_flood(store, settings):
    """Stav z artefaktu: assigned={} a lastAssignRun="" (úloha nikdy neběžela) = první běh, nic se nepošle."""
    settings.notify_enabled = True
    _seed(store)
    store.set(SYSTEM, "notify/state", {"assigned": {}, "reminded": {}, "lastAssignRun": "", "lastDailyRun": ""})
    m = FakeMailer()
    NotifyRunner(store, settings, m, TODAY).run_assigned()
    assert m.sent == [] and store.get(SYSTEM, "notify/state").data["assigned"] == {"t1": "x@h.cz"}


def test_failure_mid_run_does_not_resend_to_earlier(store, settings):
    """Chyba u druhého příjemce: první už znovu mail nedostane (stav se ukládá po každém mailu)."""
    settings.notify_enabled = True
    for i, who in enumerate(["a@h.cz", "b@h.cz"]):
        store.set(SYSTEM, f"tasks/f{i}", {"title": f"F{i}", "ownerEmail": who, "status": "todo", "dueDate": "2026-10-19"})

    class Flaky(FakeMailer):
        def send(self, m):
            if m.to == ["b@h.cz"] and not getattr(self, "recovered", False):
                raise OSError("SMTP 550")
            super().send(m)

    m = Flaky()
    import pytest
    with pytest.raises(OSError):
        NotifyRunner(store, settings, m, TODAY).run_due()
    m.recovered = True
    NotifyRunner(store, settings, m, TODAY).run_due()
    assert [x.to for x in m.sent] == [["a@h.cz"], ["b@h.cz"]]


def test_state_is_pruned(store, settings):
    settings.notify_enabled = True
    store.set(SYSTEM, "notify/state", {"assigned": {"zmizely": "x@h.cz"}, "reminded": {"x@h.cz": "2026-01-01"},
                                       "lastAssignRun": 1})
    _seed(store)
    NotifyRunner(store, settings, FakeMailer(), TODAY).run_assigned()
    st = store.get(SYSTEM, "notify/state").data
    assert "zmizely" not in st["assigned"] and st["assigned"] == {"t1": "x@h.cz"} and st["reminded"] == {}
