# Contract: MCP Tool Surface

**Feature**: `001-yahoo-fantasy-mcp` | **Date**: 2026-08-16
**Transport**: stdio (R7) | **Framework**: FastMCP 3.4.7

This is the server's external interface — the contract MCP clients (Claude, and
later the Phase 2 agentic skills) code against.

## Global contract rules

1. **Descriptions are honest (FR-011, constitution Principle IV).** A tool's
   description states only what its wired implementation does. No tool claims
   analysis, recommendation, or "AI-powered" behavior — this server returns data.
   Recommendation logic is Phase 2 and lives outside this server.
2. **Read-only (FR-014).** No tool in this contract, present or future, writes to
   Yahoo. There is no `draft_player` tool by design, not by omission.
3. **Errors are typed, never raw.** Every tool surfaces failures as one of the
   `ErrorCode` values below. No tool leaks a raw HTTP status, stack trace, or —
   critically — any token value (Principle III).
4. **Draft-bearing responses carry `retrieved_at`.** Any response containing draft
   state includes the ISO-8601 timestamp of the underlying Yahoo read, so callers
   can enforce FR-009 freshness themselves.

## ErrorCode enum

| Code | Meaning | Maps to |
|---|---|---|
| `AUTH_REQUIRED` | No credentials yet; run the one-time setup. | FR-001 |
| `AUTH_EXPIRED` | Refresh token expired/revoked — user must re-authenticate. | FR-007, edge case |
| `LEAGUE_NOT_PROVISIONED` | League valid but not yet available for this season. | FR-007, edge case |
| `LEAGUE_NOT_ACCESSIBLE` | League/team exists but this account can't access it. | edge case |
| `UNSUPPORTED_DRAFT_TYPE` | Auction draft detected; snake only. | FR-013, data-model rule 1 |
| `RATE_LIMITED` | Yahoo throttled us; backoff in effect. | R5 |
| `UPSTREAM_ERROR` | Yahoo returned an unexpected failure. | — |

`AUTH_EXPIRED` and `LEAGUE_NOT_PROVISIONED` are distinct codes specifically
because both arrive from Yahoo as a 401 — collapsing them is the exact bug
FR-007 exists to prevent.

---

## Tool: `get_league_info`

Returns the configured league's identity and current draft status.

**Input**: none (league is configured, per FR-012).

**Output**:
```json
{
  "league_key": "449.l.27081",
  "name": "Sunday Funday",
  "season": 2026,
  "num_teams": 12,
  "scoring_type": "head",
  "draft_status": "drafting"
}
```

**Satisfies**: FR-004 (scoped to the single configured league).
**Errors**: `AUTH_REQUIRED`, `AUTH_EXPIRED`, `LEAGUE_NOT_PROVISIONED`, `LEAGUE_NOT_ACCESSIBLE`.

---

## Tool: `list_teams`

Lists teams in the league, flagging which one belongs to the authenticated user.

**Input**: none.

**Output**:
```json
{
  "teams": [
    {"team_key": "449.l.27081.t.4", "name": "Team Chaos", "is_owned_by_user": true, "standing": null}
  ]
}
```

**Satisfies**: FR-004.
**Errors**: as `get_league_info`.

---

## Tool: `get_roster`

Returns a team's current roster.

**Input**:
| Param | Type | Required | Notes |
|---|---|---|---|
| `team_key` | str | no | Defaults to the user's own team. |

**Output**:
```json
{
  "team_key": "449.l.27081.t.4",
  "players": [
    {"player_id": 9490, "name": "Bijan Robinson", "positions": ["RB"], "nfl_team": "ATL"}
  ]
}
```

**Satisfies**: FR-005.
**Errors**: as `get_league_info`, plus `LEAGUE_NOT_ACCESSIBLE` for a foreign team.

---

## Tool: `get_standings`

**Input**: none.

**Output**:
```json
{"standings": [{"team_key": "449.l.27081.t.4", "name": "Team Chaos", "standing": 1}]}
```

**Satisfies**: FR-006.
**Errors**: as `get_league_info`.

---

## Tool: `get_draft_results`

**The core live-draft tool (FR-008, FR-009).** Returns every pick made so far.

**Input**: none.

**Output**:
```json
{
  "draft_status": "drafting",
  "retrieved_at": "2026-08-16T19:04:12Z",
  "is_complete": false,
  "picks": [
    {
      "pick": 1,
      "round": 1,
      "team_key": "449.l.27081.t.7",
      "player_id": 9490,
      "player_name": "Bijan Robinson",
      "positions": ["RB"],
      "nfl_team": "ATL"
    }
  ]
}
```

**Behavioral contract**:
- Pre-draft → `picks: []` with `draft_status: "predraft"`. **Not an error**
  (User Story 2, scenario 3).
- Mid-draft → picks made so far, ordered by `pick` ascending.
- Post-draft → complete board, `is_complete: true`.
- Never includes an undrafted player (User Story 2, scenario 1).
- `retrieved_at` reflects the Yahoo read backing *this* response.
- Player names come from the R4 identity cache — resolving them costs no extra
  Yahoo call per poll (R5).

**Satisfies**: FR-008, FR-009.
**Errors**: `UNSUPPORTED_DRAFT_TYPE` (auction detected), `RATE_LIMITED`, plus auth codes.

---

## Tool: `get_available_players`

Undrafted players with ranking context (FR-010).

**Input**:
| Param | Type | Required | Notes |
|---|---|---|---|
| `position` | str | no | Filter, e.g. `RB`. Omit for all. |
| `limit` | int | no | Default 50. |

**Output**:
```json
{
  "retrieved_at": "2026-08-16T19:04:12Z",
  "position": "RB",
  "count": 50,
  "players": [
    {
      "player_id": 40021,
      "name": "Jonathon Brooks",
      "positions": ["RB"],
      "nfl_team": "CAR",
      "percent_owned": 62,
      "average_pick": 71.4
    }
  ]
}
```

**Behavioral contract — the critical one**:
- Availability is **derived** from the same fresh `draft_results()` read that
  backs `retrieved_at`, per R3 and the data-model Availability Invariant. The
  implementation MUST NOT return results from the upstream library's
  `free_agents()` / `taken_players()` caches, which never expire.
- **Guarantee**: no player present in `get_draft_results` for the same
  `retrieved_at` may appear here. This is the machine-checkable form of SC-002
  and MUST have a test asserting it (constitution Principle II).
- `position` filters on eligibility, so a multi-eligible player appears under
  each position they qualify for (User Story 3, scenario 2).

**Satisfies**: FR-010.
**Errors**: as `get_draft_results`.

---

## Tool: `check_auth`

Reports credential state without exposing credentials.

**Input**: none.

**Output**:
```json
{"authenticated": true, "expires_in_seconds": 3221, "needs_reauth": false}
```

**Contract**: MUST NEVER return a token, secret, or any fragment thereof
(FR-002, Principle III). Only booleans and a duration.

**Satisfies**: FR-001, FR-003 observability.

---

## Explicitly NOT in this contract

| Absent tool | Why |
|---|---|
| `draft_player` / any write tool | FR-014 — read-only by design. Adding one requires a new spec and explicit opt-in. |
| `recommend_pick` / `rank_players` | Phase 2 (agentic skills). This server supplies data; strategy consumes it. Shipping a stub here would violate Principle IV. |
| Multi-league tools | FR-012 — single configured league. |
| Auction tools | FR-013 — snake only; auction is a hard error, not partial support. |
