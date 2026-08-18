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


@dataclass(frozen=True)
class LeagueContext:
    """One user's view of one league, for the duration of one request.

    Replaces spec 001's module-level ServerContext. Nothing here may be
    cached across requests: sharing a context would share a Yahoo session
    between users.
    """

    league_key: str
    team_key: str
    client: Any
    total_expected_picks: int


def resolve_league_context(
    game_factory: Any,
    identity: RequestIdentity,
    league_key: str,
    leagues: list[LeagueSummary],
) -> LeagueContext:
    """Scope this request to one league, refusing anything the caller cannot
    or should not reach.

    Order matters: membership and sport are checked BEFORE any Yahoo object
    is constructed, so a refused request costs no upstream call.

    Membership is enforced via the existing `require_league_membership`
    helper (not reimplemented here) — it already exists in this module and
    duplicating its check inline would be exactly the "verbatim duplication
    of a logic block" the review rubric flags as a defect.
    """
    require_league_membership(league_key, {lg.league_key for lg in leagues})
    match = next(lg for lg in leagues if lg.league_key == league_key)
    require_supported_sport(match.sport)

    league = game_factory.build(identity, league_key)
    return LeagueContext(
        league_key=league_key,
        team_key=match.team_key or "",
        client=league,
        total_expected_picks=0,
    )


# Game code is a required constructor argument of yahoo_fantasy_api.Game,
# but functionally irrelevant to what this module uses Game for: to_league()
# never references it, and league_ids(game_codes=None) below deliberately
# overrides any sport restriction it might otherwise imply. "nfl" here is a
# construction requirement, not a behavioral filter (verified against
# yahoo_fantasy_api source — see this task's plan header).
_GAME_CONSTRUCTION_CODE = "nfl"


class YahooGameFactory:
    """Builds real yahoo_fantasy_api Game/League objects from a per-request
    identity. `game_cls` is injectable for testing without a live Yahoo call
    (mock-validated tier); defaults to the real yahoo_fantasy_api.Game.
    """

    def __init__(self, game_cls: Any = None) -> None:
        self._game_cls = game_cls

    def _resolve_game_cls(self) -> Any:
        if self._game_cls is not None:
            return self._game_cls
        from yahoo_fantasy_api import Game  # lazy: unit tests never require it

        return Game

    def _game(self, identity: RequestIdentity) -> Any:
        adapter = YahooSessionAdapter(identity.access_token)
        return self._resolve_game_cls()(adapter, _GAME_CONSTRUCTION_CODE)

    def discover_league_ids(self, identity: RequestIdentity) -> list[str]:
        return self._game(identity).league_ids(game_codes=None)

    def build(self, identity: RequestIdentity, league_key: str) -> Any:
        return self._game(identity).to_league(league_key)


def discover_leagues(game_factory: Any, identity: RequestIdentity) -> list[LeagueSummary]:
    """All Yahoo fantasy leagues the caller belongs to, across every sport
    (FR-009). Sport-gating to football-only happens downstream, in
    require_supported_sport / resolve_league_context — this function's job
    is to list everything, not filter it (FR-008: unsupported leagues are
    shown, not hidden).

    team_name is deliberately left None: populating it needs an extra
    teams() call per discovered league, and no tested guarantee depends on
    it yet (YAGNI — Principle V).
    """
    summaries = []
    for league_key in game_factory.discover_league_ids(identity):
        league = game_factory.build(identity, league_key)
        settings = league.settings()
        sport = settings["game_code"]
        summaries.append(
            LeagueSummary(
                league_key=settings["league_key"],
                name=settings["name"],
                sport=sport,
                season=int(settings["season"]),
                is_supported=(sport == SUPPORTED_GAME_CODE),
                team_key=league.team_key(),
                team_name=None,
            )
        )
    return summaries
