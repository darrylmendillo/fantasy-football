# Phase 1 Contracts: MCP Tools

**Feature**: `002-hosted-multitenant-mcp` | **Date**: 2026-08-17

Contracts for the hosted server's tool surface. Supersedes
`specs/001-yahoo-fantasy-mcp/contracts/mcp-tools.md` for the hosted path: every
read tool gains a `league_key` parameter, and write tools are new.

## Conventions applying to every tool

- **Identity is never a parameter.** The calling user is resolved from the
  verified access token (research R2/R4). No tool accepts a user id — accepting
  one would defeat FR-005 isolation.
- **`league_key` is validated for membership** on every call. A league the
  caller does not belong to is refused with `LEAGUE_NOT_ACCESSIBLE`, never
  served (spec US2 sc.4).
- **No credential ever appears in a response**, including in error messages
  (FR-026).
- **Non-football leagues are refused** with `SPORT_NOT_SUPPORTED` (FR-008) —
  they still appear in `list_leagues` so users aren't confused by absence.
- Every tool records a `usage_events` row, including refusals (FR-028).

### Annotation policy (FR-024, research R9)

| Tool class | `readOnlyHint` | `destructiveHint` | `openWorldHint` |
|---|---|---|---|
| Read tools | `true` | `false` | `true` |
| `propose_*` | `true` | `false` | `true` |
| `confirm_action` | `false` | **`true`** | `true` |

`propose_*` is annotated non-destructive **because it genuinely changes
nothing**. This keeps the host's own confirmation prompt attached to the one
call that actually writes, rather than training users to click through two.

---

## Auth & discovery

### `check_auth`

Whether the caller's Yahoo authorization is currently usable.

**Parameters**: none

**Returns**: `{ authenticated: bool, expires_in_seconds: int, needs_reauth: bool }`

**MUST NOT** return a token value under any circumstance.

---

### `list_leagues`

All Yahoo fantasy leagues the caller belongs to (FR-009).

**Parameters**: `season` (int, optional — defaults to current)

**Returns**: `{ leagues: array of
{ league_key, name, sport, season, is_supported: bool, team_key, team_name } }`

(Wrapped in a `leagues` key, not returned as a bare top-level array — a bare
list broke FastMCP's structured-output validation in practice, the same
defect class already fixed once for `list_teams`/`get_standings`.)

`is_supported` is `false` for non-football leagues; they are listed so the user
can see them, but every other tool refuses them (FR-008).

---

## Read tools

All take `league_key` (string, required) plus the parameters below. Behavior is
otherwise identical to Phase 1 — including the availability guarantee.

