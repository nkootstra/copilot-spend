from __future__ import annotations

import io
import json
import stat
import urllib.error
from typing import Any

import pytest

from copilot_spend import api, login, paths
from copilot_spend.quota import NoSubscriptionError


@pytest.fixture(autouse=True)
def _cfg_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("COPILOT_SPEND_CONFIG_DIR", str(tmp_path))
    return tmp_path


def _stdin(text: str) -> io.StringIO:
    return io.StringIO(text)


def _post_json_sequence(*responses: Any):
    """Return a callable that yields each scripted response in order on call."""
    queue = list(responses)

    def fake(url: str, body: dict, *, timeout: float = 10.0):
        if not queue:
            raise AssertionError(f"unexpected extra POST to {url} with {body}")
        item = queue.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item

    return fake, queue


def _device_response(**overrides):
    base = {
        "device_code": "dev123",
        "user_code": "USER-CODE",
        "verification_uri": "https://github.com/login/device",
        "interval": 1,
        "expires_in": 900,
    }
    base.update(overrides)
    return base


def test_run_login_happy_github_com(monkeypatch, capsys):
    fake, _ = _post_json_sequence(
        _device_response(),
        {"access_token": "ghu_realtoken"},
    )
    monkeypatch.setattr(login, "_post_json", fake)
    monkeypatch.setattr(api, "fetch_quota", lambda auth, **_: {"login": "u"})

    rc = login.run_login(
        stdin=_stdin("1\n"),
        sleep=lambda _s: None,
        now=lambda: 0.0,
    )

    out = capsys.readouterr()
    assert rc == 0
    assert "Logged in" in out.out
    assert "USER-CODE" in out.out
    assert paths.auth_path().exists()
    auth_data = json.loads(paths.auth_path().read_text())
    assert auth_data == {"github-copilot": {"token": "ghu_realtoken", "host": "github.com"}}
    assert stat.S_IMODE(paths.auth_path().stat().st_mode) == 0o600


def test_run_login_happy_ghe(monkeypatch, capsys):
    captured_urls: list[str] = []

    def fake_post(url: str, body: dict, *, timeout: float = 10.0):
        captured_urls.append(url)
        if "device/code" in url:
            return _device_response()
        return {"access_token": "ghu_ghe"}

    monkeypatch.setattr(login, "_post_json", fake_post)
    monkeypatch.setattr(api, "fetch_quota", lambda auth, **_: {"login": "u"})

    rc = login.run_login(
        stdin=_stdin("2\nghe.example.com\n"),
        sleep=lambda _s: None,
        now=lambda: 0.0,
    )

    assert rc == 0
    assert captured_urls[0] == "https://ghe.example.com/login/device/code"
    assert captured_urls[1] == "https://ghe.example.com/login/oauth/access_token"
    auth_data = json.loads(paths.auth_path().read_text())
    assert auth_data["github-copilot"]["host"] == "ghe.example.com"


def test_run_login_unauthorized_client_exits_2(monkeypatch, capsys):
    fake, _ = _post_json_sequence(
        {"error": "unauthorized_client", "error_description": "App not allowed"},
    )
    monkeypatch.setattr(login, "_post_json", fake)

    rc = login.run_login(
        stdin=_stdin("1\n"),
        sleep=lambda _s: None,
        now=lambda: 0.0,
    )

    err = capsys.readouterr().err
    assert rc == 2
    assert "unauthorized_client" in err
    assert not paths.auth_path().exists()


def test_run_login_expired_token_exits_2(monkeypatch, capsys):
    fake, _ = _post_json_sequence(
        _device_response(),
        {"error": "expired_token"},
    )
    monkeypatch.setattr(login, "_post_json", fake)

    rc = login.run_login(
        stdin=_stdin("1\n"),
        sleep=lambda _s: None,
        now=lambda: 0.0,
    )

    assert rc == 2
    err = capsys.readouterr().err
    assert "timed out" in err.lower()
    assert not paths.auth_path().exists()


def test_run_login_defensive_timeout_via_monotonic(monkeypatch, capsys):
    fake, _ = _post_json_sequence(
        _device_response(),
        # Will never be returned because the elapsed-time guard fires first.
        {"error": "authorization_pending"},
    )
    monkeypatch.setattr(login, "_post_json", fake)

    clock = iter([0.0, 9999.0])

    rc = login.run_login(
        stdin=_stdin("1\n"),
        sleep=lambda _s: None,
        now=lambda: next(clock),
    )

    assert rc == 2
    err = capsys.readouterr().err
    assert "timed out" in err.lower()
    assert not paths.auth_path().exists()


