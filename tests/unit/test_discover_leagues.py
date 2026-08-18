"""Task 9a — the real game factory and multi-sport league discovery.

Design verified against installed yahoo_fantasy_api source (see plan Task 9a
header): Game.to_league() never references its own game code, and
Game.league_ids(game_codes=None) spans every sport in one call. So these
tests fake a single Game object returning leagues across two different
sports from one league_ids() call — proving discover_leagues does NOT need
to loop over game codes, and that non-football leagues are surfaced (FR-008:
listed, not hidden) rather than silently dropped.
"""

from __future__ import annotations

from yahoo_fantasy_mcp.session import (
    LeagueSummary,
    RequestIdentity,
    YahooGameFactory,
    discover_leagues,
)


class _FakeLeague:
    def __init__(self, league_key: str, name: str, game_code: str, season: str, team_key: str):
        self._settings = {
            "league_key": league_key,
            "name": name,
            "game_code": game_code,
            "season": season,
        }
        self._team_key = team_key

    def settings(self) -> dict:
        return dict(self._settings)

    def team_key(self) -> str:
        return self._team_key


_LEAGUES_BY_KEY = {
    "461.l.111": _FakeLeague("461.l.111", "A League", "nfl", "2026", "461.l.111.t.1"),
    "398.l.222": _FakeLeague("398.l.222", "B League", "mlb", "2026", "398.l.222.t.4"),
}


class _FakeGame:
    """Stands in for yahoo_fantasy_api.Game. Records how it was called so
    tests can assert discover_league_ids passes game_codes=None."""

    def __init__(self, sc, code):
        self.sc = sc
        self.code = code
        self.league_ids_calls: list[dict] = []

    def league_ids(self, game_codes=None):
        self.league_ids_calls.append({"game_codes": game_codes})
        return list(_LEAGUES_BY_KEY.keys())

    def to_league(self, league_key: str):
        return _LEAGUES_BY_KEY[league_key]


def _identity() -> RequestIdentity:
    return RequestIdentity(sub="sub-a", access_token="tok-a")


def test_discover_league_ids_spans_all_sports_in_one_call():
    """Proves no per-sport looping happens — game_codes=None is what makes
    a single call return every sport."""
    factory = YahooGameFactory(game_cls=_FakeGame)
    ids = factory.discover_league_ids(_identity())
    assert set(ids) == {"461.l.111", "398.l.222"}


def test_build_constructs_the_requested_league():
    factory = YahooGameFactory(game_cls=_FakeGame)
    league = factory.build(_identity(), "398.l.222")
    assert league.settings()["name"] == "B League"


def test_discover_leagues_includes_non_football_with_is_supported_false():
    """FR-008: unsupported leagues are listed, not hidden."""
    factory = YahooGameFactory(game_cls=_FakeGame)
    summaries = discover_leagues(factory, _identity())
    by_key = {s.league_key: s for s in summaries}

    assert by_key["461.l.111"] == LeagueSummary(
        league_key="461.l.111", name="A League", sport="nfl",
        season=2026, is_supported=True, team_key="461.l.111.t.1", team_name=None,
    )
    assert by_key["398.l.222"] == LeagueSummary(
        league_key="398.l.222", name="B League", sport="mlb",
        season=2026, is_supported=False, team_key="398.l.222.t.4", team_name=None,
    )


def test_each_users_token_produces_an_independently_constructed_game():
    """Tenant isolation at the source: two identities must never share a
    Game/session (FR-005)."""
    factory = YahooGameFactory(game_cls=_FakeGame)
    game_a = factory._game(RequestIdentity(sub="a", access_token="tok-a"))
    game_b = factory._game(RequestIdentity(sub="b", access_token="tok-b"))
    assert game_a.sc.session.headers["Authorization"] != game_b.sc.session.headers["Authorization"]
