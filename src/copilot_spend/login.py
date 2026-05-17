from __future__ import annotations

import json
import socket
import ssl
import sys
import time
import urllib.error
import urllib.request

from . import api, paths
from .auth import Auth, AuthError, is_valid_host, normalize_host
from .quota import NoSubscriptionError

CLIENT_ID = "Iv1.b507a08c87ecfe98"
OAUTH_SCOPE = "read:user"
POLL_MAX_WAIT_S = 900


def _device_url(host: str) -> str:
    if host == "github.com":
        return "https://github.com/login/device/code"
    return f"https://{host}/login/device/code"


def _access_token_url(host: str) -> str:
    if host == "github.com":
        return "https://github.com/login/oauth/access_token"
    return f"https://{host}/login/oauth/access_token"


def _post_json(url: str, body: dict, *, timeout: float = 10.0) -> dict:
    request = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    context = ssl.create_default_context()
    with urllib.request.urlopen(request, timeout=timeout, context=context) as response:
        raw = response.read()
    return json.loads(raw.decode("utf-8"))


def _prompt_host(stdin=None, stderr=None) -> str:
    stdin = stdin or sys.stdin
    stderr = stderr or sys.stderr
    print("Where do you authenticate?", file=stderr)
    print("  1) github.com", file=stderr)
    print("  2) GitHub Enterprise", file=stderr)
    print("Choose 1 or 2 [1]: ", end="", file=stderr, flush=True)
    choice = stdin.readline().strip() or "1"

    if choice == "1":
        return "github.com"
    if choice != "2":
        raise AuthError(f"Unrecognized choice: {choice!r}. Expected 1 or 2.")

    print("GHE host (e.g. ghe.example.com): ", end="", file=stderr, flush=True)
    raw = stdin.readline().strip()
    host = normalize_host(raw)
    if not is_valid_host(host):
        raise AuthError(
            f"Not a valid hostname: {raw!r}. Expected a bare hostname like `ghe.example.com`."
        )
    return host


def _request_device_code(host: str) -> dict:
    url = _device_url(host)
    try:
        payload = _post_json(url, {"client_id": CLIENT_ID, "scope": OAUTH_SCOPE})
    except urllib.error.HTTPError as exc:
        raise AuthError(
            f"GitHub returned {exc.code} from {url}. Check the host and try again."
        ) from None
    except (TimeoutError, socket.timeout):
        raise AuthError(f"Timed out reaching {host} for device-code request.") from None
    except urllib.error.URLError as exc:
        underlying = getattr(exc, "reason", exc)
        raise AuthError(f"Could not reach '{host}': {underlying}.") from None

    if not isinstance(payload, dict):
        raise AuthError(f"Unexpected response from {url}: not a JSON object.")
    error = payload.get("error")
    if error:
        description = payload.get("error_description", error)
        raise AuthError(
            f"GitHub rejected the device-code request ({error}): {description}."
        )

    required = ("device_code", "user_code", "verification_uri", "interval")
    if not all(payload.get(k) for k in required):
        raise AuthError(
            f"Device-code response from {url} is missing required fields."
        )
    return payload


