"""FastMCP tool registration for the hosted multi-tenant server (spec 002, T026/T035/T041).

`build_server(store, config) -> FastMCP` is the whole product of this module:
a fresh, fully-wired FastMCP instance with every tool registered. Every tool
follows the same three-part shape, shown in full for two structurally
different cases below (an unscoped read, a league-scoped read) rather than a
generic decorator — usage recording needs the resolved `sub`, which isn't
known until identity resolution has already run inside the body, so a
wrap-from-outside decorator doesn't actually fit here:

    1. resolve identity (and league context, if this tool is league-scoped)
       — YahooFantasyError subclasses raised here are caught and translated,
       never left to become a raw traceback
    2. call the matching pure tool_* function from tools_read.py/tools_write.py
    3. record usage (outcome "ok" on success, "refused" on a caught
       YahooFantasyError) and return

No caching of identity/leagues/context across calls — everything is resolved
fresh, every request, which is what keeps two concurrent users' data from
ever crossing (FR-005). There is no module-level `mcp` singleton and no
`register_tools(existing_server, ...)` — spec 001's single-tenant
ServerContext/register_tools pair is gone (see session.py's module
docstring); its logic now lives, once, in tools_read.py/tools_write.py.
"""

from __future__ import annotations

import time
from typing import Any

from fastmcp import FastMCP
from fastmcp.server.dependencies import get_access_token
from mcp.types import ToolAnnotations

from yahoo_fantasy_mcp.confirm import hash_token
from yahoo_fantasy_mcp.errors import AuthRequiredError, InvalidConfirmationError, YahooFantasyError
from yahoo_fantasy_mcp.logging_utils import get_logger
from yahoo_fantasy_mcp.session import (
    RequestIdentity,
    YahooGameFactory,
    discover_leagues,
    resolve_identity,
    resolve_request_league_context,
)
from yahoo_fantasy_mcp.tools_read import (
    tool_check_auth,
    tool_get_available_players,
    tool_get_draft_results,
    tool_get_league_info,
    tool_get_roster,
    tool_get_standings,
    tool_list_leagues,
    tool_list_teams,
)
from yahoo_fantasy_mcp.tools_write import (
    UnapprovedLineupWriter,
    tool_confirm_action,
    tool_propose_set_lineup,
)

logger = get_logger(__name__)

READ_ANNOTATIONS = ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=True)
WRITE_ANNOTATIONS = ToolAnnotations(readOnlyHint=False, destructiveHint=True, openWorldHint=True)

# Roster spots per team. Only affects the is_complete flag on draft results
# (Draft.is_complete), not availability-derivation correctness (spec 001
# research). ServerConfig has no roster_size field (verified: dropped when
# the config was rewritten for multi-tenancy) — not yet per-server-
# configurable; add a ServerConfig field if a real deployment ever needs a
# non-16-spot league. YAGNI until then.
DEFAULT_ROSTER_SIZE = 16


def _total_expected_picks(client: Any) -> int:
    """num_teams * DEFAULT_ROSTER_SIZE — Task 3's total_expected_picks=0
    placeholder, finally closed here. Computed lazily, only for the two
    tools that need it (get_draft_results, get_available_players), each
    exactly once per call — never cached, since num_teams could change
    between requests."""
    return client.get_league_info().num_teams * DEFAULT_ROSTER_SIZE


def _current_roster_positions(client: Any, team_key: str) -> dict[int, str]:
    """{player_id: position}, freshly fetched, for the propose/confirm
    preview and drift-detection (FR-021).

    Known, disclosed gap: client.get_roster only surfaces each player's
    ELIGIBLE positions (models.Player.positions is a list, e.g.
    ["WR", "FLEX"]) — Yahoo's actual per-player *selected* lineup slot
    (its current starting slot vs "BN") is not currently surfaced by
    client.py/models.py, so positions[0] is used as a stand-in. This still
    catches the case drift-detection exists for — the roster's membership
    changing between propose and confirm (a player added/dropped) — but
    would not catch a pure lineup-slot shuffle with no membership change.
    Acceptable for this release because dispatch is unconditionally blocked
    by UnapprovedLineupWriter (T046/gate G3): no write reaches Yahoo on this
    data regardless. Closing this precisely needs client.py to surface
    Yahoo's selected_position, which is out of this task's scope.
    """
    roster = client.get_roster(team_key)
    return {p.player_id: (p.positions[0] if p.positions else "BN") for p in roster.players}


