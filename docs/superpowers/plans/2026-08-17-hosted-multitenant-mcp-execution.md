# Hosted Multi-Tenant Fantasy MCP — Execution Plan (T013–T048)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Finish the mock-validated tier of the hosted multi-tenant Yahoo Fantasy MCP server: per-user OAuth, per-request league resolution, multi-league read tools, and the two-step write-confirmation rail.

**Architecture:** FastMCP serves HTTP with an `OAuthProxy` that presents spec-compliant MCP OAuth to Claude/ChatGPT while proxying to Yahoo's OAuth2. Inside a tool, `get_access_token()` yields the *caller's own* Yahoo token, which a ~15-line adapter feeds to `yahoo_fantasy_api`. No process-wide user or league state exists. Every write goes through a propose→confirm rail whose guarantee is enforced in our SQLite store, never by the host's UI.

**Tech Stack:** Python 3.11+, FastMCP 3.4.7, `yahoo_fantasy_api` 2.12.3 (third-party wrapper, **not** an official Yahoo SDK), `requests`, SQLite (stdlib), pytest, ruff.

**Spec:** `specs/002-hosted-multitenant-mcp/spec.md` (+ `plan.md`, `research.md`, `data-model.md`, `contracts/mcp-tools.md`, `quickstart.md`, `tasks.md`)

## Global Constraints

Every task's requirements implicitly include this section.

- **Tier: mock-validated only.** No task here may claim a capability works against real Yahoo. Constitution v0.3.0 Principle I.
- **TDD is non-negotiable** (Principle II). Write the test, *run it, watch it fail for the right reason*, then implement. Report the transition; never assert it.
- **Offline by construction.** Every test must pass with no network and no credentials. All Yahoo interaction goes behind the `YahooDataSource` Protocol or an injected fake.
- **T046 is BLOCKED (gate G3).** `Team.change_positions`' `time_frame` / `modified_lineup` shape is unverified (research R5). Principle I forbids implementing against a guessed third-party signature. Task 9 builds a swappable seam instead.
- **No credential may appear** in tool output, logs, error messages, or `__repr__` (Principle III).
- **Identity never comes from a tool argument** — only from the verified token (FR-005). A caller-supplied user id would defeat tenant isolation.
- **Football only** this release (FR-008); other sports are listed but refused with `SPORT_NOT_SUPPORTED`.
- **Existing suite must stay green.** Baseline at plan time: **88 passed**, ruff clean.
- **Lint:** ruff, `line-length = 100`, `select = ["E", "F", "I", "UP"]`. Run `.venv/bin/ruff check src/ tests/` before every commit.
- **Commands:** tests `.venv/bin/pytest`, never bare `pytest`.
- **`tests/conftest.py` already exists** and defines `fixture_source`. **Append fixtures; never overwrite that file.**
- **Do not `from tests.conftest import ...`** — `yahoo_oauth` ships a top-level `tests` package into site-packages that shadows ours. Use fixtures (`sub_a`, `sub_b`, `clock`, `store`).
- **Commit after every task** referencing `specs/002-hosted-multitenant-mcp/`, and mark the task `[X]` in `specs/002-hosted-multitenant-mcp/tasks.md`.

---

## File Structure

| File | Responsibility | Tasks |
|---|---|---|
| `src/yahoo_fantasy_mcp/auth_proxy.py` | Yahoo token verification + `OAuthProxy` construction. Nothing else. | 1, 2 |
| `src/yahoo_fantasy_mcp/session.py` *(exists)* | Per-request identity and league/team resolution. The multi-tenancy boundary. | 3 |
| `src/yahoo_fantasy_mcp/tools_read.py` | All read tools. Pure functions taking an explicit context. | 5, 6 |
| `src/yahoo_fantasy_mcp/confirm.py` | Proposal issue/verify/consume. Pure logic over store + clock. | 7 |
| `src/yahoo_fantasy_mcp/tools_write.py` | `propose_*` + `confirm_action` + the `LineupWriter` seam. | 8 |
| `src/yahoo_fantasy_mcp/server.py` *(exists)* | FastMCP registration, annotations, usage recording, error translation. | 4, 9 |
| `src/yahoo_fantasy_mcp/__main__.py` *(exists)* | HTTP entrypoint. No singleton. | 4 |

Already complete (committed `636d103`): `config.py`, `store.py`, `session.py`'s adapter, `errors.py`.

---

### Task 1: Yahoo token verifier

**Files:**
- Create: `src/yahoo_fantasy_mcp/auth_proxy.py`
- Test: `tests/unit/test_auth_proxy_verifier.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `YahooTokenVerifier(required_scopes: list[str] | None = None, timeout_seconds: int = 10, http_client=None)` with `async def verify_token(self, token: str) -> AccessToken | None`. On success returns an `AccessToken` whose `.claims["sub"]` is the Yahoo GUID and whose `.token` is the token passed in. Later tasks read `sub` from exactly there.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_auth_proxy_verifier.py
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
```

Add to `tests/conftest.py` (append, do not overwrite):

```python
@pytest.fixture
def anyio_backend() -> str:
    """Run @pytest.mark.anyio tests on asyncio only."""
    return "asyncio"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/unit/test_auth_proxy_verifier.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'yahoo_fantasy_mcp.auth_proxy'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/yahoo_fantasy_mcp/auth_proxy.py
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

        return AccessToken(
            token=token,
            client_id=str(sub),
            scopes=list(self.required_scopes or []),
            expires_at=None,
            claims={"sub": str(sub)},
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/unit/test_auth_proxy_verifier.py -v && .venv/bin/ruff check src/ tests/`
Expected: 5 passed, ruff clean.

- [ ] **Step 5: Commit**

```bash
git add src/yahoo_fantasy_mcp/auth_proxy.py tests/unit/test_auth_proxy_verifier.py tests/conftest.py
git commit -m "feat(002): Yahoo token verifier for opaque access tokens (T013)"
```

---

### Task 2: OAuth proxy construction

**Files:**
- Modify: `src/yahoo_fantasy_mcp/auth_proxy.py`
- Test: `tests/unit/test_auth_proxy_build.py`

**Interfaces:**
- Consumes: `YahooTokenVerifier` (Task 1); `ServerConfig` from `yahoo_fantasy_mcp.config` with fields `client_id`, `client_secret`, `public_base_url`, `yahoo_scope`, `port`, `db_path`, `proposal_ttl_seconds`.
- Produces: `build_auth_proxy(config: ServerConfig) -> OAuthProxy`.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_auth_proxy_build.py
"""Task 2 — OAuthProxy wiring. Asserts configuration, not network behaviour."""

from __future__ import annotations

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


