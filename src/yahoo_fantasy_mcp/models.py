"""Domain entities per specs/001-yahoo-fantasy-mcp/data-model.md.

These are intentionally decoupled from Yahoo/yahoo_fantasy_api's raw shapes —
parsing quirks stay in client.py, not here.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field


@dataclass(frozen=True)
class League:
    league_key: str
    name: str
    season: int
    num_teams: int
    scoring_type: str
    draft_status: str  # "predraft" | "drafting" | "postdraft"


@dataclass(frozen=True)
class Team:
    team_key: str
    name: str
    is_owned_by_user: bool
    standing: int | None = None


@dataclass(frozen=True)
class Player:
    """Player identity + metadata only.

    Deliberately has NO availability/drafted flag — see the Availability
    Invariant in data-model.md. Storing that as state would reintroduce the
    exact stale-cache bug identified in research.md R3.
    """

    player_id: int
    name: str
    positions: list[str]
    nfl_team: str
    percent_owned: int | None = None
    average_pick: float | None = None


@dataclass(frozen=True)
class DraftPick:
    """One selection. Snake drafts only (FR-013) — no 'cost' field.

    Auction detection happens in draft.py by checking for a 'cost' key on
    the *raw* upstream dict before construction; a DraftPick never carries
    one, so downstream code cannot accidentally treat auction data as valid.
    """

    pick: int
    round: int
    team_key: str
    player_id: int


@dataclass(frozen=True)
class Draft:
    """A draft snapshot. retrieved_at is REQUIRED (no default) — FR-009's
    freshness bound cannot be enforced by a caller without it."""

    picks: list[DraftPick]
    retrieved_at: datetime.datetime
    is_complete: bool

    def drafted_player_ids(self) -> set[int]:
        return {p.player_id for p in self.picks}


@dataclass(frozen=True)
class Roster:
    team_key: str
    players: list[Player] = field(default_factory=list)
