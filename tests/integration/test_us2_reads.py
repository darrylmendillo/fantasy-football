"""Task 6 — US2: reads work against any league, selected per call.

The availability-invariant test is carried forward from spec 001 deliberately:
it is the project's core correctness guarantee (FR-012) and the most likely
thing to break silently during a refactor.
"""

from __future__ import annotations

from yahoo_fantasy_mcp.tools_read import (
    tool_get_available_players,
    tool_get_draft_results,
    tool_get_league_info,
    tool_get_standings,
    tool_list_teams,
)


def test_league_info_returns_identity_fields(fixture_client):
    info = tool_get_league_info(fixture_client())
    assert info["league_key"] == "449.l.99001"
    assert info["name"] == "Sunday Funday"


def test_list_teams_flags_the_callers_own_team(fixture_client):
    teams = tool_list_teams(fixture_client())
    assert any(t["is_owned_by_user"] for t in teams)


def test_standings_are_ranked(fixture_client):
    standings = tool_get_standings(fixture_client())
    assert [t["standing"] for t in standings] == sorted(t["standing"] for t in standings)


def test_availability_and_drafted_never_overlap_midraft(fixture_client):
    """FR-012. If this fails, the product's central promise is broken."""
    client = fixture_client("draft_midraft.json")
    drafted = {p["player_id"] for p in tool_get_draft_results(client, 64)["picks"]}
    available = {p["player_id"] for p in tool_get_available_players(client, 64)["players"]}
    assert drafted & available == set()


def test_availability_invariant_holds_deep_into_draft(fixture_client):
    """Late-draft is where a regression to cached availability surfaces.

    draft_postdraft.json is the latest-stage fixture in the repo (verified:
    tests/fixtures/ holds predraft, midraft, postdraft, auction only — there
    is no draft_late.json).
    """
    client = fixture_client("draft_postdraft.json")
    drafted = {p["player_id"] for p in tool_get_draft_results(client, 64)["picks"]}
    available = {p["player_id"] for p in tool_get_available_players(client, 64)["players"]}
    assert drafted & available == set()
