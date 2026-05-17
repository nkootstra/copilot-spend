from __future__ import annotations

import io
import json
import socket
import stat
import time
import urllib.error
from unittest.mock import patch

import pytest

from copilot_spend import paths, session
from copilot_spend.auth import Auth, AuthError


def _auth(host: str = "github.com", token: str = "ghu_token") -> Auth:
    return Auth(token=token, host=host, source="native")


@pytest.fixture(autouse=True)
def _cfg_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("COPILOT_SPEND_CONFIG_DIR", str(tmp_path))
    return tmp_path


def _mock_urlopen(*, status: int = 200, body: bytes | dict | None = None,
                  exc: Exception | None = None):
    if exc is not None:
        def raise_exc(*_args, **_kwargs):
            raise exc
        return raise_exc

    if isinstance(body, dict):
        body = json.dumps(body).encode("utf-8")
    payload = body or b"{}"

    class _FakeResp:
        def __init__(self, raw: bytes):
            self._raw = raw

        def __enter__(self):
            return self

        def __exit__(self, *_a):
            return False

        def read(self):
            return self._raw

    def opener(*_a, **_kw):
        return _FakeResp(payload)

    return opener


def test_exchange_token_happy_github_com():
    auth = _auth()
    expires = int(time.time()) + 1800
    opener = _mock_urlopen(body={"token": "sess_secret", "expires_at": expires})

    with patch("copilot_spend.session.urllib.request.urlopen", opener):
        result = session.exchange_token(auth)

    assert result == {"token": "sess_secret", "expires_at": expires}


def test_exchange_token_ghe_url(monkeypatch):
    auth = _auth(host="ghe.example.com")
    captured = {}

    def opener(request, *_a, **_kw):
        captured["url"] = request.full_url
        captured["headers"] = dict(request.headers)

        class _R:
            def __enter__(self_): return self_
            def __exit__(self_, *_): return False
            def read(self_):
                return json.dumps({"token": "sess_x", "expires_at": int(time.time()) + 1800}).encode()
        return _R()

    monkeypatch.setattr(session.urllib.request, "urlopen", opener)
    session.exchange_token(auth)

    assert captured["url"] == "https://ghe.example.com/api/v3/copilot_internal/v2/token"


def test_exchange_sends_required_editor_headers(monkeypatch):
    auth = _auth()
    captured = {}

    def opener(request, *_a, **_kw):
        # urllib lowercases header keys via Request.headers; check by case-insensitive lookup.
        captured["headers"] = {k.lower(): v for k, v in request.headers.items()}

        class _R:
            def __enter__(self_): return self_
            def __exit__(self_, *_): return False
            def read(self_):
                return json.dumps({"token": "sess_x", "expires_at": int(time.time()) + 1800}).encode()
        return _R()

    monkeypatch.setattr(session.urllib.request, "urlopen", opener)
    session.exchange_token(auth)

    h = captured["headers"]
    assert h["editor-version"] == "vscode/1.99.0"
    assert h["editor-plugin-version"] == "copilot-chat/0.26.7"
    assert h["user-agent"] == "GitHubCopilotChat/0.26.7"
    assert h["x-github-api-version"] == "2025-04-01"
    assert h["authorization"] == "token ghu_token"


def test_exchange_401_raises_auth_error():
    auth = _auth()
    err = urllib.error.HTTPError(
        url="x", code=401, msg="Unauthorized", hdrs=None,
        fp=io.BytesIO(b'{"error": "bad token"}'),
    )

    with patch("copilot_spend.session.urllib.request.urlopen", side_effect=err):
        with pytest.raises(AuthError) as exc:
            session.exchange_token(auth)

    assert "copilot-spend login" in str(exc.value)


def test_exchange_403_raises_auth_error():
    auth = _auth()
    err = urllib.error.HTTPError(
        url="x", code=403, msg="Forbidden", hdrs=None,
        fp=io.BytesIO(b"{}"),
    )

    with patch("copilot_spend.session.urllib.request.urlopen", side_effect=err):
        with pytest.raises(AuthError):
            session.exchange_token(auth)


def test_exchange_404_raises_api_error():
    auth = _auth()
    err = urllib.error.HTTPError(
        url="x", code=404, msg="Not Found", hdrs=None,
        fp=io.BytesIO(b'{"message": "no exchange"}'),
    )

    with patch("copilot_spend.session.urllib.request.urlopen", side_effect=err):
        with pytest.raises(session.APIError) as exc:
            session.exchange_token(auth)

    assert "404" in str(exc.value)


def test_exchange_timeout_raises_api_error():
    auth = _auth()
    with patch("copilot_spend.session.urllib.request.urlopen", side_effect=socket.timeout()):
        with pytest.raises(session.APIError) as exc:
            session.exchange_token(auth)

    assert "timed out" in str(exc.value)


