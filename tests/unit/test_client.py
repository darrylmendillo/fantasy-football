"""client.py: raw fixture dicts -> domain models."""

from __future__ import annotations

from yahoo_fantasy_mcp.client import YahooClient


def test_get_league_info(fixture_source):
    client = YahooClient(fixture_source)
    league = client.get_league_info()
    assert league.league_key == "449.l.99001"
    assert league.num_teams == 4


def test_get_teams_flags_owned_team(fixture_source):
    client = YahooClient(fixture_source)
    teams = client.get_teams()
    owned = [t for t in teams if t.is_owned_by_user]
    assert len(owned) == 1
    assert owned[0].team_key == "449.l.99001.t.1"
    assert all(not t.is_owned_by_user for t in teams if t.team_key != owned[0].team_key)


def test_get_roster(fixture_source):
    client = YahooClient(fixture_source)
    roster = client.get_roster("449.l.99001.t.1")
    assert roster.team_key == "449.l.99001.t.1"
    names = {p.name for p in roster.players}
    assert "Bijan Robinson" in names


def test_get_standings_ordered_as_returned(fixture_source):
    client = YahooClient(fixture_source)
    standings = client.get_standings()
    assert [t.standing for t in standings] == [1, 2, 3, 4]
    assert standings[0].name == "Turf Wars"


def test_fetch_draft_results_raw_is_passthrough_not_parsed(fixture_source):
    """client.py must NOT pre-parse draft picks into DraftPick objects —
    draft.py needs the raw 'cost' field intact to detect auction leagues."""
    client = YahooClient(fixture_source)
    raw = client.fetch_draft_results_raw()
    assert isinstance(raw, list)
    assert raw and isinstance(raw[0], dict)
    assert "player_id" in raw[0]


def test_get_player_details(fixture_source):
    client = YahooClient(fixture_source)
    details = client.get_player_details([9001, 9002])
    assert details[9001].name == "Bijan Robinson"
    assert details[9002].positions == ["WR"]
