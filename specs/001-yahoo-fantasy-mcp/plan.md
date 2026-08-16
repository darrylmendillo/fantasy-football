# Implementation Plan: Yahoo Fantasy MCP Server

**Branch**: `001-yahoo-fantasy-mcp` | **Date**: 2026-08-16 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/001-yahoo-fantasy-mcp/spec.md`

## Summary

A locally-run, read-only MCP server (stdio) that authenticates once against the
user's Yahoo account and exposes a single configured fantasy football league:
league info, teams, rosters, standings, live draft picks, and undrafted players.

The defining technical decision came out of Phase 0 research: the upstream
`yahoo_fantasy_api` library caches `free_agents()` and `taken_players()`
**permanently, with no TTL** (research R3). Naively calling those during a live
draft would report already-drafted players as available — silently, with no
error. So this server **derives** availability as
`player_universe − drafted_ids` from a fresh, uncached `draft_results()` read,
making FR-010 and SC-002 correct by construction rather than by discipline.

Everything else follows from that: one Yahoo call per poll cycle, an immutable
player-identity cache for names, and a `retrieved_at` timestamp on every
draft-bearing response so callers can enforce the FR-009 freshness bound.

## Technical Context

**Language/Version**: Python 3.11 (`fastmcp` requires ≥3.10; local runtime 3.11.15)

**Primary Dependencies**: `fastmcp` 3.4.7 · `yahoo_fantasy_api` 2.12.3 (MIT) ·
`yahoo_oauth` 2.1.1 (MIT) — all verified on PyPI, see research R1/R7

**Storage**: No database. OAuth token JSON at a gitignored local path; in-memory
process-lifetime cache for immutable player identity only (research R4)

**Testing**: `pytest` with recorded Yahoo JSON fixtures — no live network in the
suite, so it runs deterministically without a draft in progress

**Target Platform**: Local developer machine (macOS/Linux), stdio transport

**Project Type**: Single project — MCP server library + CLI entrypoint

**Performance Goals**: Draft-pick data ≤5s stale during a live draft (FR-009);
exactly **one** Yahoo API call per poll cycle

**Constraints**: Yahoo publishes no rate limits and throttles dynamically
(research R5) → poll interval configurable, exponential backoff on throttle,
no per-poll fan-out. Read-only: no code path writes to Yahoo (FR-014)

**Scale/Scope**: Single user, single league, ~12 teams, ~200 draft picks,
~1–2 hour draft window. 7 MCP tools

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Gate | Initial | Post-Design |
|---|---|---|---|
| **I. MVP-First, Phased Delivery** | Phase 1 only (server + data). No recommendation logic, no frontend. | ✅ PASS | ✅ PASS — contract explicitly omits `recommend_pick`/`rank_players` as Phase 2 |
| **II. Test-First (NON-NEGOTIABLE)** | Tests before implementation for parsing, auth refresh, availability derivation. | ✅ PASS | ✅ PASS — quickstart names the required suite; availability-invariant test is mandatory |
| **III. No Committed Credentials** | Tokens gitignored, never logged. | ✅ PASS — `.gitignore` already covers `.env`, `oauth2.json`, `.yahoo_token.json` (incl. leading-dot variant) | ✅ PASS — `check_auth` returns booleans/duration only; error text may never carry a token |
| **IV. Honest, Wired Architecture** | Every tool description matches wired behavior; no dead code. | ✅ PASS | ✅ PASS — FR-011 encoded as global contract rule #1; no stub/aspirational tools |
| **V. Simplicity / YAGNI** | Smallest design that satisfies the spec. | ✅ PASS | ✅ PASS — no DB, no ORM, no service layer, no HTTP transport; 7 tools, flat module layout |

**Result: PASS — no violations. Complexity Tracking section omitted (nothing to justify).**

Notes on how design choices strengthened specific gates:

- **Principle IV** was the direct reason for rejecting a fork of
  `derekrbreese/fantasy-football-mcp-public`, which ships ~2,100 lines of
  unwired "strategy" code its docs present as live, plus a real OAuth token in
  git history (also a Principle III violation).
- **Principle II** has a concrete high-value target here: the empty-intersection
  test between `get_draft_results` and `get_available_players` (quickstart V5) is
  the machine-checkable form of SC-002.

## Project Structure

### Documentation (this feature)

```text
specs/001-yahoo-fantasy-mcp/
├── plan.md              # This file
├── spec.md              # Feature specification
├── research.md          # Phase 0 output — library choice, caching hazard, rate limits
├── data-model.md        # Phase 1 output — entities + Availability Invariant
├── quickstart.md        # Phase 1 output — setup + V1–V8 validation scenarios
├── contracts/
│   └── mcp-tools.md     # Phase 1 output — MCP tool surface + ErrorCode enum
├── checklists/
│   └── requirements.md  # Spec quality checklist (all green)
└── tasks.md             # Phase 2 output (/speckit-tasks — NOT created here)
```

### Source Code (repository root)

```text
src/yahoo_fantasy_mcp/
├── __init__.py
├── __main__.py          # stdio entrypoint (python -m yahoo_fantasy_mcp)
├── auth.py              # OAuth login + refresh; 401 disambiguation (FR-001/003/007)
├── client.py            # Yahoo API boundary: raw JSON in, domain models out
├── models.py            # League, Team, Player, DraftPick, Draft, Roster
├── draft.py             # Draft snapshot + availability derivation (R3 — the core logic)
├── errors.py            # ErrorCode enum + typed exceptions
├── config.py            # Env/config loading (league key, poll interval)
└── server.py            # FastMCP tool definitions (the 7 tools)