def _poll_for_token(
    host: str,
    device_code: str,
    interval: int,
    *,
    now=time.monotonic,
    sleep=time.sleep,
    max_wait: int = POLL_MAX_WAIT_S,
) -> str:
    url = _access_token_url(host)
    body = {
        "client_id": CLIENT_ID,
        "device_code": device_code,
        "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
    }
    started = now()
    current_interval = max(int(interval), 1)

    while True:
        if now() - started > max_wait:
            raise AuthError("Login timed out. Run `copilot-spend login` again.")

        sleep(current_interval)

        try:
            payload = _post_json(url, body)
        except urllib.error.HTTPError as exc:
            raise AuthError(
                f"GitHub returned {exc.code} during token polling. Run `copilot-spend login` again."
            ) from None
        except (TimeoutError, socket.timeout):
            # Transient — keep polling within the time budget.
            continue
        except urllib.error.URLError as exc:
            underlying = getattr(exc, "reason", exc)
            raise AuthError(f"Could not reach '{host}': {underlying}.") from None

        if not isinstance(payload, dict):
            raise AuthError("Unexpected non-object response from token endpoint.")

        token = payload.get("access_token")
        if token:
            if not isinstance(token, str):
                raise AuthError("GitHub returned a non-string access_token.")
            return token

        err = payload.get("error")
        if err == "authorization_pending":
            continue
        if err == "slow_down":
            current_interval += 5
            continue
        if err == "expired_token":
            raise AuthError("Login timed out. Run `copilot-spend login` again.")
        if err == "access_denied":
            raise AuthError("Authorization denied. Run `copilot-spend login` again to retry.")
        if err == "unauthorized_client":
            raise AuthError(
                "GitHub rejected the OAuth app (unauthorized_client). "
                "The bundled CLIENT_ID may not be allowed on this host. "
                "See README 'Switch to your own GitHub App'."
            )
        if err:
            description = payload.get("error_description", err)
            raise AuthError(f"GitHub returned an error during polling ({err}): {description}.")

        raise AuthError("Token response missing both access_token and error.")


def run_login(
    *,
    stdin=None,
    stdout=None,
    stderr=None,
    sleep=time.sleep,
    now=time.monotonic,
) -> int:
    stdin = stdin or sys.stdin
    stdout = stdout or sys.stdout
    stderr = stderr or sys.stderr
    try:
        host = _prompt_host(stdin=stdin, stderr=stderr)
        device = _request_device_code(host)
    except AuthError as exc:
        print(f"error: {exc}", file=stderr)
        return 2

    print(
        f"Visit {device['verification_uri']} and enter the code: {device['user_code']}",
        file=stdout,
    )
    print("Waiting for authorization...", file=stderr)

    try:
        token = _poll_for_token(
            host,
            device["device_code"],
            int(device.get("interval", 5)),
            now=now,
            sleep=sleep,
        )
    except KeyboardInterrupt:
        print("Login cancelled.", file=stderr)
        return 2
    except AuthError as exc:
        print(f"error: {exc}", file=stderr)
        return 2

    if not token.startswith("ghu_"):
        print(
            "error: GitHub returned a non-GitHub-App token (expected `ghu_…` prefix). "
            "The bundled CLIENT_ID is misconfigured — see README 'Switch to your own GitHub App'.",
            file=stderr,
        )
        return 2

    auth = Auth(token=token, host=host, source="native")

    try:
        api.fetch_quota(auth)
    except NoSubscriptionError:
        print(
            "error: post-login verification failed: this account has no Copilot quota.",
            file=stderr,
        )
        return 2
    except api.APIError as exc:
        scrubbed = paths.scrub(str(exc), token)
        print(f"error: post-login verification failed: {scrubbed}", file=stderr)
        return 2

    target = paths.auth_path()
    if target.exists():
        print(
            "Re-authenticating — previous credentials will be replaced.",
            file=stderr,
        )

    try:
        paths.write_secret_file(
            target,
            {"github-copilot": {"token": token, "host": host}},
        )
    except AuthError as exc:
        print(f"error: could not write credentials: {exc}", file=stderr)
        return 2
    except OSError as exc:
        print(f"error: could not write credentials: {exc}", file=stderr)
        return 2

    # Clean up any stale session.json from versions that cached a session token.
    paths.delete_secret_file(paths.config_dir() / "session.json")

    print(f"Logged in to GitHub Copilot via {host}.", file=stdout)
    return 0


def run_logout(*, stdout=None) -> int:
    stdout = stdout or sys.stdout
    paths.delete_secret_file(paths.auth_path())
    # Legacy cleanup: pre-session-removal versions cached a session token here.
    paths.delete_secret_file(paths.config_dir() / "session.json")
    print("Logged out of copilot-spend.", file=stdout)
    return 0
