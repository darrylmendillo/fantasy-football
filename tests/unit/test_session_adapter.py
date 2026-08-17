"""T007 — the adapter that lets yahoo_fantasy_api use a FastMCP-managed token.

Two assertions carry real weight:

1. `.session` sends the Bearer header — this is the ONLY attribute
   yahoo_fantasy_api's YHandler touches for requests (research R6, verified at
   yhandler.py:76,88,114,141).
2. The adapter must NOT expose `refresh_access_token`. YHandler guards its own
   refresh path with `hasattr(self.sc, 'refresh_access_token')` (yhandler.py:60).
   FastMCP has already refreshed the token before we see it (research R2), so
   exposing that attribute would let two refresh mechanisms race on one
   credential. The absence is deliberate, not an oversight — hence a test.
"""

from __future__ import annotations

from yahoo_fantasy_mcp.session import YahooSessionAdapter


class TestBearerHeader:
    def test_session_carries_the_bearer_token(self) -> None:
        adapter = YahooSessionAdapter("tok-abc123")
        assert adapter.session.headers["Authorization"] == "Bearer tok-abc123"

    def test_distinct_tokens_produce_distinct_sessions(self) -> None:
        """Tenant isolation starts here: two users' adapters must never share
        a session object or a header."""
        a = YahooSessionAdapter("tok-user-a")
        b = YahooSessionAdapter("tok-user-b")
        assert a.session is not b.session
        assert a.session.headers["Authorization"] != b.session.headers["Authorization"]


class TestNoDoubleRefresh:
    def test_adapter_has_no_refresh_access_token(self) -> None:
        """If this ever fails, yahoo_fantasy_api will start refreshing tokens
        behind FastMCP's back. See module docstring."""
        adapter = YahooSessionAdapter("tok-abc123")
        assert not hasattr(adapter, "refresh_access_token")


class TestNoTokenLeakage:
    def test_repr_does_not_expose_the_token(self) -> None:
        """Principle III — adapters end up in tracebacks."""
        adapter = YahooSessionAdapter("super-secret-token-value")
        assert "super-secret-token-value" not in repr(adapter)