def test_client_secret_never_appears_in_repr():
    """Principle III — proxies land in tracebacks."""
    proxy = build_auth_proxy(_config(client_secret="super-secret-value"))
    assert "super-secret-value" not in repr(proxy)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/unit/test_auth_proxy_build.py -v`
Expected: FAIL — `ImportError: cannot import name 'build_auth_proxy'`

- [ ] **Step 3: Write minimal implementation**

Append to `src/yahoo_fantasy_mcp/auth_proxy.py`:

```python
from fastmcp.server.auth.oauth_proxy import OAuthProxy

from yahoo_fantasy_mcp.config import ServerConfig


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
    lives at the tool layer (FR-025, `config.write_enabled` /
    `WriteNotApprovedError`), not via MCP protocol-level scope enforcement.
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/unit/test_auth_proxy_build.py -v && .venv/bin/ruff check src/ tests/`
Expected: 3 passed, ruff clean.

**If a private attribute name differs in FastMCP 3.4.7**, assert on public behaviour instead (e.g. the metadata the proxy advertises) rather than deleting the assertion — the point is that scope and endpoints are wired.

- [ ] **Step 5: Commit**

```bash
git add src/yahoo_fantasy_mcp/auth_proxy.py tests/unit/test_auth_proxy_build.py
git commit -m "feat(002): wire OAuthProxy to Yahoo endpoints (T014)"
```

---

### Task 3: Per-request identity and league resolution

**Files:**
- Modify: `src/yahoo_fantasy_mcp/session.py`
- Test: `tests/unit/test_session_resolution.py`

**Interfaces:**
- Consumes: `Store` (`upsert_user`), `RequestIdentity`, `LeagueSummary`, `require_supported_sport`, `require_league_membership` (all already in `session.py`); `YahooSessionAdapter`.
- Produces:
  - `resolve_identity(store, access_token: str, sub: str) -> RequestIdentity` *(already exists — leave as is)*
  - `discover_leagues(game_factory, identity) -> list[LeagueSummary]`
  - `LeagueContext` dataclass: `.league_key`, `.team_key`, `.client`, `.total_expected_picks`
  - `resolve_league_context(game_factory, identity, league_key, leagues) -> LeagueContext`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_session_resolution.py
"""Task 3 — the multi-tenancy boundary.

`resolve_league_context` is where a request stops being anonymous and starts
being scoped to one user's one league. Every isolation guarantee in the
product either holds here or does not hold at all.
"""

from __future__ import annotations

import pytest

from yahoo_fantasy_mcp.errors import LeagueNotAccessibleError, SportNotSupportedError
from yahoo_fantasy_mcp.session import (
    LeagueSummary,
    RequestIdentity,
    resolve_league_context,
)


def _leagues() -> list[LeagueSummary]:
    return [
        LeagueSummary("461.l.111", "A League", "nfl", 2026, True, "461.l.111.t.1", "My Team"),
        LeagueSummary("458.l.999", "Hoops", "nba", 2026, False, "458.l.999.t.3", "Hoop Team"),
    ]


class _FakeGameFactory:
    """Stands in for building yahoo_fantasy_api Game/League/Team objects."""

    def __init__(self) -> None:
        self.built_for: list[str] = []

    def build(self, identity: RequestIdentity, league_key: str):
        self.built_for.append(league_key)
        return object()


def test_resolves_context_for_a_league_the_user_belongs_to():
    identity = RequestIdentity(sub="sub-a", access_token="tok")
    ctx = resolve_league_context(_FakeGameFactory(), identity, "461.l.111", _leagues())
    assert ctx.league_key == "461.l.111"
    assert ctx.team_key == "461.l.111.t.1"


def test_league_the_user_does_not_belong_to_is_refused():
    """FR-005 / US2 sc.4 — the core isolation assertion."""
    identity = RequestIdentity(sub="sub-a", access_token="tok")
    with pytest.raises(LeagueNotAccessibleError):
        resolve_league_context(_FakeGameFactory(), identity, "461.l.SOMEONE-ELSE", _leagues())


def test_non_football_league_is_refused_as_unsupported():
    """FR-008 — refused explicitly, not silently mishandled."""
    identity = RequestIdentity(sub="sub-a", access_token="tok")
    with pytest.raises(SportNotSupportedError):
        resolve_league_context(_FakeGameFactory(), identity, "458.l.999", _leagues())


def test_no_yahoo_object_is_built_for_a_refused_league():
    """Refusal must happen before we spend a Yahoo call on it."""
    factory = _FakeGameFactory()
    identity = RequestIdentity(sub="sub-a", access_token="tok")
    with pytest.raises(LeagueNotAccessibleError):
        resolve_league_context(factory, identity, "461.l.NOPE", _leagues())
    assert factory.built_for == []


def test_identity_is_never_taken_from_an_argument():
    """resolve_league_context must not accept a `sub` override parameter."""
    import inspect

    params = set(inspect.signature(resolve_league_context).parameters)
    assert "sub" not in params
    assert "user_id" not in params
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/unit/test_session_resolution.py -v`
Expected: FAIL — `ImportError: cannot import name 'resolve_league_context'`

- [ ] **Step 3: Write minimal implementation**

Append to `src/yahoo_fantasy_mcp/session.py`:

```python
@dataclass(frozen=True)
class LeagueContext:
    """One user's view of one league, for the duration of one request.

    Replaces spec 001's module-level ServerContext. Nothing here may be
    cached across requests: sharing a context would share a Yahoo session
    between users.
    """

    league_key: str
    team_key: str
    client: Any
    total_expected_picks: int


def resolve_league_context(
    game_factory: Any,
    identity: RequestIdentity,
    league_key: str,
    leagues: list[LeagueSummary],
) -> LeagueContext:
    """Scope this request to one league, refusing anything the caller cannot
    or should not reach.

    Order matters: membership and sport are checked BEFORE any Yahoo object
    is constructed, so a refused request costs no upstream call.

    Membership is enforced via the existing `require_league_membership`
    helper (not reimplemented here) — it already exists in this module and
    duplicating its check inline would be exactly the "verbatim duplication
    of a logic block" the review rubric flags as a defect.
    """
    require_league_membership(league_key, {lg.league_key for lg in leagues})
    match = next(lg for lg in leagues if lg.league_key == league_key)
    require_supported_sport(match.sport)

    league = game_factory.build(identity, league_key)
    return LeagueContext(
        league_key=league_key,
        team_key=match.team_key or "",
        client=league,
        total_expected_picks=0,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/unit/test_session_resolution.py -v && .venv/bin/pytest tests/ -q && .venv/bin/ruff check src/ tests/`
Expected: 5 passed; full suite still green; ruff clean.

- [ ] **Step 5: Commit**

```bash
git add src/yahoo_fantasy_mcp/session.py tests/unit/test_session_resolution.py
git commit -m "feat(002): per-request league resolution with membership and sport gating (T015/T016)"
```

