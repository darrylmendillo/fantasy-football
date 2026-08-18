"""Task 9b — the resolution glue itself: identity -> leagues -> a scoped
client, wired without going through a live FastMCP request. Exercises the
same functions the registered tools call, directly.

The second half of this file (added on review) goes one layer further:
it invokes the REAL `@mcp_server.tool` closures built by `build_server`
(via each `FunctionTool.fn`), not just the extracted helper above, so the
identity -> discover -> resolve -> call -> record wiring inside each
closure body has at least representative coverage rather than none.
"""

from __future__ import annotations

import time
from unittest.mock import patch

import anyio
import pytest
from fastmcp.server.auth.auth import AccessToken

from yahoo_fantasy_mcp.config import ServerConfig
from yahoo_fantasy_mcp.errors import LeagueNotAccessibleError
from yahoo_fantasy_mcp.server import build_server, resolve_request_league_context
from yahoo_fantasy_mcp.session import LeagueSummary, RequestIdentity


class _FakeGameFactory:
    def __init__(self, leagues: list[LeagueSummary]):
        self._leagues = leagues

    def build(self, identity, league_key):
        return object()


def _leagues():
    return [
        LeagueSummary("461.l.111", "A League", "nfl", 2026, True, "461.l.111.t.1", None),
    ]


def test_resolve_request_league_context_scopes_to_the_right_league():
    identity = RequestIdentity(sub="sub-a", access_token="tok")
    ctx = resolve_request_league_context(
        _FakeGameFactory(_leagues()), identity, "461.l.111", _leagues()
    )
    assert ctx.league_key == "461.l.111"


def test_resolve_request_league_context_refuses_a_foreign_league():
    identity = RequestIdentity(sub="sub-a", access_token="tok")
    with pytest.raises(LeagueNotAccessibleError):
        resolve_request_league_context(
            _FakeGameFactory(_leagues()), identity, "999.l.999", _leagues()
        )


# ---------------------------------------------------------------------------
# Closure-invocation coverage: calls the real registered tool bodies.
# ---------------------------------------------------------------------------


def _config() -> ServerConfig:
    return ServerConfig(
        client_id="cid", client_secret="cs", public_base_url="https://example.test",
        port=8000, db_path=":memory:", proposal_ttl_seconds=300,
        yahoo_scope="fspt-w", poll_interval_seconds=5,
    )


def _access_token(sub: str, expires_at: int | None = None) -> AccessToken:
    return AccessToken(
        token=f"tok-{sub}", client_id=sub, scopes=[], expires_at=expires_at, claims={"sub": sub}
    )


class _FakeTeam:
    """Stands in for a yahoo_fantasy_api Team: `.roster()` returns raw
    (unparsed) player dicts, matching what YahooFantasyApiDataSource
    expects from `team.roster`."""

    def __init__(self, team_key: str) -> None:
        self._team_key = team_key

    def roster(self) -> list[dict]:
        return [
            {
                "player_id": "1",
                "name": "Bijan Robinson",
                "eligible_positions": ["RB"],
                "editorial_team_abbr": "ATL",
            }
        ]


class _FakeLeague:
    """Stands in for a yahoo_fantasy_api League: enough surface for both
    discover_leagues (`.settings()`, `.team_key()`) and a roster fetch
    through YahooFantasyApiDataSource (`.to_team()`)."""

    def __init__(self, league_key: str, team_key: str) -> None:
        self._league_key = league_key
        self._team_key = team_key

    def settings(self) -> dict:
        return {
            "league_key": self._league_key,
            "name": "A League",
            "game_code": "nfl",
            "season": "2026",
        }

    def team_key(self) -> str:
        return self._team_key

    def to_team(self, team_key: str) -> _FakeTeam:
        return _FakeTeam(team_key)


class _SingleLeagueGameFactory:
    """Every identity belongs to exactly one, same league. Good enough for
    wiring tests that only need *a* real league to flow through, not
    tenant-isolation itself (that's the adversarial test below)."""

    def __init__(self, league_key: str = "461.l.111", team_key: str = "461.l.111.t.1") -> None:
        self._league_key = league_key
        self._team_key = team_key

    def discover_league_ids(self, identity) -> list[str]:
        return [self._league_key]

    def build(self, identity, league_key: str) -> _FakeLeague:
        return _FakeLeague(league_key, self._team_key)