def test_run_login_device_code_url_error_exits_2(monkeypatch, capsys):
    def boom(url, body, **_):
        raise urllib.error.URLError("host not found")

    monkeypatch.setattr(login, "_post_json", boom)

    rc = login.run_login(
        stdin=_stdin("2\nunreachable.example.com\n"),
        sleep=lambda _s: None,
        now=lambda: 0.0,
    )

    assert rc == 2
    err = capsys.readouterr().err
    assert "unreachable.example.com" in err
    assert "USER-CODE" not in capsys.readouterr().out
    assert not paths.auth_path().exists()


def test_run_login_access_denied_exits_2(monkeypatch, capsys):
    fake, _ = _post_json_sequence(
        _device_response(),
        {"error": "access_denied"},
    )
    monkeypatch.setattr(login, "_post_json", fake)

    rc = login.run_login(
        stdin=_stdin("1\n"),
        sleep=lambda _s: None,
        now=lambda: 0.0,
    )

    assert rc == 2
    assert "denied" in capsys.readouterr().err.lower()


def test_run_login_slow_down_extends_interval(monkeypatch, capsys):
    fake, _ = _post_json_sequence(
        _device_response(interval=2),
        {"error": "slow_down"},
        {"access_token": "ghu_ok"},
    )
    monkeypatch.setattr(login, "_post_json", fake)
    monkeypatch.setattr(api, "fetch_quota", lambda auth, **_: {"login": "u"})

    sleeps: list[int] = []
    rc = login.run_login(
        stdin=_stdin("1\n"),
        sleep=lambda s: sleeps.append(s),
        now=lambda: 0.0,
    )

    assert rc == 0
    # First sleep at interval=2; after slow_down, interval becomes 7.
    assert sleeps == [2, 7]


def test_run_login_wrong_token_prefix_exits_2(monkeypatch, capsys):
    fake, _ = _post_json_sequence(
        _device_response(),
        {"access_token": "gho_oauth_token"},
    )
    monkeypatch.setattr(login, "_post_json", fake)

    rc = login.run_login(
        stdin=_stdin("1\n"),
        sleep=lambda _s: None,
        now=lambda: 0.0,
    )

    assert rc == 2
    err = capsys.readouterr().err
    assert "ghu_" in err  # mentions expected prefix
    assert not paths.auth_path().exists()


def test_run_login_verification_failure_does_not_write_auth(monkeypatch, capsys):
    fake, _ = _post_json_sequence(
        _device_response(),
        {"access_token": "ghu_real"},
    )
    monkeypatch.setattr(login, "_post_json", fake)

    def boom(_auth, **_):
        raise api.APIError("server says no")

    monkeypatch.setattr(api, "fetch_quota", boom)

    rc = login.run_login(
        stdin=_stdin("1\n"),
        sleep=lambda _s: None,
        now=lambda: 0.0,
    )

    assert rc == 2
    err = capsys.readouterr().err
    assert "verification failed" in err
    assert not paths.auth_path().exists()


def test_run_login_verification_error_redacts_token(monkeypatch, capsys):
    fake, _ = _post_json_sequence(
        _device_response(),
        {"access_token": "ghu_secret_realtoken"},
    )
    monkeypatch.setattr(login, "_post_json", fake)

    def boom(_auth, **_):
        raise api.APIError("server says: ghu_secret_realtoken is bad")

    monkeypatch.setattr(api, "fetch_quota", boom)

    rc = login.run_login(
        stdin=_stdin("1\n"),
        sleep=lambda _s: None,
        now=lambda: 0.0,
    )

    assert rc == 2
    err = capsys.readouterr().err
    assert "ghu_secret_realtoken" not in err
    assert "<redacted-token>" in err


def test_run_login_no_subscription_exits_2(monkeypatch, capsys):
    fake, _ = _post_json_sequence(
        _device_response(),
        {"access_token": "ghu_no_sub"},
    )
    monkeypatch.setattr(login, "_post_json", fake)

    def no_sub(_auth, **_):
        raise NoSubscriptionError("nope")

    monkeypatch.setattr(api, "fetch_quota", no_sub)

    rc = login.run_login(
        stdin=_stdin("1\n"),
        sleep=lambda _s: None,
        now=lambda: 0.0,
    )

    assert rc == 2
    err = capsys.readouterr().err
    assert "no copilot quota" in err.lower()
    assert not paths.auth_path().exists()


def test_run_login_reauth_notice_on_existing_auth(monkeypatch, capsys):
    # Pre-populate auth.json so re-auth path fires.
    paths.write_secret_file(
        paths.auth_path(),
        {"github-copilot": {"token": "ghu_old", "host": "github.com"}},
    )

    fake, _ = _post_json_sequence(
        _device_response(),
        {"access_token": "ghu_new"},
    )
    monkeypatch.setattr(login, "_post_json", fake)
    monkeypatch.setattr(api, "fetch_quota", lambda auth, **_: {"login": "u"})

    rc = login.run_login(
        stdin=_stdin("1\n"),
        sleep=lambda _s: None,
        now=lambda: 0.0,
    )

    assert rc == 0
    err = capsys.readouterr().err
    assert "Re-authenticating" in err
    assert json.loads(paths.auth_path().read_text())["github-copilot"]["token"] == "ghu_new"


