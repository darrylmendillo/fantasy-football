"""Entity tests per data-model.md. Written before models.py exists — must fail first."""

from __future__ import annotations

import datetime

import pytest

from yahoo_fantasy_mcp.models import (
    Draft,
    DraftPick,
    League,
    Player,
    Roster,
    Team,
)


class TestLeague:
    def test_fields(self):
        league = League(
            league_key="449.l.99001",
            name="Sunday Funday",
            season=2026,
            num_teams=4,
            scoring_type="head",
            draft_status="predraft",
        )
        assert league.league_key == "449.l.99001"
        assert league.num_teams == 4
        assert league.draft_status == "predraft"


class TestTeam:
    def test_fields(self):
        team = Team(
            team_key="449.l.99001.t.1",
            name="Team Chaos",
            is_owned_by_user=True,
            standing=None,
        )
        assert team.is_owned_by_user is True
        assert team.standing is None


class TestPlayer:
    def test_fields_and_optional_ranking(self):
        player = Player(
            player_id=9001,
            name="Bijan Robinson",
            positions=["RB"],
            nfl_team="ATL",
            percent_owned=99,
            average_pick=1.2,
        )
        assert player.player_id == 9001
        assert "RB" in player.positions

    def test_ranking_fields_default_to_none(self):
        player = Player(player_id=1, name="X", positions=["QB"], nfl_team="KC")
        assert player.percent_owned is None
        assert player.average_pick is None

    def test_player_has_no_availability_field(self):
        """The Availability Invariant (data-model.md): Player MUST NOT carry
        any is_available/is_drafted flag. Availability is always derived,
        never stored, to avoid the R3 stale-cache failure mode."""
        player = Player(player_id=1, name="X", positions=["QB"], nfl_team="KC")
        assert not hasattr(player, "is_available")
        assert not hasattr(player, "is_drafted")


class TestDraftPick:
    def test_fields_no_cost(self):
        """Snake-draft picks carry no 'cost' field (FR-013 scope)."""
        pick = DraftPick(pick=1, round=1, team_key="449.l.99001.t.1", player_id=9001)
        assert pick.pick == 1
        assert not hasattr(pick, "cost")


class TestDraft:
    def test_requires_retrieved_at(self):
        """retrieved_at is required, not optional (data-model.md — FR-009 freshness
        cannot be enforced by a caller without it)."""
        with pytest.raises(TypeError):
            Draft(picks=[], is_complete=False)  # type: ignore[call-arg]

    def test_predraft_snapshot(self):
        draft = Draft(picks=[], retrieved_at=datetime.datetime.now(datetime.UTC), is_complete=False)
        assert draft.picks == []
        assert draft.is_complete is False

    def test_drafted_ids(self):
        picks = [
            DraftPick(pick=1, round=1, team_key="t.1", player_id=9001),
            DraftPick(pick=2, round=1, team_key="t.2", player_id=9002),
        ]
        now = datetime.datetime.now(datetime.UTC)
        draft = Draft(picks=picks, retrieved_at=now, is_complete=False)
        assert draft.drafted_player_ids() == {9001, 9002}


class TestRoster:
    def test_fields(self):
        roster = Roster(
            team_key="449.l.99001.t.1",
            players=[
                Player(player_id=9001, name="Bijan Robinson", positions=["RB"], nfl_team="ATL")
            ],
        )
        assert len(roster.players) == 1