| Tool | Extra parameters | Returns |
|---|---|---|
| `get_league_info` | — | League identity, season, scoring type, draft status |
| `list_teams` | — | Teams in the league, flagging the caller's own |
| `get_roster` | `team_key` (optional, defaults to caller's team) | Current roster |
| `get_standings` | — | Current standings |
| `get_draft_results` | — | Every pick made so far, freshest read available |
| `get_available_players` | `positions` (optional) | Undrafted players with ranking context |

**Invariant carried forward from Phase 1 (FR-012)**: for the same read,
`get_available_players` and `get_draft_results` MUST NOT overlap. Availability
is always derived fresh from draft results — never cached, never read from
Yahoo's `free_agents` as live truth. This is the project's core correctness
guarantee and is unchanged by multi-tenancy, except that caches are now
per-league-scoped (data-model.md).

**Known limitation, carried forward**: `average_pick` (ADP) is always `null` —
the underlying library exposes no draft-analysis endpoint. Disclosed, not
silently broken (Principle IV).

---

## Write tools

Every write is two calls. There is no single-call write path — by design
(FR-017), and no `force`/`skip_confirm` parameter exists on any tool.

```text
  propose_*  ──► preview + confirmation_token ──► user decides ──► confirm_action
     │                                                                  │
   nothing sent to Yahoo                                    the only call that writes
```

### `propose_set_lineup`

**Parameters**: `league_key`, `week` (int, optional — defaults to current),
`changes` (array of `{ player_id, position }`)

**Returns**:
```text
{
  proposal_id, confirmation_token, expires_in_seconds,
  preview: {
    action: "set_lineup",
    week: int,
    changes: [ { player_name, player_id, from_position, to_position } ],
    warnings: [ string ]     // e.g. "Player is on bye this week"
  }
}
```

Changes nothing. `warnings` surfaces problems *before* confirmation rather than
as a post-confirm failure (spec US4 sc.4 pattern).

---

### `propose_add_drop`

**Parameters**: `league_key`, `add_player_id` (optional), `drop_player_id`
(optional), `faab_bid` (int, optional — waiver claims). At least one of
add/drop required.

**Returns**: same envelope, with
```text
  preview: {
    action: "add_drop",
    add:  { player_id, player_name, availability_status } | null,
    drop: { player_id, player_name } | null,
    resulting_roster_size: int,
    warnings: [ string ]
  }
```

When both add and drop are present, confirmation dispatches
`add_and_drop_players` — a **single** Yahoo transaction, which is what makes
FR-022 (no partial application) true rather than aspirational (research R5).

---

### `list_trade_offers`

Incoming trade offers awaiting the caller's response (FR-016). Read-only.

**Parameters**: `league_key`

**Returns**: array of
`{ transaction_key, from_team_name, players_receiving: [...], players_sending: [...], status, note }`

---

### `propose_trade_response`

**Parameters**: `league_key`, `transaction_key`, `response` (`"accept"` |
`"reject"`), `note` (string, optional)

**Returns**: same envelope, preview naming both sides of the exchange and the
response being taken.

**Out of scope**: initiating an outbound trade. A request to do so MUST be
refused with `TRADE_INITIATION_NOT_SUPPORTED` and a plain-language explanation
(spec US5 sc.5) — not a generic failure.

---

### `confirm_action`

The only tool that writes to Yahoo.

**Parameters**: `confirmation_token` (string, required)

**Returns**: `{ status: "applied", action: ..., result: {...}, applied_at }`

**Refusal conditions** — all enforced server-side (FR-020, FR-021, research R8):

| Condition | Error code |
|---|---|
| No proposal matches the token | `INVALID_CONFIRMATION` |
| Proposal expired | `PROPOSAL_EXPIRED` |
| Proposal already used | `PROPOSAL_ALREADY_USED` |
| Caller is not the issuing user | `INVALID_CONFIRMATION` |
| Preconditions changed since propose | `PRECONDITIONS_CHANGED` |
| Yahoo write access not approved | `WRITE_NOT_APPROVED` |

`INVALID_CONFIRMATION` is deliberately returned for both "no such token" and
"wrong user" — the response must not reveal whether a token exists.

A fabricated token cannot satisfy these checks, because no row was ever issued
for it. **This is the mechanism behind FR-019**: the guarantee holds even
against a client that never showed the user a prompt.

---

## Error codes

| Code | Meaning |
|---|---|
| `AUTH_REQUIRED` | No valid authorization; user must connect |
| `AUTH_EXPIRED` | Authorization expired or was revoked at Yahoo |
| `LEAGUE_NOT_ACCESSIBLE` | Caller does not belong to this league |
| `SPORT_NOT_SUPPORTED` | Non-football league (FR-008) |
| `WRITE_NOT_APPROVED` | Operator's Yahoo access lacks write scope (FR-025) |
| `INVALID_CONFIRMATION` | Unknown token, or not the issuing user |
| `PROPOSAL_EXPIRED` | TTL elapsed |
| `PROPOSAL_ALREADY_USED` | Single-use token replayed |
| `PRECONDITIONS_CHANGED` | State drifted between propose and confirm |
| `TRADE_INITIATION_NOT_SUPPORTED` | Outbound trades deferred |
| `RATE_LIMITED` | Yahoo throttling; retry later |

Every message is safe to display verbatim: no credentials, no raw Yahoo error
bodies (Principle III, carried from Phase 1's `classify_auth_failure`).
