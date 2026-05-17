from __future__ import annotations

import json
import socket
import ssl
import time
import urllib.error
import urllib.request
from typing import Any

from .auth import Auth, AuthError
from . import paths

SESSION_REFRESH_BUFFER_S = 60

# Editor-identity headers Copilot's session-token endpoint expects.
# These mimic the official VS Code Copilot Chat extension. See plan U3 risk
# row "Required Copilot editor headers change" for the pre-merge probe gate.
COPILOT_EDITOR_HEADERS: dict[str, str] = {
    "editor-version": "vscode/1.99.0",
    "editor-plugin-version": "copilot-chat/0.26.7",
    "user-agent": "GitHubCopilotChat/0.26.7",
    "x-github-api-version": "2025-04-01",
}


class APIError(Exception):
    """Raised on transport / HTTP failures during session-token exchange.

    Kept separate from copilot_spend.api.APIError to avoid an import cycle.
    Callers can catch this as a stdlib Exception; cli.py funnels both
    through the same exit-code-3 path.
    """


def _exchange_url(host: str) -> str:
    if host == "github.com":
        return "https://api.github.com/copilot_internal/v2/token"
    return f"https://{host}/api/v3/copilot_internal/v2/token"


def _body_excerpt(raw: bytes, limit: int = 500) -> str:
    try:
        text = raw.decode("utf-8", errors="replace")
    except Exception:
        text = "<unreadable response body>"
    text = text.strip()
    if len(text) > limit:
        text = text[:limit] + "…"
    return text


def _is_safe_token(value: object) -> bool:
    if not isinstance(value, str) or not value:
        return False
    return not any(ord(c) < 0x20 or ord(c) == 0x7F for c in value)


def exchange_token(auth: Auth, *, timeout: float = 10.0) -> dict[str, Any]:
    url = _exchange_url(auth.host)
    headers = {
        "Authorization": f"token {auth.token}",
        "Accept": "application/json",
        **COPILOT_EDITOR_HEADERS,
    }
    request = urllib.request.Request(url, headers=headers, method="GET")
    context = ssl.create_default_context()

    try:
        with urllib.request.urlopen(request, timeout=timeout, context=context) as response:
            raw = response.read()
    except urllib.error.HTTPError as exc:
        status = exc.code
        if status in (401, 403):
            raise AuthError(
                "GitHub rejected the Copilot token during session-token exchange. "
                "Run `copilot-spend login` to re-authenticate."
            ) from None
        try:
            body = paths.scrub(_body_excerpt(exc.read()), auth.token)
        except Exception:
            body = "<no response body>"
        raise APIError(
            f"Copilot session-token exchange returned {status} at {url}: {body}"
        ) from None
    except (TimeoutError, socket.timeout):
        raise APIError(
            f"Copilot session-token exchange to {auth.host} timed out after {timeout}s."
        ) from None
    except urllib.error.URLError as exc:
        underlying = getattr(exc, "reason", exc)
        raise APIError(
            f"Could not reach {auth.host} for session-token exchange: {underlying}"
        ) from None

    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise APIError(
            f"Copilot session-token exchange at {url} returned non-JSON: {exc}"
        ) from None

    if not isinstance(payload, dict):
        raise APIError(
            f"Copilot session-token exchange at {url} returned non-object response."
        )

    token = payload.get("token")
    if not _is_safe_token(token):
        raise APIError(
            f"Copilot session-token exchange at {url} returned an invalid token field."
        )

    expires_at = payload.get("expires_at")
    if not isinstance(expires_at, (int, float)):
        raise APIError(
            f"Copilot session-token exchange at {url} returned a non-numeric expires_at."
        )

    return {"token": token, "expires_at": int(expires_at)}


def _read_cache(path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    token = data.get("token")
    expires_at = data.get("expires_at")
    if not _is_safe_token(token):
        return None
    if not isinstance(expires_at, (int, float)):
        return None
    return {"token": token, "expires_at": int(expires_at)}


def get_or_refresh(auth: Auth, *, now: float | None = None) -> str:
    moment = time.time() if now is None else now
    cache_path = paths.session_path()
    cached = _read_cache(cache_path)
    if cached and cached["expires_at"] - moment > SESSION_REFRESH_BUFFER_S:
        return cached["token"]

    payload = exchange_token(auth)
    paths.write_secret_file(cache_path, payload)
    return payload["token"]