def _current_access_token() -> Any:
    """The raw, verified FastMCP AccessToken for this request — the single
    fetch point both `_current_identity` and `check_auth` build on, so
    neither has to call `get_access_token()` a second time.
    get_access_token().claims["sub"] and .token are populated on every
    request by YahooTokenVerifier.verify_token — see this task's plan
    header for the verified trace through OAuthProxy.load_access_token.
    """
    token = get_access_token()
    if token is None or not (token.claims or {}).get("sub"):
        raise AuthRequiredError()
    return token


def _current_identity(store: Any) -> RequestIdentity:
    """Resolve the calling user from the live FastMCP access token."""
    token = _current_access_token()
    return resolve_identity(store, token.token, token.claims["sub"])


def _record(store: Any, sub: str | None, tool_name: str, outcome: str) -> None:
    if sub is not None:
        record_tool_usage(store, sub, tool_name, outcome)


def build_server(store: Any, config: Any) -> FastMCP:
    """Build a fresh, fully-wired FastMCP server. Nothing here is shared
    across requests — see the module docstring."""
    mcp_server = FastMCP("yahoo-fantasy-mcp")
    game_factory = YahooGameFactory()

    @mcp_server.tool(
        name="check_auth",
        description=(
            "Report whether this session's Yahoo authorization is currently "
            "valid and how long it remains so. Never returns a token or any "
            "credential value."
        ),
        annotations=READ_ANNOTATIONS,
    )
    def check_auth() -> dict:
        sub = None
        try:
            token = _current_access_token()
            identity = resolve_identity(store, token.token, token.claims["sub"])
            sub = identity.sub
            # token.expires_at is a Unix timestamp, or None when Yahoo/FastMCP
            # gives no expiry (research: YahooTokenVerifier.verify_token
            # always sets expires_at=None today — Yahoo's userinfo endpoint
            # exposes no expiry). Report that honestly rather than fabricate
            # a number: a caller must be able to tell "unknown" from "3600".
            expires_in_seconds = (
                int(token.expires_at - time.time()) if token.expires_at is not None else None
            )
            result = tool_check_auth(identity, expires_in_seconds=expires_in_seconds)
            _record(store, sub, "check_auth", "ok")
            return result
        except YahooFantasyError as exc:
            _record(store, sub, "check_auth", "refused")
            return exc.to_dict()

    @mcp_server.tool(
        name="list_leagues",
        description="All Yahoo fantasy leagues the caller belongs to, across every sport.",
        annotations=READ_ANNOTATIONS,
    )
    def list_leagues() -> dict:
        sub = None
        try:
            identity = _current_identity(store)
            sub = identity.sub
            leagues = discover_leagues(game_factory, identity)
            result = tool_list_leagues(leagues)
            _record(store, sub, "list_leagues", "ok")
            return result
        except YahooFantasyError as exc:
            _record(store, sub, "list_leagues", "refused")
            return exc.to_dict()

    @mcp_server.tool(
        name="get_league_info",
        description="Identity and current draft status for one of the caller's leagues.",
        annotations=READ_ANNOTATIONS,
    )
    def get_league_info(league_key: str) -> dict:
        sub = None
        try:
            identity = _current_identity(store)
            sub = identity.sub
            leagues = discover_leagues(game_factory, identity)
            ctx = resolve_request_league_context(game_factory, identity, league_key, leagues)
            result = tool_get_league_info(ctx.client)
            _record(store, sub, "get_league_info", "ok")
            return result
        except YahooFantasyError as exc:
            _record(store, sub, "get_league_info", "refused")
            return exc.to_dict()

    @mcp_server.tool(
        name="list_teams",
        description="Teams in the league, flagging which one belongs to the caller.",
        annotations=READ_ANNOTATIONS,
    )
    def list_teams(league_key: str) -> dict:
        sub = None
        try:
            identity = _current_identity(store)
            sub = identity.sub
            leagues = discover_leagues(game_factory, identity)
            ctx = resolve_request_league_context(game_factory, identity, league_key, leagues)
            result = tool_list_teams(ctx.client)
            _record(store, sub, "list_teams", "ok")
            return result
        except YahooFantasyError as exc:
            _record(store, sub, "list_teams", "refused")
            return exc.to_dict()

    @mcp_server.tool(
        name="get_roster",
        description="A team's current roster, defaulting to the caller's own team.",
        annotations=READ_ANNOTATIONS,
    )
    def get_roster(league_key: str, team_key: str | None = None) -> dict:
        """Representative league-scoped read tool — every other league-scoped
        read tool (get_league_info, list_teams, get_standings,
        get_draft_results, get_available_players) follows this identical
        three-step shape, differing only in which discover_leagues -> ctx ->
        tool_get_*/tool_list_* call is made and which tool_* function's
        extra parameters (positions, etc.) get threaded through.
        """
        sub = None
        try:
            identity = _current_identity(store)
            sub = identity.sub
            leagues = discover_leagues(game_factory, identity)
            ctx = resolve_request_league_context(game_factory, identity, league_key, leagues)
            result = tool_get_roster(ctx.client, team_key or ctx.team_key)
            _record(store, sub, "get_roster", "ok")
            return result
        except YahooFantasyError as exc:
            _record(store, sub, "get_roster", "refused")
            return exc.to_dict()

    @mcp_server.tool(
        name="get_standings",
        description="Current standings for one of the caller's leagues.",
        annotations=READ_ANNOTATIONS,
    )
    def get_standings(league_key: str) -> dict:
        sub = None
        try:
            identity = _current_identity(store)
            sub = identity.sub
            leagues = discover_leagues(game_factory, identity)
            ctx = resolve_request_league_context(game_factory, identity, league_key, leagues)
            result = tool_get_standings(ctx.client)
            _record(store, sub, "get_standings", "ok")
            return result
        except YahooFantasyError as exc:
            _record(store, sub, "get_standings", "refused")
            return exc.to_dict()

    @mcp_server.tool(
        name="get_draft_results",
        description=(
            "Every draft pick made so far in the league, in order, with the "
            "pick/round/team/player and when this data was read. Empty "
            "before the draft starts, complete after it ends. Read-only — "
            "never submits a pick."
        ),
        annotations=READ_ANNOTATIONS,
    )
    def get_draft_results(league_key: str) -> dict:
        sub = None
        try:
            identity = _current_identity(store)
            sub = identity.sub
            leagues = discover_leagues(game_factory, identity)
            ctx = resolve_request_league_context(game_factory, identity, league_key, leagues)
            result = tool_get_draft_results(ctx.client, _total_expected_picks(ctx.client))
            _record(store, sub, "get_draft_results", "ok")
            return result
        except YahooFantasyError as exc:
            _record(store, sub, "get_draft_results", "refused")
            return exc.to_dict()

    @mcp_server.tool(
        name="get_available_players",
        description=(
            "Currently undrafted players in the league, derived from the "
            "same fresh draft read used by get_draft_results so the two "
            "never overlap. Optionally filter by position. Read-only; does "
            "not recommend or rank who to pick."
        ),
        annotations=READ_ANNOTATIONS,
    )
    def get_available_players(league_key: str, positions: list[str] | None = None) -> dict:
        sub = None
        try:
            identity = _current_identity(store)
            sub = identity.sub
            leagues = discover_leagues(game_factory, identity)
            ctx = resolve_request_league_context(game_factory, identity, league_key, leagues)
            result = tool_get_available_players(
                ctx.client, _total_expected_picks(ctx.client), positions
            )
            _record(store, sub, "get_available_players", "ok")
            return result
        except YahooFantasyError as exc:
            _record(store, sub, "get_available_players", "refused")
            return exc.to_dict()

    @mcp_server.tool(
        name="propose_set_lineup",
        description=(
            "Preview a lineup change for the caller's own team without "
            "applying it (FR-017). Returns a confirmation_token that must "
            "be passed to confirm_action to actually make the change — "
            "this call alone changes nothing upstream."
        ),
        annotations=READ_ANNOTATIONS,
    )
    def propose_set_lineup(league_key: str, week: int, changes: list[dict]) -> dict:
        """The write tools additionally need a live current_roster, fetched
        via ctx.client.get_roster(ctx.team_key) immediately before the call
        that uses it — never reused or cached between propose and confirm,
        so confirm's drift check (FR-021) sees the real, current state."""
        sub = None
        try:
            identity = _current_identity(store)
            sub = identity.sub
            leagues = discover_leagues(game_factory, identity)
            ctx = resolve_request_league_context(game_factory, identity, league_key, leagues)
            current_roster = _current_roster_positions(ctx.client, ctx.team_key)
            result = tool_propose_set_lineup(
                store,
                sub=sub,
                league_key=ctx.league_key,
                team_key=ctx.team_key,
                week=week,
                changes=changes,
                current_roster=current_roster,
                ttl_seconds=config.proposal_ttl_seconds,
                now=int(time.time()),
            )
            _record(store, sub, "propose_set_lineup", "ok")
            return result
        except YahooFantasyError as exc:
            _record(store, sub, "propose_set_lineup", "refused")
            return exc.to_dict()

    @mcp_server.tool(
        name="confirm_action",
        description=(
            "Apply a previously proposed action using the "
            "confirmation_token returned by the matching propose_* call. "
            "This is the only tool that writes anything to Yahoo. Fails if "
            "the token is unknown, already used, expired, or if the roster "
            "has changed since the action was proposed."
        ),
        annotations=WRITE_ANNOTATIONS,
    )
    def confirm_action(confirmation_token: str) -> dict:
        """No `force`/`skip_confirm` parameter exists anywhere on this tool
        or any other (FR-017) — confirmation_token is the only argument.
        The proposal itself (looked up by the token's hash) is what tells
        us which league/team this confirmation is scoped to; the caller
        never supplies league_key here, only identity-bearing tokens ever
        drive resolution (Principle: identity never comes from a tool
        argument)."""
        sub = None
        try:
            identity = _current_identity(store)
            sub = identity.sub
            row = store.get_proposal_by_hash(hash_token(confirmation_token))
            if row is None or row.sub != identity.sub:
                raise InvalidConfirmationError()
            leagues = discover_leagues(game_factory, identity)
            ctx = resolve_request_league_context(game_factory, identity, row.league_key, leagues)
            current_roster = _current_roster_positions(ctx.client, ctx.team_key)
            result = tool_confirm_action(
                store,
                sub=sub,
                token=confirmation_token,
                now=int(time.time()),
                current_roster=current_roster,
                lineup_writer=UnapprovedLineupWriter(),
                team=ctx.client,
            )
            _record(store, sub, "confirm_action", "ok")
            return result
        except YahooFantasyError as exc:
            _record(store, sub, "confirm_action", "refused")
            return exc.to_dict()

    return mcp_server


def record_tool_usage(store: Any, sub: str, tool_name: str, outcome: str) -> None:
    """Record one tool invocation (FR-028).

    Deliberately takes no arguments payload — see data-model.md. Never raises:
    a metering failure must not break a user's request.
    """
    try:
        store.record_usage(sub, tool_name, outcome)
    except Exception:  # noqa: BLE001 - metering is best-effort by design
        logger.warning("failed to record usage for tool %s", tool_name)