tests/
├── fixtures/            # Recorded Yahoo JSON: predraft, mid-draft, postdraft, auction
├── unit/
│   ├── test_models.py
│   ├── test_draft.py    # incl. the availability-invariant test (SC-002)
│   ├── test_auth.py     # refresh; AUTH_EXPIRED vs LEAGUE_NOT_PROVISIONED
│   └── test_errors.py   # no-token-in-output (FR-002)
└── integration/
    └── test_tools.py    # MCP tool contract conformance against fixtures
```

**Structure Decision**: Single project, flat module layout under
`src/yahoo_fantasy_mcp/`. No `services/`, no `repositories/`, no layered
abstraction — Principle V (YAGNI) for a single-user, single-league,
seven-tool, no-database server. The one deliberate separation is
`client.py` (Yahoo's messy JSON shapes) from `models.py` (our domain
types), so upstream parsing quirks stay at the boundary and don't leak into
the tool contract.

`draft.py` is called out as its own module because it holds the
availability-derivation logic that research R3 identified as the highest-risk
correctness area in this feature — it deserves an obvious home and a dedicated
test file, not to be buried in `client.py`.

## Phase Status

- [x] **Phase 0** — `research.md`: 7 findings (R1–R7); all NEEDS CLARIFICATION resolved
- [x] **Phase 1** — `data-model.md`, `contracts/mcp-tools.md`, `quickstart.md`
- [ ] **Phase 2** — `tasks.md` (run `/speckit-tasks`)

## Key Risks Carried Into Implementation

| Risk | Mitigation | Source |
|---|---|---|
| Upstream cache silently serves stale availability | Derive availability from fresh `draft_results()`; never call `free_agents()` in the live path; V5 test asserts empty intersection | R3 |
| Yahoo throttles mid-draft (limits undocumented) | Configurable interval, exponential backoff, 1 call/poll, name cache prevents N+1 | R5 |
| Both auth failures arrive as 401 | Explicit `AUTH_EXPIRED` vs `LEAGUE_NOT_PROVISIONED` classification + tests | R6, FR-007 |
| Auction league misread as snake | Guard on `cost` field → `UNSUPPORTED_DRAFT_TYPE`, fail loudly | data-model rule 1, FR-013 |
| Draft-day discovery of any of the above | **Rehearse V4/V5 in a Yahoo mock draft before draft day** | quickstart |