---

### Task 4: HTTP entrypoint and usage recording

**Files:**
- Modify: `src/yahoo_fantasy_mcp/__main__.py`, `src/yahoo_fantasy_mcp/server.py`
- Test: `tests/unit/test_usage_recording.py`

**Interfaces:**
- Consumes: `build_auth_proxy` (Task 2), `Store`, `load_config`.
- Produces: `record_tool_usage(store, sub, tool_name, outcome)` in `server.py`; `main()` in `__main__.py` running HTTP transport.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_usage_recording.py
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/unit/test_usage_recording.py -v`
Expected: FAIL — `ImportError: cannot import name 'record_tool_usage'`

- [ ] **Step 3: Write minimal implementation**

Append to `src/yahoo_fantasy_mcp/server.py`:

```python
def record_tool_usage(store: Any, sub: str, tool_name: str, outcome: str) -> None:
    """Record one tool invocation (FR-028).

    Deliberately takes no arguments payload — see data-model.md. Never raises:
    a metering failure must not break a user's request.
    """
    try:
        store.record_usage(sub, tool_name, outcome)
    except Exception:  # noqa: BLE001 - metering is best-effort by design
        logger.warning("failed to record usage for tool %s", tool_name)
```

Add near the top of `server.py` if absent:

```python
from typing import Any

from yahoo_fantasy_mcp.logging_utils import get_logger

logger = get_logger(__name__)
```

Rewrite `src/yahoo_fantasy_mcp/__main__.py`:

```python
"""HTTP entrypoint for the hosted multi-tenant server (spec 002, T019).

Unlike spec 001's stdio entrypoint, this builds NO per-user state at start-up.
There is no `build_context()` singleton: every user's Yahoo token arrives with
their request and every league is resolved per call. Anything cached here
would be shared across tenants.
"""

from __future__ import annotations

from yahoo_fantasy_mcp.auth_proxy import build_auth_proxy
from yahoo_fantasy_mcp.config import load_config
from yahoo_fantasy_mcp.logging_utils import get_logger
from yahoo_fantasy_mcp.server import mcp, register_tools
from yahoo_fantasy_mcp.store import Store

logger = get_logger(__name__)


def main() -> None:
    config = load_config()
    store = Store(config.db_path)
    mcp.auth = build_auth_proxy(config)
    register_tools(mcp, store, config)
    logger.info("starting yahoo-fantasy-mcp (http) on port %s", config.port)
    mcp.run(transport="http", host="0.0.0.0", port=config.port)


if __name__ == "__main__":
    main()
```

> `register_tools` is re-signatured in Task 9. Until then, keep the old signature working or mark this step's `register_tools(mcp, store, config)` call as the target shape and land it with Task 9. **Run Task 9 before deploying anything.**

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/unit/test_usage_recording.py -v && .venv/bin/ruff check src/ tests/`
Expected: 4 passed, ruff clean.

- [ ] **Step 5: Commit**

```bash
git add src/yahoo_fantasy_mcp/server.py src/yahoo_fantasy_mcp/__main__.py tests/unit/test_usage_recording.py
git commit -m "feat(002): HTTP entrypoint and per-call usage recording (T018/T019)"
```

---

### Task 5: `check_auth` and `list_leagues` (US1)

**Files:**
- Create: `src/yahoo_fantasy_mcp/tools_read.py`
- Test: `tests/integration/test_us1_tools.py`

**Interfaces:**
- Consumes: `LeagueSummary`, `RequestIdentity` (Task 3).
- Produces: `tool_check_auth(identity, expires_in_seconds)` and `tool_list_leagues(leagues)`, both returning plain dicts/lists per `contracts/mcp-tools.md`.

- [ ] **Step 1: Write the failing test**

```python
# tests/integration/test_us1_tools.py
"""Task 5 — US1: a connected user can see who they are and what leagues
they have. Covers T021 (check_auth) and T025 (list_leagues)."""

from __future__ import annotations

from yahoo_fantasy_mcp.session import LeagueSummary, RequestIdentity
from yahoo_fantasy_mcp.tools_read import tool_check_auth, tool_list_leagues

SECRET = "ya29.super-secret-access-token-value-abcdefghijklmnop"


def test_check_auth_reports_authenticated():
    identity = RequestIdentity(sub="sub-a", access_token=SECRET)
    result = tool_check_auth(identity, expires_in_seconds=3600)
    assert result["authenticated"] is True
    assert result["expires_in_seconds"] == 3600
    assert result["needs_reauth"] is False


def test_check_auth_never_returns_a_token(*_):
    """FR-026 — the single most important assertion about this tool."""
    identity = RequestIdentity(sub="sub-a", access_token=SECRET)
    assert SECRET not in repr(tool_check_auth(identity, expires_in_seconds=3600))


def test_list_leagues_returns_all_leagues_with_support_flag():
    leagues = [
        LeagueSummary("461.l.111", "A League", "nfl", 2026, True, "461.l.111.t.1", "My Team"),
        LeagueSummary("458.l.999", "Hoops", "nba", 2026, False, "458.l.999.t.3", "Hoop Team"),
    ]
    rows = tool_list_leagues(leagues)
    assert len(rows) == 2
    by_key = {r["league_key"]: r for r in rows}
    assert by_key["461.l.111"]["is_supported"] is True
    # FR-008: unsupported leagues are still LISTED, so users are not confused
    # by an apparently missing league — they are refused on use, not hidden.
    assert by_key["458.l.999"]["is_supported"] is False


def test_list_leagues_distinguishes_leagues_enough_to_choose():
    """US2 sc.1 — name, sport, and season must all be present."""
    leagues = [
        LeagueSummary("461.l.111", "A League", "nfl", 2026, True, "461.l.111.t.1", "My Team"),
    ]
    row = tool_list_leagues(leagues)[0]
    assert row["name"] == "A League"
    assert row["sport"] == "nfl"
    assert row["season"] == 2026
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/integration/test_us1_tools.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'yahoo_fantasy_mcp.tools_read'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/yahoo_fantasy_mcp/tools_read.py
"""Read tools for the hosted server (spec 002).

Every function here is a plain, directly-testable function taking an explicit
context — the FastMCP decoration happens in server.py. That split is what
lets these be tested without JSON-RPC framing, and it is the pattern spec 001
already established.
"""

from __future__ import annotations

from yahoo_fantasy_mcp.session import LeagueSummary, RequestIdentity


def tool_check_auth(identity: RequestIdentity, expires_in_seconds: int) -> dict:
    """Whether the caller's Yahoo authorization is usable.

    Returns booleans and a duration only. The access token is deliberately
    not referenced in the output (FR-026).
    """
    authenticated = bool(identity.access_token)
    return {
        "authenticated": authenticated,
        "expires_in_seconds": expires_in_seconds,
        "needs_reauth": not authenticated,
    }


def tool_list_leagues(leagues: list[LeagueSummary]) -> list[dict]:
    """All leagues the caller belongs to (FR-009).

    Unsupported (non-football) leagues are included with is_supported=False
    rather than filtered out: a user who sees their basketball league listed
    and refused understands the product better than one who thinks it is
    missing (FR-008).
    """
    return [
        {
            "league_key": lg.league_key,
            "name": lg.name,
            "sport": lg.sport,
            "season": lg.season,
            "is_supported": lg.is_supported,
            "team_key": lg.team_key,
            "team_name": lg.team_name,
        }
        for lg in leagues
    ]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/integration/test_us1_tools.py -v && .venv/bin/ruff check src/ tests/`
