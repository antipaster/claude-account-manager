from __future__ import annotations

import base64
import hashlib
import json
import secrets
import time
import urllib.error
import urllib.request
from urllib.parse import urlencode

CLIENT_ID = "9d1c250a-e61b-44d9-88ed-5944d1962f5e"  # claude code public oauth client
AUTHORIZE_URL = "https://claude.ai/oauth/authorize"
TOKEN_URL = "https://platform.claude.com/v1/oauth/token"
USAGE_URL = "https://api.anthropic.com/api/oauth/usage"
PROFILE_URL = "https://api.anthropic.com/api/oauth/profile"
REDIRECT_URI = "https://platform.claude.com/oauth/code/callback"
SCOPES = "org:create_api_key user:profile user:inference"

BETA_HEADER = "oauth-2025-04-20"
USER_AGENT = "claude-cli/2.1.128 (external, cli)"


class ApiError(Exception):
    """Network/HTTP failure, carrying the server's message when available."""


def _request(url: str, *, method: str = "GET", token: str | None = None,
             json_body: dict | None = None, form_body: dict | None = None,
             timeout: int = 30) -> dict:
    headers = {"Accept": "application/json", "User-Agent": USER_AGENT}
    data = None
    if token:
        headers["Authorization"] = "Bearer " + token
        headers["anthropic-beta"] = BETA_HEADER
        headers["anthropic-version"] = "2023-06-01"
    if json_body is not None:
        data = json.dumps(json_body).encode()
        headers["Content-Type"] = "application/json"
    elif form_body is not None:
        data = urlencode(form_body).encode()
        headers["Content-Type"] = "application/x-www-form-urlencoded"

    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")
        msg = body
        try:
            parsed = json.loads(body)
            err = parsed.get("error")
            if isinstance(err, dict):
                msg = err.get("message") or err.get("type") or body
            else:
                msg = parsed.get("error_description") or err or body
        except Exception:
            pass
        raise ApiError(f"HTTP {exc.code}: {msg}") from None
    except urllib.error.URLError as exc:
        raise ApiError(f"network error: {exc.reason}") from None


def get_usage(access_token: str) -> dict:
    return _request(USAGE_URL, token=access_token)


def get_profile(access_token: str) -> dict:
    return _request(PROFILE_URL, token=access_token)


def _to_bundle(resp: dict) -> dict:
    """Normalize a token response into our stored claudeAiOauth shape."""
    expires_in = resp.get("expires_in")
    expires_at = int((time.time() + expires_in) * 1000) if expires_in else resp.get("expires_at")
    scope = resp.get("scope")
    return {
        "accessToken": resp["access_token"],
        "refreshToken": resp.get("refresh_token"),
        "expiresAt": expires_at,
        "scopes": scope.split() if isinstance(scope, str) else scope,
    }


def refresh_token(refresh_tok: str) -> dict:
    resp = _request(
        TOKEN_URL,
        method="POST",
        form_body={"grant_type": "refresh_token", "refresh_token": refresh_tok, "client_id": CLIENT_ID},
    )
    return _to_bundle(resp)


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def start_login() -> tuple[str, str, str]:
    """(authorize_url, code_verifier, state) for the manual PKCE login flow."""
    verifier = _b64url(secrets.token_bytes(32))
    challenge = _b64url(hashlib.sha256(verifier.encode()).digest())
    state = _b64url(secrets.token_bytes(32))
    params = {
        "code": "true",
        "response_type": "code",
        "client_id": CLIENT_ID,
        "redirect_uri": REDIRECT_URI,
        "scope": SCOPES,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "state": state,
    }
    return f"{AUTHORIZE_URL}?{urlencode(params)}", verifier, state


def finish_login(pasted: str, verifier: str, state: str) -> dict:
    code = pasted.strip()
    if "#" in code:
        code, _, st = code.partition("#")
        state = st or state
    resp = _request(
        TOKEN_URL,
        method="POST",
        form_body={
            "grant_type": "authorization_code",
            "client_id": CLIENT_ID,
            "code": code.strip(),
            "redirect_uri": REDIRECT_URI,
            "code_verifier": verifier,
            "state": state,
        },
    )
    return _to_bundle(resp)
