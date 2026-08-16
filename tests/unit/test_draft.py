"""Draft snapshot tests (FR-008, FR-009, FR-013). Written before draft.py
exists — must fail first. T043-T045 (US3, availability derivation) are
added in a later commit alongside get_available_players."""

from __future__ import annotations

import datetime

import pytest

from yahoo_fantasy_mcp.errors import UnsupportedDraftTypeError, UpstreamError

# 4-team, 3-round test league (matches tests/fixtures/draft_*.json)
TOTAL_EXPECTED_PICKS = 12


class TestPredraft:
    def test_empty_picks_no_error(self, fixture_source):
        """US2 scenario 3: pre-draft must return empty, not raise."""
        from yahoo_fantasy_mcp.draft import build_draft_snapshot

        fixture_source.draft_fixture = "draft_predraft.json"
        raw = fixture_source.fetch_draft_results_raw()
        snapshot = build_draft_snapshot(raw, total_expected_picks=TOTAL_EXPECTED_PICKS)
        assert snapshot.picks == []
        assert snapshot.is_complete is False


class TestMidraft:
    def test_only_picks_so_far_ordered(self, fixture_source):
        """US2 scenario 1, FR-008: partial results, ordered by pick ascending."""
        from yahoo_fantasy_mcp.draft import build_draft_snapshot

        fixture_source.draft_fixture = "draft_midraft.json"
        raw = fixture_source.fetch_draft_results_raw()
        snapshot = build_draft_snapshot(raw, total_expected_picks=TOTAL_EXPECTED_PICKS)
        assert [p.pick for p in snapshot.picks] == [1, 2, 3, 4, 5]
        assert snapshot.is_complete is False


class TestPostdraft:
    def test_complete_board(self, fixture_source):
        """US2 scenario 2: complete board, is_complete True."""
        from yahoo_fantasy_mcp.draft import build_draft_snapshot

        fixture_source.draft_fixture = "draft_postdraft.json"
        raw = fixture_source.fetch_draft_results_raw()
        snapshot = build_draft_snapshot(raw, total_expected_picks=TOTAL_EXPECTED_PICKS)
        assert len(snapshot.picks) == 12
        assert snapshot.is_complete is True


class TestRetrievedAt:
    def test_populated_on_every_snapshot(self, fixture_source):
        """FR-009: every draft-bearing response must carry retrieved_at."""
        from yahoo_fantasy_mcp.draft import build_draft_snapshot

        for fixture in ["draft_predraft.json", "draft_midraft.json", "draft_postdraft.json"]:
            fixture_source.draft_fixture = fixture
            raw = fixture_source.fetch_draft_results_raw()
            snapshot = build_draft_snapshot(raw, total_expected_picks=TOTAL_EXPECTED_PICKS)
            assert isinstance(snapshot.retrieved_at, datetime.datetime)
            assert snapshot.retrieved_at.tzinfo is not None


class TestAuctionGuard:
    def test_auction_fixture_raises(self, fixture_source):
        """FR-013, data-model rule 1: a non-null 'cost' field means auction —
        must fail loudly, never be silently parsed as a snake pick."""
        from yahoo_fantasy_mcp.draft import build_draft_snapshot

        fixture_source.draft_fixture = "draft_auction.json"
        raw = fixture_source.fetch_draft_results_raw()
        with pytest.raises(UnsupportedDraftTypeError):
            build_draft_snapshot(raw, total_expected_picks=TOTAL_EXPECTED_PICKS)


class TestDuplicatePickDetection:
    def test_duplicate_player_id_is_surfaced_not_deduped(self):
        """data-model rule 2: a duplicate player_id across picks indicates a
        corrupt/racy read and must raise, never silently deduplicate."""
        from yahoo_fantasy_mcp.draft import build_draft_snapshot

        raw = [
            {"pick": 1, "round": 1, "team_key": "t.1", "player_id": 9001},
            {"pick": 2, "round": 1, "team_key": "t.2", "player_id": 9001},  # duplicate
        ]
        with pytest.raises(UpstreamError):
            build_draft_snapshot(raw, total_expected_picks=TOTAL_EXPECTED_PICKS)


# Full pool of players under consideration in the test fixtures: 12 drafted
# (9001-9012) + 5 undrafted (40001-40005). See tests/fixtures/player_details.json.
ALL_TEST_PLAYER_IDS = list(range(9001, 9013)) + list(range(40001, 40006))


