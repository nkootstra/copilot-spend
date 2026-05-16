from __future__ import annotations

import json
import os
import re
import stat
import sys
from dataclasses import dataclass
from pathlib import Path

AUTH_PATH = Path.home() / ".local/share/opencode/auth.json"

# RFC 1123 hostname: dot-separated labels, each 1-63 chars of [A-Za-z0-9-],
# not starting or ending with a hyphen. Total length ≤ 253.
_HOSTNAME_LABEL = r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
_HOSTNAME_RE = re.compile(rf"^{_HOSTNAME_LABEL}(?:\.{_HOSTNAME_LABEL})*$")


class AuthError(Exception):
    pass


@dataclass(frozen=True)
class Auth:
    token: str
    host: str

    def __repr__(self) -> str:
        return f"Auth(token=<redacted>, host={self.host!r})"


def _is_valid_host(host: str) -> bool:
    return bool(host) and len(host) <= 253 and bool(_HOSTNAME_RE.match(host))


def _normalize_host(raw: str) -> str:
    host = raw.strip()
    for prefix in ("https://", "http://"):
        if host.startswith(prefix):
            host = host[len(prefix):]
            break
    return host.rstrip("/").strip()


def _warn_if_permissive(path: Path) -> None:
    if os.name != "posix":
        return
    try:
        mode = path.stat().st_mode
    except OSError:
        return
    # Anything beyond owner-read/write (group or other bits set) is too permissive
    # for a file holding a long-lived bearer token.
    permissive_bits = mode & (stat.S_IRWXG | stat.S_IRWXO)
    if permissive_bits:
        owner_octal = stat.S_IMODE(mode)
        print(
            f"warning: {path} permissions are {oct(owner_octal)} — "
            "the file holds a long-lived Copilot token; consider `chmod 600`.",
            file=sys.stderr,
        )


def resolve_auth(path: Path = AUTH_PATH) -> Auth:
    if not path.exists():
        raise AuthError(
            f"opencode auth file not found at {path}. "
            "Authenticate with opencode first."
        )

    _warn_if_permissive(path)

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise AuthError(f"opencode auth file is malformed JSON at {path}: {exc.msg}") from None

    if not isinstance(data, dict):
        raise AuthError(f"opencode auth file at {path} is not a JSON object.")

    entry = data.get("github-copilot") or {}
    if not isinstance(entry, dict):
        raise AuthError(
            f"opencode auth file at {path} has a malformed github-copilot entry."
        )

    token = entry.get("access")
    if not token or not isinstance(token, str):
        raise AuthError(
            f"No GitHub Copilot token in {path}. Run `opencode login` first."
        )

    enterprise_raw = entry.get("enterpriseUrl")
    if enterprise_raw is None:
        enterprise_raw = ""
    if not isinstance(enterprise_raw, str):
        raise AuthError(
            f"opencode auth file at {path} has a non-string enterpriseUrl field."
        )

    enterprise = _normalize_host(enterprise_raw)
    if not enterprise:
        host = "github.com"
    else:
        if not _is_valid_host(enterprise):
            raise AuthError(
                f"enterpriseUrl in {path} is not a valid hostname: {enterprise_raw!r}. "
                "Expected a bare hostname like `ghe.example.com`."
            )
        host = enterprise

    return Auth(token=token, host=host)
