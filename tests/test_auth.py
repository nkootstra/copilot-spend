from __future__ import annotations

import json
import os
import stat
from pathlib import Path

import pytest

from copilot_spend.auth import Auth, AuthError, resolve_auth


def _write(path: Path, payload: dict | str) -> None:
    if isinstance(payload, str):
        path.write_text(payload, encoding="utf-8")
    else:
        path.write_text(json.dumps(payload), encoding="utf-8")
    os.chmod(path, 0o600)


def test_ghe_host_from_enterprise_url(tmp_path):
    auth_file = tmp_path / "auth.json"
    _write(auth_file, {"github-copilot": {"access": "tok", "enterpriseUrl": "ghe.example.com"}})

    auth = resolve_auth(auth_file)

    assert auth == Auth(token="tok", host="ghe.example.com")


def test_defaults_to_github_com_when_enterprise_url_absent(tmp_path):
    auth_file = tmp_path / "auth.json"
    _write(auth_file, {"github-copilot": {"access": "tok"}})

    auth = resolve_auth(auth_file)

    assert auth.host == "github.com"


def test_defaults_to_github_com_when_enterprise_url_empty(tmp_path):
    auth_file = tmp_path / "auth.json"
    _write(auth_file, {"github-copilot": {"access": "tok", "enterpriseUrl": ""}})

    auth = resolve_auth(auth_file)

    assert auth.host == "github.com"


def test_normalizes_https_prefix_and_trailing_slash(tmp_path):
    auth_file = tmp_path / "auth.json"
    _write(auth_file, {"github-copilot": {"access": "tok", "enterpriseUrl": "https://ghe.example.com/"}})

    auth = resolve_auth(auth_file)

    assert auth.host == "ghe.example.com"


def test_normalizes_http_prefix(tmp_path):
    auth_file = tmp_path / "auth.json"
    _write(auth_file, {"github-copilot": {"access": "tok", "enterpriseUrl": "http://internal.ghe.example/"}})

    auth = resolve_auth(auth_file)

    assert auth.host == "internal.ghe.example"


def test_missing_file_raises_with_path(tmp_path):
    missing = tmp_path / "missing.json"

    with pytest.raises(AuthError) as exc:
        resolve_auth(missing)

    assert str(missing) in str(exc.value)
    assert "opencode" in str(exc.value).lower()


def test_malformed_json_raises(tmp_path):
    auth_file = tmp_path / "auth.json"
    _write(auth_file, "{not json")

    with pytest.raises(AuthError) as exc:
        resolve_auth(auth_file)

    assert "malformed json" in str(exc.value).lower()


def test_missing_token_raises(tmp_path):
    auth_file = tmp_path / "auth.json"
    _write(auth_file, {"github-copilot": {"enterpriseUrl": "ghe.example.com"}})

    with pytest.raises(AuthError) as exc:
        resolve_auth(auth_file)

    assert "copilot token" in str(exc.value).lower()


def test_empty_token_raises(tmp_path):
    auth_file = tmp_path / "auth.json"
    _write(auth_file, {"github-copilot": {"access": ""}})

    with pytest.raises(AuthError):
        resolve_auth(auth_file)


def test_invalid_hostname_rejected(tmp_path):
    auth_file = tmp_path / "auth.json"
    _write(auth_file, {"github-copilot": {"access": "tok", "enterpriseUrl": "attacker@evil.com"}})

    with pytest.raises(AuthError) as exc:
        resolve_auth(auth_file)

    assert "hostname" in str(exc.value).lower()


def test_hostname_with_port_rejected(tmp_path):
    auth_file = tmp_path / "auth.json"
    _write(auth_file, {"github-copilot": {"access": "tok", "enterpriseUrl": "ghe.example.com:8080"}})

    with pytest.raises(AuthError):
        resolve_auth(auth_file)


def test_hostname_with_path_after_strip_rejected(tmp_path):
    auth_file = tmp_path / "auth.json"
    _write(auth_file, {"github-copilot": {"access": "tok", "enterpriseUrl": "https://ghe.example.com/oops"}})

    with pytest.raises(AuthError):
        resolve_auth(auth_file)


def test_repr_redacts_token():
    auth = Auth(token="super-secret-token-value", host="ghe.example.com")

    text = repr(auth)

    assert "super-secret-token-value" not in text
    assert "<redacted>" in text
    assert "ghe.example.com" in text


def test_permissive_file_emits_warning(tmp_path, capsys):
    if os.name != "posix":
        pytest.skip("POSIX permission check only")
    auth_file = tmp_path / "auth.json"
    auth_file.write_text(json.dumps({"github-copilot": {"access": "tok"}}), encoding="utf-8")
    os.chmod(auth_file, 0o644)

    resolve_auth(auth_file)

    err = capsys.readouterr().err
    assert "warning" in err.lower()
    assert "chmod 600" in err


def test_strict_mode_no_warning(tmp_path, capsys):
    if os.name != "posix":
        pytest.skip("POSIX permission check only")
    auth_file = tmp_path / "auth.json"
    auth_file.write_text(json.dumps({"github-copilot": {"access": "tok"}}), encoding="utf-8")
    os.chmod(auth_file, 0o600)

    resolve_auth(auth_file)

    err = capsys.readouterr().err
    assert err == ""
