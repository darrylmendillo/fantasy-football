"""Task 2 — OAuthProxy wiring. Asserts configuration, not network behaviour."""

from __future__ import annotations

from pydantic import SecretStr

from yahoo_fantasy_mcp.auth_proxy import (
    YAHOO_AUTHORIZE_URL,
    YAHOO_TOKEN_URL,
    build_auth_proxy,
)
from yahoo_fantasy_mcp.config import ServerConfig


def _config(**kw) -> ServerConfig:
    defaults = dict(
        client_id="cid",
        client_secret="csecret",
        public_base_url="https://example.test",
        port=8000,
        db_path=":memory:",
        proposal_ttl_seconds=300,
        yahoo_scope="fspt-w",
        poll_interval_seconds=5,
    )
    defaults.update(kw)
    return ServerConfig(**defaults)


def test_proxy_targets_yahoo_endpoints():
    proxy = build_auth_proxy(_config())
    assert proxy._upstream_authorization_endpoint == YAHOO_AUTHORIZE_URL
    assert proxy._upstream_token_endpoint == YAHOO_TOKEN_URL


def test_configured_scope_is_advertised():
    proxy = build_auth_proxy(_config(yahoo_scope="fspt-r"))
    assert "fspt-r" in proxy.client_registration_options.valid_scopes


def test_client_secret_is_never_stored_as_plaintext():
    """Principle III — client secret wrapped in SecretStr to prevent exposure in logs."""
    proxy = build_auth_proxy(_config(client_secret="super-secret-value"))
    assert isinstance(proxy._upstream_client_secret, SecretStr)
    assert "super-secret-value" not in str(proxy._upstream_client_secret)
    assert "super-secret-value" not in repr(proxy._upstream_client_secret)
