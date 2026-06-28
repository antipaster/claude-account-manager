"""Export/import round-trips and backup pruning — the cross-machine migration path.

Saved account records are platform-agnostic, so a bundle exported on one OS must
read back identically on another. These tests also pin the `shutil` regression in
`_prune_backups` (it used to NameError once a store accumulated >backups_to_keep).
"""
from __future__ import annotations

import json

import pytest

from cam import config, store


@pytest.fixture
def store_dir(tmp_path, monkeypatch):
    """Redirect the CAM store at the config layer so nothing touches the real one."""
    monkeypatch.setattr(config, "STORE", tmp_path)
    monkeypatch.setattr(config, "ACCOUNTS_DIR", tmp_path / "accounts")
    monkeypatch.setattr(config, "BACKUPS_DIR", tmp_path / "backups")
    monkeypatch.setattr(config, "SETTINGS_PATH", tmp_path / "settings.json")
    return tmp_path


def _make_account(acct_id: str, email: str) -> dict:
    return {
        "id": acct_id,
        "label": email.split("@")[0],
        "email": email,
        "identity": {"accountUuid": acct_id, "emailAddress": email},
        "userID": "u-" + acct_id,
        "claudeAiOauth": {
            "accessToken": "tok-" + acct_id,
            "refreshToken": "ref-" + acct_id,
            "expiresAt": 0,
        },
        "added_at": "2026-01-01T00:00:00+00:00",
        "updated_at": "2026-01-02T00:00:00+00:00",
        "last_used_at": None,
    }


def test_export_import_roundtrip(store_dir, tmp_path):
    store._write_record(_make_account("a1", "a@x.com"))
    store._write_record(_make_account("b2", "b@x.com"))

    dest = tmp_path / "bundle.json"
    assert store.export_accounts(dest) == 2

    # Simulate landing on a fresh machine with an empty store.
    for p in config.ACCOUNTS_DIR.glob("*.json"):
        p.unlink()
    assert store.list_accounts() == []

    assert store.import_accounts(dest) == (2, 0)
    assert {a.id for a in store.list_accounts()} == {"a1", "b2"}

    a = store.get_account("a1")
    assert a.email == "a@x.com"
    assert a.claude_oauth["accessToken"] == "tok-a1"
    assert a.claude_oauth["refreshToken"] == "ref-a1"


def test_import_skips_existing_unless_forced(store_dir, tmp_path):
    store._write_record(_make_account("a1", "a@x.com"))
    dest = tmp_path / "bundle.json"
    store.export_accounts(dest)

    assert store.import_accounts(dest) == (0, 1)
    assert store.import_accounts(dest, overwrite=True) == (1, 0)


def test_import_accepts_bare_list_and_single_record(store_dir, tmp_path):
    bare_list = tmp_path / "list.json"
    bare_list.write_text(json.dumps([_make_account("a1", "a@x.com")]), encoding="utf-8")
    assert store.import_accounts(bare_list) == (1, 0)

    single = tmp_path / "single.json"
    single.write_text(json.dumps(_make_account("b2", "b@x.com")), encoding="utf-8")
    assert store.import_accounts(single) == (1, 0)


def test_import_missing_file_errors(store_dir, tmp_path):
    with pytest.raises(store.CamError):
        store.import_accounts(tmp_path / "nope.json")


def test_export_bundle_shape(store_dir, tmp_path):
    store._write_record(_make_account("a1", "a@x.com"))
    dest = tmp_path / "bundle.json"
    store.export_accounts(dest)

    data = json.loads(dest.read_text(encoding="utf-8"))
    assert data["cam_export_version"] == store.EXPORT_VERSION
    assert isinstance(data["accounts"], list) and len(data["accounts"]) == 1
    assert "exported_at" in data


def test_prune_backups_survives_overflow(store_dir):
    """Regression: _prune_backups called shutil.rmtree without importing shutil."""
    config.BACKUPS_DIR.mkdir(parents=True)
    for i in range(5):
        (config.BACKUPS_DIR / f"2026010{i}-x").mkdir()
    config.SETTINGS_PATH.write_text(json.dumps({"backups_to_keep": 2}), encoding="utf-8")

    store._prune_backups()  # must not raise

    assert sorted(p.name for p in config.BACKUPS_DIR.iterdir()) == ["20260103-x", "20260104-x"]
