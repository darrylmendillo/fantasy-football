# Phase 0 Research: Yahoo Fantasy MCP Server

**Feature**: `001-yahoo-fantasy-mcp` | **Date**: 2026-08-16

All findings below were verified against upstream source code and PyPI metadata,
not vendor documentation or blog posts.

---

## R1: Yahoo API client library

**Decision**: `yahoo_fantasy_api` 2.12.3 (MIT), by Matt Spilchen.

**Rationale**:

- **MIT licensed** — the only clean license of the three candidates.
- Actively maintained (last release 2026-04-03) and owned end-to-end by one
  maintainer who also ships an MCP server against it, so API drift is caught.
- Supports every endpoint this spec needs: `draft_results()`, `free_agents()`,
  `taken_players()`, `player_details()`, `percent_owned()`, `standings()`,
  `teams()`, plus `Team.roster()`.
- Thin, readable wrapper (~1k LOC core) — the internals are auditable, which
  matters given R3 below.

**Alternatives considered**:

| Library | Why rejected |
|---|---|
| `yfpy` (uberfastman) | **GPL-3.0** — copyleft. Fine for private use, but constrains any future redistribution of the Oracle-hosted app (constitution Phase 3). More stars (258) but licensing risk is not worth it when the MIT option covers our endpoints. |
| `yahoofantasy` (mattdodge) | **No LICENSE file and no license declared** in README or `pyproject.toml` — legally all-rights-reserved. Disqualifying regardless of code quality. |
| Fork an existing Yahoo MCP server | Reviewed in prior research: the most feature-complete one (`derekrbreese/fantasy-football-mcp-public`) has a live OAuth token committed to git history and ~2,100 lines of unwired "strategy" code that its docs present as live. Violates constitution Principles III and IV. |

---

## R2: Draft-pick retrieval (FR-008, FR-009)

**Decision**: Poll `League.draft_results()` as the single source of truth for
draft state.

**Rationale** — verified in `yahoo_fantasy_api/league.py:731-775`:

- Returns exactly the fields FR-008 requires:
  ```python
  {'pick': 1, 'round': 1, 'cost': '4', 'team_key': '388.l.27081.t.4', 'player_id': 9490}
  ```
- **Uncached** — unlike most of this library's methods, `draft_results()` hits
  `league/{id}/draftresults` on every call. Safe to poll (see R3 for why this
  is not true of the other methods).
- Upstream docstring confirms both live-draft behaviors the spec depends on:
  - *"If this is called during the draft this includes the players that have
    been drafted thus far"* → satisfies FR-009 / User Story 2 scenario 1.
  - *"If this is called for a league that has not yet done a draft then it will
    return an empty list"* → satisfies User Story 2 scenario 3 (empty, not
    error).

**Consequence**: `draft_results()` returns `player_id` only — **no player name**.
Names must be resolved separately (see R4).

---

## R3: ⚠️ Availability must be *derived*, not read (FR-010, SC-002)

**Decision**: Compute available players as
`player_universe − {player_id from fresh draft_results()}`.
**Do NOT call `free_agents()` per poll during a live draft.**

**Rationale** — this is the highest-risk finding of Phase 0. Verified in
`yahoo_fantasy_api/league.py:297-321` and `:360-379`:

```python
def free_agents(self, position):
    if position not in self.free_agent_cache:          # ← populated once
        self.free_agent_cache[position] = self._fetch_players('FA', position=position)
    return self.free_agent_cache[position]             # ← returned forever after

def taken_players(self):
    if not self.taken_players_cache:                   # ← populated once
        self.taken_players_cache = self._fetch_players('T')
    return self.taken_players_cache
```

Both caches are **unbounded and have no TTL and no invalidation path**. On a
long-lived `League` object — exactly what an MCP server holds — the first
`free_agents('RB')` call is frozen for the process lifetime. During a live
draft that means a player drafted at pick 30 would still be reported available
at pick 80.

