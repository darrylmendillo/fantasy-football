"""Task 9b — annotation contract (FR-024, research R9).

Both Claude and ChatGPT drive their native confirmation UI from these
annotations, and OpenAI's Apps SDK requires all three for submission. They
are a UX layer over the server-side guarantee (Task 7), never a
replacement for it — which is why propose_* is non-destructive: the host
prompt belongs on the call that actually writes.
"""

from __future__ import annotations

import anyio
import pytest

from yahoo_fantasy_mcp.config import ServerConfig
from yahoo_fantasy_mcp.server import build_server
from yahoo_fantasy_mcp.store import Store

READ_ONLY_TOOLS = {
    "check_auth", "list_leagues", "get_league_info", "list_teams",
    "get_roster", "get_standings", "get_draft_results",
    "get_available_players", "propose_set_lineup",
}
DESTRUCTIVE_TOOLS = {"confirm_action"}


@pytest.fixture
def tools():
    config = ServerConfig(
        client_id="cid", client_secret="cs", public_base_url="https://example.test",
        port=8000, db_path=":memory:", proposal_ttl_seconds=300,
        yahoo_scope="fspt-w", poll_interval_seconds=5,
    )
    server = build_server(Store(":memory:"), config)
    return {t.name: t for t in anyio.run(server.list_tools)}


def test_every_tool_declares_all_three_hints(tools):
    for name, tool in tools.items():
        ann = tool.annotations
        assert ann is not None, f"{name} has no annotations"
        assert ann.readOnlyHint is not None, f"{name} missing readOnlyHint"
        assert ann.destructiveHint is not None, f"{name} missing destructiveHint"
        assert ann.openWorldHint is not None, f"{name} missing openWorldHint"


def test_read_and_propose_tools_are_non_destructive(tools):
    for name in READ_ONLY_TOOLS & set(tools):
        assert tools[name].annotations.readOnlyHint is True, name
        assert tools[name].annotations.destructiveHint is False, name


def test_confirm_action_is_destructive(tools):
    for name in DESTRUCTIVE_TOOLS & set(tools):
        assert tools[name].annotations.readOnlyHint is False, name
        assert tools[name].annotations.destructiveHint is True, name


def test_no_tool_offers_a_confirmation_bypass(tools):
    """FR-017: there is no single-call write path, by construction."""
    for name, tool in tools.items():
        params = set(getattr(tool, "parameters", {}).get("properties", {}))
        assert "force" not in params, name
        assert "skip_confirm" not in params, name


def test_all_nine_tools_are_registered(tools):
    expected = READ_ONLY_TOOLS | DESTRUCTIVE_TOOLS
    assert expected.issubset(set(tools)), sorted(expected - set(tools))