def test_exchange_url_error_raises_api_error():
    auth = _auth(host="ghe.example.com")
    with patch(
        "copilot_spend.session.urllib.request.urlopen",
        side_effect=urllib.error.URLError("host not found"),
    ):
        with pytest.raises(session.APIError) as exc:
            session.exchange_token(auth)

    assert "ghe.example.com" in str(exc.value)


def test_exchange_token_rejects_invalid_token_field():
    auth = _auth()
    opener = _mock_urlopen(body={"token": "bad\nvalue", "expires_at": 1})

    with patch("copilot_spend.session.urllib.request.urlopen", opener):
        with pytest.raises(session.APIError) as exc:
            session.exchange_token(auth)

    assert "invalid token field" in str(exc.value)


def test_exchange_token_rejects_non_numeric_expires_at():
    auth = _auth()
    opener = _mock_urlopen(body={"token": "sess_ok", "expires_at": "soon"})

    with patch("copilot_spend.session.urllib.request.urlopen", opener):
        with pytest.raises(session.APIError):
            session.exchange_token(auth)


def test_exchange_token_redacts_oauth_token_in_error_body():
    auth = _auth(token="ghu_super_secret")
    err = urllib.error.HTTPError(
        url="x", code=500, msg="boom", hdrs=None,
        fp=io.BytesIO(b'leaked: ghu_super_secret here'),
    )

    with patch("copilot_spend.session.urllib.request.urlopen", side_effect=err):
        with pytest.raises(session.APIError) as exc:
            session.exchange_token(auth)

    assert "ghu_super_secret" not in str(exc.value)
    assert "<redacted-token>" in str(exc.value)


# --- get_or_refresh ---


def test_get_or_refresh_uses_fresh_cache(tmp_path):
    payload = {"token": "sess_cached", "expires_at": int(time.time()) + 1800}
    paths.write_secret_file(paths.session_path(), payload)

    with patch("copilot_spend.session.urllib.request.urlopen") as mock_open:
        token = session.get_or_refresh(_auth())

    assert token == "sess_cached"
    mock_open.assert_not_called()


def test_get_or_refresh_refreshes_on_stale_cache():
    payload = {"token": "sess_old", "expires_at": int(time.time()) + 10}  # < 60s buffer
    paths.write_secret_file(paths.session_path(), payload)

    new_expires = int(time.time()) + 1800
    opener = _mock_urlopen(body={"token": "sess_new", "expires_at": new_expires})

    with patch("copilot_spend.session.urllib.request.urlopen", opener):
        token = session.get_or_refresh(_auth())

    assert token == "sess_new"
    cached = json.loads(paths.session_path().read_text())
    assert cached["token"] == "sess_new"


def test_get_or_refresh_refreshes_on_missing_cache():
    new_expires = int(time.time()) + 1800
    opener = _mock_urlopen(body={"token": "sess_fresh", "expires_at": new_expires})

    with patch("copilot_spend.session.urllib.request.urlopen", opener):
        token = session.get_or_refresh(_auth())

    assert token == "sess_fresh"
    assert paths.session_path().exists()
    mode = stat.S_IMODE(paths.session_path().stat().st_mode)
    assert mode == 0o600


def test_get_or_refresh_malformed_cache_is_silent_miss():
    paths.session_path().parent.mkdir(parents=True, exist_ok=True)
    paths.session_path().write_text("{not json")

    new_expires = int(time.time()) + 1800
    opener = _mock_urlopen(body={"token": "sess_recovered", "expires_at": new_expires})

    with patch("copilot_spend.session.urllib.request.urlopen", opener):
        token = session.get_or_refresh(_auth())

    assert token == "sess_recovered"


def test_get_or_refresh_cache_with_control_chars_is_silent_miss():
    paths.write_secret_file(
        paths.session_path(),
        {"token": "embedded\ncontrol", "expires_at": int(time.time()) + 1800},
    )

    new_expires = int(time.time()) + 1800
    opener = _mock_urlopen(body={"token": "sess_clean", "expires_at": new_expires})

    with patch("copilot_spend.session.urllib.request.urlopen", opener):
        token = session.get_or_refresh(_auth())

    assert token == "sess_clean"


def test_get_or_refresh_cache_missing_fields_is_silent_miss():
    paths.write_secret_file(paths.session_path(), {"only": "wrong-keys"})

    new_expires = int(time.time()) + 1800
    opener = _mock_urlopen(body={"token": "sess_ok", "expires_at": new_expires})

    with patch("copilot_spend.session.urllib.request.urlopen", opener):
        token = session.get_or_refresh(_auth())

    assert token == "sess_ok"


def test_get_or_refresh_401_propagates_without_writing_cache():
    err = urllib.error.HTTPError(
        url="x", code=401, msg="Unauthorized", hdrs=None,
        fp=io.BytesIO(b"{}"),
    )

    with patch("copilot_spend.session.urllib.request.urlopen", side_effect=err):
        with pytest.raises(AuthError):
            session.get_or_refresh(_auth())

    assert not paths.session_path().exists()
