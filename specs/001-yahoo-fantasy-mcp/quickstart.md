# Quickstart & Validation: Yahoo Fantasy MCP Server

**Feature**: `001-yahoo-fantasy-mcp` | **Date**: 2026-08-16

How to set the server up and prove it actually works end-to-end. Scenarios below
map to spec acceptance criteria — they are the manual counterpart to the
automated tests, not a substitute for them.

---

## Prerequisites

- Python 3.11+ (`fastmcp` requires ≥3.10; repo targets 3.11).
- A Yahoo account that is a member of the target fantasy football league.
- A Yahoo Developer app (Client ID + Client Secret) with Fantasy Sports
  **read** permission. Read-only is sufficient and intentional — the server
  never writes (FR-014), so do not grant write scope.
- The league key for the single league in scope (FR-012), e.g. `449.l.27081`.

## Setup

```bash
# 1. Install dependencies
uv sync            # or: pip install -e .

# 2. Provide Yahoo app credentials (never committed — FR-002)
cp .env.example .env
$EDITOR .env       # set YAHOO_CLIENT_ID, YAHOO_CLIENT_SECRET, YAHOO_LEAGUE_KEY

# 3. One-time OAuth consent (FR-001)
uv run python -m yahoo_fantasy_mcp.auth login
```

Step 3 opens Yahoo's consent page once and writes a token file to a **gitignored**
path. After this, refresh is automatic (FR-003) — you should not need to log in
again.

**Verify nothing secret is tracked** before any commit:

```bash
git status --porcelain          # expect: no .env, no token file
git check-ignore -v .env oauth2.json
```

## Register with Claude Code

```bash
claude mcp add yahoo-fantasy -- uv run python -m yahoo_fantasy_mcp
```

Transport is stdio (R7) — nothing listens on a port and credentials never leave
the machine.

---

## Validation scenarios

Each maps to acceptance criteria in [spec.md](./spec.md). Tool shapes are defined
in [contracts/mcp-tools.md](./contracts/mcp-tools.md); entity semantics in
[data-model.md](./data-model.md).

### V1 — Auth survives token expiry (US1 scenarios 1–2, FR-003)

1. Complete setup above; call `check_auth` → `authenticated: true`.
2. Call `get_league_info` → league name/season returned.
3. Wait past access-token expiry (>1h), or fast-forward by editing the stored
   token's expiry field.
4. Call `get_league_info` again.

**Expected**: succeeds with no re-login prompt; `check_auth` shows a refreshed
`expires_in_seconds`. **No token value appears in any output or log.**

### V2 — League, teams, roster, standings (US1 scenario 3; FR-004/005/006)

Call `get_league_info`, `list_teams`, `get_roster`, `get_standings`.

**Expected**: league matches Yahoo's UI; exactly one team has
`is_owned_by_user: true`; roster matches that team's roster on Yahoo.

### V3 — Pre-draft returns empty, not an error (US2 scenario 3)

Before the draft starts, call `get_draft_results`.

**Expected**: `draft_status: "predraft"`, `picks: []`, **no error raised**. A
non-empty result or an exception here is a failure.

### V4 — Live draft freshness (US2 scenario 1; FR-008, FR-009) — *the critical one*

Run against a live draft (a Yahoo **mock draft** is the safe rehearsal; do this
before draft day, not on it).

1. Call `get_draft_results`; note `retrieved_at` and the last `pick`.
2. Compare side-by-side with Yahoo's own draft board.
3. Let several picks pass; call again.

**Expected**: picks match Yahoo's board; `pick`/`round`/`team_key` correct;
`retrieved_at` advances; no player appears who has not actually been drafted;
staleness stays within the FR-009 bound.

### V5 — Availability never contradicts the draft board (US3 scenario 1; FR-010, SC-002) — *the correctness proof*

Mid-draft, in immediate succession:

1. Call `get_draft_results` → collect all `player_id`s.
2. Call `get_available_players` (no position filter, high `limit`).
3. Intersect the two id sets.

**Expected**: **the intersection is empty.** Any overlap means availability is
being served from stale state instead of derived from the fresh draft read —
the exact `free_agent_cache` failure mode identified in
[research.md](./research.md) R3, and a direct SC-002 violation.

Repeat after 20+ further picks. A run that passes at pick 5 but fails at pick 40
is the signature of that caching bug.

### V6 — Position filter (US3 scenario 2)

Call `get_available_players` with `position: "RB"`.

**Expected**: every returned player lists `RB` in `positions`; multi-eligible
players (e.g. RB/WR) appear under each position they qualify for.

### V7 — Auth errors are distinguishable (FR-007)

- Point at a league not yet provisioned for the season → expect
  `LEAGUE_NOT_PROVISIONED`.
- Revoke access in Yahoo account settings, then call any tool → expect
  `AUTH_EXPIRED`.

**Expected**: two *distinct* error codes. Both arrive from Yahoo as a 401, so a
single generic auth error here is a FR-007 failure. Neither message may contain
a token.

### V8 — Auction draft is rejected loudly (FR-013)

Point the server at an auction-draft league (or replay an auction fixture).

**Expected**: `UNSUPPORTED_DRAFT_TYPE`. Silently treating auction `cost` data as
snake picks is a failure — partial support is worse than a clear refusal.

---

## Automated test expectations

Per constitution Principle II (test-first), these are written **before**
implementation:

| Area | Must cover |
|---|---|
| Draft parsing | `draft_results()` → `DraftPick`, incl. empty pre-draft and partial mid-draft |
| **Availability derivation** | **V5's empty-intersection invariant — the highest-value test in the suite** |
| Auth | refresh-on-expiry; `AUTH_EXPIRED` vs `LEAGUE_NOT_PROVISIONED` (FR-007) |
| Secret hygiene | no token value in any tool output or log line (FR-002) |
| Draft-type guard | auction fixture → `UNSUPPORTED_DRAFT_TYPE` |
| Freshness | `retrieved_at` present and advancing on every draft-bearing response |

Yahoo API responses are **fixtures** in unit tests — no live network calls, so
the suite is deterministic and runnable without a draft in progress.

---

## Definition of done for this feature

- [ ] V1–V8 pass manually against a real Yahoo account.
- [ ] V4 and V5 verified during a **Yahoo mock draft**, before draft day.
- [ ] Automated suite green; availability-derivation test present.
- [ ] `git log -p` contains no token, secret, or `.env` at any commit (SC-004).
- [ ] Every shipped MCP tool description matches wired behavior (FR-011).
