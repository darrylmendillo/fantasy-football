"""FastMCP tool definitions for the Yahoo Fantasy MCP server.

Per contracts/mcp-tools.md global rule #1 (FR-011, constitution Principle
IV): every tool description below states only what the wired
implementation actually does. No tool claims analysis, recommendation, or
"AI-powered" behavior — that's Phase 2 (agentic skills), not this server.

Each `tool_*` function is the plain, directly-testable implementation;
the `@mcp.tool()`-decorated wrapper is a thin adapter so
tests/integration/test_tools.py can call the real logic without going
through FastMCP's JSON-RPC framing.
"""

from __future__ import annotations

from fastmcp import FastMCP

from yahoo_fantasy_mcp.client import YahooClient
from yahoo_fantasy_mcp.errors import YahooFantasyError

mcp = FastMCP("yahoo-fantasy-mcp")


def tool_get_league_info(client: YahooClient) -> dict:
    league = client.get_league_info()
    return {
        "league_key": league.league_key,
        "name": league.name,
        "season": league.season,
        "num_teams": league.num_teams,
        "scoring_type": league.scoring_type,
        "draft_status": league.draft_status,
    }


def tool_list_teams(client: YahooClient) -> dict:
    teams = client.get_teams()
    return {
        "teams": [
            {
                "team_key": t.team_key,
                "name": t.name,
                "is_owned_by_user": t.is_owned_by_user,
                "standing": t.standing,
            }
            for t in teams
        ]
    }


def tool_get_roster(client: YahooClient, team_key: str | None) -> dict:
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


def tool_get_standings(client: YahooClient) -> dict:
    standings = client.get_standings()
    return {
        "standings": [
            {"team_key": t.team_key, "name": t.name, "standing": t.standing} for t in standings
        ]
    }


class ServerContext:
    """Holds the process-lifetime client + auth handle the FastMCP tool
    wrappers close over. Constructed once in __main__.py."""

    def __init__(self, client: YahooClient, token_provider) -> None:
        self.client = client
        self.token_provider = token_provider


def register_tools(mcp_server: FastMCP, ctx: ServerContext) -> None:
    """Wire the plain tool_* functions above into FastMCP, translating any
    YahooFantasyError into the {error_code, message} shape from
    contracts/mcp-tools.md rather than letting FastMCP surface a raw
    traceback."""

    def _guarded(fn):
        def wrapper(*args, **kwargs):
            try:
                return fn(*args, **kwargs)
            except YahooFantasyError as exc:
                return exc.to_dict()

        wrapper.__name__ = fn.__name__
        return wrapper

    @mcp_server.tool(
        name="check_auth",
        description=(
            "Report whether this server currently holds a valid Yahoo OAuth "
            "credential and how long it remains valid. Never returns a token "
            "or any credential value — booleans and a duration only."
        ),
    )
    @_guarded
    def check_auth() -> dict:
        from yahoo_fantasy_mcp.auth import build_check_auth_result

        expires_in = getattr(ctx.token_provider, "token_time_remaining", lambda: 0)()
        return build_check_auth_result(ctx.token_provider, expires_in_seconds=int(expires_in))

    @mcp_server.tool(
        name="get_league_info",
        description=(
            "Return identity and current draft status for the single Yahoo "
            "fantasy football league this server is configured for. Read-only."
        ),
    )
    @_guarded
    def get_league_info() -> dict:
        return tool_get_league_info(ctx.client)

    @mcp_server.tool(
        name="list_teams",
        description=(
            "List the teams in the configured league, flagging which one "
            "belongs to the authenticated user. Read-only."
        ),
    )
    @_guarded
    def list_teams() -> dict:
        return tool_list_teams(ctx.client)

    @mcp_server.tool(
        name="get_roster",
        description=(
            "Return a team's current roster. Defaults to the authenticated "
            "user's own team if team_key is omitted. Read-only."
        ),
    )
    @_guarded
    def get_roster(team_key: str | None = None) -> dict:
        return tool_get_roster(ctx.client, team_key)

    @mcp_server.tool(
        name="get_standings",
        description="Return current league standings. Read-only.",
    )
    @_guarded
    def get_standings() -> dict:
        return tool_get_standings(ctx.client)
