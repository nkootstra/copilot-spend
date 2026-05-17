from __future__ import annotations

import json
import ssl
import urllib.error
import urllib.request
from importlib.metadata import PackageNotFoundError, version
from typing import Any, cast

from copilot_spend.auth import Auth
from copilot_spend.paths import scrub
from copilot_spend.quota import NoSubscriptionError


class APIError(Exception):
    pass


def _package_version() -> str:
    try:
        return version("copilot-spend")
    except PackageNotFoundError:
        return "dev"


def _build_url(host: str) -> str:
    if host == "github.com":
        return "https://api.github.com/copilot_internal/user"
    return f"https://{host}/api/v3/copilot_internal/user"


def _body_excerpt(raw: bytes, limit: int = 500) -> str:
    try:
        text = raw.decode("utf-8", errors="replace")
    except Exception:
        text = "<unreadable response body>"
    text = text.strip()
    if len(text) > limit:
        text = text[:limit] + "…"
    return text


def _reauth_message(source: str) -> str:
    if source == "native":
        return "Token rejected by GitHub Copilot. Run `copilot-spend login` to re-authenticate."
    return (
        "Token rejected by GitHub Copilot — opencode token may be expired. "
        "Run `opencode login` to refresh."
    )


def fetch_quota(auth: Auth, *, timeout: float = 10.0) -> dict[str, Any]:
    # `/copilot_internal/user` accepts the OAuth/GitHub-App user token
    # directly as Bearer for both `ghu_` (native) and `gho_` (opencode).
    # No session-token exchange — that token (`/copilot_internal/v2/token`)
    # is for the Copilot Chat proxy at api.githubcopilot.com, not this endpoint.
    url = _build_url(auth.host)
    request = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {auth.token}",
            "User-Agent": f"copilot-spend/{_package_version()}",
            "Accept": "application/json",
        },
        method="GET",
    )

    context = ssl.create_default_context()

    try:
        with urllib.request.urlopen(request, timeout=timeout, context=context) as response:
            raw = response.read()
    except urllib.error.HTTPError as exc:
        status = exc.code
        if status in (401, 403):
            raise APIError(_reauth_message(auth.source)) from None
        if status == 404:
            raise NoSubscriptionError("No Copilot quota on this account.") from None
        try:
            body = scrub(_body_excerpt(exc.read()), auth.token)
        except Exception:
            body = "<no response body>"
        if 500 <= status < 600:
            raise APIError(
                f"GitHub Copilot API returned {status} at {url} — try again shortly."
            ) from None
        raise APIError(f"GitHub Copilot API returned {status} at {url}: {body}") from None
    except TimeoutError:
        raise APIError(f"Request to {auth.host} timed out after {timeout}s.") from None
    except urllib.error.URLError as exc:
        underlying = getattr(exc, "reason", exc)
        raise APIError(f"Could not reach {auth.host}: {underlying}") from None

    try:
        parsed = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise APIError(f"GitHub Copilot API at {url} returned a non-JSON response: {exc}") from None
    if not isinstance(parsed, dict):
        raise APIError(f"GitHub Copilot API at {url} returned non-object JSON.") from None
    return cast(dict[str, Any], parsed)
