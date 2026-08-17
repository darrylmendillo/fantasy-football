# Phase 0 Research: Hosted Multi-Tenant Fantasy MCP Server

**Feature**: `002-hosted-multitenant-mcp` | **Date**: 2026-08-17

Every decision below was verified against installed package source or vendor
documentation. Where something is *not* yet verified, it says so explicitly
(Principle IV — no claiming what hasn't been checked).

**Dependency provenance**: the Yahoo-facing packages (`yahoo_fantasy_api`,
`yahoo_oauth`) are third-party community wrappers — Yahoo ships no official
Python SDK. See R5.

---

## R1 — Yahoo OAuth2 endpoints and scopes

**Decision**: Configure the OAuth proxy against Yahoo's OAuth2 endpoints:

| Purpose | URL |
|---|---|
| Authorization | `https://api.login.yahoo.com/oauth2/request_auth` |
| Token | `https://api.login.yahoo.com/oauth2/get_token` |

Scope: **`fspt-w`** (Fantasy Sports read/write). `fspt-r` is the read-only
counterpart and is the correct value if only read approval lands.

**Rationale**: These are Yahoo's documented OAuth 2.0 authorization-code
endpoints. The scope must match what Yahoo approves for the operator's Client
ID — requesting `fspt-w` without write approval will fail at consent or at
call time, which is precisely why FR-025 requires a clear error for that case.

**Alternatives considered**: Yahoo's OIDC flow (`openid` scope) — needed only
if we want identity claims; see R3, where we use it *additionally* for the
`sub`, not instead of.

**Unverified**: whether Yahoo issues `fspt-w` consent before the API Access
Application is approved, or rejects it at authorize time. Determine during
Phase A validation; it changes the error surface for FR-025, not the design.

---

## R2 — Getting the per-user Yahoo token inside a tool ⭐

**Decision**: Inside a tool, call `fastmcp.server.dependencies.get_access_token()`.
The returned `AccessToken.token` **is the caller's live upstream Yahoo access
token**. Do not build any bespoke per-user token storage, refresh loop, or
credential lifecycle.

**Rationale** — traced through `fastmcp/server/auth/oauth_proxy/proxy.py`:

- `OAuthProxy.load_access_token()` verifies the FastMCP JWT, looks up the
  stored upstream token set, and calls `self._token_validator.verify_token(verification_token)`.
- `_get_verification_token()` (line 1683) returns `upstream_token_set.access_token`
  — the Yahoo token.
- The `AccessToken` returned therefore carries the Yahoo token in `.token`.
- Expiry is handled for us: `load_access_token` detects a token within the
  expiry threshold and calls `_try_transparent_refresh()`, re-reading and
  re-validating on contention from other workers.

This is the single most important finding in this research: it collapses what
looked like the largest subsystem (multi-tenant credential management) into
one function call. FastMCP stores upstream tokens encrypted
(`UpstreamTokenSet`, "Encryption is handled transparently at the storage layer
via FernetEncryptionWrapper. Tokens are never exposed to MCP clients").

**Alternatives considered**:
- *Own the Yahoo tokens in our SQLite* — duplicates encrypted storage FastMCP
  already provides correctly, and forces us to reimplement refresh races.
  Rejected as both more code and less safe.
- *Re-run `yahoo_oauth` per user* — its file-based, interactive-prompt model is
  fundamentally single-user and headless-hostile. Rejected.

---

## R3 — Verifying an opaque Yahoo token (`TokenVerifier`)

**Decision**: Implement a small `YahooTokenVerifier(TokenVerifier)` that
validates a Yahoo access token by calling Yahoo's OIDC userinfo endpoint
(`https://api.login.yahoo.com/openid/v1/userinfo`), and use the returned `sub`
as the stable per-user identity. Follow the shape of FastMCP's existing
`GitHubTokenVerifier` / `GoogleTokenVerifier` (`fastmcp/server/auth/providers/`),
which solve exactly this problem for other opaque-token providers.

**Rationale**: Yahoo access tokens are opaque — there is no JWKS to validate
against, so `JWTVerifier` does not apply, and Yahoo publishes no RFC 7662
introspection endpoint for `IntrospectionTokenVerifier`. Calling a cheap
authenticated endpoint is the established FastMCP pattern for this case, and it
yields the stable subject identifier we need anyway (R4).

**Cost**: one extra Yahoo call per token validation. Mitigate with a short-TTL
cache keyed by token hash if it proves hot; do not pre-optimize (Principle V).

**Unverified**: exact userinfo response shape and whether `openid` must be
co-requested with `fspt-w` at authorize time. Confirm in Phase A.

**Alternative considered**: validate by calling a trivial Fantasy API endpoint
instead of userinfo. Rejected — it conflates "is this token valid" with "does
this user have fantasy data," and gives no stable identity.

---

## R4 — User identity

**Decision**: Key each user by the Yahoo `sub` (GUID) from R3's userinfo call.
Store it as the primary key in our SQLite `users` table. Never key on email
(mutable), on the MCP `client_id` (per-client, not per-person — one person
using both Claude and ChatGPT must resolve to one account), or on league/team
keys (per-season).

**Rationale**: FR-005 requires complete cross-user isolation, which demands one
stable identifier per human that survives token refresh, re-consent, and
connecting from a second AI client.

---

## R5 — Yahoo write API surface

**Library provenance — stated up front, because it changes the risk profile**:
`yahoo_fantasy_api` (2.12.3, Matt Spilchen, MIT) and `yahoo_oauth` (2.1.1,
Josue Kouka, MIT) are **third-party community wrappers, not official Yahoo
SDKs**. Yahoo publishes no official Python client; its developer portal
documents the REST API and directs developers to third-party OAuth libraries.
So "the method exists" below means *this wrapper implements it*, not *Yahoo
guarantees this interface*.

**Decision**: Use `yahoo_fantasy_api.Team` methods directly. **Verified present
in the installed package** (2.12.3) via runtime introspection:

| Spec requirement | Method |
|---|---|
| FR-014 set lineup | `Team.change_positions(time_frame, modified_lineup)` |
| FR-015 add / drop / both | `Team.add_player(id)`, `drop_player(id)`, `add_and_drop_players(add, drop)` |
| FR-015 waiver claims (w/ FAAB) | `Team.claim_player(id, faab=)`, `claim_and_drop_players(add, drop, faab=)` |
| FR-016 list incoming offers | `Team.proposed_trades()` |
| FR-016 accept / reject | `Team.accept_trade(transaction_key, note)`, `reject_trade(transaction_key, note)` |
| *(out of scope)* initiate trade | `Team.propose_trade(...)` — exists, deliberately unused |

**Rationale**: No hand-written HTTP against Yahoo's Transactions/Roster
resources is needed. This materially shrinks Phases D and E and removes an
entire class of XML/JSON payload bugs.

**Note for FR-015**: `add_and_drop_players` is a *single* Yahoo transaction, so
FR-022 (no partially-applied state) is satisfied by Yahoo itself for the
combined case rather than by client-side compensation. Do **not** implement
add/drop as two sequential calls.

**Unverified**: exact `time_frame` semantics for NFL (`change_positions` takes
week for football, date for daily sports) and the `modified_lineup` dict shape.
Confirm against a real team in Phase D before writing the lineup tool.

**Risk accepted (recorded, not mitigated in this release)**: this wrapper
becomes *load-bearing for writes*, where Phase 1 used it only for reads. Its
write paths are plausibly less exercised in the wild than its read paths —
most consumers of a fantasy library read — and the unverified items above are
exactly where that would bite. It is also a single-maintainer dependency in a
product hosted for other people. Two fallbacks exist if a write path proves
broken, neither adopted now (Principle V): a thin direct-HTTP write client
against Yahoo's documented Transactions/Roster resources while keeping the
wrapper for reads, or switching to an alternative community wrapper
(`yahoofantasy`, `yfantasy-api`). Phase D validation (quickstart V5–V8) is the
decision point — that is where a broken write path surfaces.

---

## R6 — Adapting `yahoo_fantasy_api` to a FastMCP-managed token ⭐

**Decision**: Build a tiny per-request adapter exposing exactly one attribute,
`.session` — a `requests.Session` with `Authorization: Bearer <token>` — and
pass it where `yahoo_oauth.OAuth2` used to go:

```text
YahooSessionAdapter(token) -> .session
    └─> yahoo_fantasy_api.Game(adapter, "nfl") -> .to_league(key) -> .to_team(key)
```

**Rationale** — verified in `yahoo_fantasy_api/yhandler.py`: the handler only
ever touches `self.sc.session.get/put/post` (lines 76, 88, 114, 141). Its
refresh path is guarded by `if not hasattr(self.sc, 'refresh_access_token')`
(line 60), so an adapter that *omits* that attribute short-circuits the
library's own refresh logic — which is what we want, because FastMCP already
refreshed the token before we got it (R2). Two refresh mechanisms racing on the
same credential would be a genuine bug.

**Consequence**: `yahoo_oauth` leaves the hosted dependency path entirely.

**Alternative considered**: subclass/monkeypatch `OAuth2` to accept an
injected token. Rejected — more coupling to a library we're otherwise dropping.

---

## R7 — Application state storage

**Decision**: SQLite on the host, one file, accessed through a thin `store.py`.
Tables: `users` (sub, tier, created_at), `usage_events` (sub, tool, timestamp),
`proposals` (see data-model.md). FastMCP's own encrypted file store continues
to own OAuth client registrations and upstream tokens — we do not co-mingle.

**Rationale**: Scale is tens of users on one box (spec Assumptions). SQLite is
in the standard library, survives restart, handles this concurrency trivially,
and needs no separate service on the Oracle server. FR-028's tier + usage
columns exist from day one specifically so the later monetization phase does
not require re-architecting.

**Alternatives considered**: Postgres — correct at 10k users, premature at 20
(Principle V); the migration path is a `store.py` swap. In-memory/JSON —
rejected in plan.md's Complexity Tracking (loses pending proposals on restart).

---

## R8 — Confirmation token design

**Decision**: On propose, persist a `proposal` row and return an opaque,
high-entropy `confirmation_token` (`secrets.token_urlsafe(32)`). Store only its
**hash**. On confirm, look up by hash and require **all** of:

1. Not expired (TTL ~5 minutes, configurable).
2. Not already consumed — mark consumed in the same transaction that performs
   the write (single-use, satisfying FR-023 replay protection).
3. `proposal.user_sub` equals the *calling* user's sub from R4 (FR-020).
4. Preconditions still hold — re-read current roster/offer state and compare
   against the snapshot taken at propose time (FR-021).

**Rationale**: This is what makes FR-019 true — the guarantee lives in our
server, not in the host's UI. A model that hallucinates a plausible-looking
token cannot satisfy (1)+(2)+(3) simultaneously, because the token was never
issued and has no row. Hashing at rest means a leaked database still can't be
used to confirm actions.

**Explicitly rejected**: MCP **elicitation** as the enforcement mechanism.
Verified client support as of 2026-08: Claude Code CLI supports it (v2.1.76+),
but **Claude Desktop and claude.ai return `-32601 Method not found`**, and
ChatGPT has no elicitation support. Since the spec's target users connect via
claude.ai and ChatGPT, elicitation-based confirmation would hard-fail for
nearly the entire audience. It may be layered on later as an opportunistic UX
enhancement for clients that advertise the capability — never as the guarantee.

---

## R9 — Tool annotations and host-level confirmation

**Decision**: Set `readOnlyHint`, `destructiveHint`, and `openWorldHint` on
every tool (FR-024). Read tools: `readOnly=true`, `openWorld=true`. `propose_*`
tools: `readOnly=true` (they change nothing), `openWorld=true`.
`confirm_action`: `readOnly=false`, `destructive=true`, `openWorld=true`.

**Rationale**: These are standard MCP `ToolAnnotations`, consumed by both
hosts. OpenAI's Apps SDK *requires* all three for submission, and ChatGPT
renders a confirmation modal for destructive tools on web and iOS. It is free
UX and costs nothing to set correctly.

**Why it is not the guarantee** (reinforcing FR-019): ChatGPT's modal offers
"allow always," letting a user disable confirmation permanently; there is a
documented Android defect where the modal can be bypassed before the call
reaches MCP; and annotation handling differs per host. Annotations are a
supplementary layer over R8, never a replacement.

Marking `propose_*` as non-destructive is deliberate: it keeps the host's
confirmation prompt attached to the step that actually writes, instead of
training users to click through two prompts.

---

## Summary of what this research removed from scope

| Initially assumed necessary | Actually needed |
|---|---|
| Build an OAuth 2.1 authorization server | Configure `OAuthProxy` |
| Per-user Yahoo token storage + refresh | One `get_access_token()` call (R2) |
| Hand-rolled HTTP for Yahoo writes | Existing `yahoo_fantasy_api.Team` methods (R5) |
| Fork or wrap `yahoo_oauth` | ~15-line `.session` adapter (R6) |
| Postgres | SQLite (R7) |

The remaining genuinely-new work is the multi-tenancy boundary, the
propose/confirm rail, the write tools, and deployment.
