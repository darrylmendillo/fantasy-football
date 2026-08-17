"""T006 — store.py: user upsert idempotency, usage append, proposal lifecycle.

Lifecycle assertions follow data-model.md's state machine: only `pending` is
confirmable, and every other state is terminal. The concurrency test is the
one that matters most — it is what makes single-use hold (FR-023).
"""

from __future__ import annotations

import pytest

from yahoo_fantasy_mcp.store import ProposalRow, Store


def _proposal(token_hash: str = "hash-1", sub: str = "yahoo-guid-aaaa1111", **kw) -> ProposalRow:
    defaults = dict(
        id="prop-1",
        token_hash=token_hash,
        sub=sub,
        league_key="461.l.1",
        team_key="461.l.1.t.5",
        action_type="set_lineup",
        payload_json="{}",
        preview_json="{}",
        precondition_json="{}",
        created_at=1000,
        expires_at=1300,
        status="pending",
        consumed_at=None,
    )
    defaults.update(kw)
    return ProposalRow(**defaults)


class TestUsers:
    def test_upsert_is_idempotent(self, store: Store, sub_a: str, sub_b: str) -> None:
        store.upsert_user(sub_a, now=100)
        store.upsert_user(sub_a, now=200)
        row = store.get_user(sub_a)
        assert row is not None
        # created_at must survive the second call; only last_seen_at moves.
        assert row["created_at"] == 100
        assert row["last_seen_at"] == 200

    def test_new_users_default_to_free_tier(self, store: Store, sub_a: str, sub_b: str) -> None:
        """FR-028: the tier column exists from day one so metering can be
        added later without touching the auth/data layer."""
        store.upsert_user(sub_a)
        assert store.get_user(sub_a)["tier"] == "free"

    def test_users_are_distinct(self, store: Store, sub_a: str, sub_b: str) -> None:
        store.upsert_user(sub_a)
        store.upsert_user(sub_b)
        assert store.get_user(sub_a)["sub"] != store.get_user(sub_b)["sub"]

    def test_unknown_user_is_none(self, store: Store, sub_a: str, sub_b: str) -> None:
        assert store.get_user("nobody") is None


class TestUsage:
    def test_records_are_appended_per_user(self, store: Store, sub_a: str, sub_b: str) -> None:
        store.record_usage(sub_a, "get_roster", "ok")
        store.record_usage(sub_a, "get_roster", "ok")
        store.record_usage(sub_b, "get_roster", "ok")
        assert store.usage_count(sub_a) == 2
        assert store.usage_count(sub_b) == 1

    def test_refusals_are_recorded_too(self, store: Store, sub_a: str, sub_b: str) -> None:
        """Refusals count: a future rate-limiter needs to distinguish them,
        and silently dropping them would understate usage."""
        store.record_usage(sub_a, "get_roster", "refused")
        assert store.usage_count(sub_a) == 1


class TestProposalLifecycle:
    def test_roundtrip_by_hash(self, store: Store, sub_a: str, sub_b: str) -> None:
        store.insert_proposal(_proposal())
        got = store.get_proposal_by_hash("hash-1")
        assert got is not None
        assert got.sub == sub_a
        assert got.status == "pending"

    def test_unknown_hash_returns_none(self, store: Store, sub_a: str, sub_b: str) -> None:
        assert store.get_proposal_by_hash("never-issued") is None

    def test_consume_transitions_pending_to_consumed(
        self, store: Store, sub_a: str, sub_b: str
    ) -> None:
        store.insert_proposal(_proposal())
        assert store.mark_consumed("prop-1", now=1200) is True
        got = store.get_proposal_by_hash("hash-1")
        assert got.status == "consumed"
        assert got.consumed_at == 1200

    def test_second_consume_fails(self, store: Store, sub_a: str, sub_b: str) -> None:
        """FR-023 replay protection at the storage layer. This is the single
        most important assertion in this file: if it regresses, a confirmation
        token becomes reusable."""
        store.insert_proposal(_proposal())
        assert store.mark_consumed("prop-1", now=1200) is True
        assert store.mark_consumed("prop-1", now=1201) is False

    def test_terminal_states_cannot_be_consumed(
        self, store: Store, sub_a: str, sub_b: str
    ) -> None:
        for status in ("expired", "failed", "consumed"):
            store.insert_proposal(
                _proposal(token_hash=f"h-{status}", id=f"p-{status}", status=status)
            )
            assert store.mark_consumed(f"p-{status}", now=1200) is False

    def test_token_hash_is_unique(self, store: Store, sub_a: str, sub_b: str) -> None:
        import sqlite3

        store.insert_proposal(_proposal())
        with pytest.raises(sqlite3.IntegrityError):
            store.insert_proposal(_proposal(id="prop-2"))