class TestAvailabilityInvariant:
    """The highest-value test in this suite (research R3, SC-002): available
    players must never overlap with drafted players. This is the guard
    against the exact upstream cache-staleness bug identified in research.md
    — free_agents()/taken_players() cache forever with no TTL, so calling
    them during a live draft would silently report drafted players as
    available. derive_available_players() must be immune to that by
    construction."""

    def test_empty_intersection_midraft(self, fixture_source):
        from yahoo_fantasy_mcp.client import YahooClient
        from yahoo_fantasy_mcp.draft import build_draft_snapshot, derive_available_players

        fixture_source.draft_fixture = "draft_midraft.json"
        client = YahooClient(fixture_source)
        draft = build_draft_snapshot(
            client.fetch_draft_results_raw(), total_expected_picks=TOTAL_EXPECTED_PICKS
        )
        universe = client.get_player_details(ALL_TEST_PLAYER_IDS)

        available = derive_available_players(draft, universe)
        available_ids = {p.player_id for p in available}
        drafted_ids = draft.drafted_player_ids()

        assert available_ids & drafted_ids == set(), (
            "SC-002 violation: a drafted player was returned as available"
        )
        assert drafted_ids == {9001, 9002, 9003, 9004, 9005}

    def test_empty_intersection_holds_deep_into_draft(self, fixture_source):
        """T044: re-assert the invariant against a later-stage draft — this
        is where the R3 caching bug class would actually surface if
        derive_available_players ever regressed to using a cached call."""
        from yahoo_fantasy_mcp.client import YahooClient
        from yahoo_fantasy_mcp.draft import build_draft_snapshot, derive_available_players

        fixture_source.draft_fixture = "draft_postdraft.json"
        client = YahooClient(fixture_source)
        draft = build_draft_snapshot(
            client.fetch_draft_results_raw(), total_expected_picks=TOTAL_EXPECTED_PICKS
        )
        universe = client.get_player_details(ALL_TEST_PLAYER_IDS)

        available = derive_available_players(draft, universe)
        available_ids = {p.player_id for p in available}

        assert available_ids & draft.drafted_player_ids() == set()
        assert available_ids == {40001, 40002, 40003, 40004, 40005}

    def test_predraft_all_players_available(self, fixture_source):
        from yahoo_fantasy_mcp.client import YahooClient
        from yahoo_fantasy_mcp.draft import build_draft_snapshot, derive_available_players

        fixture_source.draft_fixture = "draft_predraft.json"
        client = YahooClient(fixture_source)
        draft = build_draft_snapshot(
            client.fetch_draft_results_raw(), total_expected_picks=TOTAL_EXPECTED_PICKS
        )
        universe = client.get_player_details(ALL_TEST_PLAYER_IDS)

        available = derive_available_players(draft, universe, limit=len(ALL_TEST_PLAYER_IDS))
        assert {p.player_id for p in available} == set(ALL_TEST_PLAYER_IDS)


class TestPositionFiltering:
    def test_filters_to_eligible_position(self, fixture_source):
        """US3 scenario 2: only players eligible at the requested position."""
        from yahoo_fantasy_mcp.client import YahooClient
        from yahoo_fantasy_mcp.draft import build_draft_snapshot, derive_available_players

        fixture_source.draft_fixture = "draft_midraft.json"
        client = YahooClient(fixture_source)
        draft = build_draft_snapshot(
            client.fetch_draft_results_raw(), total_expected_picks=TOTAL_EXPECTED_PICKS
        )
        universe = client.get_player_details(ALL_TEST_PLAYER_IDS)

        rbs = derive_available_players(draft, universe, position="RB")
        assert rbs
        assert all("RB" in p.positions for p in rbs)

    def test_multi_eligible_player_appears_under_each_position(self, fixture_source):
        """Player 40005 (Rachaad White) is eligible at RB and W/R/T."""
        from yahoo_fantasy_mcp.client import YahooClient
        from yahoo_fantasy_mcp.draft import build_draft_snapshot, derive_available_players

        fixture_source.draft_fixture = "draft_predraft.json"
        client = YahooClient(fixture_source)
        draft = build_draft_snapshot(
            client.fetch_draft_results_raw(), total_expected_picks=TOTAL_EXPECTED_PICKS
        )
        universe = client.get_player_details([40005])

        rb_results = derive_available_players(draft, universe, position="RB")
        flex_results = derive_available_players(draft, universe, position="W/R/T")
        assert any(p.player_id == 40005 for p in rb_results)
        assert any(p.player_id == 40005 for p in flex_results)
