"""Tests for YahooFantasyApiDataSource: player identity caching (research
R4) and rate-limit backoff (research R5). Written before the
implementation exists — must fail first.

Uses a fake `league` object rather than real yahoo_fantasy_api, since
that requires a live authenticated session (see quickstart.md).
"""

from __future__ import annotations

import pytest

from yahoo_fantasy_mcp.errors import RateLimitedError


class _FakeResponse:
    def __init__(self, status_code: int, text: str = "") -> None:
        self.status_code = status_code
        self.text = text


class _FakeHTTPError(Exception):
    def __init__(self, status_code: int) -> None:
        self.response = _FakeResponse(status_code)
        super().__init__(f"HTTP {status_code}")


class _FakeLeague:
    def __init__(self) -> None:
        self.player_details_calls: list[list[int]] = []
        self.percent_owned_calls: list[list[int]] = []
        self.free_agents_calls: list[str] = []
        self._raw_players = {
            9001: {
                "player_id": "9001",
                "name": {"full": "Bijan Robinson"},
                "eligible_positions": [{"position": "RB"}],
                "editorial_team_abbr": "ATL",
            },
            9002: {
                "player_id": "9002",
                "name": {"full": "CeeDee Lamb"},
                "eligible_positions": [{"position": "WR"}],
                "editorial_team_abbr": "DAL",
            },
        }

    def player_details(self, player_ids: list[int]) -> list[dict]:
        self.player_details_calls.append(list(player_ids))
        return [self._raw_players[pid] for pid in player_ids]

    def percent_owned(self, player_ids: list[int]) -> list[dict]:
        self.percent_owned_calls.append(list(player_ids))
        return [{"player_id": pid, "percent_owned": 90} for pid in player_ids]

    def free_agents(self, position: str) -> list[dict]:
        self.free_agents_calls.append(position)
        return [
            {
                "player_id": "40001",
                "name": "Jonathon Brooks",
                "eligible_positions": [{"position": "RB"}],
                "editorial_team_abbr": "CAR",
            }
        ]


class TestPlayerIdentityCache:
    def test_second_call_for_same_ids_does_not_refetch(self):
        """research R4: identity is immutable during a draft, so caching it
        (unlike availability, R3) is correct and saves calls."""
        from yahoo_fantasy_mcp.client import YahooFantasyApiDataSource

        league = _FakeLeague()
        source = YahooFantasyApiDataSource(league, my_team_key="t.1")

        first = source.fetch_player_details_raw([9001, 9002])
        second = source.fetch_player_details_raw([9001, 9002])

        assert first == second
        assert len(league.player_details_calls) == 1, "should not re-fetch cached identities"

    def test_new_ids_trigger_fetch_only_for_the_new_ones(self):
        from yahoo_fantasy_mcp.client import YahooFantasyApiDataSource

        league = _FakeLeague()
        source = YahooFantasyApiDataSource(league, my_team_key="t.1")

        source.fetch_player_details_raw([9001])
        source.fetch_player_details_raw([9001, 9002])

        assert league.player_details_calls == [[9001], [9002]]


class TestBackoff:
    def test_retries_then_succeeds(self, monkeypatch):
        from yahoo_fantasy_mcp.client import YahooFantasyApiDataSource

        monkeypatch.setattr("time.sleep", lambda seconds: None)

        attempts = {"n": 0}

        def flaky_settings():
            attempts["n"] += 1
            if attempts["n"] < 3:
                raise _FakeHTTPError(429)
            return {
                "league_key": "449.l.99001",
                "name": "Sunday Funday",
                "season": 2026,
                "num_teams": 4,
                "scoring_type": "head",
                "draft_status": "predraft",
            }

        league = _FakeLeague()
        league.settings = flaky_settings
        source = YahooFantasyApiDataSource(league, my_team_key="t.1")

        result = source.fetch_league_raw()
        assert result["league_key"] == "449.l.99001"
        assert attempts["n"] == 3

    def test_exhausted_retries_raise_rate_limited(self, monkeypatch):
        from yahoo_fantasy_mcp.client import YahooFantasyApiDataSource

        monkeypatch.setattr("time.sleep", lambda seconds: None)

        def always_429():
            raise _FakeHTTPError(429)

        league = _FakeLeague()
        league.settings = always_429
        source = YahooFantasyApiDataSource(league, my_team_key="t.1")

        with pytest.raises(RateLimitedError):
            source.fetch_league_raw()


class TestPlayerUniverseSeeding:
    """The player universe (candidate pool for get_available_players) is
    seeded via free_agents() exactly ONCE per position, ever — not per poll.
    That's what makes calling free_agents() safe despite research R3: we
    never rely on it staying fresh, we only use its point-in-time snapshot
    once and derive all subsequent availability from fresh draft_results()
    (see draft.derive_available_players)."""

    def test_fetches_once_per_position(self):
        from yahoo_fantasy_mcp.client import YahooFantasyApiDataSource

        league = _FakeLeague()
        source = YahooFantasyApiDataSource(league, my_team_key="t.1")

        source.fetch_player_universe_raw(["RB"])
        source.fetch_player_universe_raw(["RB"])
        source.fetch_player_universe_raw(["RB", "WR"])

        assert league.free_agents_calls.count("RB") == 1, "RB must only be fetched once, ever"

    def test_returns_normalized_shape(self):
        from yahoo_fantasy_mcp.client import YahooFantasyApiDataSource

        league = _FakeLeague()
        source = YahooFantasyApiDataSource(league, my_team_key="t.1")

        universe = source.fetch_player_universe_raw(["RB"])
        assert universe["40001"]["name"] == "Jonathon Brooks"
        assert universe["40001"]["eligible_positions"] == ["RB"]
