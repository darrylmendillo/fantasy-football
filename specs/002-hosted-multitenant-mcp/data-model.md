# Phase 1 Data Model: Hosted Multi-Tenant Fantasy MCP Server

**Feature**: `002-hosted-multitenant-mcp` | **Date**: 2026-08-17

Two storage domains, deliberately kept separate:

- **FastMCP-owned** (encrypted file store): OAuth client registrations, FastMCP
  JWTs, and upstream Yahoo token sets. We never read or write these directly —
  see research R2. They are listed here only so the boundary is explicit.
- **Application-owned** (SQLite, `store.py`): everything below.

---

## Persisted entities

### `users`

One row per human, created on first authenticated request.

| Field | Type | Notes |
|---|---|---|
| `sub` | TEXT PK | Yahoo OIDC subject (GUID) — research R4. Stable across token refresh, re-consent, and connecting from a second AI client. |
| `tier` | TEXT NOT NULL | `'free'` for every user in this release. Exists from day one per FR-028 so monetization needs no re-architecture. **No limit is enforced against it now.** |
| `created_at` | INTEGER NOT NULL | Unix seconds. |
| `last_seen_at` | INTEGER NOT NULL | Updated per request; cheap operational signal. |

**Validation rules**
- `sub` MUST come from the verified token (R3), never from a tool argument — accepting a caller-supplied user id would defeat FR-005 isolation.
- No Yahoo token, email, or display name is stored. Nothing here is a credential (Principle III).

---

### `usage_events`

Append-only. Satisfies the FR-028 "timestamped history of usage."

| Field | Type | Notes |
|---|---|---|
| `id` | INTEGER PK | |
| `sub` | TEXT NOT NULL → `users.sub` | |
| `tool_name` | TEXT NOT NULL | |
| `occurred_at` | INTEGER NOT NULL | Unix seconds. |
| `outcome` | TEXT NOT NULL | `ok` \| `error` \| `refused`. Lets a future rate-limiter avoid charging users for our own failures. |

**Validation rules**
- Written for every tool invocation, including refusals.
- MUST NOT record tool *arguments* — arguments can contain roster/league detail, and the point of this table is metering, not surveillance. Tool name and outcome are sufficient for FR-028.
- Retention/pruning is not specified in this release; the table is small at this scale.

---

### `proposals`

The heart of the write-safety guarantee (FR-017–FR-023, research R8).

| Field | Type | Notes |
|---|---|---|
| `id` | TEXT PK | Opaque proposal id, safe to show. |
| `token_hash` | TEXT UNIQUE NOT NULL | SHA-256 of the confirmation token. **The raw token is returned to the caller once and never stored** — a leaked DB cannot confirm anything. |
| `sub` | TEXT NOT NULL → `users.sub` | Enforces FR-020: only the issuing user may confirm. |
| `league_key` | TEXT NOT NULL | |
| `team_key` | TEXT NOT NULL | The user's team in that league. |
| `action_type` | TEXT NOT NULL | `set_lineup` \| `add_drop` \| `trade_response`. |
| `payload_json` | TEXT NOT NULL | Exactly the arguments that will be passed to the Yahoo call on confirm. Nothing is recomputed at confirm time, so the preview cannot drift from the action (FR-018). |
| `preview_json` | TEXT NOT NULL | The human-readable preview shown at propose time, retained for audit and for FR-018 verification. |
| `precondition_json` | TEXT NOT NULL | Snapshot of the state the proposal assumed (see below). Re-checked on confirm per FR-021. |
| `created_at` | INTEGER NOT NULL | |
| `expires_at` | INTEGER NOT NULL | `created_at + TTL` (default 300s, configurable). |
| `status` | TEXT NOT NULL | `pending` \| `consumed` \| `expired` \| `failed`. |
| `consumed_at` | INTEGER NULL | Set in the same transaction as the write attempt (single-use). |

**State transitions**

```text
                 confirm (all checks pass)
   pending ──────────────────────────────────► consumed   [terminal]
      │
      ├── confirm, precondition drift / Yahoo error ─────► failed   [terminal]
      │
      └── TTL elapses (lazy, on read) ───────────────────► expired  [terminal]
```

