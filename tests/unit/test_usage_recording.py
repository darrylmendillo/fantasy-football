"""Task 4 — usage metering (FR-028).

The tier column and this log exist from day one so monetization can be added
later without touching auth or data. Nothing enforces a limit in this release.
"""

from __future__ import annotations

from yahoo_fantasy_mcp.server import record_tool_usage


def test_successful_call_is_recorded(store, sub_a):
    record_tool_usage(store, sub_a, "get_roster", "ok")
    assert store.usage_count(sub_a) == 1


def test_refusals_are_recorded_too(store, sub_a):
    record_tool_usage(store, sub_a, "get_roster", "refused")
    assert store.usage_count(sub_a) == 1


def test_usage_is_attributed_per_user(store, sub_a, sub_b):
    record_tool_usage(store, sub_a, "get_roster", "ok")
    record_tool_usage(store, sub_b, "get_roster", "ok")
    record_tool_usage(store, sub_b, "get_roster", "ok")
    assert store.usage_count(sub_a) == 1
    assert store.usage_count(sub_b) == 2


def test_arguments_are_not_recorded(store, sub_a):
    """data-model.md: tool name and outcome only. Arguments carry roster and
    league detail; this table is for metering, not surveillance."""
    import inspect

    params = set(inspect.signature(record_tool_usage).parameters)
    assert "args" not in params
    assert "arguments" not in params
    assert "payload" not in params
