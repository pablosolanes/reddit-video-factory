from __future__ import annotations

import os
import secrets
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer

import requests


TIKTOK_AUTH_URL = "https://www.tiktok.com/v2/auth/authorize/"
TIKTOK_TOKEN_URL = "https://open.tiktokapis.com/v2/oauth/token/"


class TikTokOAuthError(RuntimeError):
    """Raised when TikTok OAuth cannot complete."""


def run_tiktok_login(redirect_uri: str, scopes: list[str]) -> dict:
    client_key = os.getenv("TIKTOK_CLIENT_KEY")
    client_secret = os.getenv("TIKTOK_CLIENT_SECRET")
    if not client_key or not client_secret:
        raise TikTokOAuthError("Missing TIKTOK_CLIENT_KEY or TIKTOK_CLIENT_SECRET in .env")

    state = secrets.token_urlsafe(24)
    server = _OAuthCallbackServer(redirect_uri, state)
    auth_url = _authorization_url(client_key, redirect_uri, scopes, state)

    print(f"[TIKTOK-OAUTH] Opening browser: {auth_url}")
    webbrowser.open(auth_url)
    print(f"[TIKTOK-OAUTH] Waiting for callback on {redirect_uri}")
    server.handle_request()

    if server.error:
        raise TikTokOAuthError(server.error)
    if not server.code:
        raise TikTokOAuthError("TikTok did not return an authorization code")

    token_payload = _exchange_code(
        client_key=client_key,
        client_secret=client_secret,
        code=server.code,
        redirect_uri=redirect_uri,
    )
    print("[TIKTOK-OAUTH] OK. Add these values to .env:")
    print(f"TIKTOK_ACCESS_TOKEN={token_payload.get('access_token', '')}")
    print(f"TIKTOK_REFRESH_TOKEN={token_payload.get('refresh_token', '')}")
    print(f"TIKTOK_ACCESS_TOKEN_EXPIRES_IN={token_payload.get('expires_in', '')}")
    print(f"TIKTOK_REFRESH_TOKEN_EXPIRES_IN={token_payload.get('refresh_expires_in', '')}")
    print(f"TIKTOK_SCOPE={token_payload.get('scope', '')}")
    return token_payload


def _authorization_url(client_key: str, redirect_uri: str, scopes: list[str], state: str) -> str:
    params = {
        "client_key": client_key,
        "response_type": "code",
        "scope": ",".join(scopes),
        "redirect_uri": redirect_uri,
        "state": state,
    }
    return TIKTOK_AUTH_URL + "?" + urllib.parse.urlencode(params)


def _exchange_code(client_key: str, client_secret: str, code: str, redirect_uri: str) -> dict:
    response = requests.post(
        TIKTOK_TOKEN_URL,
        data={
            "client_key": client_key,
            "client_secret": client_secret,
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": redirect_uri,
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=120,
    )
    if response.status_code >= 400:
        raise TikTokOAuthError(f"Token exchange failed: {response.status_code} {response.text[:1000]}")
    data = response.json()
    if "access_token" not in data:
        raise TikTokOAuthError(f"Token response did not include access_token: {data}")
    return data


class _OAuthCallbackServer:
    def __init__(self, redirect_uri: str, expected_state: str) -> None:
        parsed = urllib.parse.urlparse(redirect_uri)
        port = parsed.port
        if parsed.hostname not in {"127.0.0.1", "localhost"} or not port:
            raise TikTokOAuthError("Redirect URI must look like http://127.0.0.1:8765/callback/")
        self.code: str | None = None
        self.error: str | None = None
        self.expected_state = expected_state
        self.httpd = HTTPServer((parsed.hostname, port), self._handler_class(parsed.path or "/callback/"))

    def handle_request(self) -> None:
        self.httpd.handle_request()

    def _handler_class(self, expected_path: str):
        parent = self

        class CallbackHandler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                parsed = urllib.parse.urlparse(self.path)
                params = urllib.parse.parse_qs(parsed.query)
                if parsed.path != expected_path.rstrip("/") and parsed.path != expected_path:
                    parent.error = f"Unexpected callback path: {parsed.path}"
                    self._write_response(404, "Unexpected callback path.")
                    return
                if params.get("state", [""])[0] != parent.expected_state:
                    parent.error = "Invalid OAuth state"
                    self._write_response(400, "Invalid OAuth state.")
                    return
                if "error" in params:
                    parent.error = params.get("error_description", params["error"])[0]
                    self._write_response(400, "TikTok authorization failed.")
                    return
                parent.code = params.get("code", [""])[0]
                self._write_response(200, "TikTok authorization completed. You can close this tab.")

            def log_message(self, format: str, *args) -> None:
                return

            def _write_response(self, status: int, message: str) -> None:
                body = message.encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        return CallbackHandler

