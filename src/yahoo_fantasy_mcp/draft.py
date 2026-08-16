"""Draft snapshot construction and availability derivation.

This is the module research.md R3 exists for: yahoo_fantasy_api's
free_agents()/taken_players() cache permanently with no TTL, so a
long-lived server process would silently report drafted players as
available. Every function here is built to make that failure mode
impossible by construction — availability is always derived from a fresh
draft_results() read, never read from a separately-cached "available
players" call.
"""

from __future__ import annotations

import datetime

from yahoo_fantasy_mcp.errors import UnsupportedDraftTypeError, UpstreamError
from yahoo_fantasy_mcp.models import Draft, DraftPick


def build_draft_snapshot(raw_picks: list[dict], total_expected_picks: int) -> Draft:
    """Parse yahoo_fantasy_api's draft_results() output into a Draft.

    raw_picks is intentionally the *raw* dict list from client.py's
    fetch_draft_results_raw (see that module's docstring) — the 'cost'
    field, present only on auction picks, must still be intact here for
    the FR-013 guard below.
    """
    if any(p.get("cost") not in (None, "") for p in raw_picks):
        raise UnsupportedDraftTypeError()

    picks = [
        DraftPick(
            pick=p["pick"], round=p["round"], team_key=p["team_key"], player_id=p["player_id"]
        )
        for p in raw_picks
    ]
    picks.sort(key=lambda p: p.pick)

    seen_players: set[int] = set()
    for p in picks:
        if p.player_id in seen_players:
            raise UpstreamError(
                f"Duplicate player_id {p.player_id} across draft picks — "
                "likely a racy/corrupt read, refusing to silently deduplicate."
            )
        seen_players.add(p.player_id)

    retrieved_at = datetime.datetime.now(datetime.UTC)
    is_complete = len(picks) >= total_expected_picks and total_expected_picks > 0
    return Draft(picks=picks, retrieved_at=retrieved_at, is_complete=is_complete)