That is a direct violation of **FR-010** ("excluding every player already
returned by FR-008") and would break **SC-002** ("zero false-availability
incidents"), silently — the call returns a plausible-looking list, not an error.
This is precisely the failure mode SC-002 was written to prevent.

Deriving availability from the uncached `draft_results()` makes FR-010 correct
**by construction**: a player cannot appear in both the drafted set and the
available set, because the available set is defined as the complement of the
drafted set from the same fresh read.

**Alternatives considered**:

- *Construct a fresh `League` object per poll to bypass the cache*: works, but
  re-fetches settings/positions/stat-categories on every poll (more API calls
  against an undocumented rate limit, see R5), and depends on library-internal
  caching behavior that could change. Rejected as both wasteful and fragile.
- *Monkey-patch / clear the cache dicts between polls*: reaches into library
  internals; brittle across versions. Rejected.
- *Upstream a TTL to the library*: correct long-term, but blocks our draft on a
  third-party merge. Out of scope for this MVP; the derivation approach needs
  no upstream change.

---

## R4: Player identity resolution

**Decision**: Resolve `player_id` → name/position via `League.player_details()`,
and cache it for the process lifetime.

**Rationale**: A player's id→name/position mapping is **immutable** for the
duration of a draft, so caching it is correct here — unlike the R3 caches, which
cache *mutable* availability state. The library's own `player_details_cache` is
therefore safe to rely on for this purpose.

This also matters for R5: without a name cache, every poll would trigger N
detail lookups, turning a 1-call poll into an N+1 storm against an undocumented
rate limit.

---

## R5: Polling interval and rate limiting (FR-009)

**Decision**: Default 5s poll, **configurable**, with exponential backoff on
throttle responses. Exactly **one** API call per poll cycle.

**Rationale**: Yahoo publishes **no documented rate limit**. Their developer
guide states only that usage may be throttled if "excessive over short periods."
Real-world reports (e.g. `uberfastman/yfpy` issue #51) show developers hitting
connection-level throttling — `Remote end closed connection without response` —
under sustained request volume.

Budget check: 5s polling ≈ 720 calls/hour; a typical snake draft runs 1–2 hours,
so ~720–1,440 calls total for the draft. Plausible, but not something to gamble
a live draft on with no fallback. Therefore:

- The interval MUST be configurable, not hardcoded (so it can be relaxed live).
- Throttle/5xx responses MUST trigger exponential backoff rather than a tight
  retry loop.
- A poll cycle MUST issue exactly one Yahoo call (`draft_results()`); name
  resolution comes from the R4 cache, and availability is derived locally per
  R3 — no per-poll fan-out.

**Risk accepted & documented**: if Yahoo throttles harder than expected mid-draft,
the mitigation is to widen the interval (config change), degrading freshness
rather than failing. The spec's 5s figure in FR-009 is a target, not a guarantee
Yahoo contractually provides.

---

## R6: OAuth2, token refresh, and the 401 disambiguation (FR-001, FR-002, FR-003, FR-007)

**Decision**: Use `yahoo_oauth` 2.1.1 (MIT) as the auth layer, with the token
file stored at a gitignored local path.

**Rationale** — verified in `yahoo_fantasy_api/yhandler.py`:

- `yahoo_oauth` performs the one-time browser consent flow (FR-001) and persists
  tokens to a JSON file; the library calls `sc.refresh_access_token()`
  automatically on detecting expiry, satisfying **FR-003** with no user
  interaction.
- The token file (`oauth2.json`) and `.yahoo_token.json` are **already covered by
  this repo's `.gitignore`**, satisfying **FR-002**. Note the leading-dot variant
  is explicitly listed — the exact gitignore-mismatch bug that leaked a real
  token in `derekrbreese/fantasy-football-mcp-public`.
- `YHandler._is_token_expired_error()` inspects 401/403 bodies for
  `token_expired` / `oauth_problem` markers, distinguishing credential expiry
  from other 401s. This is the hook **FR-007** needs to separate "league not yet
  provisioned for the season" from "your credentials expired." Independent
  corroboration that FR-007 is a real-world failure mode and not a hypothetical:
  the derekrbreese repo carries a commit titled *"Distinguish Yahoo provisioning
  401s from expired-token 401s."*

**Security posture**: tokens are never logged (constitution Principle III). The
server MUST NOT echo token values in error messages, which is a real hazard when
surfacing FR-007's disambiguated auth errors — error text must name the
*condition*, never the credential.

---

## R7: MCP framework and runtime

**Decision**: `fastmcp` 3.4.7 on Python 3.11, stdio transport.

**Rationale**:

- `fastmcp` 3.4.7 published 2026-08-10 (actively maintained), `requires_python
  >=3.10`; local runtime is Python 3.11.15 — compatible.
- Mandated by the project constitution's Technology & Integration Constraints.
- **stdio** transport is the correct choice for a locally-run, single-user tool
  that holds the user's personal OAuth credentials — no network listener, no
  exposed port, credentials never leave the machine. (A future HTTP transport
  would be a Phase 3 concern when the Oracle-hosted frontend arrives, and would
  need its own auth story — explicitly out of scope here.)

---

## Resolved unknowns summary

| Unknown | Resolution |
|---|---|
| Which Yahoo library | `yahoo_fantasy_api` 2.12.3 (MIT) — R1 |
| Can it read live draft picks | Yes, `draft_results()`, uncached, partial mid-draft — R2 |
| How to keep availability correct | Derive from fresh draft results; never trust `free_agents()` cache — R3 |
| How to get player names | `player_details()` + process-lifetime cache (immutable data) — R4 |
| Is 5s polling safe | Undocumented limits; 5s configurable + backoff + 1 call/poll — R5 |
| How auth/refresh works | `yahoo_oauth` auto-refresh; gitignored token file — R6 |
| MCP framework/transport | `fastmcp` 3.4.7, stdio, Python 3.11 — R7 |

**No unresolved NEEDS CLARIFICATION items remain.**
