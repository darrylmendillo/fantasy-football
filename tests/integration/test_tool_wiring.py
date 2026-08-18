"""Task 9b — the resolution glue itself: identity -> leagues -> a scoped
client, wired without going through a live FastMCP request. Exercises the
same functions the registered tools call, directly.
"""

from __future__ import annotations

import pytest

from yahoo_fantasy_mcp.errors import LeagueNotAccessibleError
from yahoo_fantasy_mcp.server import resolve_request_league_context
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
