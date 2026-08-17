"""Read tools for the hosted server (spec 002).

Every function here is a plain, directly-testable function taking an explicit
context — the FastMCP decoration happens in server.py. That split is what
lets these be tested without JSON-RPC framing, and it is the pattern spec 001
already established.
"""

from __future__ import annotations

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
