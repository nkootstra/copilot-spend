from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from copilot_spend.auth import (
    Auth,
    AuthError,
    is_valid_host,
    normalize_host,
    resolve_auth,
)


@pytest.fixture
def missing_native(tmp_path) -> Path:
    return tmp_path / "no-native.json"


def _write(path: Path, payload: dict | str) -> None:
    if isinstance(payload, str):
        path.write_text(payload, encoding="utf-8")
    else:
        path.write_text(json.dumps(payload), encoding="utf-8")
    os.chmod(path, 0o600)


def test_ghe_host_from_enterprise_url(tmp_path, missing_native):
    auth_file = tmp_path / "auth.json"
    _write(auth_file, {"github-copilot": {"access": "tok", "enterpriseUrl": "ghe.example.com"}})

    auth = resolve_auth(native_path=missing_native, opencode_path=auth_file)

    assert auth == Auth(token="tok", host="ghe.example.com", source="opencode")


def test_defaults_to_github_com_when_enterprise_url_absent(tmp_path, missing_native):
    auth_file = tmp_path / "auth.json"
    _write(auth_file, {"github-copilot": {"access": "tok"}})

    auth = resolve_auth(native_path=missing_native, opencode_path=auth_file)

    assert auth.host == "github.com"


def test_defaults_to_github_com_when_enterprise_url_empty(tmp_path, missing_native):
    auth_file = tmp_path / "auth.json"
    _write(auth_file, {"github-copilot": {"access": "tok", "enterpriseUrl": ""}})

    auth = resolve_auth(native_path=missing_native, opencode_path=auth_file)

    assert auth.host == "github.com"


def test_normalizes_https_prefix_and_trailing_slash(tmp_path, missing_native):
    auth_file = tmp_path / "auth.json"
    _write(
        auth_file,
        {"github-copilot": {"access": "tok", "enterpriseUrl": "https://ghe.example.com/"}},
    )

    auth = resolve_auth(native_path=missing_native, opencode_path=auth_file)

    assert auth.host == "ghe.example.com"


def test_normalizes_http_prefix(tmp_path, missing_native):
    auth_file = tmp_path / "auth.json"
    _write(
        auth_file,
        {"github-copilot": {"access": "tok", "enterpriseUrl": "http://internal.ghe.example/"}},
    )

    auth = resolve_auth(native_path=missing_native, opencode_path=auth_file)

    assert auth.host == "internal.ghe.example"


def test_missing_file_raises_with_path(tmp_path, missing_native):
    missing = tmp_path / "missing.json"

    with pytest.raises(AuthError) as exc:
        resolve_auth(native_path=missing_native, opencode_path=missing)

    msg = str(exc.value)
    assert "copilot-spend login" in msg


def test_malformed_json_raises(tmp_path, missing_native):
    auth_file = tmp_path / "auth.json"
    _write(auth_file, "{not json")

    with pytest.raises(AuthError) as exc:
        resolve_auth(native_path=missing_native, opencode_path=auth_file)

    assert "malformed json" in str(exc.value).lower()


def test_missing_token_raises(tmp_path, missing_native):
    auth_file = tmp_path / "auth.json"
    _write(auth_file, {"github-copilot": {"enterpriseUrl": "ghe.example.com"}})

    with pytest.raises(AuthError) as exc:
        resolve_auth(native_path=missing_native, opencode_path=auth_file)

    assert "copilot token" in str(exc.value).lower()


def test_empty_token_raises(tmp_path, missing_native):
    auth_file = tmp_path / "auth.json"
    _write(auth_file, {"github-copilot": {"access": ""}})

    with pytest.raises(AuthError):
        resolve_auth(native_path=missing_native, opencode_path=auth_file)


def test_invalid_hostname_rejected(tmp_path, missing_native):
    auth_file = tmp_path / "auth.json"
    _write(auth_file, {"github-copilot": {"access": "tok", "enterpriseUrl": "attacker@evil.com"}})

    with pytest.raises(AuthError) as exc:
        resolve_auth(native_path=missing_native, opencode_path=auth_file)

    assert "hostname" in str(exc.value).lower()


def test_hostname_with_port_rejected(tmp_path, missing_native):
    auth_file = tmp_path / "auth.json"
    _write(
        auth_file, {"github-copilot": {"access": "tok", "enterpriseUrl": "ghe.example.com:8080"}}
    )

    with pytest.raises(AuthError):
        resolve_auth(native_path=missing_native, opencode_path=auth_file)


def test_hostname_with_path_after_strip_rejected(tmp_path, missing_native):
    auth_file = tmp_path / "auth.json"
    _write(
        auth_file,
        {"github-copilot": {"access": "tok", "enterpriseUrl": "https://ghe.example.com/oops"}},
    )

    with pytest.raises(AuthError):
        resolve_auth(native_path=missing_native, opencode_path=auth_file)


def test_repr_redacts_token():
    auth = Auth(token="super-secret-token-value", host="ghe.example.com")

    text = repr(auth)

    assert "super-secret-token-value" not in text
    assert "<redacted>" in text
    assert "ghe.example.com" in text


