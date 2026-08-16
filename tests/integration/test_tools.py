"""Contract tests for MCP tools against contracts/mcp-tools.md.

Tests call the tools' underlying implementation functions directly (not
through the FastMCP protocol layer) — that's the boundary worth testing
here; FastMCP's own JSON-RPC framing is the library's concern, not ours.
"""

from __future__ import annotations

from yahoo_fantasy_mcp.client import YahooClient
from yahoo_fantasy_mcp.server import (
    tool_get_league_info,
    tool_get_roster,
    tool_get_standings,
    tool_list_teams,
)


class TestGetLeagueInfo:
    def test_shape(self, fixture_source):
        client = YahooClient(fixture_source)
        result = tool_get_league_info(client)
        assert result == {
            "league_key": "449.l.99001",
            "name": "Sunday Funday",
            "season": 2026,
            "num_teams": 4,
            "scoring_type": "head",
            "draft_status": "drafting",
        }


class TestListTeams:
    def test_exactly_one_team_owned_by_user(self, fixture_source):
        client = YahooClient(fixture_source)
        result = tool_list_teams(client)
        owned = [t for t in result["teams"] if t["is_owned_by_user"]]
        assert len(owned) == 1
        assert owned[0]["team_key"] == "449.l.99001.t.1"

    def test_all_teams_present(self, fixture_source):
        client = YahooClient(fixture_source)
        result = tool_list_teams(client)
        assert len(result["teams"]) == 4


class TestGetRoster:
    def test_defaults_to_users_own_team(self, fixture_source):
        client = YahooClient(fixture_source)
        result = tool_get_roster(client, team_key=None)
        assert result["team_key"] == "449.l.99001.t.1"
        assert any(p["name"] == "Bijan Robinson" for p in result["players"])

    def test_explicit_team_key(self, fixture_source):
        client = YahooClient(fixture_source)
        result = tool_get_roster(client, team_key="449.l.99001.t.1")
        assert result["team_key"] == "449.l.99001.t.1"


class TestGetStandings:
    def test_shape_and_order(self, fixture_source):
        client = YahooClient(fixture_source)
        result = tool_get_standings(client)
        assert [t["standing"] for t in result["standings"]] == [1, 2, 3, 4]
        assert result["standings"][0]["name"] == "Turf Wars"
