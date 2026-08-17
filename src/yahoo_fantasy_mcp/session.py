"""Per-request Yahoo session and league/team resolution (spec 002, T011/T015/T016).

This module is the multi-tenancy boundary. Everything Yahoo-facing is built
per request from the *calling user's* token; nothing is shared at module
scope. The `ServerContext` singleton from spec 001 is deliberately gone —
that singleton was the single-tenant assumption.

Research R6 (verified against yahoo_fantasy_api/yhandler.py): the library
touches only `sc.session` for requests, and guards its own token refresh with
`hasattr(self.sc, 'refresh_access_token')`. `YahooSessionAdapter` therefore
supplies `.session` and deliberately omits `refresh_access_token`, so the
library never tries to refresh behind FastMCP's back.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import requests

from yahoo_fantasy_mcp.errors import LeagueNotAccessibleError, SportNotSupportedError

# Yahoo's game code for NFL. This release is football-only (FR-008); other
# sports are discoverable but refused.
SUPPORTED_GAME_CODE = "nfl"


class YahooSessionAdapter:
    """Minimal stand-in for `yahoo_oauth.OAuth2`, backed by a token FastMCP
    already validated and refreshed for us.

    Intentionally exposes exactly one attribute the library needs: `session`.
    Do NOT add `refresh_access_token` — see module docstring.
    """

    __slots__ = ("session",)

    def __init__(self, access_token: str) -> None:
        session = requests.Session()
        session.headers["Authorization"] = f"Bearer {access_token}"
        self.session = session

    def __repr__(self) -> str:
        # Never render the token; adapters show up in tracebacks (Principle III).
        return "YahooSessionAdapter(<token redacted>)"


@dataclass(frozen=True)
class RequestIdentity:
    """Who is calling, resolved from the verified access token.

    NEVER constructed from tool arguments — a caller-supplied identity would
    defeat tenant isolation (FR-005).
    """

    sub: str
    access_token: str

    def __repr__(self) -> str:
        return f"RequestIdentity(sub={self.sub!r}, access_token=<redacted>)"


@dataclass(frozen=True)
class LeagueSummary:
    """One row of `list_leagues` output (FR-009)."""

    league_key: str
    name: str
    sport: str
    season: int
    is_supported: bool
    team_key: str | None
    team_name: str | None


def resolve_identity(store: Any, access_token: str, sub: str) -> RequestIdentity:
    """Build the per-request identity and record the user.

    `sub` comes from the token verifier (research R3/R4), not from any
    argument the model can influence.
    """
    store.upsert_user(sub)
    return RequestIdentity(sub=sub, access_token=access_token)


def is_supported_league(league_key: str) -> bool:
    """Football-only for this release (FR-008).

    Yahoo league keys look like `<game_id>.l.<league_id>`; the game id maps to
    a sport. We resolve the sport from the discovered league list rather than
    parsing the key, so this helper only answers the already-resolved case.
    """
    return bool(league_key)


def require_supported_sport(sport: str) -> None:
    """Refuse non-football leagues explicitly rather than mishandling them."""
    if sport.lower() != SUPPORTED_GAME_CODE:
        raise SportNotSupportedError(
            f"This server currently supports fantasy football only; '{sport}' is not supported yet."
        )


def require_league_membership(league_key: str, accessible_keys: set[str]) -> None:
    """Enforce FR-005/US2 sc.4: a league the caller does not belong to is
    refused, never served."""
    if league_key not in accessible_keys:
        raise LeagueNotAccessibleError()