def test_permissive_file_emits_warning(tmp_path, missing_native, capsys):
    if os.name != "posix":
        pytest.skip("POSIX permission check only")
    auth_file = tmp_path / "auth.json"
    auth_file.write_text(json.dumps({"github-copilot": {"access": "tok"}}), encoding="utf-8")
    os.chmod(auth_file, 0o644)

    resolve_auth(native_path=missing_native, opencode_path=auth_file)

    err = capsys.readouterr().err
    assert "warning" in err.lower()
    assert "chmod 600" in err


def test_strict_mode_no_warning(tmp_path, missing_native, capsys):
    if os.name != "posix":
        pytest.skip("POSIX permission check only")
    auth_file = tmp_path / "auth.json"
    auth_file.write_text(json.dumps({"github-copilot": {"access": "tok"}}), encoding="utf-8")
    os.chmod(auth_file, 0o600)

    resolve_auth(native_path=missing_native, opencode_path=auth_file)

    err = capsys.readouterr().err
    assert err == ""


# --- New: multi-source resolution and native-file reading ---


def test_native_file_wins_over_opencode(tmp_path):
    native_file = tmp_path / "native.json"
    opencode_file = tmp_path / "opencode.json"
    _write(native_file, {"github-copilot": {"token": "ghu_native", "host": "github.com"}})
    _write(opencode_file, {"github-copilot": {"access": "gho_opencode"}})

    auth = resolve_auth(native_path=native_file, opencode_path=opencode_file)

    assert auth.token == "ghu_native"
    assert auth.source == "native"


def test_native_missing_falls_to_opencode(tmp_path, missing_native):
    opencode_file = tmp_path / "opencode.json"
    _write(opencode_file, {"github-copilot": {"access": "gho_opencode"}})

    auth = resolve_auth(native_path=missing_native, opencode_path=opencode_file)

    assert auth.source == "opencode"
    assert auth.token == "gho_opencode"


def test_both_missing_raises_pointing_at_login(tmp_path):
    with pytest.raises(AuthError) as exc:
        resolve_auth(
            native_path=tmp_path / "no-native.json",
            opencode_path=tmp_path / "no-opencode.json",
        )

    assert "copilot-spend login" in str(exc.value)


def test_native_malformed_does_not_fall_to_opencode(tmp_path):
    native_file = tmp_path / "native.json"
    opencode_file = tmp_path / "opencode.json"
    _write(native_file, "{broken")
    _write(opencode_file, {"github-copilot": {"access": "gho_opencode"}})

    with pytest.raises(AuthError) as exc:
        resolve_auth(native_path=native_file, opencode_path=opencode_file)

    assert "copilot-spend" in str(exc.value).lower()


def test_native_missing_token_raises(tmp_path, missing_native):
    native_file = tmp_path / "native.json"
    _write(native_file, {"github-copilot": {"host": "github.com"}})

    with pytest.raises(AuthError):
        resolve_auth(native_path=native_file, opencode_path=missing_native)


def test_native_empty_host_defaults_to_github_com(tmp_path, missing_native):
    native_file = tmp_path / "native.json"
    _write(native_file, {"github-copilot": {"token": "ghu_xxx", "host": ""}})

    auth = resolve_auth(native_path=native_file, opencode_path=missing_native)

    assert auth.host == "github.com"


def test_native_ghe_host(tmp_path, missing_native):
    native_file = tmp_path / "native.json"
    _write(native_file, {"github-copilot": {"token": "ghu_xxx", "host": "ghe.example.com"}})

    auth = resolve_auth(native_path=native_file, opencode_path=missing_native)

    assert auth.host == "ghe.example.com"
    assert auth.source == "native"


def test_native_uses_paths_auth_path_by_default(monkeypatch, tmp_path):
    monkeypatch.setenv("COPILOT_SPEND_CONFIG_DIR", str(tmp_path / "cfg"))
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    os.chmod(cfg, 0o700)
    native_file = cfg / "auth.json"
    _write(native_file, {"github-copilot": {"token": "ghu_default", "host": "github.com"}})

    auth = resolve_auth(opencode_path=tmp_path / "no-opencode.json")

    assert auth.token == "ghu_default"
    assert auth.source == "native"


# --- New: SSRF-relevant host validation ---


@pytest.mark.parametrize(
    "ip",
    [
        "127.0.0.1",
        "10.0.0.1",
        "192.168.1.1",
        "172.16.0.1",
        "169.254.169.254",
        "0.0.0.0",
        "::1",
    ],
)
def test_is_valid_host_rejects_private_ip_literal(ip):
    assert not is_valid_host(ip)


@pytest.mark.parametrize(
    "host",
    [
        "github.com",
        "ghe.example.com",
        "api.github.com",
        "internal.ghe.example",
    ],
)
def test_is_valid_host_accepts_ordinary_hostnames(host):
    assert is_valid_host(host)


def test_normalize_host_strips_scheme_and_trailing_slash():
    assert normalize_host("https://ghe.example.com/") == "ghe.example.com"
    assert normalize_host("http://ghe.example.com") == "ghe.example.com"
    assert normalize_host("ghe.example.com") == "ghe.example.com"
