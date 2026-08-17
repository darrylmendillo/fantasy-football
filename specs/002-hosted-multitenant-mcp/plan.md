# Implementation Plan: Hosted Multi-Tenant Fantasy MCP Server

**Branch**: `pivot/hosted-multitenant-mcp` | **Date**: 2026-08-17 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/002-hosted-multitenant-mcp/spec.md`

## Summary

Turn the single-user, single-league, read-only, stdio MCP server into a hosted multi-tenant one that Claude and ChatGPT users connect to over HTTP with their own Yahoo accounts, and add write capability (lineup, add/drop, trade responses) behind a server-enforced two-step confirmation.

The architecture rests on four findings from Phase 0 research, all verified against installed source rather than assumed:

1. **FastMCP's `OAuthProxy` does the multi-tenant auth work.** It presents spec-compliant MCP OAuth (DCR/CIMD/PKCE) to Claude and ChatGPT while proxying to Yahoo's non-DCR OAuth2 underneath, storing each user's Yahoo tokens encrypted and refreshing them transparently.
2. **`get_access_token().token` returns the caller's live *Yahoo* access token** inside a tool. This is the linchpin: per-user Yahoo credentials need no bespoke storage, refresh, or lifecycle code of our own.
3. **Every write operation already exists in `yahoo_fantasy_api`** — `Team.change_positions`, `add_and_drop_players`, `accept_trade`, `reject_trade`, and friends. No hand-rolled HTTP. Note this is a **third-party, single-maintainer wrapper** (Matt Spilchen, MIT), not an official Yahoo SDK — Yahoo publishes none for Python. See research R5 for the risk this carries now that it becomes load-bearing for writes.
4. **`yahoo_fantasy_api` needs only `sc.session`** from its session object, so a ~15-line adapter wrapping a `requests.Session` with a Bearer token replaces the `yahoo_oauth` dependency in the hosted path entirely.

The consequence is that most of this feature is composition, not invention. The genuinely new code is: the multi-tenancy boundary (per-request league/team resolution replacing module-level singletons), the propose/confirm machinery, the write tools, and a small persistence layer for proposals, tier, and usage.

## Technical Context

**Language/Version**: Python 3.11+ (dev venv 3.12)

**Primary Dependencies**: FastMCP 3.4.7 (`OAuthProxy`, HTTP transport, tool annotations); `yahoo_fantasy_api` 2.12.3 (read + write) — a **community wrapper, not an official Yahoo SDK**; `requests`. **Removed from the hosted path**: `yahoo_oauth` 2.1.1 (also community; replaced by FastMCP-managed tokens, retained only if the local stdio entrypoint is kept).

**Storage**: SQLite on the host for application state (users, tier, usage log, pending proposals). FastMCP's own encrypted file store handles OAuth/client/token state. Postgres deferred — see research R7.

**Testing**: pytest with fixture-based fakes, as in Phase 1. New requirement: a fake `YahooDataSource` write surface and a clock/TTL fake for proposal expiry, so the entire confirm flow is testable without network or a live account.

**Target Platform**: Linux (operator's Oracle Cloud server), behind TLS on a public hostname.

**Project Type**: Single Python project — remote MCP server. No frontend (constitution v0.2.0).

**Performance Goals**: Not latency-critical. Yahoo's API is the bottleneck and is undocumented-rate-limited (Phase 1 research R5), so the goals are *correctness under concurrency* and *not tripping Yahoo's limits*: per-user request isolation, no cross-user cache bleed, and retry/backoff preserved from Phase 1.

**Constraints**: Draft-time availability freshness guarantee (spec FR-012) must survive the move to multi-tenancy — the Phase 1 caches are per-process today and become a cross-user correctness bug if left as-is. Write actions must be impossible without a distinct confirmation step (FR-017–FR-021).

**Scale/Scope**: Tens of users (operator + friends), single server, single sport (football), current season.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

Checked against constitution v0.2.0.

| Principle | Status | How this plan complies |
|---|---|---|
| **I. MVP-First, Phased Delivery** | ⚠️ **Gated, not violated** | This is exactly the Phase 2 the constitution describes. But Principle I requires Phase 1 be "proven working end-to-end" first, and it is not — validation is blocked on Yahoo API access approval. **Planning is permitted; implementation MUST NOT start until Phase 1 validation passes.** Tracked below as a release gate, not designed around. |
| **II. Test-First (NON-NEGOTIABLE)** | ✅ | Constitution explicitly extends TDD to "the OAuth-proxy/multi-tenancy layer and the write-confirmation flow." Design keeps both testable without network: the confirm flow is pure logic over an injected store + clock; multi-tenancy is exercised via two fake identities. Write tools sit behind the existing `YahooDataSource` Protocol so they test against fixtures. |
| **III. No Committed Credentials** | ✅ | Per-user Yahoo tokens live only in FastMCP's encrypted store, never in our SQLite, never in tool output (FR-026), never logged — existing `mask_secrets` retained. Nothing new is added to git. |
| **IV. Honest, Wired Architecture** | ✅ | Write tools must not ship claiming capability that Yahoo's approval doesn't yet grant: FR-025 requires they fail with an explicit "write access not approved" rather than a vague error. No tool description may promise sports or trade-initiation that are out of scope. |
| **V. Simplicity / YAGNI** | ✅ | SQLite over Postgres; no frontend; no billing/metering logic (only the tier+usage columns FR-028 requires); trade *initiation* and non-football sports deliberately excluded. `OAuthProxy` used as-is rather than writing an auth server. |

**No violations requiring justification.** The one flag is a sequencing gate (Principle I), recorded in Release Gates below.

### Release Gates (must be true before implementation begins)

1. **Yahoo API access approved** for the operator's Client ID — **read+write** (`fspt-w`). Read-only approval permits Phases A–C below but blocks D–E.
2. **Phase 1 validated end-to-end** against a real Yahoo account (spec 001 T055), per constitution Principle I.

## Project Structure

### Documentation (this feature)

```text
specs/002-hosted-multitenant-mcp/
├── plan.md              # This file
├── research.md          # Phase 0 output — 9 decisions, all verified against source
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output — validation scenarios
├── contracts/
│   └── mcp-tools.md     # Phase 1 output — tool contracts + annotations
├── checklists/
│   └── requirements.md  # Spec quality checklist (complete)
└── tasks.md             # Phase 2 output (/speckit-tasks — NOT created here)
```

### Source Code (repository root)

```text
src/yahoo_fantasy_mcp/
├── __main__.py          # REWRITTEN: HTTP transport, no build_context singleton
├── auth_proxy.py        # NEW: YahooOAuthProxy + YahooTokenVerifier (R1, R2, R3)
├── session.py           # NEW: per-request Yahoo session adapter + league/team resolution (R6)
├── config.py            # REWRITTEN: server config only — no per-user league/token
├── server.py            # REWRITTEN: tools take league_key; annotations added
├── tools_read.py        # NEW: read tools split out of server.py
├── tools_write.py       # NEW: propose/confirm write tools
├── confirm.py           # NEW: proposal creation, token issue/verify, expiry, single-use
├── store.py             # NEW: SQLite persistence (users, usage, proposals)
├── client.py            # EXTENDED: write methods on YahooDataSource Protocol
├── draft.py             # UNCHANGED: availability invariant logic
├── models.py            # EXTENDED: proposal/trade/lineup entities
├── errors.py            # EXTENDED: WriteNotApprovedError, ProposalExpiredError, etc.
├── logging_utils.py     # UNCHANGED
└── auth.py              # RETAINED for local stdio path only (or deleted if dropped)

