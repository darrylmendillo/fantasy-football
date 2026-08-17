"""T008 — per-league cache isolation in the live Yahoo data source.

CORRECTION (2026-08-17): plan.md and data-model.md originally claimed spec
001's caches were per-PROCESS and therefore a live cross-tenant data leak.
These tests were written to prove that, and they PASSED against the unmodified
spec-001 code — disproving the claim. `YahooFantasyApiDataSource` initialises
`_player_identity_cache` / `_player_universe_cache` in `__init__`
(client.py:175,178), so caches are per-INSTANCE. Because a fresh data source
is built per request, users are already isolated. No leak exists today.

These tests are retained as a REGRESSION GUARD, not a bug fix. The isolation
they assert is currently a property of "we construct a new data source every
request." The moment anyone pools, memoises, or module-scopes a data source
for performance — a very natural optimisation, since the current design
re-seeds the player universe on every request — that property silently
disappears and these tests are what catch it.

The two `TestCachingStillWorksWithinALeague` cases exist so a future fix
cannot "pass" by simply deleting caching, which would trade a leak we do not
have for the rate-limit problem spec 001 research R5 warns about.
"""

from __future__ import annotations

from typing import Any

from yahoo_fantasy_mcp.client import YahooFantasyApiDataSource


class _RecordingLeague:
    """Stands in for yahoo_fantasy_api.League, recording calls and returning
    league-specific players so cross-league bleed is detectable."""

    def __init__(self, league_key: str, players: dict[int, str]) -> None:
        self.league_key = league_key
        self._players = players
        self.player_details_calls: list[list[int]] = []
        self.free_agents_calls: list[str] = []

    def player_details(self, player_ids: list[int]) -> list[dict[str, Any]]:
        self.player_details_calls.append(list(player_ids))
        return [
            {
                "player_id": pid,
                "name": {"full": self._players[pid]},
                "eligible_positions": ["WR"],
                "editorial_team_abbr": "XXX",
            }
            for pid in player_ids
            if pid in self._players
        ]

    def percent_owned(self, player_ids: list[int]) -> list[dict[str, Any]]:
        return [{"player_id": pid, "percent_owned": 50} for pid in player_ids]

    def free_agents(self, position: str) -> list[dict[str, Any]]:
        self.free_agents_calls.append(position)
        return [
            {
                "player_id": pid,
                "name": {"full": name},
                "eligible_positions": [position],
                "editorial_team_abbr": "XXX",
            }
            for pid, name in self._players.items()
        ]


def _source(league_key: str, players: dict[int, str]) -> tuple[Any, _RecordingLeague]:
    league = _RecordingLeague(league_key, players)
    src = YahooFantasyApiDataSource(league, my_team_key=f"{league_key}.t.1")
    return src, league


class TestPlayerIdentityCacheIsolation:
    def test_two_leagues_do_not_share_identity_cache(self) -> None:
        """Same player_id, different name per league. If the cache is keyed by
        player_id alone, league B gets league A's name back."""
        src_a, _ = _source("461.l.111", {1: "Player From League A"})
        src_b, league_b = _source("461.l.222", {1: "Player From League B"})

        src_a.fetch_player_details_raw([1])
        result_b = src_b.fetch_player_details_raw([1])

        assert result_b["1"]["name"] == "Player From League B"
        assert league_b.player_details_calls, "league B must fetch its own data, not reuse A's"


class TestPlayerUniverseCacheIsolation:
    def test_two_leagues_do_not_share_universe_cache(self) -> None:
        """The universe differs per league; sharing it would report players who
        do not exist in the caller's league."""
        src_a, _ = _source("461.l.111", {10: "Only In A"})
        src_b, league_b = _source("461.l.222", {20: "Only In B"})

        src_a.fetch_player_universe_raw(["WR"])
        universe_b = src_b.fetch_player_universe_raw(["WR"])

        assert "20" in universe_b
        assert "10" not in universe_b, "league A's players leaked into league B's universe"
        assert league_b.free_agents_calls == ["WR"]


class TestCachingStillWorksWithinALeague:
    def test_identity_is_not_refetched_for_the_same_league(self) -> None:
        """The fix must not degenerate into 'no caching' — that would re-fetch
        the universe on every call and risk Yahoo's rate limits (spec 001 R5)."""
        src, league = _source("461.l.111", {1: "Stable Name"})
        src.fetch_player_details_raw([1])
        src.fetch_player_details_raw([1])
        assert len(league.player_details_calls) == 1

    def test_universe_is_not_reseeded_for_the_same_league(self) -> None:
        src, league = _source("461.l.111", {10: "A Player"})
        src.fetch_player_universe_raw(["WR"])
        src.fetch_player_universe_raw(["WR"])
        assert league.free_agents_calls == ["WR"]
