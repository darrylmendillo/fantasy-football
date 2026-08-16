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
