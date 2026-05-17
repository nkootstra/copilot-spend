from __future__ import annotations

import pytest

import copilot_spend.cli as cli_module


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


def test_bare_invocation_runs_show_quota(monkeypatch):
    called = {}

    def fake_show():
        called["show"] = True
        return 0

    monkeypatch.setattr(cli_module, "_run_show_quota", fake_show)

    rc = cli_module.main([])

    assert rc == 0
    assert called == {"show": True}


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