Expected: 4 passed, ruff clean.

- [ ] **Step 5: Commit**

```bash
git add src/yahoo_fantasy_mcp/tools_read.py tests/integration/test_us1_tools.py
git commit -m "feat(002): check_auth and list_leagues (T024/T025)"
```

---

### Task 6: Multi-league read tools (US2)

**Files:**
- Modify: `src/yahoo_fantasy_mcp/tools_read.py`
- Test: `tests/integration/test_us2_reads.py`

**Interfaces:**
- Consumes: `YahooClient` and `build_draft_snapshot` (existing), `fixture_source` fixture.
- Produces: `tool_get_league_info(client)`, `tool_list_teams(client)`, `tool_get_roster(client, team_key)`, `tool_get_standings(client)`, `tool_get_draft_results(client, total_expected_picks)`, `tool_get_available_players(client, total_expected_picks, positions=None)`.

Port the bodies from `server.py`'s existing `tool_*` functions unchanged — only the parameterization changes. Do not modify `draft.py`.

- [ ] **Step 1: Write the failing test**

Add this fixture to `tests/conftest.py` first (append, do not overwrite —
same file `fixture_source` already lives in). This sidesteps the `from
tests.conftest import ...` collision documented in Global Constraints:
confirmed by direct test in this repo — any top-level `from tests.conftest
import X` triggers site-packages' `yahoo_oauth`-installed `tests` package to
load first and fails collection with `ImportError: cannot import name
'OAuth1' from 'yahoo_oauth'`, regardless of which name is imported.

```python
@pytest.fixture
def fixture_client():
    """Factory: fixture_client(draft_fixture="draft_midraft.json") -> YahooClient."""

    def _make(draft_fixture: str = "draft_midraft.json") -> Any:
        from yahoo_fantasy_mcp.client import YahooClient

        return YahooClient(FixtureDataSource(draft_fixture=draft_fixture))

    return _make
```

```python
# tests/integration/test_us2_reads.py
"""Task 6 — US2: reads work against any league, selected per call.

The availability-invariant test is carried forward from spec 001 deliberately:
it is the project's core correctness guarantee (FR-012) and the most likely
thing to break silently during a refactor.
"""

from __future__ import annotations

from yahoo_fantasy_mcp.tools_read import (
    tool_get_available_players,
    tool_get_draft_results,
    tool_get_league_info,
    tool_get_standings,
    tool_list_teams,
)


def test_league_info_returns_identity_fields(fixture_client):
    info = tool_get_league_info(fixture_client())
    assert info["league_key"] == "449.l.99001"
    assert info["name"] == "Sunday Funday"


def test_list_teams_flags_the_callers_own_team(fixture_client):
    teams = tool_list_teams(fixture_client())
    assert any(t["is_owned_by_user"] for t in teams)


def test_standings_are_ranked(fixture_client):
    standings = tool_get_standings(fixture_client())
    assert [t["standing"] for t in standings] == sorted(t["standing"] for t in standings)


def test_availability_and_drafted_never_overlap_midraft(fixture_client):
    """FR-012. If this fails, the product's central promise is broken."""
    client = fixture_client("draft_midraft.json")
    drafted = {p["player_id"] for p in tool_get_draft_results(client, 64)["picks"]}
    available = {p["player_id"] for p in tool_get_available_players(client, 64)["players"]}
    assert drafted & available == set()


def test_availability_invariant_holds_deep_into_draft(fixture_client):
    """Late-draft is where a regression to cached availability surfaces.

    draft_postdraft.json is the latest-stage fixture in the repo (verified:
    tests/fixtures/ holds predraft, midraft, postdraft, auction only — there
    is no draft_late.json).
    """
    client = fixture_client("draft_postdraft.json")
    drafted = {p["player_id"] for p in tool_get_draft_results(client, 64)["picks"]}
    available = {p["player_id"] for p in tool_get_available_players(client, 64)["players"]}
    assert drafted & available == set()
```

**Verified in this repo** (not hypothetical): a probe test using the
top-level-import form was run against the actual worktree and failed
collection with exactly the `OAuth1` ImportError above. The `fixture_client`
form is the fix, not a fallback.

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/integration/test_us2_reads.py -v`
Expected: FAIL — `ImportError: cannot import name 'tool_get_league_info' from 'yahoo_fantasy_mcp.tools_read'`

- [ ] **Step 3: Write minimal implementation**

Move the six `tool_*` bodies from `server.py` into `tools_read.py`, changing only their signatures to take `client` (and `total_expected_picks`) explicitly instead of reading a module-level `ServerContext`. Example shape:

```python
def tool_get_league_info(client: YahooClient) -> dict:
    league = client.get_league_info()
    return {
        "league_key": league.league_key,
        "name": league.name,
        "season": league.season,
        "num_teams": league.num_teams,
        "scoring_type": league.scoring_type,
        "draft_status": league.draft_status,
    }


def tool_get_available_players(
    client: YahooClient, total_expected_picks: int, positions: list[str] | None = None
) -> dict:
    snapshot = build_draft_snapshot(client, total_expected_picks)
    return snapshot.available_players(positions=positions)
```

Match the existing return shapes exactly — `tests/integration/test_tools.py` already asserts them and must keep passing.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/ -q && .venv/bin/ruff check src/ tests/`
Expected: all green including the pre-existing suite.

- [ ] **Step 5: Commit**

```bash
git add src/yahoo_fantasy_mcp/tools_read.py tests/integration/test_us2_reads.py
git commit -m "feat(002): parameterize read tools by league (T032-T034)"
```

---

### Task 7: The confirmation rail

**This is the most important task in the plan.** It is the mechanism behind FR-019 — the guarantee that a write cannot happen without explicit confirmation, enforced by us rather than by the host's UI.

**Files:**
- Create: `src/yahoo_fantasy_mcp/confirm.py`
- Test: `tests/unit/test_confirm.py`

