"""Task 5 — US1: a connected user can see who they are and what leagues
they have. Covers T021 (check_auth) and T025 (list_leagues)."""

from __future__ import annotations

from yahoo_fantasy_mcp.session import LeagueSummary, RequestIdentity
from yahoo_fantasy_mcp.tools_read import tool_check_auth, tool_list_leagues

SECRET = "ya29.super-secret-access-token-value-abcdefghijklmnop"


def test_check_auth_reports_authenticated():
    identity = RequestIdentity(sub="sub-a", access_token=SECRET)
    result = tool_check_auth(identity, expires_in_seconds=3600)
    assert result["authenticated"] is True
    assert result["expires_in_seconds"] == 3600
    assert result["needs_reauth"] is False


def test_check_auth_never_returns_a_token(*_):
    """FR-026 — the single most important assertion about this tool."""
    identity = RequestIdentity(sub="sub-a", access_token=SECRET)
    assert SECRET not in repr(tool_check_auth(identity, expires_in_seconds=3600))


def test_list_leagues_returns_all_leagues_with_support_flag():
    leagues = [
        LeagueSummary("461.l.111", "A League", "nfl", 2026, True, "461.l.111.t.1", "My Team"),
        LeagueSummary("458.l.999", "Hoops", "nba", 2026, False, "458.l.999.t.3", "Hoop Team"),
    ]
    result = tool_list_leagues(leagues)
    rows = result["leagues"]
    assert len(rows) == 2
    by_key = {r["league_key"]: r for r in rows}
    assert by_key["461.l.111"]["is_supported"] is True
    # FR-008: unsupported leagues are still LISTED, so users are not confused
    # by an apparently missing league — they are refused on use, not hidden.
    assert by_key["458.l.999"]["is_supported"] is False


def test_list_leagues_returns_a_dict_not_a_bare_list():
    """A bare list as the top-level return breaks FastMCP's structured
    output validation (real client failure: 'Invalid structured content
    returned by tool list_leagues'). The wrapping dict is the fix."""
    assert isinstance(tool_list_leagues([]), dict)
    assert tool_list_leagues([])["leagues"] == []


def test_list_leagues_distinguishes_leagues_enough_to_choose():
    """US2 sc.1 — name, sport, and season must all be present."""
    leagues = [
        LeagueSummary("461.l.111", "A League", "nfl", 2026, True, "461.l.111.t.1", "My Team"),
    ]
    row = tool_list_leagues(leagues)["leagues"][0]
    assert row["name"] == "A League"
    assert row["sport"] == "nfl"
    assert row["season"] == 2026
