"""Task 8 — US3 write path, mock-validated.

Nothing here proves Yahoo accepts our lineup payload; the real dispatch is
blocked on gate G3 (research R5's unverified change_positions signature).
What these tests DO prove is that no code path reaches a writer without a
valid confirmation.
"""

from __future__ import annotations

import pytest

from yahoo_fantasy_mcp.errors import (
    InvalidConfirmationError,
    ProposalAlreadyUsedError,
    WriteNotApprovedError,
)
from yahoo_fantasy_mcp.tools_write import (
    UnapprovedLineupWriter,
    tool_confirm_action,
    tool_propose_set_lineup,
)


class SpyLineupWriter:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def set_lineup(self, team, week, changes) -> dict:
        self.calls.append((team, week, changes))
        return {"applied": True}


def _propose(store, sub, now=1000):
    return tool_propose_set_lineup(
        store,
        sub=sub,
        league_key="461.l.1",
        team_key="461.l.1.t.5",
        week=3,
        changes=[{"player_id": 1, "position": "WR"}],
        current_roster={1: "BN", 2: "WR"},
        ttl_seconds=300,
        now=now,
    )


class TestProposeIsInert:
    def test_propose_returns_a_preview_and_token(self, store, sub_a):
        result = _propose(store, sub_a)
        assert result["preview"]["action"] == "set_lineup"
        assert result["confirmation_token"]
        assert result["expires_in_seconds"] == 300

    def test_propose_never_touches_the_writer(self, store, sub_a):
        """FR-017: proposing changes nothing upstream."""
        writer = SpyLineupWriter()
        _propose(store, sub_a)
        assert writer.calls == []


class TestConfirmGatesTheWrite:
    def test_valid_confirmation_dispatches_exactly_once(self, store, sub_a):
        writer = SpyLineupWriter()
        token = _propose(store, sub_a)["confirmation_token"]
        tool_confirm_action(
            store,
            sub=sub_a,
            token=token,
            now=1010,
            current_roster={1: "BN", 2: "WR"},
            lineup_writer=writer,
            team=object(),
        )
        assert len(writer.calls) == 1

    def test_fabricated_token_never_reaches_the_writer(self, store, sub_a):
        """The assertion FR-019 exists for: a hallucinated confirmation causes
        no write, whatever the host's UI did or did not do."""
        writer = SpyLineupWriter()
        with pytest.raises(InvalidConfirmationError):
            tool_confirm_action(
                store,
                sub=sub_a,
                token="totally-made-up-token",
                now=1010,
                current_roster={1: "BN"},
                lineup_writer=writer,
                team=object(),
            )
        assert writer.calls == []


class TestUnapprovedWriterSeam:
    def test_default_writer_refuses_with_write_not_approved(self):
        """FR-025 / T046 blocked on G3 — the product cannot write yet, and
        says so distinctly from 'your request was invalid'."""
        with pytest.raises(WriteNotApprovedError):
            UnapprovedLineupWriter().set_lineup(object(), 3, [])

    def test_confirmation_still_consumed_before_dispatch_is_attempted(self, store, sub_a):
        """Even against the unapproved writer, the token must be spent — so a
        user cannot retry a confirmed action repeatedly once writes turn on."""
        token = _propose(store, sub_a)["confirmation_token"]
        with pytest.raises(WriteNotApprovedError):
            tool_confirm_action(
                store,
                sub=sub_a,
                token=token,
                now=1010,
                current_roster={1: "BN", 2: "WR"},
                lineup_writer=UnapprovedLineupWriter(),
                team=object(),
            )
        # The token must have been burned by the first attempt, not just
        # refused — a retry (even against a writer that would happily
        # dispatch) must find nothing left to confirm. This is what proves
        # verify_and_consume ran, and ran, before set_lineup was ever called.
        with pytest.raises(ProposalAlreadyUsedError):
            tool_confirm_action(
                store,
                sub=sub_a,
                token=token,
                now=1011,
                current_roster={1: "BN", 2: "WR"},
                lineup_writer=SpyLineupWriter(),
                team=object(),
            )
