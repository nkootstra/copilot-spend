from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from importlib.metadata import PackageNotFoundError, version

from copilot_spend.api import APIError, fetch_quota
from copilot_spend.auth import AuthError, resolve_auth
from copilot_spend.output import render
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
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    parser.parse_args(argv)

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
        message = _scrub(str(exc), auth.token if auth else None)
        print(message, file=sys.stderr)
        return 3

    try:
        spend = parse_quota(payload)
    except NoSubscriptionError as exc:
        print(f"no Copilot quota on this account: {exc}", file=sys.stderr)
        return 4

    try:
        print(render(spend, now=datetime.now(timezone.utc)))
    except Exception as exc:
        message = _scrub(f"unexpected error rendering output: {exc}", auth.token if auth else None)
        print(message, file=sys.stderr)
        return 1

    return 0


def _scrub(text: str, token: str | None) -> str:
    if token and token in text:
        return text.replace(token, "<redacted-token>")
    return text


def _entrypoint() -> None:
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception as exc:
        # Defensive top-level catch — no traceback exposed to user.
        # We have no auth object here; print a generic single-line message.
        print(f"unexpected error: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    _entrypoint()