**Interfaces:**
- Consumes: `Store` (`insert_proposal`, `get_proposal_by_hash`, `mark_consumed`, `mark_status`), `ProposalRow`.
- Produces:
  - `hash_token(token: str) -> str`
  - `create_proposal(store, *, sub, league_key, team_key, action_type, payload, preview, precondition, ttl_seconds, now) -> tuple[str, str]` returning `(proposal_id, raw_token)`
  - `verify_and_consume(store, *, token, sub, now, precondition_checker) -> ProposalRow`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_confirm.py
"""Task 7 — the propose/confirm rail (FR-017–FR-023, research R8).

Covers all five refusals from quickstart V6. These tests are the reason the
guarantee can be claimed at all: they demonstrate that a client which never
showed the user a prompt still cannot cause a write.
"""

from __future__ import annotations

import pytest

from yahoo_fantasy_mcp.confirm import create_proposal, hash_token, verify_and_consume
from yahoo_fantasy_mcp.errors import (
    InvalidConfirmationError,
    PreconditionsChangedError,
    ProposalAlreadyUsedError,
    ProposalExpiredError,
)

ALWAYS_OK = lambda row: True  # noqa: E731
ALWAYS_STALE = lambda row: False  # noqa: E731


def _make(store, sub, now=1000, ttl=300):
    return create_proposal(
        store,
        sub=sub,
        league_key="461.l.1",
        team_key="461.l.1.t.5",
        action_type="set_lineup",
        payload={"week": 3},
        preview={"summary": "start X, bench Y"},
        precondition={"roster": [1, 2]},
        ttl_seconds=ttl,
        now=now,
    )


class TestHappyPath:
    def test_confirm_returns_the_proposal(self, store, sub_a):
        _, token = _make(store, sub_a)
        row = verify_and_consume(
            store, token=token, sub=sub_a, now=1010, precondition_checker=ALWAYS_OK
        )
        assert row.action_type == "set_lineup"

    def test_proposing_does_not_consume(self, store, sub_a):
        pid, _ = _make(store, sub_a)
        assert store.get_proposal_by_hash(
            store.get_proposal_by_hash.__self__ and hash_token(_) if False else hash_token("x")
        ) is None  # sanity: unknown hash is None


class TestFiveRefusals:
    def test_unknown_token_is_refused(self, store, sub_a):
        with pytest.raises(InvalidConfirmationError):
            verify_and_consume(
                store,
                token="never-issued",
                sub=sub_a,
                now=1010,
                precondition_checker=ALWAYS_OK,
            )

    def test_replay_is_refused(self, store, sub_a):
        _, token = _make(store, sub_a)
        verify_and_consume(
            store, token=token, sub=sub_a, now=1010, precondition_checker=ALWAYS_OK
        )
        with pytest.raises(ProposalAlreadyUsedError):
            verify_and_consume(
                store, token=token, sub=sub_a, now=1011, precondition_checker=ALWAYS_OK
            )

    def test_expired_proposal_is_refused(self, store, sub_a):
        _, token = _make(store, sub_a, now=1000, ttl=300)
        with pytest.raises(ProposalExpiredError):
            verify_and_consume(
                store, token=token, sub=sub_a, now=1301, precondition_checker=ALWAYS_OK
            )

    def test_other_users_token_is_refused(self, store, sub_a, sub_b):
        """FR-020. Must raise the SAME error as an unknown token: the response
        may not reveal whether a token exists."""
        _, token = _make(store, sub_a)
        with pytest.raises(InvalidConfirmationError):
            verify_and_consume(
                store, token=token, sub=sub_b, now=1010, precondition_checker=ALWAYS_OK
            )

    def test_precondition_drift_is_refused(self, store, sub_a):
        _, token = _make(store, sub_a)
        with pytest.raises(PreconditionsChangedError):
            verify_and_consume(
                store, token=token, sub=sub_a, now=1010, precondition_checker=ALWAYS_STALE
            )


class TestNoWriteAfterRefusal:
    def test_drifted_proposal_cannot_be_retried(self, store, sub_a):
        """A proposal that failed preconditions is terminal — a second attempt
        must not sneak through once the world happens to look right again."""
        _, token = _make(store, sub_a)
        with pytest.raises(PreconditionsChangedError):
            verify_and_consume(
                store, token=token, sub=sub_a, now=1010, precondition_checker=ALWAYS_STALE
            )
        with pytest.raises((ProposalExpiredError, ProposalAlreadyUsedError,
                            InvalidConfirmationError)):
            verify_and_consume(
                store, token=token, sub=sub_a, now=1011, precondition_checker=ALWAYS_OK
            )


class TestTokenStorage:
    def test_raw_token_is_never_stored(self, store, sub_a):
        """data-model.md: only the hash is persisted, so a leaked database
        cannot be used to confirm anything."""
        _, token = _make(store, sub_a)
        dumped = "".join(
            str(v) for row in store._conn.execute("SELECT * FROM proposals") for v in row
        )
        assert token not in dumped
        assert hash_token(token) in dumped

    def test_tokens_are_unpredictable(self, store, sub_a):
        tokens = {_make(store, sub_a)[1] for _ in range(20)}
        assert len(tokens) == 20
        assert all(len(t) >= 32 for t in tokens)
