"""Propose/confirm rail — the server-side write guarantee (spec 002, research R8).

FR-019 requires that the two-step guarantee hold regardless of which MCP host
is connected, and NOT depend on the host's own approval prompt. That is why
every check below lives here rather than in a tool description or an
annotation: a client that never showed the user anything still cannot cause a
write, because it cannot produce a token that satisfies all of these checks.

Only the SHA-256 of a confirmation token is persisted. The raw token is
returned to the caller once and never stored.
"""

from __future__ import annotations

import hashlib
import json
import secrets
import uuid
from collections.abc import Callable
from typing import Any

from yahoo_fantasy_mcp.errors import (
    InvalidConfirmationError,
    PreconditionsChangedError,
    ProposalAlreadyUsedError,
    ProposalExpiredError,
)
from yahoo_fantasy_mcp.store import ProposalRow, Store

TOKEN_BYTES = 32


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create_proposal(
    store: Store,
    *,
    sub: str,
    league_key: str,
    team_key: str,
    action_type: str,
    payload: dict[str, Any],
    preview: dict[str, Any],
    precondition: dict[str, Any],
    ttl_seconds: int,
    now: int,
) -> tuple[str, str]:
    """Record an intent-to-write and mint its single-use confirmation token.

    Changes nothing upstream. Returns (proposal_id, raw_token); the raw token
    is the only copy that will ever exist outside the caller.
    """
    proposal_id = str(uuid.uuid4())
    token = secrets.token_urlsafe(TOKEN_BYTES)
    store.insert_proposal(
        ProposalRow(
            id=proposal_id,
            token_hash=hash_token(token),
            sub=sub,
            league_key=league_key,
            team_key=team_key,
            action_type=action_type,
            payload_json=json.dumps(payload),
            preview_json=json.dumps(preview),
            precondition_json=json.dumps(precondition),
            created_at=now,
            expires_at=now + ttl_seconds,
            status="pending",
            consumed_at=None,
        )
    )
    return proposal_id, token


def verify_and_consume(
    store: Store,
    *,
    token: str,
    sub: str,
    now: int,
    precondition_checker: Callable[[ProposalRow], bool],
) -> ProposalRow:
    """Validate a confirmation and atomically claim it, or raise.

    Check order is deliberate:
      1. unknown token and wrong-user both raise InvalidConfirmationError, so
         the response cannot be used to probe whether a token exists;
      2. already-consumed outranks expiry, because "you already did this" is
         more useful to a user than "it expired";
      3. preconditions are re-read last, since that is the expensive check;
      4. consumption is claimed via a conditional UPDATE, so two racing
         confirms cannot both win.
    """
    row = store.get_proposal_by_hash(hash_token(token))
    if row is None or row.sub != sub:
        raise InvalidConfirmationError()

    if row.status == "consumed":
        raise ProposalAlreadyUsedError()
    if row.status != "pending":
        raise ProposalExpiredError()

    if now >= row.expires_at:
        store.mark_status(row.id, "expired")
        raise ProposalExpiredError()

    if not precondition_checker(row):
        # Terminal: the user must re-propose against current reality (FR-021).
        store.mark_status(row.id, "failed")
        raise PreconditionsChangedError()

    if not store.mark_consumed(row.id, now):
        # Lost a race with a concurrent confirm of the same token.
        raise ProposalAlreadyUsedError()

    return row
