"""Task 7 — the propose/confirm rail (FR-017–FR-023, research R8).

Covers all five refusals from quickstart V6. These tests are the reason the
guarantee can be claimed at all: they demonstrate that a client which never
showed the user a prompt still cannot cause a write.
"""

from __future__ import annotations

import pytest

from yahoo_fantasy_mcp.confirm import create_proposal, hash_token, verify_and_consume
from yahoo_fantasy_mcp.errors import (
    InvalidConfirmationError,
    PreconditionsChangedError,
    ProposalAlreadyUsedError,
    ProposalExpiredError,
)

ALWAYS_OK = lambda row: True  # noqa: E731
ALWAYS_STALE = lambda row: False  # noqa: E731


def _make(store, sub, now=1000, ttl=300):
    return create_proposal(
        store,
        sub=sub,
        league_key="461.l.1",
        team_key="461.l.1.t.5",
        action_type="set_lineup",
        payload={"week": 3},
        preview={"summary": "start X, bench Y"},
        precondition={"roster": [1, 2]},
        ttl_seconds=ttl,
        now=now,
    )


class TestHappyPath:
    def test_confirm_returns_the_proposal(self, store, sub_a):
        _, token = _make(store, sub_a)
        row = verify_and_consume(
            store, token=token, sub=sub_a, now=1010, precondition_checker=ALWAYS_OK
        )
        assert row.action_type == "set_lineup"

    def test_proposing_does_not_consume(self, store, sub_a):
        _, token = _make(store, sub_a)
        row = store.get_proposal_by_hash(hash_token(token))
        assert row.status == "pending"
        assert row.consumed_at is None


class TestFiveRefusals:
    def test_unknown_token_is_refused(self, store, sub_a):
        with pytest.raises(InvalidConfirmationError):
            verify_and_consume(
                store,
                token="never-issued",
                sub=sub_a,
                now=1010,
                precondition_checker=ALWAYS_OK,
            )

    def test_replay_is_refused(self, store, sub_a):
        _, token = _make(store, sub_a)
        verify_and_consume(
            store, token=token, sub=sub_a, now=1010, precondition_checker=ALWAYS_OK
        )
        with pytest.raises(ProposalAlreadyUsedError):
            verify_and_consume(
                store, token=token, sub=sub_a, now=1011, precondition_checker=ALWAYS_OK
            )

    def test_expired_proposal_is_refused(self, store, sub_a):
        _, token = _make(store, sub_a, now=1000, ttl=300)
        with pytest.raises(ProposalExpiredError):
            verify_and_consume(
                store, token=token, sub=sub_a, now=1301, precondition_checker=ALWAYS_OK
            )

    def test_other_users_token_is_refused(self, store, sub_a, sub_b):
        """FR-020. Must raise the SAME error as an unknown token: the response
        may not reveal whether a token exists."""
        _, token = _make(store, sub_a)
        with pytest.raises(InvalidConfirmationError):
            verify_and_consume(
                store, token=token, sub=sub_b, now=1010, precondition_checker=ALWAYS_OK
            )

    def test_precondition_drift_is_refused(self, store, sub_a):
        _, token = _make(store, sub_a)
        with pytest.raises(PreconditionsChangedError):
            verify_and_consume(
                store, token=token, sub=sub_a, now=1010, precondition_checker=ALWAYS_STALE
            )


class TestNoWriteAfterRefusal:
    def test_drifted_proposal_cannot_be_retried(self, store, sub_a):
        """A proposal that failed preconditions is terminal — a second attempt
        must not sneak through once the world happens to look right again."""
        _, token = _make(store, sub_a)
        with pytest.raises(PreconditionsChangedError):
            verify_and_consume(
                store, token=token, sub=sub_a, now=1010, precondition_checker=ALWAYS_STALE
            )
        with pytest.raises((ProposalExpiredError, ProposalAlreadyUsedError,
                            InvalidConfirmationError)):
            verify_and_consume(
                store, token=token, sub=sub_a, now=1011, precondition_checker=ALWAYS_OK
            )


class TestTokenStorage:
    def test_raw_token_is_never_stored(self, store, sub_a):
        """data-model.md: only the hash is persisted, so a leaked database
        cannot be used to confirm anything."""
        _, token = _make(store, sub_a)
        dumped = "".join(
            str(v) for row in store._conn.execute("SELECT * FROM proposals") for v in row
        )
        assert token not in dumped
        assert hash_token(token) in dumped

    def test_tokens_are_unpredictable(self, store, sub_a):
        tokens = {_make(store, sub_a)[1] for _ in range(20)}
        assert len(tokens) == 20
        assert all(len(t) >= 32 for t in tokens)