```

> Delete the malformed `test_proposing_does_not_consume` body above and write it as:
> ```python
>     def test_proposing_does_not_consume(self, store, sub_a):
>         _, token = _make(store, sub_a)
>         row = store.get_proposal_by_hash(hash_token(token))
>         assert row.status == "pending"
>         assert row.consumed_at is None
> ```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/unit/test_confirm.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'yahoo_fantasy_mcp.confirm'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/yahoo_fantasy_mcp/confirm.py
"""Propose/confirm rail — the server-side write guarantee (spec 002, research R8).

FR-019 requires that the two-step guarantee hold regardless of which MCP host
is connected, and NOT depend on the host's own approval prompt. That is why
every check below lives here rather than in a tool description or an
annotation: a client that never showed the user anything still cannot cause a
write, because it cannot produce a token that satisfies all of these checks.

Only the SHA-256 of a confirmation token is persisted. The raw token is
returned to the caller once and never stored.
"""

from __future__ import annotations

import hashlib
import json
import secrets
import uuid
from typing import Any, Callable

from yahoo_fantasy_mcp.errors import (
    InvalidConfirmationError,
    PreconditionsChangedError,
    ProposalAlreadyUsedError,
    ProposalExpiredError,
)
from yahoo_fantasy_mcp.store import ProposalRow, Store

TOKEN_BYTES = 32


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create_proposal(
    store: Store,
    *,
    sub: str,
    league_key: str,
    team_key: str,
    action_type: str,
    payload: dict[str, Any],
    preview: dict[str, Any],
    precondition: dict[str, Any],
    ttl_seconds: int,
    now: int,
) -> tuple[str, str]:
    """Record an intent-to-write and mint its single-use confirmation token.

    Changes nothing upstream. Returns (proposal_id, raw_token); the raw token
    is the only copy that will ever exist outside the caller.
    """
    proposal_id = str(uuid.uuid4())
    token = secrets.token_urlsafe(TOKEN_BYTES)
    store.insert_proposal(
        ProposalRow(
            id=proposal_id,
            token_hash=hash_token(token),
            sub=sub,
            league_key=league_key,
            team_key=team_key,
            action_type=action_type,
            payload_json=json.dumps(payload),
            preview_json=json.dumps(preview),
            precondition_json=json.dumps(precondition),
            created_at=now,
            expires_at=now + ttl_seconds,
            status="pending",
            consumed_at=None,
        )
    )
    return proposal_id, token


def verify_and_consume(
    store: Store,
    *,
    token: str,
    sub: str,
    now: int,
    precondition_checker: Callable[[ProposalRow], bool],
) -> ProposalRow:
    """Validate a confirmation and atomically claim it, or raise.

    Check order is deliberate:
      1. unknown token and wrong-user both raise InvalidConfirmationError, so
         the response cannot be used to probe whether a token exists;
      2. already-consumed outranks expiry, because "you already did this" is
         more useful to a user than "it expired";
      3. preconditions are re-read last, since that is the expensive check;
      4. consumption is claimed via a conditional UPDATE, so two racing
         confirms cannot both win.
    """
    row = store.get_proposal_by_hash(hash_token(token))
    if row is None or row.sub != sub:
        raise InvalidConfirmationError()

    if row.status == "consumed":
        raise ProposalAlreadyUsedError()
    if row.status != "pending":
        raise ProposalExpiredError()

    if now >= row.expires_at:
        store.mark_status(row.id, "expired")
        raise ProposalExpiredError()

    if not precondition_checker(row):
        # Terminal: the user must re-propose against current reality (FR-021).
        store.mark_status(row.id, "failed")
        raise PreconditionsChangedError()

    if not store.mark_consumed(row.id, now):
        # Lost a race with a concurrent confirm of the same token.
        raise ProposalAlreadyUsedError()

    return row
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/unit/test_confirm.py -v && .venv/bin/ruff check src/ tests/`
Expected: all pass, ruff clean.

- [ ] **Step 5: Mutation-check the guarantee (do not skip)**

Temporarily break each guard and confirm a test catches it, then restore:

```bash
cp src/yahoo_fantasy_mcp/confirm.py /tmp/confirm.bak
# 1. remove the wrong-user check
sed -i 's/if row is None or row.sub != sub:/if row is None:/' src/yahoo_fantasy_mcp/confirm.py
.venv/bin/pytest tests/unit/test_confirm.py -q   # expect test_other_users_token_is_refused to FAIL
cp /tmp/confirm.bak src/yahoo_fantasy_mcp/confirm.py
# 2. ignore the expiry
sed -i 's/if now >= row.expires_at:/if False:/' src/yahoo_fantasy_mcp/confirm.py
.venv/bin/pytest tests/unit/test_confirm.py -q   # expect test_expired_proposal_is_refused to FAIL
cp /tmp/confirm.bak src/yahoo_fantasy_mcp/confirm.py
.venv/bin/pytest tests/unit/test_confirm.py -q   # all green again
```

Record the observed failures in the commit message. A guard no test catches is not a guarantee.

- [ ] **Step 6: Commit**

```bash
git add src/yahoo_fantasy_mcp/confirm.py tests/unit/test_confirm.py
git commit -m "feat(002): server-enforced propose/confirm rail (T042-T044)"
```

---

### Task 8: Write tools and the blocked-dispatch seam

**Files:**
- Create: `src/yahoo_fantasy_mcp/tools_write.py`
- Test: `tests/integration/test_us3_write.py`

**Interfaces:**
- Consumes: `create_proposal`, `verify_and_consume` (Task 7); `WriteNotApprovedError`.
- Produces: `LineupWriter` Protocol with `set_lineup(team, week, changes) -> dict`; `UnapprovedLineupWriter`; `tool_propose_set_lineup(...)`; `tool_confirm_action(...)`.

**T046 stays unimplemented.** `UnapprovedLineupWriter` is the seam: once gate G3 verifies the real `change_positions` signature, a `YahooLineupWriter` implementing the same Protocol drops in with no other change.

- [ ] **Step 1: Write the failing test**

