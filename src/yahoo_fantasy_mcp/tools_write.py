"""Write tools: propose/confirm only (spec 002, US3).

There is deliberately no single-call write path and no `force` or
`skip_confirm` parameter anywhere in this module (FR-017).

DISPATCH IS BLOCKED. `Team.change_positions`' time_frame/modified_lineup
shape is unverified (research R5), and constitution v0.3.0 Principle I
forbids implementing against a guessed third-party signature. The
`LineupWriter` Protocol is the seam: once gate G3 verifies the real shape, a
`YahooLineupWriter` implementing it replaces `UnapprovedLineupWriter` with no
other change to this file.
"""

from __future__ import annotations

import json
from typing import Any, Protocol

from yahoo_fantasy_mcp.confirm import create_proposal, verify_and_consume
from yahoo_fantasy_mcp.errors import WriteNotApprovedError
from yahoo_fantasy_mcp.store import ProposalRow, Store


class LineupWriter(Protocol):
    """The one place this server can change a Yahoo lineup."""

    def set_lineup(self, team: Any, week: int, changes: list[dict]) -> dict: ...


class UnapprovedLineupWriter:
    """Default writer while Yahoo write access / signature verification is
    outstanding. Fails loudly and specifically (FR-025)."""

    def set_lineup(self, team: Any, week: int, changes: list[dict]) -> dict:
        raise WriteNotApprovedError()


def tool_propose_set_lineup(
    store: Store,
    *,
    sub: str,
    league_key: str,
    team_key: str,
    week: int,
    changes: list[dict],
    current_roster: dict[int, str],
    ttl_seconds: int,
    now: int,
) -> dict:
    """Describe a lineup change without making it (FR-017).

    The preview names the exact players and slots, and the precondition
    snapshot records the roster state this proposal assumed, so confirm can
    detect drift (FR-021).
    """
    warnings: list[str] = []
    for change in changes:
        if change["player_id"] not in current_roster:
            warnings.append(f"Player {change['player_id']} is not on this roster.")

    preview = {
        "action": "set_lineup",
        "week": week,
        "changes": [
            {
                "player_id": c["player_id"],
                "from_position": current_roster.get(c["player_id"]),
                "to_position": c["position"],
            }
            for c in changes
        ],
        "warnings": warnings,
    }
    proposal_id, token = create_proposal(
        store,
        sub=sub,
        league_key=league_key,
        team_key=team_key,
        action_type="set_lineup",
        payload={"week": week, "changes": changes},
        preview=preview,
        precondition={"roster": current_roster},
        ttl_seconds=ttl_seconds,
        now=now,
    )
    return {
        "proposal_id": proposal_id,
        "confirmation_token": token,
        "expires_in_seconds": ttl_seconds,
        "preview": preview,
    }


def _lineup_preconditions_hold(row: ProposalRow, current_roster: dict[int, str]) -> bool:
    snapshot = json.loads(row.precondition_json).get("roster", {})
    # JSON object keys are strings; normalise before comparing.
    snapshot = {int(k): v for k, v in snapshot.items()}
    return snapshot == current_roster


def tool_confirm_action(
    store: Store,
    *,
    sub: str,
    token: str,
    now: int,
    current_roster: dict[int, str],
    lineup_writer: LineupWriter,
    team: Any,
) -> dict:
    """The only path that writes. Validates, consumes, then dispatches."""
    row = verify_and_consume(
        store,
        token=token,
        sub=sub,
        now=now,
        precondition_checker=lambda r: _lineup_preconditions_hold(r, current_roster),
    )
    payload = json.loads(row.payload_json)
    result = lineup_writer.set_lineup(team, payload["week"], payload["changes"])
    return {
        "status": "applied",
        "action": row.action_type,
        "result": result,
        "applied_at": now,
    }
