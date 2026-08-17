"""Shared test fixtures: JSON loading + a YahooDataSource test double.

FixtureDataSource lets every test file exercise real parsing/derivation
logic against realistic yahoo_fantasy_api-shaped data with zero network
calls, per quickstart.md's "Automated test expectations" (fixtures, not
live calls).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> Any:
    with open(FIXTURES_DIR / name) as f:
        return json.load(f)


class FixtureDataSource:
    """A YahooDataSource backed by static JSON fixtures.

    `draft_fixture` selects which draft_*.json file fetch_draft_results_raw
    returns, so tests can swap draft state without touching anything else.
    """

    def __init__(self, draft_fixture: str = "draft_midraft.json") -> None:
        self.draft_fixture = draft_fixture
        self._teams = load_fixture("teams.json")
        self._standings = load_fixture("standings.json")
        self._roster = load_fixture("roster.json")
        self._player_details = load_fixture("player_details.json")

    def fetch_league_raw(self) -> dict[str, Any]:
        return {
            "league_key": "449.l.99001",
            "name": "Sunday Funday",
            "season": 2026,
            "num_teams": 4,
            "scoring_type": "head",
            "draft_status": "drafting",
        }

    def fetch_teams_raw(self) -> list[dict[str, Any]]:
        return self._teams

    def fetch_roster_raw(self, team_key: str) -> dict[str, Any]:
        assert team_key == self._roster["team_key"]
        return self._roster

    def fetch_standings_raw(self) -> list[dict[str, Any]]:
        return self._standings

    def fetch_draft_results_raw(self) -> list[dict[str, Any]]:
        return load_fixture(self.draft_fixture)

    def fetch_player_details_raw(self, player_ids: list[int]) -> dict[str, dict[str, Any]]:
        return {
            str(pid): self._player_details[str(pid)]
            for pid in player_ids
            if str(pid) in self._player_details
        }

    def fetch_player_universe_raw(self, positions: list[str]) -> dict[str, dict[str, Any]]:
        """The full player_details fixture pool, filtered to the requested
        positions — stands in for a one-time free_agents() seed (see
        YahooFantasyApiDataSource.fetch_player_universe_raw)."""
        return {
            pid: p
            for pid, p in self._player_details.items()
            if any(pos in p["eligible_positions"] for pos in positions)
        }


@pytest.fixture
def fixture_source() -> FixtureDataSource:
    return FixtureDataSource()


# ---------------------------------------------------------------------------
# spec 002 (hosted multi-tenant) fixtures — T004
#
# Offline by construction: no network, no live credentials, no real clock.
# Constitution v0.3.0 calls this the *mock-validated* tier: these prove our
# logic is self-consistent, NOT that Yahoo's contract was understood.
# ---------------------------------------------------------------------------

# Two distinct identities, for proving tenant isolation (FR-005). Any test
# that passes with only one of these is not testing isolation.
SUB_A = "yahoo-guid-aaaa1111"
SUB_B = "yahoo-guid-bbbb2222"


class FakeClock:
    """Controllable time source, so TTL/expiry logic is deterministic rather
    than sleep-dependent."""

    def __init__(self, now: int = 1_700_000_000) -> None:
        self._now = now

    def now(self) -> int:
        return self._now

    def advance(self, seconds: int) -> None:
        self._now += seconds


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def store():
    """In-memory application store, fresh per test."""
    from yahoo_fantasy_mcp.store import Store

    s = Store(":memory:")
    yield s
    s.close()


# Exposed as fixtures rather than importable constants: yahoo_oauth ships a
# top-level `tests` package into site-packages, so `from tests.conftest import
# ...` resolves to ITS module, not ours. Fixtures sidestep the collision.
@pytest.fixture
def sub_a() -> str:
    return SUB_A


@pytest.fixture
def sub_b() -> str:
    return SUB_B


@pytest.fixture
def anyio_backend() -> str:
    """Run @pytest.mark.anyio tests on asyncio only."""
    return "asyncio"
