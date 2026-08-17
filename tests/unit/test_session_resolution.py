"""Task 3 — the multi-tenancy boundary.

`resolve_league_context` is where a request stops being anonymous and starts
being scoped to one user's one league. Every isolation guarantee in the
product either holds here or does not hold at all.
"""

from __future__ import annotations

import pytest

from yahoo_fantasy_mcp.errors import LeagueNotAccessibleError, SportNotSupportedError
from yahoo_fantasy_mcp.session import (
    LeagueSummary,
    RequestIdentity,
    resolve_league_context,
)


def _leagues() -> list[LeagueSummary]:
    return [
        LeagueSummary("461.l.111", "A League", "nfl", 2026, True, "461.l.111.t.1", "My Team"),
        LeagueSummary("458.l.999", "Hoops", "nba", 2026, False, "458.l.999.t.3", "Hoop Team"),
    ]


class _FakeGameFactory:
    """Stands in for building yahoo_fantasy_api Game/League/Team objects."""

    def __init__(self) -> None:
        self.built_for: list[str] = []

    def build(self, identity: RequestIdentity, league_key: str):
        self.built_for.append(league_key)
        return object()


def test_resolves_context_for_a_league_the_user_belongs_to():
    identity = RequestIdentity(sub="sub-a", access_token="tok")
    ctx = resolve_league_context(_FakeGameFactory(), identity, "461.l.111", _leagues())
    assert ctx.league_key == "461.l.111"
    assert ctx.team_key == "461.l.111.t.1"


def test_league_the_user_does_not_belong_to_is_refused():
    """FR-005 / US2 sc.4 — the core isolation assertion."""
    identity = RequestIdentity(sub="sub-a", access_token="tok")
    with pytest.raises(LeagueNotAccessibleError):
        resolve_league_context(_FakeGameFactory(), identity, "461.l.SOMEONE-ELSE", _leagues())


def test_non_football_league_is_refused_as_unsupported():
    """FR-008 — refused explicitly, not silently mishandled."""
    identity = RequestIdentity(sub="sub-a", access_token="tok")
    with pytest.raises(SportNotSupportedError):
        resolve_league_context(_FakeGameFactory(), identity, "458.l.999", _leagues())


def test_no_yahoo_object_is_built_for_a_refused_league():
    """Refusal must happen before we spend a Yahoo call on it."""
    factory = _FakeGameFactory()
    identity = RequestIdentity(sub="sub-a", access_token="tok")
    with pytest.raises(LeagueNotAccessibleError):
        resolve_league_context(factory, identity, "461.l.NOPE", _leagues())
    assert factory.built_for == []


def test_identity_is_never_taken_from_an_argument():
    """resolve_league_context must not accept a `sub` override parameter."""
    import inspect

    params = set(inspect.signature(resolve_league_context).parameters)
    assert "sub" not in params
    assert "user_id" not in params