tests/
├── unit/                # confirm.py logic, store.py, session resolution, adapters
├── integration/         # tool-level: multi-tenant isolation, propose→confirm, annotations
└── contract/            # NEW: OAuth metadata endpoints, tool schema/annotation assertions
```

**Structure Decision**: Single project, evolved in place. `server.py` currently holds all tools and a module-level `ServerContext`; that singleton is the multi-tenancy bug and is what gets dismantled. Read tools move to `tools_read.py` unchanged in logic but re-parameterized by league; write tools land in `tools_write.py`. `draft.py`'s availability derivation — the correctness crown jewel — is untouched.

## Implementation Phases

Ordered so each phase is independently demonstrable, per Principle I. Phases A–C need only read approval; D–E need write approval.

| Phase | Delivers | Spec coverage | Gate |
|---|---|---|---|
| **A. Transport + Auth** | Server runs over HTTP; a real user completes Yahoo OAuth from Claude and calls `check_auth` | US1, FR-001–007 | Yahoo read approval |
| **B. Multi-tenancy** | Per-request identity; two users concurrently see only their own data; caches keyed per user | US1 sc.3, FR-005, FR-026 | — |
| **C. Multi-league reads** | `list_leagues` + all Phase 1 reads parameterized by league; availability invariant preserved | US2, FR-008–013 | — |
| **D. Confirm machinery + lineup writes** | `propose_*`/`confirm_action`; lineup change end-to-end | US3, FR-014, FR-017–024 | **Yahoo write approval** |
| **E. Add/drop + trade responses** | Remaining write tools on the proven confirm rail | US4, US5, FR-015, FR-016 | **Yahoo write approval** |
| **F. Deployment** | TLS, systemd, backups, runbook | FR-029 | — |

## Post-Design Constitution Re-Check

Re-evaluated after Phase 1 artifacts (research.md, data-model.md, contracts/, quickstart.md).

| Principle | Post-design status |
|---|---|
| **I. MVP-First** | Unchanged — still gated on Phase 1 validation. Design did not expand scope: research R5 *shrank* it by finding the write API already exists. Phase table A–F keeps each step independently demonstrable. |
| **II. Test-First** | **Strengthened.** The confirm rail was deliberately designed as pure logic over an injected store + clock precisely so V6's five adversarial cases are unit-testable with no live account. quickstart.md names the required automated coverage explicitly. |
| **III. No Committed Credentials** | **Verified at design level.** data-model.md's `users` table holds no credential; `proposals` stores only a token *hash*; upstream Yahoo tokens stay in FastMCP's encrypted store (R2) and are held request-scoped only. Contracts forbid tokens in every response, including errors. |
| **IV. Honest, Wired Architecture** | **Held.** research.md flags four items as explicitly *unverified* (Yahoo consent behavior pre-approval, userinfo shape, `change_positions` semantics, `openid`+`fspt-w` co-request) rather than asserting them. ADP remains disclosed as `null`. V9 exists to validate the not-yet-approved path honestly. |
| **V. Simplicity / YAGNI** | **Held, and improved by research.** Five subsystems initially assumed necessary were eliminated (research summary table). Tier column exists but enforces nothing; no billing logic; no frontend; trade initiation excluded despite the library supporting it. |

**No new violations.** The sole outstanding item remains the Principle I sequencing gate.

## Complexity Tracking

> No constitution violations require justification. Two deliberate complexity additions are recorded here because they are not obvious from the spec:

| Addition | Why needed | Simpler alternative rejected because |
|---|---|---|
| SQLite + a `store.py` layer | FR-028 mandates tier + usage history from day one; proposals need durable, single-use, expiring state that must survive restart | In-memory proposals would silently drop pending confirmations on restart and give a false "expired" to users mid-conversation; a JSON file would race under concurrent users |
| Per-user cache keying in `client.py` | Phase 1 caches player identity/universe per process. Under multi-tenancy that is a cross-user data-leak and correctness bug | Deleting the caches entirely would re-fetch the player universe on every call and risk Yahoo rate limits (Phase 1 research R5) |
