"""Read tools for the hosted server (spec 002).

Every function here is a plain, directly-testable function taking an explicit
context — the FastMCP decoration happens in server.py. That split is what
lets these be tested without JSON-RPC framing, and it is the pattern spec 001
already established.
"""

from __future__ import annotations

from yahoo_fantasy_mcp.client import YahooClient
from yahoo_fantasy_mcp.draft import build_draft_snapshot
from yahoo_fantasy_mcp.session import LeagueSummary, RequestIdentity


def tool_check_auth(identity: RequestIdentity, expires_in_seconds: int) -> dict:
    """Whether the caller's Yahoo authorization is usable.

    Returns booleans and a duration only. The access token is deliberately
    not referenced in the output (FR-026).
    """
    authenticated = bool(identity.access_token)
    return {
        "authenticated": authenticated,
        "expires_in_seconds": expires_in_seconds,
        "needs_reauth": not authenticated,
    }


def tool_list_leagues(leagues: list[LeagueSummary]) -> list[dict]:
    """All leagues the caller belongs to (FR-009).

    Unsupported (non-football) leagues are included with is_supported=False
    rather than filtered out: a user who sees their basketball league listed
    and refused understands the product better than one who thinks it is
    missing (FR-008).
    """
    return [
        {
            "league_key": lg.league_key,
            "name": lg.name,
            "sport": lg.sport,
            "season": lg.season,
            "is_supported": lg.is_supported,
            "team_key": lg.team_key,
            "team_name": lg.team_name,
        }
        for lg in leagues
    ]


def tool_get_league_info(client: YahooClient) -> dict:
    """League identity and current draft status."""
    league = client.get_league_info()
    return {
        "league_key": league.league_key,
        "name": league.name,
        "season": league.season,
        "num_teams": league.num_teams,
        "scoring_type": league.scoring_type,
        "draft_status": league.draft_status,
    }


def tool_list_teams(client: YahooClient) -> list[dict]:
    """Teams in the league, flagging the authenticated user's own team."""
    teams = client.get_teams()
    return [
        {
            "team_key": t.team_key,
            "name": t.name,
            "is_owned_by_user": t.is_owned_by_user,
            "standing": t.standing,
        }
        for t in teams
    ]


def tool_get_roster(client: YahooClient, team_key: str | None) -> dict:
    """A team's current roster, defaulting to the authenticated user's own team."""
    if team_key is None:
        owned = [t for t in client.get_teams() if t.is_owned_by_user]
        team_key = owned[0].team_key if owned else None
        if team_key is None:
            from yahoo_fantasy_mcp.errors import LeagueNotAccessibleError

            raise LeagueNotAccessibleError("Could not determine the user's own team.")
    roster = client.get_roster(team_key)
    return {
        "team_key": roster.team_key,
        "players": [
            {
                "player_id": p.player_id,
                "name": p.name,
                "positions": p.positions,
                "nfl_team": p.nfl_team,
            }
            for p in roster.players
        ],
    }


def tool_get_standings(client: YahooClient) -> list[dict]:
    """Current league standings."""
    standings = client.get_standings()
    return [
        {"team_key": t.team_key, "name": t.name, "standing": t.standing} for t in standings
    ]


def tool_get_draft_results(client: YahooClient, total_expected_picks: int) -> dict:
    """Every draft pick made so far, in order.

    The core live-draft tool (FR-008, FR-009). Exactly one Yahoo call per
    invocation (research R5) — player names come from client.py's identity
    cache, not a second fetch.
    """
    raw_picks = client.fetch_draft_results_raw()
    draft = build_draft_snapshot(raw_picks, total_expected_picks=total_expected_picks)

    player_ids = [p.player_id for p in draft.picks]
    players_by_id = client.get_player_details(player_ids) if player_ids else {}

    return {
        "draft_status": "postdraft"
        if draft.is_complete
        else ("predraft" if not draft.picks else "drafting"),
        "retrieved_at": draft.retrieved_at.isoformat(),
        "is_complete": draft.is_complete,
        "picks": [
            {
                "pick": p.pick,
                "round": p.round,
                "team_key": p.team_key,
                "player_id": p.player_id,
                "player_name": players_by_id[p.player_id].name
                if p.player_id in players_by_id
                else None,
                "positions": players_by_id[p.player_id].positions
                if p.player_id in players_by_id
                else [],
                "nfl_team": players_by_id[p.player_id].nfl_team
                if p.player_id in players_by_id
                else None,
            }
            for p in draft.picks
        ],
    }


# Core Yahoo NFL fantasy positions used to seed the player universe when no
# position filter is given (see client.get_player_universe / research note
# in YahooFantasyApiDataSource.fetch_player_universe_raw — each is fetched
# via free_agents() at most once, ever, not per poll).
CORE_POSITIONS = ["QB", "RB", "WR", "TE", "K", "DEF"]


def tool_get_available_players(
    client: YahooClient, total_expected_picks: int, positions: list[str] | None = None
) -> dict:
    """Currently undrafted players in the league.

    FR-010. Availability is derived from the SAME fresh draft read used by
    get_draft_results — never from a cached free-agent list (research R3,
    draft.derive_available_players). Guaranteed to exclude every player
    already returned by get_draft_results for the same retrieved_at.
    """
    raw_picks = client.fetch_draft_results_raw()
    draft = build_draft_snapshot(raw_picks, total_expected_picks=total_expected_picks)

    seed_positions = positions if positions else CORE_POSITIONS
    universe = client.get_player_universe(seed_positions)

    # Get available players: all in universe minus drafted
    drafted_ids = draft.drafted_player_ids()
    available = [p for p in universe.values() if p.player_id not in drafted_ids]

    # If specific positions requested, filter further
    if positions:
        available = [p for p in available if any(pos in p.positions for pos in positions)]

    # Sort by percent_owned (matching derive_available_players behavior)
    available.sort(key=lambda p: (p.percent_owned is None, -(p.percent_owned or 0)))

    return {
        "retrieved_at": draft.retrieved_at.isoformat(),
        "positions": positions,
        "count": len(available),
        "players": [
            {
                "player_id": p.player_id,
                "name": p.name,
                "positions": p.positions,
                "nfl_team": p.nfl_team,
                "percent_owned": p.percent_owned,
                "average_pick": p.average_pick,
            }
            for p in available
        ],
    }