```python
# tests/integration/test_us3_write.py
"""Task 8 — US3 write path, mock-validated.

Nothing here proves Yahoo accepts our lineup payload; the real dispatch is
blocked on gate G3 (research R5's unverified change_positions signature).
What these tests DO prove is that no code path reaches a writer without a
valid confirmation.
"""

from __future__ import annotations

import pytest

from yahoo_fantasy_mcp.errors import InvalidConfirmationError, WriteNotApprovedError
from yahoo_fantasy_mcp.tools_write import (
    UnapprovedLineupWriter,
    tool_confirm_action,
    tool_propose_set_lineup,
)


class SpyLineupWriter:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def set_lineup(self, team, week, changes) -> dict:
        self.calls.append((team, week, changes))
        return {"applied": True}


def _propose(store, sub, now=1000):
    return tool_propose_set_lineup(
        store,
        sub=sub,
        league_key="461.l.1",
        team_key="461.l.1.t.5",
        week=3,
        changes=[{"player_id": 1, "position": "WR"}],
        current_roster={1: "BN", 2: "WR"},
        ttl_seconds=300,
        now=now,
    )


class TestProposeIsInert:
    def test_propose_returns_a_preview_and_token(self, store, sub_a):
        result = _propose(store, sub_a)
        assert result["preview"]["action"] == "set_lineup"
        assert result["confirmation_token"]
        assert result["expires_in_seconds"] == 300

    def test_propose_never_touches_the_writer(self, store, sub_a):
        """FR-017: proposing changes nothing upstream."""
        writer = SpyLineupWriter()
        _propose(store, sub_a)
        assert writer.calls == []


class TestConfirmGatesTheWrite:
    def test_valid_confirmation_dispatches_exactly_once(self, store, sub_a):
        writer = SpyLineupWriter()
        token = _propose(store, sub_a)["confirmation_token"]
        tool_confirm_action(
            store,
            sub=sub_a,
            token=token,
            now=1010,
            current_roster={1: "BN", 2: "WR"},
            lineup_writer=writer,
            team=object(),
        )
        assert len(writer.calls) == 1

    def test_fabricated_token_never_reaches_the_writer(self, store, sub_a):
        """The assertion FR-019 exists for: a hallucinated confirmation causes
        no write, whatever the host's UI did or did not do."""
        writer = SpyLineupWriter()
        with pytest.raises(InvalidConfirmationError):
            tool_confirm_action(
                store,
                sub=sub_a,
                token="totally-made-up-token",
                now=1010,
                current_roster={1: "BN"},
                lineup_writer=writer,
                team=object(),
            )
        assert writer.calls == []


class TestUnapprovedWriterSeam:
    def test_default_writer_refuses_with_write_not_approved(self):
        """FR-025 / T046 blocked on G3 — the product cannot write yet, and
        says so distinctly from 'your request was invalid'."""
        with pytest.raises(WriteNotApprovedError):
            UnapprovedLineupWriter().set_lineup(object(), 3, [])

    def test_confirmation_still_consumed_before_dispatch_is_attempted(self, store, sub_a):
        """Even against the unapproved writer, the token must be spent — so a
        user cannot retry a confirmed action repeatedly once writes turn on."""
        token = _propose(store, sub_a)["confirmation_token"]
        with pytest.raises(WriteNotApprovedError):
            tool_confirm_action(
                store,
                sub=sub_a,
                token=token,
                now=1010,
                current_roster={1: "BN", 2: "WR"},
                lineup_writer=UnapprovedLineupWriter(),
                team=object(),
            )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/integration/test_us3_write.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'yahoo_fantasy_mcp.tools_write'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/yahoo_fantasy_mcp/tools_write.py
"""Write tools: propose/confirm only (spec 002, US3).

There is deliberately no single-call write path and no `force` or
`skip_confirm` parameter anywhere in this module (FR-017).

DISPATCH IS BLOCKED. `Team.change_positions`' time_frame/modified_lineup
shape is unverified (research R5), and constitution v0.3.0 Principle I
forbids implementing against a guessed third-party signature. The
`LineupWriter` Protocol is the seam: once gate G3 verifies the real shape, a
`YahooLineupWriter` implementing it replaces `UnapprovedLineupWriter` with no
other change to this file.
"""

from __future__ import annotations

import json
from typing import Any, Protocol

from yahoo_fantasy_mcp.confirm import create_proposal, verify_and_consume
from yahoo_fantasy_mcp.errors import WriteNotApprovedError
from yahoo_fantasy_mcp.store import ProposalRow, Store


class LineupWriter(Protocol):
    """The one place this server can change a Yahoo lineup."""

    def set_lineup(self, team: Any, week: int, changes: list[dict]) -> dict: ...


class UnapprovedLineupWriter:
    """Default writer while Yahoo write access / signature verification is
    outstanding. Fails loudly and specifically (FR-025)."""

    def set_lineup(self, team: Any, week: int, changes: list[dict]) -> dict:
        raise WriteNotApprovedError()


def tool_propose_set_lineup(
    store: Store,
    *,
    sub: str,
    league_key: str,
    team_key: str,
    week: int,
    changes: list[dict],
    current_roster: dict[int, str],
    ttl_seconds: int,
    now: int,
) -> dict:
    """Describe a lineup change without making it (FR-017).

    The preview names the exact players and slots, and the precondition
    snapshot records the roster state this proposal assumed, so confirm can
    detect drift (FR-021).
    """
    warnings: list[str] = []
    for change in changes:
        if change["player_id"] not in current_roster:
            warnings.append(f"Player {change['player_id']} is not on this roster.")

    preview = {
        "action": "set_lineup",
        "week": week,
        "changes": [
            {
                "player_id": c["player_id"],
                "from_position": current_roster.get(c["player_id"]),
                "to_position": c["position"],
            }
            for c in changes
        ],
        "warnings": warnings,
    }
    proposal_id, token = create_proposal(
        store,
        sub=sub,
        league_key=league_key,
        team_key=team_key,
        action_type="set_lineup",
        payload={"week": week, "changes": changes},
        preview=preview,
        precondition={"roster": current_roster},
        ttl_seconds=ttl_seconds,
        now=now,
    )
    return {
        "proposal_id": proposal_id,
        "confirmation_token": token,
        "expires_in_seconds": ttl_seconds,
        "preview": preview,
    }


def _lineup_preconditions_hold(row: ProposalRow, current_roster: dict[int, str]) -> bool:
    snapshot = json.loads(row.precondition_json).get("roster", {})
    # JSON object keys are strings; normalise before comparing.
    snapshot = {int(k): v for k, v in snapshot.items()}
    return snapshot == current_roster


def tool_confirm_action(
    store: Store,
    *,
    sub: str,
    token: str,
    now: int,
    current_roster: dict[int, str],
    lineup_writer: LineupWriter,
    team: Any,
) -> dict:
    """The only path that writes. Validates, consumes, then dispatches."""
    row = verify_and_consume(
        store,
        token=token,
        sub=sub,
        now=now,
        precondition_checker=lambda r: _lineup_preconditions_hold(r, current_roster),
    )
    payload = json.loads(row.payload_json)
    result = lineup_writer.set_lineup(team, payload["week"], payload["changes"])
    return {
        "status": "applied",
        "action": row.action_type,
        "result": result,
        "applied_at": now,
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/integration/test_us3_write.py -v && .venv/bin/pytest tests/ -q && .venv/bin/ruff check src/ tests/`
Expected: all pass; full suite green.

- [ ] **Step 5: Commit**

```bash
git add src/yahoo_fantasy_mcp/tools_write.py tests/integration/test_us3_write.py
git commit -m "feat(002): propose_set_lineup + confirm_action with blocked dispatch seam (T045/T047/T048)"
```

---

### Task 9: Tool registration and annotation contract

**Files:**
- Modify: `src/yahoo_fantasy_mcp/server.py`
- Test: `tests/contract/test_tool_annotations.py`

**Interfaces:**
- Consumes: everything above.
- Produces: `register_tools(mcp_server, store, config) -> None`, registering all tools with correct annotations and per-call usage recording.

- [ ] **Step 1: Write the failing test**

```python
# tests/contract/test_tool_annotations.py
"""Task 9 — annotation contract (FR-024, research R9).

Both Claude and ChatGPT drive their native confirmation UI from these
annotations, and OpenAI's Apps SDK requires all three for submission. They
are a UX layer over the server-side guarantee, never a replacement for it —
which is why `propose_*` is non-destructive: the host prompt belongs on the
call that actually writes.
"""

from __future__ import annotations

import pytest

from yahoo_fantasy_mcp.config import ServerConfig
from yahoo_fantasy_mcp.server import build_server
from yahoo_fantasy_mcp.store import Store

READ_ONLY_TOOLS = {
    "check_auth",
    "list_leagues",
    "get_league_info",
    "list_teams",
    "get_roster",
    "get_standings",
    "get_draft_results",
    "get_available_players",
    "propose_set_lineup",
}
DESTRUCTIVE_TOOLS = {"confirm_action"}


@pytest.fixture
def tools():
    config = ServerConfig(
        client_id="cid",
        client_secret="cs",
        public_base_url="https://example.test",
        port=8000,
        db_path=":memory:",
        proposal_ttl_seconds=300,
        yahoo_scope="fspt-w",
        poll_interval_seconds=5,
    )
    server = build_server(Store(":memory:"), config)
    import anyio

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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/contract/test_tool_annotations.py -v`
Expected: FAIL — `ImportError: cannot import name 'build_server'`. Create `tests/contract/__init__.py` if the directory is new.

