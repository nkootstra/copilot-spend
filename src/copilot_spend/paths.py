from __future__ import annotations

import json
import os
import stat
import tempfile
from pathlib import Path
from typing import Any

from .auth import AuthError


def config_dir() -> Path:
    override = os.environ.get("COPILOT_SPEND_CONFIG_DIR")
    if override:
        return Path(override)
    xdg = os.environ.get("XDG_CONFIG_HOME")
    if xdg:
        return Path(xdg) / "copilot-spend"
    return Path.home() / ".config" / "copilot-spend"


def auth_path() -> Path:
    return config_dir() / "auth.json"


def session_path() -> Path:
    return config_dir() / "session.json"


def assert_safe_parent(parent: Path) -> None:
    if os.name != "posix":
        return
    if not parent.exists():
        return
    try:
        info = parent.stat()
    except OSError as exc:
        raise AuthError(f"Cannot stat config directory {parent}: {exc}") from None
    if info.st_uid != os.getuid():
        raise AuthError(
            f"Refusing to use config directory {parent}: owned by uid "
            f"{info.st_uid}, expected {os.getuid()}. "
            "Set COPILOT_SPEND_CONFIG_DIR or XDG_CONFIG_HOME to a directory "
            "you own."
        )
    if info.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
        raise AuthError(
            f"Refusing to use config directory {parent}: mode "
            f"{oct(stat.S_IMODE(info.st_mode))} grants group or world write. "
            f"Run `chmod 700 {parent}`."
        )


def write_secret_file(path: Path, payload: dict[str, Any]) -> None:
    parent = path.parent
    assert_safe_parent(parent)
    parent.mkdir(parents=True, exist_ok=True)
    if os.name == "posix":
        os.chmod(parent, 0o700)

    fd, tmp_str = tempfile.mkstemp(dir=parent, prefix=".tmp-", suffix=".json")
    tmp_path = Path(tmp_str)
    try:
        if os.name == "posix":
            os.chmod(fd, 0o600)
        with os.fdopen(fd, "wb") as handle:
            handle.write(json.dumps(payload, indent=2).encode("utf-8"))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, path)
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise


def delete_secret_file(path: Path) -> None:
    path.unlink(missing_ok=True)


def scrub(text: str, *tokens: str | None) -> str:
    for token in tokens:
        if token and token in text:
            text = text.replace(token, "<redacted-token>")
    return text