class _PerIdentityGameFactory:
    """Maps each identity.sub to its OWN, DIFFERENT accessible league.

    Needed specifically for the adversarial confirm_action test: it lets
    that test tell apart "the sub-ownership pre-check rejected this"
    (InvalidConfirmationError, the correct behavior per Finding 1's fix)
    from "it fell through to unrelated league-membership enforcement and
    got refused for a different, more informative reason"
    (LeagueNotAccessibleError, the leak Finding 1 was about) — a fake that
    gave every identity access to the same league could not distinguish
    those two cases, because verify_and_consume's own sub check would mask
    the bug being guarded against.
    """

    def __init__(self, league_by_sub: dict[str, str]) -> None:
        self._league_by_sub = league_by_sub

    def discover_league_ids(self, identity) -> list[str]:
        return [self._league_by_sub[identity.sub]]

    def build(self, identity, league_key: str) -> _FakeLeague:
        return _FakeLeague(league_key, f"{league_key}.t.1")


def test_check_auth_closure_resolves_identity_end_to_end(store, sub_a):
    """Unscoped read: proves the basic identity-resolution wiring inside a
    real registered closure (not just the extracted helper) works, and that
    a successful call is recorded under the resolved sub.

    expires_at=None on the fake token (matching what YahooTokenVerifier.
    verify_token actually sets today) must surface as an honest
    expires_in_seconds=None — NOT a fabricated number (final-review
    Finding 4). See test_check_auth_reports_a_real_expiry_when_available
    below for the case where the token DOES carry a real expiry."""
    server = build_server(store, _config())
    tools = {t.name: t for t in anyio.run(server.list_tools)}

    with patch("yahoo_fantasy_mcp.server.get_access_token", return_value=_access_token(sub_a)):
        result = tools["check_auth"].fn()

    assert result == {"authenticated": True, "expires_in_seconds": None, "needs_reauth": False}
    assert store.usage_count(sub_a) == 1


def test_check_auth_reports_a_real_expiry_when_available(store, sub_a):
    """When the access token DOES carry a real expires_at, check_auth must
    derive expires_in_seconds from it (expires_at - now) rather than any
    hardcoded literal. Regression guard for final-review Finding 4: the
    previous implementation always returned a hardcoded 3600 no matter what
    the real token said."""
    server = build_server(store, _config())
    tools = {t.name: t for t in anyio.run(server.list_tools)}
    expires_at = int(time.time()) + 120

    with patch(
        "yahoo_fantasy_mcp.server.get_access_token",
        return_value=_access_token(sub_a, expires_at=expires_at),
    ):
        result = tools["check_auth"].fn()

    assert result["authenticated"] is True
    # Allow a small tolerance for wall-clock time elapsed during the call.
    assert 100 <= result["expires_in_seconds"] <= 120


def test_get_roster_closure_threads_league_scoping_and_calls_through(store, sub_a):
    """League-scoped read: proves discover_leagues -> resolve_request_league_
    context -> the real tool_get_roster call all thread correctly inside the
    actual registered closure."""
    with patch("yahoo_fantasy_mcp.server.YahooGameFactory", _SingleLeagueGameFactory):
        server = build_server(store, _config())
        tools = {t.name: t for t in anyio.run(server.list_tools)}

        with patch(
            "yahoo_fantasy_mcp.server.get_access_token", return_value=_access_token(sub_a)
        ):
            result = tools["get_roster"].fn(league_key="461.l.111")

    assert result["team_key"] == "461.l.111.t.1"
    assert any(p["name"] == "Bijan Robinson" for p in result["players"])
    assert store.usage_count(sub_a) == 1


def test_confirm_action_rejects_a_different_users_token(store, sub_a, sub_b):
    """Regression guard for Finding 1: presenting sub_b's identity against a
    confirmation token that belongs to sub_a's proposal must be refused as
    INVALID_CONFIRMATION -- specifically NOT surfaced as
    LeagueNotAccessibleError (or anything else), which is exactly the
    distinguishable-error leak Finding 1 identified in the pre-check that
    runs before verify_and_consume is ever reached."""
    game_factory = _PerIdentityGameFactory({sub_a: "461.l.111", sub_b: "999.l.999"})
    with patch("yahoo_fantasy_mcp.server.YahooGameFactory", lambda: game_factory):
        server = build_server(store, _config())
        tools = {t.name: t for t in anyio.run(server.list_tools)}

        with patch(
            "yahoo_fantasy_mcp.server.get_access_token", return_value=_access_token(sub_a)
        ):
            proposal = tools["propose_set_lineup"].fn(
                league_key="461.l.111", week=3, changes=[{"player_id": 1, "position": "WR"}]
            )
        confirmation_token = proposal["confirmation_token"]

        with patch(
            "yahoo_fantasy_mcp.server.get_access_token", return_value=_access_token(sub_b)
        ):
            result = tools["confirm_action"].fn(confirmation_token=confirmation_token)

    assert result["error_code"] == "INVALID_CONFIRMATION"
