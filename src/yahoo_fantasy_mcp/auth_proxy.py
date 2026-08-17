"""Yahoo OAuth verification and proxy construction (spec 002, T013/T014).

Yahoo access tokens are opaque, so verification means calling Yahoo and
seeing whether it answers. We use the OIDC userinfo endpoint because it
also returns `sub`, the stable per-user identity everything else keys on
(research R3/R4).
"""

from __future__ import annotations

import contextlib

import httpx
from fastmcp.server.auth.auth import AccessToken, TokenVerifier

from yahoo_fantasy_mcp.logging_utils import get_logger

logger = get_logger(__name__)

YAHOO_AUTHORIZE_URL = "https://api.login.yahoo.com/oauth2/request_auth"
YAHOO_TOKEN_URL = "https://api.login.yahoo.com/oauth2/get_token"
YAHOO_USERINFO_URL = "https://api.login.yahoo.com/openid/v1/userinfo"


class YahooTokenVerifier(TokenVerifier):
    """Validate an opaque Yahoo access token by calling userinfo."""

    def __init__(
        self,
        *,
        required_scopes: list[str] | None = None,
        timeout_seconds: int = 10,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        super().__init__(required_scopes=required_scopes)
        self.timeout_seconds = timeout_seconds
        self._http_client = http_client

    def __repr__(self) -> str:
        return f"YahooTokenVerifier(timeout_seconds={self.timeout_seconds})"

    async def verify_token(self, token: str) -> AccessToken | None:
        try:
            async with (
                contextlib.nullcontext(self._http_client)
                if self._http_client is not None
                else httpx.AsyncClient(timeout=self.timeout_seconds)
            ) as client:
                response = await client.get(
                    YAHOO_USERINFO_URL,
                    headers={"Authorization": f"Bearer {token}"},
                )
                if response.status_code != 200:
                    # Never log the body: it can echo the token back.
                    logger.debug("Yahoo token verification failed: %d", response.status_code)
                    return None
                data = response.json()
        except Exception as exc:  # noqa: BLE001 - any transport failure is a non-verification
            logger.debug("Yahoo token verification errored: %s", type(exc).__name__)
            return None

        sub = data.get("sub")
        if not sub:
            # Without a stable subject we cannot isolate tenants (FR-005),
            # so an unidentifiable token is treated as invalid.
            logger.debug("Yahoo userinfo returned no sub; rejecting token")
            return None

        # Yahoo's userinfo endpoint exposes no granted-scope info; access gating
        # happens at the tool layer via config.write_enabled, not MCP-level scopes.
        return AccessToken(
            token=token,
            client_id=str(sub),
            scopes=[],
            expires_at=None,
            claims={"sub": str(sub)},
        )
