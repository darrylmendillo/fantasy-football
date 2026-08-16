"""Yahoo API boundary: converts yahoo_fantasy_api's dict shapes into our
domain models (models.py), keeping upstream JSON quirks out of the tool
layer (server.py) and out of draft.py's derivation logic.

Design note: this module depends on a `YahooDataSource` Protocol rather
than importing `yahoo_fantasy_api`/`yahoo_oauth` directly. That keeps the
parsing/conversion logic here testable against JSON fixtures with no
network access or live credentials (see tests/unit/test_client.py). The
concrete, auth-aware implementation (`YahooFantasyApiDataSource`) is wired
up in auth.py once OAuth is in place (Phase 3 / US1), including the 401
disambiguation from research R6.

Draft data is deliberately returned RAW (undecoded dicts) from
`fetch_draft_results_raw`, not as parsed DraftPick objects — draft.py needs
to inspect the raw 'cost' field to detect an auction league (FR-013)
*before* any DraftPick is constructed, so pre-parsing here would hide the
one signal that guard depends on.
"""

from __future__ import annotations

from typing import Any, Protocol

from yahoo_fantasy_mcp.models import League, Player, Roster, Team


class YahooDataSource(Protocol):
    """Everything client.py needs from an authenticated Yahoo session.

    Implementations translate Yahoo/yahoo_fantasy_api failures into the
    typed errors in errors.py (AuthExpiredError, LeagueNotProvisionedError,
    etc.) — client.py itself does not know how to tell those apart; that's
    the auth-layer's job (FR-007, research R6).
    """

    def fetch_league_raw(self) -> dict[str, Any]: ...
    def fetch_teams_raw(self) -> dict[str, Any]: ...
    def fetch_roster_raw(self, team_key: str) -> dict[str, Any]: ...
    def fetch_standings_raw(self) -> list[dict[str, Any]]: ...
    def fetch_draft_results_raw(self) -> list[dict[str, Any]]: ...
    def fetch_player_details_raw(self, player_ids: list[int]) -> dict[str, dict[str, Any]]: ...


def _player_from_raw(raw: dict[str, Any]) -> Player:
    return Player(
        player_id=raw["player_id"],
        name=raw["name"],
        positions=list(raw["eligible_positions"]),
        nfl_team=raw["editorial_team_abbr"],
        percent_owned=raw.get("percent_owned"),
        average_pick=raw.get("average_pick"),
    )


class YahooClient:
    """Domain-model view over a YahooDataSource."""

    def __init__(self, source: YahooDataSource) -> None:
        self._source = source

    def get_league_info(self) -> League:
        raw = self._source.fetch_league_raw()
        return League(
            league_key=raw["league_key"],
            name=raw["name"],
            season=int(raw["season"]),
            num_teams=int(raw["num_teams"]),
            scoring_type=raw["scoring_type"],
            draft_status=raw["draft_status"],
        )

    def get_teams(self) -> list[Team]:
        raw = self._source.fetch_teams_raw()
        my_team_key = raw["my_team_key"]
        return [
            Team(
                team_key=t["team_key"],
                name=t["name"],
                is_owned_by_user=(t["team_key"] == my_team_key),
                standing=t.get("rank"),
            )
            for t in raw["teams"]
        ]

    def get_roster(self, team_key: str) -> Roster:
        raw = self._source.fetch_roster_raw(team_key)
        return Roster(
            team_key=raw["team_key"],
            players=[_player_from_raw(p) for p in raw["players"]],
        )

    def get_standings(self) -> list[Team]:
        raw = self._source.fetch_standings_raw()
        return [
            Team(team_key=t["team_key"], name=t["name"], is_owned_by_user=False, standing=t["rank"])
            for t in raw
        ]

    def fetch_draft_results_raw(self) -> list[dict[str, Any]]:
        """Passthrough for draft.py — see module docstring for why this is
        not pre-parsed into DraftPick here."""
        return self._source.fetch_draft_results_raw()

    def get_player_details(self, player_ids: list[int]) -> dict[int, Player]:
        raw = self._source.fetch_player_details_raw(player_ids)
        return {pid: _player_from_raw(p) for pid, p in ((int(k), v) for k, v in raw.items())}
