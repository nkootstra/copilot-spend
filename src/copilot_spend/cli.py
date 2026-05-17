from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone
from importlib.metadata import PackageNotFoundError, version

from copilot_spend.api import APIError, fetch_quota
from copilot_spend.auth import AuthError, resolve_auth
from copilot_spend.output import render, render_json
from copilot_spend.paths import scrub
from copilot_spend.quota import NoSubscriptionError, parse_quota


def _package_version() -> str:
    try:
        return version("copilot-spend")
    except PackageNotFoundError:
        return "dev"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="copilot-spend",
        description="Print your current-period GitHub Copilot spend and reset date.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"copilot-spend {_package_version()}",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print the current spend as JSON (stable schema).",
    )
    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser(
        "login",
        help="Authenticate via GitHub OAuth device flow (github.com or GHE).",
    )
    subparsers.add_parser(
        "logout",
        help="Remove copilot-spend's stored credentials.",
    )
    subparsers.add_parser(
        "whoami",
        help="Print the current login, host, credential source, and Copilot plan.",
    )
    return parser


def _run_show_quota(*, as_json: bool = False) -> int:
    auth = None
    try:
        auth = resolve_auth()
    except AuthError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    try:
        payload = fetch_quota(auth)
    except NoSubscriptionError as exc:
        print(f"no Copilot quota on this account: {exc}", file=sys.stderr)
        return 4
    except APIError as exc:
        print(scrub(str(exc), auth.token if auth else None), file=sys.stderr)
        return 3

    try:
        spend = parse_quota(payload)
    except NoSubscriptionError as exc:
        print(f"no Copilot quota on this account: {exc}", file=sys.stderr)
        return 4

    try:
        if as_json:
            print(render_json(spend))
        else:
            print(render(spend, now=datetime.now(timezone.utc)))
    except Exception as exc:
        print(
            scrub(f"unexpected error rendering output: {exc}", auth.token if auth else None),
            file=sys.stderr,
        )
        return 1

    return 0


def _run_whoami() -> int:
    try:
        auth = resolve_auth()
    except AuthError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    login = ""
    plan = ""
    try:
        payload = fetch_quota(auth)
    except NoSubscriptionError:
        # Identity is still meaningful without a quota — print what we have.
        payload = None
    except APIError as exc:
        print(scrub(str(exc), auth.token), file=sys.stderr)
        return 3

    if isinstance(payload, dict):
        login = str(payload.get("login") or "")
        plan = str(payload.get("copilot_plan") or "")

    lines = [
        f"host:   {auth.host}",
        f"source: {auth.source}",
    ]
    if login:
        lines.insert(0, f"login:  {login}")
    if plan:
        lines.append(f"plan:   {plan}")
    elif payload is None:
        lines.append("plan:   (no Copilot quota on this account)")

    print("\n".join(lines))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command == "login":
        from copilot_spend.login import run_login

        return run_login()
    if args.command == "logout":
        from copilot_spend.login import run_logout

        return run_logout()
    if args.command == "whoami":
        return _run_whoami()

    return _run_show_quota(as_json=bool(args.json))


def _entrypoint() -> None:
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception as exc:
        if os.environ.get("COPILOT_SPEND_DEBUG") == "1":
            raise
        print(
            f"unexpected error: {exc} (set COPILOT_SPEND_DEBUG=1 for a full traceback)",
            file=sys.stderr,
        )
        sys.exit(1)


if __name__ == "__main__":
    _entrypoint()
