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
    def fetch_teams_raw(self) -> list[dict[str, Any]]: ...
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
        # is_owned_by_current_login comes straight from yahoo_fantasy_api's
        # League.teams() — verified against upstream source, not guessed.
        raw = self._source.fetch_teams_raw()
        return [
            Team(
                team_key=t["team_key"],
                name=t["name"],
                is_owned_by_user=bool(t["is_owned_by_current_login"]),
                standing=t.get("rank"),
            )
            for t in raw
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


def _flatten_name(name: Any) -> str:
    """yahoo_fantasy_api's own docstrings disagree with each other on shape:
    Team.roster() shows name as a flat string, but League.player_details()
    shows {'full': ..., 'first': ..., 'last': ...}. Handle both rather than
    assume one — this is exactly the kind of upstream inconsistency this
    module exists to absorb."""
    if isinstance(name, dict):
        return str(name.get("full", ""))
    return str(name)


def _flatten_positions(positions: Any) -> list[str]:
    """Same divergence as _flatten_name: roster() shows ['C','1B'],
    player_details() shows [{'position': 'RW'}]."""
    if not positions:
        return []
    if isinstance(positions[0], dict):
        return [p["position"] for p in positions]
    return list(positions)


class YahooFantasyApiDataSource:
    """Live YahooDataSource backed by yahoo_fantasy_api + an authenticated
    yahoo_oauth session (see auth.login()).

    Known, disclosed limitation (Principle IV — flagged rather than
    silently guessed): yahoo_fantasy_api has no ADP/draft-analysis endpoint
    (verified — its League class exposes draft_results, player_details,
    percent_owned, free_agents, taken_players, standings, teams, settings;
    nothing else touches average draft position). `average_pick` is
    therefore always None from this data source until a supplementary ADP
    source is added — contracts/mcp-tools.md and data-model.md document
    this; it is not a bug, but also not implemented, and no tool
    description may claim otherwise (FR-011).

    Errors: any 401/403 from the underlying `requests` call is classified
    via auth.classify_auth_failure (FR-007). Exact exception plumbing from
    yahoo_fantasy_api/yahoo_oauth for non-auth failures is not fully
    verified against a live account yet — flagged for quickstart V7/V8.
    """

    # Throttle/server-error codes eligible for retry-with-backoff (research
    # R5 — Yahoo publishes no documented limit, so treat these as transient).
    _RETRYABLE_STATUS_CODES = (429, 500, 502, 503, 504)
    _MAX_RETRIES = 3
    _BACKOFF_BASE_SECONDS = 1.0

    def __init__(self, league: Any, my_team_key: str) -> None:
        # `league` is a yahoo_fantasy_api.League already constructed with an
        # authenticated session (see auth.login() + yahoo_fantasy_api.Game).
        self._league = league
        self._my_team_key = my_team_key
        # Player identity is immutable during a draft (research R4) — safe
        # to cache for the process lifetime, unlike availability (R3).
        self._player_identity_cache: dict[int, dict[str, Any]] = {}

    def _call(self, fn, *args, **kwargs):
        import time

        from yahoo_fantasy_mcp.auth import classify_auth_failure
        from yahoo_fantasy_mcp.errors import RateLimitedError

        last_status: int | None = None
        for attempt in range(self._MAX_RETRIES):
            try:
                return fn(*args, **kwargs)
            except Exception as exc:  # noqa: BLE001 - narrowed below
                response = getattr(exc, "response", None)
                status_code = getattr(response, "status_code", None)
                if status_code is None:
                    raise
                if status_code not in self._RETRYABLE_STATUS_CODES:
                    body = getattr(response, "text", "") or ""
                    classify_auth_failure(status_code, body)
                    raise
                last_status = status_code
                if attempt < self._MAX_RETRIES - 1:
                    time.sleep(self._BACKOFF_BASE_SECONDS * (2**attempt))
        raise RateLimitedError(
            f"Yahoo returned HTTP {last_status} after {self._MAX_RETRIES} attempts."
        )

    def fetch_league_raw(self) -> dict[str, Any]:
        settings = self._call(self._league.settings)
        return {
            "league_key": settings["league_key"],
            "name": settings["name"],
            "season": settings["season"],
            "num_teams": settings["num_teams"],
            "scoring_type": settings["scoring_type"],
            # Yahoo's own value is passed through as-is (verified: 'predraft'
            # is a real value per upstream docstring). Anything else is
            # treated as "drafting" unless draft_results() is complete —
            # draft.py's Draft.is_complete is the source of truth for the
            # postdraft boundary, not this string.
            "draft_status": settings.get("draft_status", "predraft"),
        }

    def fetch_teams_raw(self) -> list[dict[str, Any]]:
        teams = self._call(self._league.teams)
        return [
            {
                "team_key": key,
                "name": _flatten_name(t["name"]),
                "is_owned_by_current_login": bool(int(t.get("is_owned_by_current_login", 0))),
            }
            for key, t in teams.items()
        ]

    def fetch_roster_raw(self, team_key: str) -> dict[str, Any]:
        team = self._league.to_team(team_key)
        players = self._call(team.roster)
        return {
            "team_key": team_key,
            "players": [
                {
                    "player_id": int(p["player_id"]),
                    "name": _flatten_name(p["name"]),
                    "eligible_positions": _flatten_positions(p["eligible_positions"]),
                    "editorial_team_abbr": p.get("editorial_team_abbr", ""),
                }
                for p in players
            ],
        }

    def fetch_standings_raw(self) -> list[dict[str, Any]]:
        standings = self._call(self._league.standings)
        return [
            {"team_key": t["team_key"], "name": _flatten_name(t["name"]), "rank": int(t["rank"])}
            for t in standings
        ]

    def fetch_draft_results_raw(self) -> list[dict[str, Any]]:
        # Deliberately NOT normalized further here — draft.py needs the raw
        # 'cost' key (present only for auction picks) intact.
        return self._call(self._league.draft_results)

    def fetch_player_details_raw(self, player_ids: list[int]) -> dict[str, dict[str, Any]]:
        if not player_ids:
            return {}

        # Identity (name/positions/team) is immutable during a draft (R4) —
        # only fetch what isn't already cached. percent_owned is NOT cached
        # here (data-model.md: it's mutable ranking context, refetched fresh
        # every call) — see below.
        missing_ids = [pid for pid in player_ids if pid not in self._player_identity_cache]
        if missing_ids:
            details = self._call(self._league.player_details, missing_ids)
            for p in details:
                pid = int(p["player_id"])
                self._player_identity_cache[pid] = {
                    "player_id": pid,
                    "name": _flatten_name(p["name"]),
                    "eligible_positions": _flatten_positions(p["eligible_positions"]),
                    "editorial_team_abbr": p.get("editorial_team_abbr", ""),
                }

        ownership = {
            p["player_id"]: p["percent_owned"]
            for p in self._call(self._league.percent_owned, player_ids)
        }

        result: dict[str, dict[str, Any]] = {}
        for pid in player_ids:
            identity = self._player_identity_cache.get(pid)
            if identity is None:
                continue
            result[str(pid)] = {
                **identity,
                "percent_owned": ownership.get(pid),
                # See class docstring: not available from this library.
                "average_pick": None,
            }
        return result
