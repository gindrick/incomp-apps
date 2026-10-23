"""Sémantika dokumentového úložiště (musí odpovídat platformě, na kterou je napsaný frontend)."""
import pytest

from semafor.docstore.store import deep_merge
from semafor.errors import InvalidArgument, NotFound, PermissionDenied, TooLarge, VersionConflict
from semafor.principal import Principal

ADMIN = Principal("a", "a@x.cz", "A", ("Semafor.Admin",), is_admin=True, can_edit=True)
USER = Principal("u", "u@x.cz", "U", ("Semafor.User",), is_admin=False, can_edit=True)
READER = Principal("r", "r@x.cz", "R", ("Semafor.Reader",), is_admin=False, can_edit=False)


def test_deep_merge_like_platform():
    t = {"events": {"e1": {"x": 1}}, "arr": [1, 2], "s": "a"}
    deep_merge(t, {"events": {"e2": {"y": 2}, "e1": None}, "arr": [3], "n": None})
    assert t == {"events": {"e1": None, "e2": {"y": 2}}, "arr": [3], "s": "a", "n": None}


def test_set_get_update_delete_versions(store):
    d = store.set(USER, "projects/p1", {"title": "A", "m": {"a": 1}})
    assert d.version == 1
    d2 = store.update(USER, "projects/p1", {"m": {"b": 2}})
    assert d2.version == 2 and d2.seq > d.seq
    assert store.get(USER, "projects/p1").data == {"title": "A", "m": {"a": 1, "b": 2}}
    store.delete(USER, "projects/p1")
    assert not store.get(USER, "projects/p1").exists
    docs, _ = store.list_collection(USER, "projects")
    assert docs == []


def test_update_missing_is_not_found(store):
    with pytest.raises(NotFound):
        store.update(USER, "history/x", {"events": {}})


def test_set_after_delete_recreates(store):
    store.set(USER, "tasks/t1", {"a": 1})
    store.delete(USER, "tasks/t1")
    d = store.set(USER, "tasks/t1", {"a": 2})
    assert d.version == 3 and store.get(USER, "tasks/t1").data == {"a": 2}


def test_if_version(store):
    store.set(USER, "tasks/t1", {"a": 1})
    with pytest.raises(VersionConflict):
        store.set(USER, "tasks/t1", {"a": 2}, if_version=5)
    store.set(USER, "tasks/t1", {"a": 2}, if_version=1)
    with pytest.raises(VersionConflict):
        store.set(USER, "tasks/new", {"a": 1}, if_version=1)
    store.set(USER, "tasks/new", {"a": 1}, if_version=0)


def test_rules(store):
    with pytest.raises(PermissionDenied):
        store.set(READER, "tasks/t1", {"a": 1})
    with pytest.raises(PermissionDenied):
        store.set(USER, "settings/finance", {"rate": 1})
    with pytest.raises(PermissionDenied):
        store.set(USER, "people/x", {"email": "x"})
    store.set(ADMIN, "settings/finance", {"rate": 1})
    assert store.get(USER, "settings/finance").data == {"rate": 1}
    with pytest.raises(PermissionDenied):
        store.set(USER, "evil/x", {"a": 1})
    with pytest.raises(PermissionDenied):
        store.get(USER, "notify/state")


def test_private_subtree(store):
    store.set(USER, "data/users/u/private/todos/1", {"t": "moje"})
    with pytest.raises(PermissionDenied):
        store.get(ADMIN, "data/users/u/private/todos/1")
    with pytest.raises(PermissionDenied):
        store.list_collection(ADMIN, "data/users/u/private/todos")
    with pytest.raises(PermissionDenied):
        store.set(ADMIN, "data/users/u/private/todos/2", {"t": "cizí"})
    changes, _ = store.changes_since(ADMIN, 0)
    assert not any(c["path"].startswith("data/") for c in changes)
    mine, _ = store.changes_since(USER, 0)
    assert any(c["path"] == "data/users/u/private/todos/1" for c in mine)


@pytest.mark.parametrize("bad", ["", "projects", "projects/a/b", "../x/y", "projects/a b", "projects/" + "x" * 300])
def test_bad_paths(store, bad):
    with pytest.raises((InvalidArgument, PermissionDenied)):
        store.set(USER, bad, {"a": 1})


def test_size_limit(store):
    with pytest.raises(TooLarge):
        store.set(USER, "tasks/big", {"x": "a" * (store.max_doc_bytes + 1)})


def test_non_object_rejected(store):
    with pytest.raises(InvalidArgument):
        store.set(USER, "tasks/t", ["a"])


def test_lease(store):
    r1 = store.acquire(USER, "projects/p1", "u:1", 10000)
    assert r1["acquired"]
    r2 = store.acquire(ADMIN, "projects/p1", "a:1", 10000)
    assert not r2["acquired"] and r2["expiresAt"]
    assert store.acquire(USER, "projects/p1", "u:1", 10000)["acquired"]   # prodloužení týmž držitelem
    store.acquire(USER, "projects/p1", "u:1", 1)                          # "uvolnění" krátkým TTL
    import time; time.sleep(0.01)
    assert store.acquire(ADMIN, "projects/p1", "a:1", 10000)["acquired"]
    with pytest.raises(PermissionDenied):
        store.acquire(READER, "projects/p1", "r:1", 1000)


def test_changes_feed_order_and_deletes(store):
    store.set(USER, "tasks/a", {"n": 1})
    _, s0 = store.changes_since(USER, 0)
    store.update(USER, "tasks/a", {"n": 2})
    store.delete(USER, "tasks/a")
    ch, s1 = store.changes_since(USER, s0)
    assert s1 > s0 and [c["deleted"] for c in ch] == [True]   # jeden řádek = poslední stav dokumentu
    assert store.changes_since(USER, s1)[0] == []


def test_concurrent_updates_are_not_lost(store):
    """Souběžné přírůstky historie (update s vlastními klíči) se nesmí přepsat."""
    from concurrent.futures import ThreadPoolExecutor
    store.set(USER, "history/h", {"events": {}})
    with ThreadPoolExecutor(8) as ex:
        list(ex.map(lambda i: store.update(USER, "history/h", {"events": {f"e{i}": {"i": i}}}), range(40)))
    assert len(store.get(USER, "history/h").data["events"]) == 40


def test_bulk_set_atomic(store):
    with pytest.raises(PermissionDenied):
        store.bulk_set(USER, [("tasks/a", {"a": 1}), ("settings/x", {"b": 1})])
    assert not store.get(USER, "tasks/a").exists
