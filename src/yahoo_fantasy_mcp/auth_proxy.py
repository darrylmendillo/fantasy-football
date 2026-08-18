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
from fastmcp.server.auth.oauth_proxy import OAuthProxy

from yahoo_fantasy_mcp.config import ServerConfig
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
        # happens at the tool layer, not MCP-level scopes. Today that gate is
        # the hardcoded UnapprovedLineupWriter seam in server.py (T046/gate
        # G3), not config.write_enabled — see build_auth_proxy's docstring
        # below for the full picture.
        return AccessToken(
            token=token,
            client_id=str(sub),
            scopes=[],
            expires_at=None,
            claims={"sub": str(sub)},
        )


def build_auth_proxy(config: ServerConfig) -> OAuthProxy:
    """Present spec-compliant MCP OAuth to clients, proxy to Yahoo underneath.

    Yahoo is a non-DCR provider with a fixed client id/secret, which is
    exactly the case `OAuthProxy` exists for (research R1/R2). Consent is
    left at its default (always shown) — this server can write to a user's
    team, so silently re-approving is the wrong trade.

    `YahooTokenVerifier` is deliberately constructed with NO `required_scopes`
    (ruling recorded in the SDD ledger, Task 1 review, Finding A). Passing
    `required_scopes` here would propagate to `OAuthProxy.required_scopes`
    (`proxy.py:403`) and from there into `RequireAuthMiddleware`, which the
    fastmcp HTTP transport mounts on every route (`fastmcp/server/http.py`)
    to gate requests on `required_scope in auth_credentials.scopes`. Yahoo's
    userinfo endpoint exposes no granted-scope information, so the verifier
    cannot honestly report a token's real scope — Task 1's `verify_token`
    returns `scopes=[]` for exactly this reason. Configuring a non-empty
    `required_scopes` against a verifier that always returns `[]` would
    reject every single authenticated request. `valid_scopes` below is a
    different, legitimate mechanism (what scope MCP clients request during
    OAuth consent/DCR) and is unaffected by this. Real write-vs-read gating
    lives at the tool layer (FR-025), not via MCP protocol-level scope
    enforcement — but as of this writing that gate is the hardcoded
    `UnapprovedLineupWriter` in server.py's `confirm_action` closure
    (`WriteNotApprovedError` unconditionally, regardless of config), NOT
    `config.write_enabled`. Nothing in `src/` currently reads
    `config.write_enabled`; it exists as a forward-looking property for when
    a real `LineupWriter` implementation lands (see tools_write.py's module
    docstring — dispatch is blocked on gate G3) and selecting between
    writers based on granted scope becomes meaningful.
    """
    scopes = [s for s in config.yahoo_scope.split() if s]
    return OAuthProxy(
        upstream_authorization_endpoint=YAHOO_AUTHORIZE_URL,
        upstream_token_endpoint=YAHOO_TOKEN_URL,
        upstream_client_id=config.client_id,
        upstream_client_secret=config.client_secret,
        token_verifier=YahooTokenVerifier(),
        base_url=config.public_base_url,
        valid_scopes=scopes,
        # Yahoo supports PKCE; forwarding it is strictly safer.
        forward_pkce=True,
    )
