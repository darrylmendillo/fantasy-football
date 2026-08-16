"""Contract tests for MCP tools against contracts/mcp-tools.md.

Tests call the tools' underlying implementation functions directly (not
through the FastMCP protocol layer) — that's the boundary worth testing
here; FastMCP's own JSON-RPC framing is the library's concern, not ours.
"""

from __future__ import annotations

from yahoo_fantasy_mcp.client import YahooClient
from yahoo_fantasy_mcp.server import (
    tool_get_available_players,
    tool_get_draft_results,
    tool_get_league_info,
    tool_get_roster,
    tool_get_standings,
    tool_list_teams,
)

TOTAL_EXPECTED_PICKS = 12  # matches the 4-team/3-round test league fixtures


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


class TestGetDraftResults:
    def test_predraft_is_empty_not_error(self, fixture_source):
        fixture_source.draft_fixture = "draft_predraft.json"
        client = YahooClient(fixture_source)
        result = tool_get_draft_results(client, TOTAL_EXPECTED_PICKS)
        assert result["picks"] == []
        assert result["draft_status"] == "predraft"
        assert result["is_complete"] is False

    def test_midraft_includes_resolved_player_names(self, fixture_source):
        fixture_source.draft_fixture = "draft_midraft.json"
        client = YahooClient(fixture_source)
        result = tool_get_draft_results(client, TOTAL_EXPECTED_PICKS)
        assert len(result["picks"]) == 5
        assert result["draft_status"] == "drafting"
        assert result["picks"][0]["player_name"] == "Bijan Robinson"
        assert result["retrieved_at"]  # non-empty ISO timestamp

    def test_postdraft_is_complete(self, fixture_source):
        fixture_source.draft_fixture = "draft_postdraft.json"
        client = YahooClient(fixture_source)
        result = tool_get_draft_results(client, TOTAL_EXPECTED_PICKS)
        assert result["is_complete"] is True
        assert result["draft_status"] == "postdraft"
        assert len(result["picks"]) == 12


class TestGetAvailablePlayers:
    def test_shape(self, fixture_source):
        fixture_source.draft_fixture = "draft_midraft.json"
        client = YahooClient(fixture_source)
        result = tool_get_available_players(client, TOTAL_EXPECTED_PICKS, position=None, limit=50)
        assert result["retrieved_at"]
        assert result["count"] == len(result["players"])
        assert all("average_pick" in p for p in result["players"])

    def test_position_filter(self, fixture_source):
        fixture_source.draft_fixture = "draft_midraft.json"
        client = YahooClient(fixture_source)
        result = tool_get_available_players(
            client, TOTAL_EXPECTED_PICKS, position="RB", limit=50
        )
        assert all("RB" in p["positions"] for p in result["players"])

    def test_never_overlaps_with_draft_results_same_call(self, fixture_source):
        """SC-002 at the tool boundary: a client calling both tools during a
        live draft must never see the same player in both responses."""
        fixture_source.draft_fixture = "draft_midraft.json"
        client = YahooClient(fixture_source)

        draft_result = tool_get_draft_results(client, TOTAL_EXPECTED_PICKS)
        available_result = tool_get_available_players(
            client, TOTAL_EXPECTED_PICKS, position=None, limit=50
        )

        drafted_ids = {p["player_id"] for p in draft_result["picks"]}
        available_ids = {p["player_id"] for p in available_result["players"]}
        assert drafted_ids & available_ids == set()
