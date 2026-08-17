"""Task 1 — verifying an opaque Yahoo access token.

Yahoo access tokens are opaque: no JWKS to validate against and no RFC 7662
introspection endpoint, so `JWTVerifier`/`IntrospectionTokenVerifier` do not
apply (research R3). We verify by calling Yahoo's OIDC userinfo endpoint,
which doubles as how we learn the stable `sub` (research R4).

Modelled on FastMCP's own GitHubTokenVerifier, which solves the same problem.
"""

from __future__ import annotations

import httpx
import pytest

from yahoo_fantasy_mcp.auth_proxy import YahooTokenVerifier


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


@pytest.mark.anyio
async def test_valid_token_yields_sub_claim():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer good-token"
        return httpx.Response(200, json={"sub": "GUID123", "name": "Test User"})

    verifier = YahooTokenVerifier(http_client=_client(handler))
    token = await verifier.verify_token("good-token")

    assert token is not None
    assert token.claims["sub"] == "GUID123"
    assert token.token == "good-token"


@pytest.mark.anyio
async def test_rejected_token_returns_none():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": "invalid_token"})

    verifier = YahooTokenVerifier(http_client=_client(handler))
    assert await verifier.verify_token("bad-token") is None


@pytest.mark.anyio
async def test_missing_sub_is_rejected():
    """No stable identity means no tenant isolation, so this must not pass."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"name": "No Sub Here"})

    verifier = YahooTokenVerifier(http_client=_client(handler))
    assert await verifier.verify_token("weird-token") is None


@pytest.mark.anyio
async def test_network_failure_returns_none_not_exception():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom")

    verifier = YahooTokenVerifier(http_client=_client(handler))
    assert await verifier.verify_token("any-token") is None


@pytest.mark.anyio
async def test_token_value_never_appears_in_repr():
    verifier = YahooTokenVerifier()
    assert "secret" not in repr(verifier)
