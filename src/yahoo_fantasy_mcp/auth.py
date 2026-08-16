"""OAuth login, refresh, and 401/403 disambiguation (FR-001, FR-003, FR-007).

Design note on classify_auth_failure: both "your credentials expired" and
"this league isn't provisioned for the season yet" arrive from Yahoo as a
plain HTTP 401 (research R6) — the *body* is the only signal that tells
them apart. Yahoo's own error payloads reliably mark real token expiry
with 'token_expired' or 'oauth_problem' (verified against
yahoo_fantasy_api's YHandler._is_token_expired_error). There is no
similarly documented signature for the provisioning case, so it is
treated as the fallback: any 401/403 *without* an expiry marker is
classified as LEAGUE_NOT_PROVISIONED. This is a best-effort heuristic
pending real-world verification (quickstart V7) — if Yahoo's provisioning
error turns out to have its own marker, tighten this rather than widen
the token_expired check.
"""

from __future__ import annotations

from typing import Protocol

from yahoo_fantasy_mcp.errors import AuthExpiredError, LeagueNotProvisionedError
from yahoo_fantasy_mcp.logging_utils import get_logger, mask_secrets

logger = get_logger(__name__)

_TOKEN_EXPIRY_MARKERS = ("token_expired", "oauth_problem")


class TokenProvider(Protocol):
    """What auth.py needs from a yahoo_oauth.OAuth2 session."""

    def token_is_valid(self) -> bool: ...
    def refresh_access_token(self) -> None: ...


def ensure_fresh(provider: TokenProvider) -> None:
    """Refresh credentials only if actually expired (FR-003). Never
    refreshes unconditionally — that would waste a call and risk hitting
    Yahoo's undocumented rate limits (research R5) on every tool call."""
    if not provider.token_is_valid():
        logger.info("access token expired, refreshing")
        provider.refresh_access_token()


def classify_auth_failure(status_code: int, body: str) -> None:
    """Raise the correctly-classified exception for a 401/403 response.
    Never raises with the raw body in the message (Principle III) — only a
    fixed, safe description of the condition.
    """
    if status_code not in (401, 403):
        return
    lowered = body.lower()
    if any(marker in lowered for marker in _TOKEN_EXPIRY_MARKERS):
        raise AuthExpiredError()
    raise LeagueNotProvisionedError()


def build_check_auth_result(provider: TokenProvider, expires_in_seconds: int) -> dict:
    """The check_auth tool's payload. MUST NEVER include a token value —
    only booleans and a duration (contracts/mcp-tools.md)."""
    authenticated = provider.token_is_valid()
    return {
        "authenticated": authenticated,
        "expires_in_seconds": expires_in_seconds,
        "needs_reauth": not authenticated,
    }


def ensure_seed_file(token_path: str, client_id: str, client_secret: str) -> None:
    """Pre-seed the token file yahoo_oauth.OAuth2(from_file=...) will load.

    Verified against yahoo_oauth's actual source (not assumed): when
    `from_file` is passed, OAuth2.__init__ calls open(from_file)
    immediately — a missing file raises FileNotFoundError instead of
    starting the consent flow — and any client_id/client_secret passed as
    constructor arguments are silently ignored in that branch; only the
    file's contents are used. So the file must exist first, containing
    exactly the two keys OAuth2 expects (consumer_key/consumer_secret),
    before OAuth2() is ever constructed. If the file already has tokens in
    it (a real login already happened), this is a no-op — never
    overwrite real credentials back to a bare seed.
    """
    import json
    import os

    if os.path.exists(token_path):
        return
    os.makedirs(os.path.dirname(token_path), exist_ok=True)
    with open(token_path, "w") as f:
        json.dump({"consumer_key": client_id, "consumer_secret": client_secret}, f)


def login(client_id: str, client_secret: str, token_path: str) -> TokenProvider:
    """One-time interactive OAuth consent flow (FR-001).

    Delegates to yahoo_oauth.OAuth2. ensure_seed_file() above is what makes
    the *first-ever* call here work rather than crash — see its docstring.

    browser_callback=False is passed deliberately (verified against
    yahoo_oauth's source): with it True (the library default), it calls
    webbrowser.open(authorize_url) and only logs the URL at DEBUG level —
    in a headless environment (a GitHub Codespace terminal, an SSH
    session) webbrowser.open() fails silently and the user is left at a
    bare "Enter verifier:" prompt with no URL ever shown. With it False,
    yahoo_oauth prints the authorize URL as part of the input() prompt
    itself, which works identically whether or not a browser is available
    — strictly more robust, so we always use it, not just for headless
    cases.

    This function itself is exercised by quickstart.md V1, not the unit
    suite: it requires a real browser and a real Yahoo account, which is
    exactly why ensure_fresh(), classify_auth_failure(), and
    ensure_seed_file() are factored out as pure, independently testable
    logic instead of being buried inside this call.
    """
    from yahoo_oauth import OAuth2  # imported lazily so unit tests never require it

    ensure_seed_file(token_path, client_id, client_secret)
    logger.info("starting Yahoo OAuth consent flow (token_path=%s)", mask_secrets(token_path))
    oauth = OAuth2(None, None, from_file=token_path, browser_callback=False)
    if not oauth.token_is_valid():
        oauth.refresh_access_token()
    return oauth