def test_run_login_cleans_up_legacy_session_json(monkeypatch, capsys, tmp_path):
    # Pre-existing legacy session.json from prior version.
    legacy = paths.config_dir() / "session.json"
    paths.write_secret_file(legacy, {"token": "old_sess", "expires_at": 1})
    assert legacy.exists()

    fake, _ = _post_json_sequence(
        _device_response(),
        {"access_token": "ghu_x"},
    )
    monkeypatch.setattr(login, "_post_json", fake)
    monkeypatch.setattr(api, "fetch_quota", lambda auth, **_: {"login": "u"})

    rc = login.run_login(
        stdin=_stdin("1\n"),
        sleep=lambda _s: None,
        now=lambda: 0.0,
    )

    assert rc == 0
    assert not legacy.exists(), "login should remove stale legacy session.json"


def test_run_login_ctrl_c_during_polling(monkeypatch, capsys):
    fake, _ = _post_json_sequence(
        _device_response(),
        KeyboardInterrupt(),
    )
    monkeypatch.setattr(login, "_post_json", fake)

    rc = login.run_login(
        stdin=_stdin("1\n"),
        sleep=lambda _s: None,
        now=lambda: 0.0,
    )

    assert rc == 2
    assert "cancelled" in capsys.readouterr().err.lower()
    assert not paths.auth_path().exists()


def test_run_login_rejects_ssrf_target(monkeypatch, capsys):
    rc = login.run_login(
        stdin=_stdin("2\n169.254.169.254\n"),
        sleep=lambda _s: None,
        now=lambda: 0.0,
    )

    assert rc == 2
    err = capsys.readouterr().err
    assert "hostname" in err.lower()
    assert not paths.auth_path().exists()


def _http_error(status: int, body: bytes = b"") -> urllib.error.HTTPError:
    return urllib.error.HTTPError(
        url="https://github.test/x",
        code=status,
        msg="error",
        hdrs=None,
        fp=io.BytesIO(body),
    )


def test_run_login_device_code_http_error_surfaces_json_error_description(monkeypatch, capsys):
    body = json.dumps(
        {"error": "invalid_request", "error_description": "client_id is missing"}
    ).encode("utf-8")
    fake, _ = _post_json_sequence(_http_error(422, body))
    monkeypatch.setattr(login, "_post_json", fake)

    rc = login.run_login(
        stdin=_stdin("1\n"),
        sleep=lambda _s: None,
        now=lambda: 0.0,
    )

    assert rc == 2
    err = capsys.readouterr().err
    assert "422" in err
    assert "invalid_request" in err
    assert "client_id is missing" in err


def test_run_login_device_code_http_error_with_non_json_body_includes_excerpt(monkeypatch, capsys):
    fake, _ = _post_json_sequence(_http_error(503, b"upstream unavailable"))
    monkeypatch.setattr(login, "_post_json", fake)

    rc = login.run_login(
        stdin=_stdin("1\n"),
        sleep=lambda _s: None,
        now=lambda: 0.0,
    )

    assert rc == 2
    err = capsys.readouterr().err
    assert "503" in err
    assert "upstream unavailable" in err


def test_run_login_polling_http_error_surfaces_json_error_description(monkeypatch, capsys):
    body = json.dumps(
        {"error": "incorrect_client_credentials", "error_description": "client_secret invalid"}
    ).encode("utf-8")
    fake, _ = _post_json_sequence(
        _device_response(),
        _http_error(401, body),
    )
    monkeypatch.setattr(login, "_post_json", fake)

    rc = login.run_login(
        stdin=_stdin("1\n"),
        sleep=lambda _s: None,
        now=lambda: 0.0,
    )

    assert rc == 2
    err = capsys.readouterr().err
    assert "401" in err
    assert "incorrect_client_credentials" in err
    assert "client_secret invalid" in err


def test_run_logout_removes_auth_and_legacy_session(capsys):
    paths.write_secret_file(paths.auth_path(), {"k": "v"})
    legacy = paths.config_dir() / "session.json"
    paths.write_secret_file(legacy, {"token": "sess", "expires_at": 1})

    rc = login.run_logout()

    assert rc == 0
    assert "Logged out" in capsys.readouterr().out
    assert not paths.auth_path().exists()
    assert not legacy.exists()


def test_run_logout_when_missing_is_idempotent(capsys):
    rc = login.run_logout()

    assert rc == 0
    assert "Logged out" in capsys.readouterr().out