Only `pending` is confirmable. All terminal states are final — there is no
resurrection path, which is what makes replay (FR-023) impossible.

**Validation rules — every one MUST hold before any Yahoo write**
1. Row exists for the presented token's hash.
2. `status == 'pending'`.
3. `now < expires_at`.
4. `proposals.sub == ` the authenticated caller's sub.
5. Preconditions still hold (below).
6. Consumption and the write occur atomically: mark `consumed` in the same
   transaction that dispatches the write, so a crash cannot leave a token
   reusable.

**Precondition snapshot by action type** — what R8/FR-021 re-verifies:

| `action_type` | Snapshot contents | Refused on confirm when |
|---|---|---|
| `set_lineup` | Player ids and current slots for the affected players; week | A player is no longer rostered, or their slot already differs |
| `add_drop` | Add-player id + availability; drop-player id + rostered status; roster size | The added player is no longer available (claimed by someone else), or the dropped player is already gone |
| `trade_response` | `transaction_key` + offer status + both sides' player ids | The offer was withdrawn, already accepted, or already rejected elsewhere |

The add/drop case is why FR-022 is satisfiable: research R5 confirmed
`add_and_drop_players` is a *single* Yahoo transaction, so there is no window
in which the drop lands without the add.

---

## Request-scoped (not persisted)

### `RequestIdentity`

Derived per request from the verified access token; never from tool arguments.

| Field | Source |
|---|---|
| `sub` | Yahoo userinfo `sub` (R3/R4) |
| `yahoo_access_token` | `get_access_token().token` (R2) — held only for the duration of the request, never logged, never returned |

### `LeagueContext`

Resolved per request from `(identity, league_key)`. Replaces Phase 1's
module-level `ServerContext` singleton, which is the multi-tenancy bug.

| Field | Notes |
|---|---|
| `league_key` | Validated to be a league this user actually belongs to — otherwise refused (spec US2 sc.4) |
| `team_key` | The caller's own team in that league |
| `client` | `YahooClient` over a `YahooFantasyApiDataSource` built on this request's token |
| `total_expected_picks` | For `Draft.is_complete`; derived from league settings + roster size, no longer from a global env var |

---

## Caching under multi-tenancy

> **Corrected 2026-08-17.** This section previously claimed Phase 1's caches
> were per-process and therefore a live cross-tenant leak. That was wrong.
> `YahooFantasyApiDataSource` initialises its caches in `__init__`
> (`client.py:175,178`), so they are **per-instance**; with a fresh data source
> built per request, users are already isolated. The error was caught by
> writing the test that was supposed to prove the bug (T008) and watching it
> pass against unmodified code.

**Actual state**: isolation today is a consequence of *constructing a new data
source per request*, not of the cache keys. That is correct but not free — it
re-seeds the player universe on every request, which is precisely the
rate-limit exposure spec 001 research R5 warns about.

**Rule**: per-request construction is the current, deliberate design. If a data
source is ever pooled, memoised, or module-scoped for performance, every cache
key MUST at that point be scoped by `(league_key, …)`, and any cache holding
user-specific state MUST additionally be scoped by `sub`. `tests/unit/test_client_cache_isolation.py`
is the regression guard that fails if that is forgotten.

| Cache | New key | Rationale |
|---|---|---|
| Player identity (name, positions, NFL team) | `(league_key, player_id)` | Player identity is league-independent in principle, but keeping it league-scoped avoids cross-league staleness assumptions and costs little |
| Player universe (`free_agents` seed) | `(league_key, position)` | Universe differs per league; sharing it across leagues would report players who don't exist in the caller's league |
| Availability | **NOT CACHED — EVER** | The Phase 1 correctness guarantee (spec FR-012, 001 research R3). Always derived fresh from `draft_results()`. Unchanged by this feature and MUST remain so |

---

## Entity relationships

```text
users (sub)
  │
  ├──< usage_events            (metering, FR-028)
  │
  └──< proposals               (write safety, FR-017–023)
            │
            └── references league_key / team_key
                (Yahoo-owned; never mirrored locally)
```

League, team, roster, player, and trade-offer data are **not** persisted.
They are read from Yahoo per request and returned. Mirroring them locally would
create staleness bugs of exactly the kind the availability invariant exists to
prevent.
