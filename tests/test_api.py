from __future__ import annotations

import io
import json
import socket
import urllib.error
from unittest.mock import MagicMock, patch

import pytest

from copilot_spend.api import APIError, fetch_quota
from copilot_spend.auth import Auth
from copilot_spend.quota import NoSubscriptionError


def _make_response(payload: dict, status: int = 200):
    """Create a context manager that mimics urllib's urlopen() response."""
    data = json.dumps(payload).encode("utf-8")
    mock_resp = MagicMock()
    mock_resp.__enter__ = MagicMock(return_value=mock_resp)
    mock_resp.__exit__ = MagicMock(return_value=False)
    mock_resp.read = MagicMock(return_value=data)
    mock_resp.status = status
    return mock_resp


def _http_error(status: int, body: bytes = b"") -> urllib.error.HTTPError:
    return urllib.error.HTTPError(
        url="https://example.test/x",
        code=status,
        msg="error",
        hdrs=None,
        fp=io.BytesIO(body),
    )


def test_ghe_host_targets_api_v3_path():
    auth = Auth(token="t", host="ghe.example.com")

    with patch("copilot_spend.api.urllib.request.urlopen") as urlopen:
        urlopen.return_value = _make_response({"ok": True})
        fetch_quota(auth)

    assert urlopen.call_count == 1
    request_arg = urlopen.call_args.args[0]
    assert request_arg.full_url == "https://ghe.example.com/api/v3/copilot_internal/user"


def test_github_com_host_targets_api_github_com():
    auth = Auth(token="t", host="github.com")

    with patch("copilot_spend.api.urllib.request.urlopen") as urlopen:
        urlopen.return_value = _make_response({"ok": True})
        fetch_quota(auth)

    request_arg = urlopen.call_args.args[0]
    assert request_arg.full_url == "https://api.github.com/copilot_internal/user"


def test_returns_parsed_json_on_200():
    auth = Auth(token="t", host="ghe.example.com")
    payload = {"login": "u", "copilot_plan": "business"}

    with patch("copilot_spend.api.urllib.request.urlopen") as urlopen:
        urlopen.return_value = _make_response(payload)
        result = fetch_quota(auth)

    assert result == payload


def test_request_does_not_send_copilot_integration_id_header():
    auth = Auth(token="t", host="ghe.example.com")

    with patch("copilot_spend.api.urllib.request.urlopen") as urlopen:
        urlopen.return_value = _make_response({"ok": True})
        fetch_quota(auth)

    request_arg = urlopen.call_args.args[0]
    header_keys = {k.lower() for k in request_arg.headers.keys()}
    assert "copilot-integration-id" not in header_keys


def test_request_includes_bearer_authorization():
    auth = Auth(token="secret-tok", host="ghe.example.com")

    with patch("copilot_spend.api.urllib.request.urlopen") as urlopen:
        urlopen.return_value = _make_response({"ok": True})
        fetch_quota(auth)

    request_arg = urlopen.call_args.args[0]
    assert request_arg.headers["Authorization"] == "Bearer secret-tok"


def test_request_includes_user_agent_with_version():
    auth = Auth(token="t", host="ghe.example.com")

    with patch("copilot_spend.api.urllib.request.urlopen") as urlopen:
        urlopen.return_value = _make_response({"ok": True})
        fetch_quota(auth)

    request_arg = urlopen.call_args.args[0]
    ua = request_arg.headers["User-agent"]
    assert ua.startswith("copilot-spend/")


def test_passes_explicit_ssl_context_to_urlopen():
    auth = Auth(token="t", host="ghe.example.com")

    with patch("copilot_spend.api.urllib.request.urlopen") as urlopen:
        urlopen.return_value = _make_response({"ok": True})
        fetch_quota(auth)

    assert "context" in urlopen.call_args.kwargs, (
        "fetch_quota must pass an explicit ssl context to urlopen"
    )
    assert urlopen.call_args.kwargs["context"] is not None


def test_401_raises_apierror_about_reauth():
    auth = Auth(token="t", host="ghe.example.com")

    with patch("copilot_spend.api.urllib.request.urlopen") as urlopen:
        urlopen.side_effect = _http_error(401)
        with pytest.raises(APIError) as exc:
            fetch_quota(auth)

    message = str(exc.value).lower()
    assert "token" in message
    assert "opencode login" in message


def test_403_raises_apierror_about_reauth():
    auth = Auth(token="t", host="ghe.example.com")

    with patch("copilot_spend.api.urllib.request.urlopen") as urlopen:
        urlopen.side_effect = _http_error(403)
        with pytest.raises(APIError) as exc:
            fetch_quota(auth)

    assert "token" in str(exc.value).lower()


def test_404_raises_no_subscription_error():
    auth = Auth(token="t", host="ghe.example.com")

    with patch("copilot_spend.api.urllib.request.urlopen") as urlopen:
        urlopen.side_effect = _http_error(404)
        with pytest.raises(NoSubscriptionError):
            fetch_quota(auth)


def test_500_includes_status_and_url():
    auth = Auth(token="t", host="ghe.example.com")

    with patch("copilot_spend.api.urllib.request.urlopen") as urlopen:
        urlopen.side_effect = _http_error(500)
        with pytest.raises(APIError) as exc:
            fetch_quota(auth)

    message = str(exc.value)
    assert "500" in message
    assert "ghe.example.com" in message


def test_418_includes_status_url_and_body_excerpt():
    auth = Auth(token="t", host="ghe.example.com")

    with patch("copilot_spend.api.urllib.request.urlopen") as urlopen:
        urlopen.side_effect = _http_error(418, b'{"message":"teapot"}')
        with pytest.raises(APIError) as exc:
            fetch_quota(auth)

    message = str(exc.value)
    assert "418" in message
    assert "ghe.example.com" in message
    assert "teapot" in message


def test_urlerror_includes_host():
    auth = Auth(token="t", host="ghe.example.com")

    with patch("copilot_spend.api.urllib.request.urlopen") as urlopen:
        urlopen.side_effect = urllib.error.URLError("DNS lookup failed")
        with pytest.raises(APIError) as exc:
            fetch_quota(auth)

    assert "ghe.example.com" in str(exc.value)


def test_timeout_mentions_duration():
    auth = Auth(token="t", host="ghe.example.com")

    with patch("copilot_spend.api.urllib.request.urlopen") as urlopen:
        urlopen.side_effect = TimeoutError("timed out")
        with pytest.raises(APIError) as exc:
            fetch_quota(auth, timeout=5.0)

    assert "timed out" in str(exc.value).lower() or "5.0" in str(exc.value)


def test_socket_timeout_mentions_duration():
    auth = Auth(token="t", host="ghe.example.com")

    with patch("copilot_spend.api.urllib.request.urlopen") as urlopen:
        urlopen.side_effect = socket.timeout("timed out")
        with pytest.raises(APIError) as exc:
            fetch_quota(auth, timeout=7.5)

    assert "timed out" in str(exc.value).lower() or "7.5" in str(exc.value)


def test_error_messages_do_not_contain_bearer_token():
    auth = Auth(token="hunter2-secret-token", host="ghe.example.com")
    body = b'{"token":"hunter2-secret-token","status":"error"}'

    with patch("copilot_spend.api.urllib.request.urlopen") as urlopen:
        urlopen.side_effect = _http_error(500, body)
        with pytest.raises(APIError) as exc:
            fetch_quota(auth)

    # Even if the body contained the token (5xx path excludes body, but verify it),
    # the message must not include the bearer token.
    assert "hunter2-secret-token" not in str(exc.value)
