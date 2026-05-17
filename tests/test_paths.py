from __future__ import annotations

import json
import os
import stat
from pathlib import Path

import pytest

from copilot_spend import paths
from copilot_spend.auth import AuthError


@pytest.fixture(autouse=True)
def _clear_env(monkeypatch):
    monkeypatch.delenv("COPILOT_SPEND_CONFIG_DIR", raising=False)
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)


def test_config_dir_default(monkeypatch):
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: Path("/home/u")))

    assert paths.config_dir() == Path("/home/u/.config/copilot-spend")


def test_config_dir_respects_xdg_config_home(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))

    assert paths.config_dir() == tmp_path / "copilot-spend"


def test_config_dir_override_wins_over_xdg(monkeypatch, tmp_path):
    override = tmp_path / "override"
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    monkeypatch.setenv("COPILOT_SPEND_CONFIG_DIR", str(override))

    assert paths.config_dir() == override


def test_auth_path_uses_config_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("COPILOT_SPEND_CONFIG_DIR", str(tmp_path))

    assert paths.auth_path() == tmp_path / "auth.json"


def test_write_secret_file_sets_0600_on_file(monkeypatch, tmp_path):
    monkeypatch.setenv("COPILOT_SPEND_CONFIG_DIR", str(tmp_path / "cfg"))
    target = paths.config_dir() / "auth.json"

    paths.write_secret_file(target, {"hello": "world"})

    assert target.exists()
    mode = stat.S_IMODE(target.stat().st_mode)
    assert mode == 0o600, f"expected 0o600, got {oct(mode)}"


def test_write_secret_file_sets_0700_on_parent(monkeypatch, tmp_path):
    cfg = tmp_path / "cfg"
    monkeypatch.setenv("COPILOT_SPEND_CONFIG_DIR", str(cfg))

    paths.write_secret_file(cfg / "auth.json", {"k": "v"})

    parent_mode = stat.S_IMODE(cfg.stat().st_mode)
    assert parent_mode == 0o700, f"expected 0o700, got {oct(parent_mode)}"


def test_write_secret_file_round_trip(monkeypatch, tmp_path):
    monkeypatch.setenv("COPILOT_SPEND_CONFIG_DIR", str(tmp_path))
    target = tmp_path / "auth.json"
    payload = {"github-copilot": {"token": "ghu_xxx", "host": "github.com"}}

    paths.write_secret_file(target, payload)

    assert json.loads(target.read_text()) == payload


def test_write_secret_file_atomic_on_replace_failure(monkeypatch, tmp_path):
    monkeypatch.setenv("COPILOT_SPEND_CONFIG_DIR", str(tmp_path))
    target = tmp_path / "auth.json"

    def boom(_src, _dst):
        raise OSError("disk full")

    monkeypatch.setattr(os, "replace", boom)

    with pytest.raises(OSError):
        paths.write_secret_file(target, {"k": "v"})

    assert not target.exists()
    leftovers = [p for p in tmp_path.iterdir() if p.name.startswith(".tmp-")]
    assert leftovers == [], f"tempfile leaked: {leftovers}"


def test_write_secret_file_rewrites_loose_permissions(monkeypatch, tmp_path):
    monkeypatch.setenv("COPILOT_SPEND_CONFIG_DIR", str(tmp_path))
    target = tmp_path / "auth.json"
    target.write_text("{}")
    os.chmod(target, 0o644)

    paths.write_secret_file(target, {"k": "v"})

    assert stat.S_IMODE(target.stat().st_mode) == 0o600


def test_delete_secret_file_missing_is_noop(tmp_path):
    paths.delete_secret_file(tmp_path / "nope.json")


def test_delete_secret_file_removes(tmp_path):
    f = tmp_path / "x.json"
    f.write_text("{}")

    paths.delete_secret_file(f)

    assert not f.exists()


def test_assert_safe_parent_happy(monkeypatch, tmp_path):
    parent = tmp_path / "cfg"
    parent.mkdir()
    os.chmod(parent, 0o700)

    paths.assert_safe_parent(parent)


def test_assert_safe_parent_missing_is_ok(tmp_path):
    paths.assert_safe_parent(tmp_path / "not-yet")


def test_assert_safe_parent_rejects_group_writable(tmp_path):
    parent = tmp_path / "cfg"
    parent.mkdir()
    os.chmod(parent, 0o770)

    with pytest.raises(AuthError) as exc:
        paths.assert_safe_parent(parent)

    assert "chmod 700" in str(exc.value)


def test_assert_safe_parent_rejects_world_writable(tmp_path):
    parent = tmp_path / "cfg"
    parent.mkdir()
    os.chmod(parent, 0o707)

    with pytest.raises(AuthError):
        paths.assert_safe_parent(parent)


def test_assert_safe_parent_rejects_foreign_uid(monkeypatch, tmp_path):
    parent = tmp_path / "cfg"
    parent.mkdir()
    os.chmod(parent, 0o700)
    real_stat = parent.stat()

    class _Foreign:
        st_uid = os.getuid() + 99999
        st_mode = real_stat.st_mode

    monkeypatch.setattr(Path, "stat", lambda self: _Foreign() if self == parent else real_stat)

    with pytest.raises(AuthError) as exc:
        paths.assert_safe_parent(parent)

    assert "owned by uid" in str(exc.value)


def test_scrub_replaces_single_token():
    assert paths.scrub("hello ghu_secret world", "ghu_secret") == "hello <redacted-token> world"


def test_scrub_handles_none_and_multiple_tokens():
    out = paths.scrub("ghu_aaa and sess_bbb", "ghu_aaa", None, "sess_bbb")

    assert out == "<redacted-token> and <redacted-token>"


def test_scrub_no_match_returns_input():
    assert paths.scrub("nothing here", "ghu_xxx") == "nothing here"


def test_scrub_skips_empty_string_token():
    # Empty string would otherwise match everywhere; treat as no-op.
    assert paths.scrub("hello", "") == "hello"
