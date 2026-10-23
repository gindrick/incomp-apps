"""Import ze zálohy artefaktu: identity, kontrola čtením zpět, ochrana neprázdné databáze."""
import json

import pytest

from semafor.backup import export_all
from semafor.migration import MigrationReport, run_import, transform

LEGACY = "u_3u7_12hKum_ByXRlPXg9Kw"


def sample():
    return {"docs": {
        "projects/p1": {"title": "P", "ownerUserId": LEGACY, "ownerEmail": "", "attachments": [{"kind": "file", "assetId": "ab12", "name": "x.pdf"}]},
        "tasks/t1": {"title": "T", "ownerUserId": "u_unknown", "ownerEmail": ""},
        "tasks/t2": {"title": "T2", "ownerEmail": "karel@hranipex.com"},
        "history/t1": {"events": {"e1": {"by": "Honza", "byId": LEGACY, "type": "created"}}},
        "data/users/x/private/todos/1": {"title": "nesmí"},
        "foo/bar": {"x": 1},
    }}


def test_transform_identities():
    rep = MigrationReport("x", "y")
    out = transform(sample()["docs"], {LEGACY: "Jan.Kratky@hranipex.com"}, rep)
    assert out["projects/p1"]["ownerEmail"] == "jan.kratky@hranipex.com" and out["projects/p1"]["ownerUserId"] == ""
    assert out[f"people/{LEGACY}"]["email"] == "jan.kratky@hranipex.com"
    assert out["history/t1"]["events"]["e1"]["byId"] == LEGACY        # historie se nepřepisuje
    assert "u_unknown" in rep.unpaired_ids and out["tasks/t1"]["ownerUserId"] == "u_unknown"
    assert set(rep.skipped) == {"data/users/x/private/todos/1", "foo/bar"}
    assert rep.attachments[0]["assetId"] == "ab12"


def test_import_apply_verify_and_roundtrip(tmp_path, store, assets):
    src = tmp_path / "zaloha.json"
    src.write_text(json.dumps(sample()), encoding="utf-8")
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "ab12.pdf").write_bytes(b"%PDF-1.4")
    dry = run_import(store, assets, str(src), identity_map={LEGACY: "jan.kratky@hranipex.com"}, assets_dir=str(tmp_path / "assets"))
    assert not dry.applied and store.current_seq() == 0
    rep = run_import(store, assets, str(src), identity_map={LEGACY: "jan.kratky@hranipex.com"},
                     assets_dir=str(tmp_path / "assets"), apply=True)
    assert rep.applied and not rep.verify_mismatch and rep.verified_equal == rep.written == 5
    assert rep.attachments_imported == 1 and assets.load("ab12").data == b"%PDF-1.4"
    with pytest.raises(RuntimeError):
        run_import(store, assets, str(src), apply=True)
    info = export_all(store, str(tmp_path / "export.json"))
    assert info["documents"] == 5
    exported = json.loads((tmp_path / "export.json").read_text(encoding="utf-8"))
    assert exported["docs"]["tasks/t2"] == {"title": "T2", "ownerEmail": "karel@hranipex.com"}


def test_real_backup_if_available(tmp_path, store, assets):
    """Skutečná záloha ostré (pokud je k dispozici): všechny dokumenty projdou a shodují se."""
    import os
    path = os.environ.get("SEMAFOR_TEST_BACKUP")
    if not path:
        pytest.skip("SEMAFOR_TEST_BACKUP není nastaveno")
    rep = run_import(store, assets, path, identity_map={LEGACY: "jan.kratky@hranipex.com"}, apply=True)
    assert rep.applied and not rep.verify_mismatch and not rep.unpaired_ids