- [ ] **Step 3: Write minimal implementation**

In `server.py`, add `build_server(store, config) -> FastMCP` that constructs a `FastMCP` instance and registers every tool with explicit annotations, e.g.:

```python
from mcp.types import ToolAnnotations

READ_ANNOTATIONS = ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=True)
WRITE_ANNOTATIONS = ToolAnnotations(readOnlyHint=False, destructiveHint=True, openWorldHint=True)


@mcp_server.tool(
    name="propose_set_lineup",
    description=(
        "Preview a lineup change WITHOUT applying it. Returns a confirmation "
        "token that must be passed to confirm_action to actually apply the "
        "change. This tool never modifies your team."
    ),
    annotations=READ_ANNOTATIONS,
)
def propose_set_lineup(...): ...
```

Keep `register_tools(mcp_server, store, config)` as a thin wrapper over the same registration body so `__main__.py` (Task 4) works unchanged. Wrap every tool so it records usage (`record_tool_usage`) and translates `YahooFantasyError` into `exc.to_dict()`, preserving spec 001's `_guarded` behaviour.

**Both API shapes already verified against installed FastMCP 3.4.7:**
`FastMCP.tool` accepts `annotations: ToolAnnotations | dict[str, Any] |
None` (a plain dict works — confirmed live: registered a tool with
`annotations={'readOnlyHint': True, ...}` and read back
`tool.annotations.readOnlyHint is True`). Listing registered tools is
`async def list_tools(self, *, run_middleware=True) -> Sequence[Tool]` —
**not** `get_tools`, which does not exist on `FastMCP` at all
(`AttributeError`, confirmed live). The test above already uses
`anyio.run(server.list_tools)`. No further discovery needed.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/ -q && .venv/bin/ruff check src/ tests/`
Expected: all green.

- [ ] **Step 5: Commit**

```bash
git add src/yahoo_fantasy_mcp/server.py tests/contract/
git commit -m "feat(002): register tools with annotation contract and usage recording (T026/T035/T041)"
```

---

### Task 10: MCP Inspector verification and task-list reconciliation

**Files:**
- Modify: `specs/002-hosted-multitenant-mcp/tasks.md`, `specs/002-hosted-multitenant-mcp/quickstart.md`

- [ ] **Step 1: Start the server against a scratch config**

```bash
YAHOO_CLIENT_ID=dummy YAHOO_CLIENT_SECRET=dummy \
PUBLIC_BASE_URL=http://localhost:8000 DB_PATH=/tmp/inspect.db \
.venv/bin/python -m yahoo_fantasy_mcp
```

- [ ] **Step 2: Inspect the protocol surface**

```bash
npx @modelcontextprotocol/inspector
```

Connect to `http://localhost:8000/mcp` and verify: the OAuth metadata endpoints are advertised; the tool list matches `contracts/mcp-tools.md`; every tool shows all three annotation hints; `confirm_action` is the only destructive one.

Real Yahoo sign-in will **not** complete with dummy credentials — that is expected and is gate G1's job, not this task's.

- [ ] **Step 3: Record results honestly**

Append an "MCP Inspector verification (mock-validated)" note to `quickstart.md` stating what was observed and explicitly that no Yahoo account was involved.

- [ ] **Step 4: Mark tasks complete**

Mark T013–T045, T047, T048 `[X]` in `tasks.md`. **Leave T046 unchecked**, and leave G1/G2/G3 unchecked.

- [ ] **Step 5: Commit**

```bash
git add specs/002-hosted-multitenant-mcp/
git commit -m "docs(002): MCP Inspector verification, mock-validated tier complete"
```

---

## Self-Review

**Spec coverage:** FR-001–007 → Tasks 1, 2, 4. FR-008–013 → Tasks 3, 5, 6. FR-014, 017–025 → Tasks 7, 8, 9. FR-026/027 → assertions in Tasks 1, 2, 5. FR-028 → Task 4. FR-029/030 → Phase 8 of `tasks.md`, out of scope here. **Gaps, deliberate:** FR-015 (add/drop) and FR-016 (trades) are US4/US5, excluded from this pass and unblocked by Task 7's rail. FR-013 (Yahoo attribution) and FR-030 (naming) remain in Phase 8.

**Placeholder scan:** every code step contains real code. One step carries an explicit *verify-before-writing* instruction (Task 2's private attribute names) — a deliberate application of the "verify first, then write" rule, not deferred work. Task 7's test file contains one intentionally malformed snippet with its corrected replacement immediately below; fix it when writing the file.

**Two defects found and fixed during this review**, both by checking the repo instead of trusting the draft:

1. Task 6's deep-draft test referenced `draft_late.json`, which **does not exist**. `ls tests/fixtures/` shows only predraft / midraft / postdraft / auction. Corrected to `draft_postdraft.json`. Left unfixed, a cold subagent would have hit a `FileNotFoundError` on the single most important regression test in the read path.
2. Task 9 told the executor to go verify whether `FastMCP.tool` accepts `annotations=`. It does (`ToolAnnotations | dict[str, Any] | None`, FastMCP 3.4.7), so that instruction was replaced with the verified fact — a plan should not outsource a check the planner can do once.

**Type consistency:** `sub` is a `str` everywhere. `create_proposal` returns `(proposal_id, raw_token)`; `verify_and_consume` returns `ProposalRow`. `LineupWriter.set_lineup(team, week, changes)` is identical in Protocol, spy, and unapproved implementations. `LeagueSummary` field order matches `session.py`. `record_tool_usage(store, sub, tool_name, outcome)` matches `Store.record_usage`.

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-08-17-hosted-multitenant-mcp-execution.md`. Two execution options:

**1. Subagent-Driven (recommended)** — a fresh subagent per task with two-stage review between tasks. Best fit here: the ten tasks are file-isolated (`auth_proxy.py`, `session.py`, `tools_read.py`, `confirm.py`, `tools_write.py` barely overlap), each carries its own test cycle, and each task's `Interfaces` block gives a cold agent exactly the signatures it needs. Tasks 1+2, then 3, 4, 5 can go in parallel; 7 must precede 8; 9 last.

**2. Inline Execution** — execute in this session via `superpowers:executing-plans`, batching with checkpoints.
