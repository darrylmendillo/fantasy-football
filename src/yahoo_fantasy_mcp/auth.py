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


def login(client_id: str, client_secret: str, token_path: str) -> TokenProvider:
    """One-time interactive OAuth consent flow (FR-001).

    Delegates to yahoo_oauth.OAuth2, which opens a browser for consent and
    persists the resulting token to `token_path` (a gitignored local path
    — see config.DEFAULT_TOKEN_PATH). This function is exercised by
    quickstart.md V1, not by the unit suite: it requires a real browser
    and a real Yahoo account, which is exactly why ensure_fresh() and
    classify_auth_failure() above are factored out as pure, independently
    testable logic instead of being buried inside this call.
    """
    from yahoo_oauth import OAuth2  # imported lazily so unit tests never require it

    logger.info("starting Yahoo OAuth consent flow (token_path=%s)", mask_secrets(token_path))
    oauth = OAuth2(client_id, client_secret, from_file=token_path)
    if not oauth.token_is_valid():
        oauth.refresh_access_token()
    return oauth
