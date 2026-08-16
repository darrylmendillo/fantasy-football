# Phase 1 Data Model: Yahoo Fantasy MCP Server

**Feature**: `001-yahoo-fantasy-mcp` | **Date**: 2026-08-16

Entities below are the server's *internal* domain model. They are deliberately
decoupled from Yahoo's raw JSON shapes so that parsing quirks stay at the
boundary (see Validation Rules) and the MCP tool contracts stay stable.

---

## Entity: League

The single league this server is scoped to (FR-012).

| Field | Type | Notes |
|---|---|---|
| `league_key` | str | Yahoo key, e.g. `449.l.27081`. Configured, not discovered. |
| `name` | str | Display name. |
| `season` | int | e.g. 2026. |
| `num_teams` | int | Used to derive round boundaries from overall pick number. |
| `scoring_type` | str | e.g. `head`, `points`. Informational for Phase 2. |
| `draft_status` | enum | `predraft` \| `drafting` \| `postdraft` — see State Transitions. |

**Relationships**: has many `Team`; has one `Draft`.

---

## Entity: Team

| Field | Type | Notes |
|---|---|---|
| `team_key` | str | Yahoo key, e.g. `449.l.27081.t.4`. Join key for `DraftPick`. |
| `name` | str | Manager's team name. |
| `is_owned_by_user` | bool | Identifies *my* team — needed so Phase 2 can reason about "my" roster needs. |
| `standing` | int \| None | Rank; `None` pre-season. |

**Relationships**: belongs to `League`; has one `Roster`; has many `DraftPick`.

---

## Entity: Player

Identity and metadata only. Deliberately excludes availability — see the
Availability Invariant below.

| Field | Type | Notes |
|---|---|---|
| `player_id` | int | Yahoo numeric id. Primary key throughout the server. |
| `name` | str | Resolved via `player_details()`, cached for process lifetime (R4). |
| `positions` | list[str] | Eligible positions, e.g. `["RB", "W/R/T"]`. |
| `nfl_team` | str | e.g. `KC`. |
| `percent_owned` | int \| None | Ownership %, when available. Ranking context for FR-010. |
| `average_pick` | float \| None | ADP, when available. **Currently always `None`** — `yahoo_fantasy_api` has no draft-analysis/ADP endpoint (verified against source during implementation); this needs a supplementary data source to populate. Not a bug — a disclosed gap. |

**Immutability**: `player_id`, `name`, `positions`, `nfl_team` are treated as
immutable for the duration of a draft — this is what makes the R4 name cache
correct. `percent_owned` / `average_pick` are *not* cached across polls.

---

## Entity: DraftPick

One selection in the draft. The atomic unit of FR-008.

| Field | Type | Notes |
|---|---|---|
| `pick` | int | Overall pick number, 1-based. |
| `round` | int | Round number, 1-based. |
| `team_key` | str | Drafting team (FK → `Team`). |
| `player_id` | int | Drafted player (FK → `Player`). |

**Note**: Yahoo's `draft_results()` also returns `cost` for auction drafts. Auction
is out of scope (FR-013), so `cost` is intentionally **not** modeled. If an auction
league is ever configured, the server must fail loudly rather than silently
misinterpret auction data as snake data — see Validation Rules.

---

## Entity: Draft

Aggregate over `DraftPick` representing draft state at a point in time.

| Field | Type | Notes |
|---|---|---|
| `picks` | list[DraftPick] | Ordered by `pick` ascending. Empty pre-draft. |
| `retrieved_at` | datetime | **Required.** When this snapshot was read from Yahoo. |
| `is_complete` | bool | True once `len(picks) == num_teams * total_rounds`. |

**`retrieved_at` is not optional.** FR-009 bounds staleness at 5 seconds; a
consumer (and Phase 2's recommendation layer) cannot honor that bound unless
every draft snapshot carries its own read timestamp. Any tool returning draft
state MUST surface this so a caller can tell fresh data from stale.

---

## Entity: Roster

| Field | Type | Notes |
|---|---|---|
| `team_key` | str | FK → `Team`. |
| `players` | list[Player] | Currently rostered. |

---

## The Availability Invariant

There is **no `is_available` field on `Player`**, and no `AvailablePlayer`
entity is persisted. This is a deliberate modeling decision carrying the R3
finding into the data model:

> **Available players are always computed as
> `player_universe − {p.player_id for p in draft.picks}`, where `draft` is a
> snapshot whose `retrieved_at` is within the FR-009 freshness bound.**

Storing availability as state would reintroduce exactly the bug R3 identified in
the upstream library's `free_agent_cache`: a stored flag can go stale silently,
while a derived value cannot. FR-010's requirement that available players exclude
every drafted player is thereby satisfied **by construction**, and SC-002 ("zero
false-availability incidents") becomes a property of the model rather than
something enforced by discipline at each call site.

---

## State Transitions: `League.draft_status`

```
predraft  ──(first pick made)──>  drafting  ──(final pick made)──>  postdraft
```

| State | `draft.picks` | Required behavior |
|---|---|---|
| `predraft` | empty | Return empty result, **not** an error (User Story 2, scenario 3). |
| `drafting` | partial | Poll per FR-009; `retrieved_at` freshness is critical here. |
| `postdraft` | complete | Full board (User Story 2, scenario 2). Polling may stop. |

Transitions are **observed, never asserted** — the server infers state from the
pick count returned by Yahoo. It never assumes a draft has started or finished
based on wall-clock time or configuration.

---

## Validation Rules

Derived from spec requirements and edge cases:

1. **Snake-only guard (FR-013)**: if `draft_results()` returns entries carrying a
   non-null `cost`, the league is an auction draft. The server MUST raise a clear
   "auction drafts are not supported" error rather than silently modeling auction
   picks as snake picks.
2. **Monotonic picks**: `pick` values must be unique and strictly increasing
   within a snapshot. A duplicate `player_id` across two picks indicates a
   corrupt/racy read (spec edge case) and MUST be surfaced, not silently
   deduplicated.
3. **Freshness (FR-009)**: any consumer acting on draft data MUST check
   `retrieved_at`; data older than the configured bound is reported as stale
   rather than presented as current.
4. **Auth error disambiguation (FR-007)**: a 401/403 must be classified as either
   *credential-expired* or *league-not-provisioned* before surfacing. Error
   messages MUST name the condition and MUST NOT include any token value
   (constitution Principle III).
5. **Read-only (FR-014)**: no entity in this model has a persistence or write
   path back to Yahoo. The server has no code path that submits a pick.
