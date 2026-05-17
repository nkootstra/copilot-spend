from __future__ import annotations

import ipaddress
import json
import os
import re
import stat
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

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
    source: Literal["native", "opencode"] = "opencode"

    def __repr__(self) -> str:
        return f"Auth(token=<redacted>, host={self.host!r}, source={self.source!r})"


def _is_private_ip_literal(host: str) -> bool:
    try:
        addr = ipaddress.ip_address(host)
    except ValueError:
        return False
    return (
        addr.is_private
        or addr.is_loopback
        or addr.is_link_local
        or addr.is_reserved
        or addr.is_multicast
        or addr.is_unspecified
    )


def is_valid_host(host: str) -> bool:
    if not host or len(host) > 253:
        return False
    if _is_private_ip_literal(host):
        return False
    return bool(_HOSTNAME_RE.match(host))


def normalize_host(raw: str) -> str:
    host = raw.strip()
    for prefix in ("https://", "http://"):
        if host.startswith(prefix):
            host = host[len(prefix) :]
            break
    return host.rstrip("/").strip()


# Backwards-compat aliases retained for module-internal use.
_is_valid_host = is_valid_host
_normalize_host = normalize_host


def _warn_if_permissive(path: Path) -> None:
    if os.name != "posix":
        return
    try:
        mode = path.stat().st_mode
    except OSError:
        return
    permissive_bits = mode & (stat.S_IRWXG | stat.S_IRWXO)
    if permissive_bits:
        owner_octal = stat.S_IMODE(mode)
        print(
            f"warning: {path} permissions are {oct(owner_octal)} — "
            "the file holds a long-lived Copilot token; consider `chmod 600`.",
            file=sys.stderr,
        )


def _read_opencode(path: Path) -> Auth | None:
    if not path.exists():
        return None

    _warn_if_permissive(path)

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise AuthError(f"opencode auth file is malformed JSON at {path}: {exc.msg}") from None

    if not isinstance(data, dict):
        raise AuthError(f"opencode auth file at {path} is not a JSON object.")

    entry = data.get("github-copilot") or {}
    if not isinstance(entry, dict):
        raise AuthError(f"opencode auth file at {path} has a malformed github-copilot entry.")

    token = entry.get("access")
    if not token or not isinstance(token, str):
        raise AuthError(f"No GitHub Copilot token in {path}. Run `opencode login` first.")

    enterprise_raw = entry.get("enterpriseUrl")
    if enterprise_raw is None:
        enterprise_raw = ""
    if not isinstance(enterprise_raw, str):
        raise AuthError(f"opencode auth file at {path} has a non-string enterpriseUrl field.")

    enterprise = normalize_host(enterprise_raw)
    if not enterprise:
        host = "github.com"
    else:
        if not is_valid_host(enterprise):
            raise AuthError(
                f"enterpriseUrl in {path} is not a valid hostname: {enterprise_raw!r}. "
                "Expected a bare hostname like `ghe.example.com`."
            )
        host = enterprise

    return Auth(token=token, host=host, source="opencode")


def _read_native(path: Path) -> Auth | None:
    if not path.exists():
        return None

    _warn_if_permissive(path)

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise AuthError(
            f"copilot-spend auth file is malformed JSON at {path}: {exc.msg}. "
            "Run `copilot-spend login` to recreate it."
        ) from None

    if not isinstance(data, dict):
        raise AuthError(f"copilot-spend auth file at {path} is not a JSON object.")

    entry = data.get("github-copilot") or {}
    if not isinstance(entry, dict):
        raise AuthError(f"copilot-spend auth file at {path} has a malformed github-copilot entry.")

    token = entry.get("token")
    if not token or not isinstance(token, str):
        raise AuthError(f"No GitHub Copilot token in {path}. Run `copilot-spend login`.")

    host_raw = entry.get("host", "")
    if not isinstance(host_raw, str):
        raise AuthError(f"copilot-spend auth file at {path} has a non-string host field.")

    host = normalize_host(host_raw) or "github.com"
    if host != "github.com" and not is_valid_host(host):
        raise AuthError(f"host in {path} is not a valid hostname: {host_raw!r}.")

    return Auth(token=token, host=host, source="native")


def resolve_auth(
    *,
    native_path: Path | None = None,
    opencode_path: Path = AUTH_PATH,
) -> Auth:
    if native_path is None:
        # Defer the import to call time so test monkeypatching of
        # COPILOT_SPEND_CONFIG_DIR is honored.
        from . import paths as _paths

        native_path = _paths.auth_path()

    native = _read_native(native_path)
    if native is not None:
        return native

    opencode = _read_opencode(opencode_path)
    if opencode is not None:
        return opencode

    raise AuthError(
        "No credentials found. Run `copilot-spend login` to authenticate, "
        "or install opencode and run `opencode login`."
    )
