from __future__ import annotations

import pytest

import copilot_spend.cli as cli_module
from copilot_spend.api import APIError
from copilot_spend.auth import Auth, AuthError
from copilot_spend.quota import NoSubscriptionError


def test_module_imports():
    import copilot_spend
    import copilot_spend.cli

    assert callable(copilot_spend.cli.main)
    assert callable(copilot_spend.cli._entrypoint)


def test_version_flag_prints_and_exits_zero(capsys):
    with pytest.raises(SystemExit) as exc:
        cli_module.main(["--version"])

    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "copilot-spend" in out


def test_login_subcommand_dispatches(monkeypatch):
    called = {}

    def fake_login():
        called["login"] = True
        return 0

    # Patch the import target so the lazy import in main() picks up the fake.
    import copilot_spend.login as login_module

    monkeypatch.setattr(login_module, "run_login", fake_login)

    rc = cli_module.main(["login"])

    assert rc == 0
    assert called == {"login": True}


def test_logout_subcommand_dispatches(monkeypatch):
    called = {}

    def fake_logout():
        called["logout"] = True
        return 0

    import copilot_spend.login as login_module

    monkeypatch.setattr(login_module, "run_logout", fake_logout)

    rc = cli_module.main(["logout"])

    assert rc == 0
    assert called == {"logout": True}


def test_unknown_subcommand_exits_nonzero(capsys):
    with pytest.raises(SystemExit) as exc:
        cli_module.main(["nope"])

    assert exc.value.code != 0


def test_whoami_subcommand_dispatches(monkeypatch):
    called = {}

    def fake_whoami():
        called["whoami"] = True
        return 0

    monkeypatch.setattr(cli_module, "_run_whoami", fake_whoami)

    rc = cli_module.main(["whoami"])

    assert rc == 0
    assert called == {"whoami": True}


def test_whoami_prints_login_host_source_and_plan(monkeypatch, capsys):
    auth = Auth(token="t", host="github.com", source="native")
    monkeypatch.setattr(cli_module, "resolve_auth", lambda: auth)
    monkeypatch.setattr(
        cli_module,
        "fetch_quota",
        lambda a: {"login": "alice", "copilot_plan": "business"},
    )

    rc = cli_module.main(["whoami"])

    assert rc == 0
    out = capsys.readouterr().out
    assert "login:" in out and "alice" in out
    assert "host:" in out and "github.com" in out
    assert "source:" in out and "native" in out
    assert "plan:" in out and "business" in out


def test_whoami_prints_identity_even_without_subscription(monkeypatch, capsys):
    auth = Auth(token="t", host="ghe.example.com", source="opencode")
    monkeypatch.setattr(cli_module, "resolve_auth", lambda: auth)

    def no_sub(_a):
        raise NoSubscriptionError("no quota")

    monkeypatch.setattr(cli_module, "fetch_quota", no_sub)

    rc = cli_module.main(["whoami"])

    assert rc == 0
    out = capsys.readouterr().out
    assert "ghe.example.com" in out
    assert "opencode" in out
    assert "no Copilot quota" in out


def test_whoami_auth_error_exits_2(monkeypatch, capsys):
    def boom():
        raise AuthError("no creds")

    monkeypatch.setattr(cli_module, "resolve_auth", boom)

    rc = cli_module.main(["whoami"])

    assert rc == 2
    err = capsys.readouterr().err
    assert "no creds" in err


def test_whoami_api_error_exits_3_and_scrubs_token(monkeypatch, capsys):
    auth = Auth(token="hunter2-token", host="github.com", source="native")
    monkeypatch.setattr(cli_module, "resolve_auth", lambda: auth)

    def api_boom(_a):
        raise APIError("upstream said hunter2-token is bad")

    monkeypatch.setattr(cli_module, "fetch_quota", api_boom)

    rc = cli_module.main(["whoami"])

    assert rc == 3
    err = capsys.readouterr().err
    assert "hunter2-token" not in err


def test_bare_invocation_runs_show_quota(monkeypatch):
    called = {}

    def fake_show(*, as_json=False):
        called["show"] = True
        called["as_json"] = as_json
        return 0

    monkeypatch.setattr(cli_module, "_run_show_quota", fake_show)

    rc = cli_module.main([])

    assert rc == 0
    assert called == {"show": True, "as_json": False}


def test_json_flag_passes_through_to_show_quota(monkeypatch):
    called = {}

    def fake_show(*, as_json=False):
        called["as_json"] = as_json
        return 0

    monkeypatch.setattr(cli_module, "_run_show_quota", fake_show)

    rc = cli_module.main(["--json"])

    assert rc == 0
    assert called["as_json"] is True


def test_json_flag_emits_parseable_json(monkeypatch, capsys):
    import json

    from copilot_spend.quota import Spend

    auth = Auth(token="t", host="github.com", source="native")
    monkeypatch.setattr(cli_module, "resolve_auth", lambda: auth)
    monkeypatch.setattr(cli_module, "fetch_quota", lambda a: {})
    fake_spend = Spend(
        login="alice",
        plan="business",
        entitlement=300,
        consumed=100,
        billable_prus=0,
        free_remaining_prus=200,
        dollars_owed=0.0,
        dollars_entitlement=12.0,
        dollars_free_remaining=8.0,
        reset=None,
    )
    monkeypatch.setattr(cli_module, "parse_quota", lambda _payload: fake_spend)

    rc = cli_module.main(["--json"])

    assert rc == 0
    out = capsys.readouterr().out
    parsed = json.loads(out)
    assert parsed["login"] == "alice"
    assert parsed["consumed_prus"] == 100


def test_entrypoint_catches_unexpected_exception(monkeypatch, capsys):
    def boom(_argv=None):
        raise RuntimeError("kaboom")

    monkeypatch.setattr(cli_module, "main", boom)

    with pytest.raises(SystemExit) as exc:
        cli_module._entrypoint()

    assert exc.value.code == 1
    assert "unexpected error" in capsys.readouterr().err


def test_entrypoint_passes_through_system_exit(monkeypatch):
    def exits():
        raise SystemExit(7)

    monkeypatch.setattr(cli_module, "main", exits)

    with pytest.raises(SystemExit) as exc:
        cli_module._entrypoint()

    assert exc.value.code == 7


def test_entrypoint_mentions_debug_env_in_error(monkeypatch, capsys):
    def boom(_argv=None):
        raise RuntimeError("kaboom")

    monkeypatch.setattr(cli_module, "main", boom)
    monkeypatch.delenv("COPILOT_SPEND_DEBUG", raising=False)

    with pytest.raises(SystemExit):
        cli_module._entrypoint()

    err = capsys.readouterr().err
    assert "COPILOT_SPEND_DEBUG" in err


def test_entrypoint_reraises_under_debug_env(monkeypatch):
    def boom(_argv=None):
        raise RuntimeError("kaboom")

    monkeypatch.setattr(cli_module, "main", boom)
    monkeypatch.setenv("COPILOT_SPEND_DEBUG", "1")

    with pytest.raises(RuntimeError, match="kaboom"):
        cli_module._entrypoint()
