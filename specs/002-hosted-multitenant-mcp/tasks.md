---

description: "Task list for 002-hosted-multitenant-mcp"
---

# Tasks: Hosted Multi-Tenant Fantasy MCP Server

**Input**: Design documents from `/specs/002-hosted-multitenant-mcp/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/mcp-tools.md, quickstart.md

**Tests**: REQUIRED. Constitution v0.2.0 Principle II is NON-NEGOTIABLE and explicitly extends TDD to "the OAuth-proxy/multi-tenancy logic and the write-confirmation flow." Tests are written first and confirmed failing before implementation.

**Organization**: Tasks grouped by user story so each is independently implementable and testable.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (US1–US5)
- Exact file paths included in every task

## Path Conventions

Single project: `src/yahoo_fantasy_mcp/`, `tests/` at repository root.

---

## ⚠️ RELEASE GATES — two tiers (constitution v0.3.0, Principle I)

Implementation proceeds to **mock-validated** tier now. **Integration-validated** tier is gated on external approval. Nothing is "done," "working," or deployable until integration-validated — a passing mock proves our code is self-consistent, never that Yahoo's contract was understood correctly.

**Buildable now (mock-validated)** — no Yahoo approval required:

- Phases 1–2 in full; US1/US2 logic against fixtures; the entire confirm rail and its adversarial tests
- Protocol-level verification via **MCP Inspector**: OAuth metadata discovery, DCR/PKCE endpoints, tool schemas, and the full annotation matrix
- **Stop line for this pass**: T046 (`change_positions` dispatch). Its signature is unverified (research R5) and Principle I now forbids implementing against a guessed shape — verify against a real team first, then write

**Gated on external approval (integration-validated)**:

- [ ] **G1** Yahoo API Access Application approved for the operator's Client ID (<https://sports.yahoo.com/developer/access/>). **Read (`fspt-r`) unblocks live US1/US2 validation. Read+write (`fspt-w`) required for US3/US4/US5 dispatch.**
- [ ] **G2** Phase 1 (spec 001) validated end-to-end against a real Yahoo account — spec 001 task T055.
- [ ] **G3** Live verification of unverified interface shapes from research R5/R1/R3 — `change_positions` `time_frame`/`modified_lineup`, Yahoo userinfo response, `openid`+`fspt-w` co-request behavior. **Blocks T046 specifically.**

**Time-sensitive**: run quickstart **V9** (`WRITE_NOT_APPROVED` path) *before* write approval lands — that state is unreproducible afterward.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Dependency and skeleton changes needed by everything downstream.

- [X] T001 Update `pyproject.toml`: add `requests`, confirm `fastmcp>=3.4.7`, and move `yahoo_oauth` to an optional/local-only extra (research R6 removes it from the hosted path)
- [X] T002 [P] Create empty modules with docstrings only: `src/yahoo_fantasy_mcp/auth_proxy.py`, `session.py`, `store.py`, `confirm.py`, `tools_read.py`, `tools_write.py`
- [X] T003 [P] Rewrite `.env.example`: remove `YAHOO_LEAGUE_KEY`; add `PUBLIC_BASE_URL`, `PORT`, `DB_PATH`, `PROPOSAL_TTL_SECONDS`, `YAHOO_SCOPE`
- [X] T004 [P] Add shared test helpers in `tests/conftest.py`: fake clock, in-memory store factory, and two fake identities (`sub_a`, `sub_b`) for isolation tests

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Multi-tenancy, auth, transport, and persistence. **No user story can begin until this is complete.**

**⚠️ CRITICAL**: This phase dismantles the single-tenant `ServerContext` singleton in `server.py`. Nothing works until it is done.

### Tests first

- [X] T005 [P] Unit tests for server config in `tests/unit/test_config.py` — asserts no per-user/league fields, required vars named in errors, no secret values in messages
- [X] T006 [P] Unit tests for `store.py` in `tests/unit/test_store.py` — user upsert idempotency, usage append, proposal lifecycle per data-model.md state machine
- [X] T007 [P] Unit tests for the Yahoo session adapter in `tests/unit/test_session_adapter.py` — asserts `.session` carries the Bearer header AND that the adapter has **no** `refresh_access_token` attribute (research R6: prevents double-refresh races)
- [X] T008 [P] Unit tests for per-user cache isolation in `tests/unit/test_client_cache_isolation.py` — two leagues/users must not share cached player identity or universe entries

### Implementation

- [X] T009 Rewrite `src/yahoo_fantasy_mcp/config.py`: server-level `ServerConfig` only (base URL, port, client id/secret, db path, proposal TTL, scope); delete `league_key` and `token_path`
- [X] T010 Implement SQLite schema and accessors in `src/yahoo_fantasy_mcp/store.py` per data-model.md — `users`, `usage_events`, `proposals` tables with indices on `token_hash` and `sub`
- [X] T011 [P] Implement `YahooSessionAdapter` in `src/yahoo_fantasy_mcp/session.py` — wraps a `requests.Session` with `Authorization: Bearer <token>`; deliberately omits `refresh_access_token`
- [X] T012 [P] Extend `src/yahoo_fantasy_mcp/errors.py` with the contract's error codes: `LeagueNotAccessibleError`, `SportNotSupportedError`, `WriteNotApprovedError`, `InvalidConfirmationError`, `ProposalExpiredError`, `ProposalAlreadyUsedError`, `PreconditionsChangedError`, `TradeInitiationNotSupportedError`
- [X] T013 Implement `YahooTokenVerifier` in `src/yahoo_fantasy_mcp/auth_proxy.py` — validates the opaque Yahoo token via userinfo and returns `sub` (research R3/R4), modeled on FastMCP's `GitHubTokenVerifier`
- [X] T014 Implement `build_auth_proxy()` in `src/yahoo_fantasy_mcp/auth_proxy.py` — `OAuthProxy` wired to `request_auth`/`get_token` with the configured scope (research R1)
- [X] T015 Implement `resolve_identity()` in `src/yahoo_fantasy_mcp/session.py` — `get_access_token().token` → Yahoo token + `sub`; upserts the user row (research R2). **MUST NOT** accept any caller-supplied identity
- [X] T016 Implement `resolve_league_context()` in `src/yahoo_fantasy_mcp/session.py` — builds `Game`/`League`/`Team` per request, validates league membership (raises `LeagueNotAccessibleError`) and football-only (raises `SportNotSupportedError`)
- [X] T017 ✅ **NO FIX NEEDED — claim withdrawn.** Investigated re-keying `client.py` caches. The premise was wrong: caches are per-INSTANCE (`client.py:175,178`), not per-process, and per-request construction already isolates users. T008's tests pass against unmodified code. Tests retained as a regression guard for future pooling/memoisation. Real residual risk is the inverse (universe re-seeded per request → rate limits, spec 001 R5) — logged, not fixed
- [X] T018 Add usage recording in `src/yahoo_fantasy_mcp/server.py` — one `usage_events` row per tool call including refusals; records tool name and outcome only, never arguments (data-model.md)
- [X] T019 Rewrite `src/yahoo_fantasy_mcp/__main__.py` — HTTP transport via `mcp.run(transport="http", …)`, auth provider attached, no `build_context()` singleton

**Checkpoint**: Server starts over HTTP, presents OAuth metadata, and resolves a per-request identity. User stories can begin.

---

## Phase 3: User Story 1 — Connect a Yahoo account (Priority: P1) 🎯 MVP

**Goal**: A user adds the server in Claude or ChatGPT, signs in with Yahoo, and their assistant can see their leagues — no local setup, no credential files.

**Independent Test**: From a fresh assistant, add the server URL, complete sign-in, ask "what fantasy leagues am I in?" and get that user's correct leagues.

### Tests for User Story 1 ⚠️ write first, confirm failing

> **Task 10 reconciliation note (2026-08-18):** T020–T023 specify exact filenames that
> the actual SDD execution consolidated differently — the coverage genuinely exists,
> just organized per-implementation-task rather than per-original-task-number. Checked
> off where real, reviewed coverage exists; file mapping given inline. This is a
> deliberate organizational choice made and reviewed during Tasks 1–9b, not an
> unverified claim — see `.superpowers/sdd/2026-08-17-hosted-multitenant-mcp-execution/progress.md`
> for the review trail of each.

- [X] T020 [P] [US1] Contract test — actual coverage: `tests/unit/test_auth_proxy_build.py` (endpoints/scopes wired correctly, Task 2, reviewed) plus this task's own live `curl` verification against a running server (quickstart.md "MCP Inspector verification" section) — no dedicated `tests/contract/test_oauth_metadata.py` file exists
- [X] T021 [P] [US1] Integration test — actual coverage: `tests/integration/test_us1_tools.py` (Task 5, reviewed)
- [X] T022 [P] [US1] Integration test — actual coverage: `tests/unit/test_session_resolution.py` (Task 3, membership/refusal logic), `tests/unit/test_discover_leagues.py::test_each_users_token_produces_an_independently_constructed_game` (Task 9a), and `tests/integration/test_tool_wiring.py::test_confirm_action_rejects_a_different_users_token` (Task 9b fix round — the adversarial cross-tenant case, reviewed twice)
- [ ] T023 [P] [US1] Integration test — **genuinely not covered.** No test exercises a revoked/expired upstream token surfacing `AUTH_EXPIRED` with reconnect guidance; see T027 below, the same real gap.

### Implementation for User Story 1

- [X] T024 [US1] Implement `check_auth` in `src/yahoo_fantasy_mcp/tools_read.py` per contracts — no token value in any field
- [X] T025 [US1] Implement `list_leagues` in `src/yahoo_fantasy_mcp/tools_read.py` using `Game.league_ids()`, returning `league_key`/`name`/`sport`/`season`/`is_supported`/`team_key`/`team_name` (research R5)
- [X] T026 [US1] Register both tools with `readOnlyHint=true`, `openWorldHint=true` annotations in `src/yahoo_fantasy_mcp/server.py` (FR-024)
- [ ] T027 [US1] **Genuine, unclosed gap — verified, not just left over.** `_current_identity` (server.py) raises `AuthRequiredError` when a token is missing/unidentifiable, but nothing maps a Yahoo `401` that indicates a *revoked/expired* upstream session (as opposed to a not-yet-provisioned league) to `AUTH_EXPIRED` reusing Phase 1's `classify_auth_failure` — that function exists (`auth.py`) but is never called from the new `auth_proxy.py`/`server.py` path. Plausible reason this is smaller than it looks: `OAuthProxy` already handles token refresh transparently (Task 2), so the case this task defends against is narrower now (a genuinely *revoked* grant, not routine expiry) — but it is still unhandled. Real work for a follow-up task, not integration-gated.
- [ ] T028 [US1] **Genuine, unclosed gap.** `mask_secrets` itself is tested generically (`tests/unit/test_errors.py`), but no test specifically asserts it covers the log call sites added across Tasks 1–9b (`auth_proxy.py`, `session.py`, `confirm.py`, `server.py`). Worth a follow-up test before this ships past mock-validated tier.

**Checkpoint**: US1 fully functional. Run quickstart V1, V2, V3, V10. **This is the MVP** — a real user can connect and see their leagues.

---

## Phase 4: User Story 2 — See any of my leagues (Priority: P2)

**Goal**: All Phase 1 read capabilities work against any league the user belongs to, selected per request.

**Independent Test**: A user in ≥2 leagues requests standings in each by name and gets correct, distinct results.

### Tests for User Story 2 ⚠️ write first, confirm failing

- [X] T029 [P] [US2] Integration tests — actual coverage: `tests/integration/test_us2_reads.py` (Task 6, reviewed; fixed one real return-shape defect during review)
- [X] T030 [P] [US2] Integration test — actual coverage: `tests/unit/test_session_resolution.py::test_non_football_league_is_refused_as_unsupported` (Task 3; rewritten during the final whole-branch review, Finding 2, to call the real `resolve_request_league_context` in `session.py` — the version this test exercised previously called a same-shaped but dead sibling function that no registered tool ever invoked, so this assertion had zero coverage on the live path until the rewrite) plus `discover_leagues`' `is_supported` field (Task 9a) — `list_leagues` lists non-football leagues, other tools refuse them
- [X] T031 [P] [US2] Regression test — actual coverage: `tests/integration/test_us2_reads.py::test_availability_invariant_holds_deep_into_draft` (Task 6, reviewer independently constructed an adversarial midraft-vs-postdraft scenario and confirmed it catches a real regression)

### Implementation for User Story 2

- [X] T032 [P] [US2] Port `get_league_info` and `list_teams` to `src/yahoo_fantasy_mcp/tools_read.py`, parameterized by `league_key`
- [X] T033 [P] [US2] Port `get_roster` and `get_standings` to `src/yahoo_fantasy_mcp/tools_read.py` (`team_key` optional, defaults to caller's team)
- [X] T034 [US2] Port `get_draft_results` and `get_available_players` to `src/yahoo_fantasy_mcp/tools_read.py`, deriving `total_expected_picks` from league settings rather than a global env var
- [X] T035 [US2] Register all read tools with correct annotations in `src/yahoo_fantasy_mcp/server.py`
- [X] T036 [US2] Delete the now-unused single-tenant tool bodies and `ServerContext` from `src/yahoo_fantasy_mcp/server.py` (Principle IV — no dead code implying it's live)

**Checkpoint**: US1 + US2 both work. Run quickstart V4. Read-only product is complete and shippable.

---

## Phase 5: User Story 3 — Set my lineup, with confirmation (Priority: P3) 🔒 requires G1 write approval

**Goal**: Lineup changes reach Yahoo only after an explicit, server-enforced confirmation.

**Independent Test**: Propose a lineup change, verify Yahoo is unchanged, confirm, verify it applied.

### Tests for User Story 3 ⚠️ write first, confirm failing

- [X] T037 [P] [US3] Unit tests for the confirm rail — actual coverage: `tests/unit/test_confirm.py` (Task 7). All five refusals present and independently mutation-tested twice over — once by the implementer (wrong-user, expiry guards) and once by the controller (precondition-drift, atomic-consume guards) — every mutation produced the expected test failure.
- [X] T038 [P] [US3] Unit test — actual coverage: `tests/unit/test_confirm.py::TestTokenStorage::test_raw_token_is_never_stored` (Task 7)
- [X] T039 [P] [US3] Unit test — actual coverage: `tests/unit/test_store.py::test_second_consume_fails` plus the `mark_status` race-condition fix and its regression test (Task 7, fix round 1) — atomicity holds; "crash mid-write" specifically is not simulated (SQLite's own transaction commit is trusted, not independently fault-injected)
- [ ] T040 [P] [US3] **Not literally done — correctly, given T046 is blocked.** No test dispatches a real `change_positions` call, because no code does (T046/gate G3). What IS tested: propose issues no write, and confirm dispatches through the `LineupWriter` seam exactly once, ending in `WriteNotApprovedError` (`tests/integration/test_us3_write.py`, Task 8) — the same guarantee, against the blocked-writer stand-in. Re-verify against a real `change_positions` call once T046 unblocks.
- [X] T041 [P] [US3] Contract test — actual coverage: `tests/contract/test_tool_annotations.py` (Task 9b) — this one exists at exactly the filename specified. All 10 registered tools verified: reads + `propose_set_lineup` non-destructive, `confirm_action` the sole destructive tool.

### Implementation for User Story 3

- [X] T042 [US3] Implement proposal creation in `src/yahoo_fantasy_mcp/confirm.py` — `secrets.token_urlsafe(32)`, store SHA-256 hash, TTL from config, snapshot preconditions
- [X] T043 [US3] Implement `verify_and_consume()` in `src/yahoo_fantasy_mcp/confirm.py` — enforces the six checks from data-model.md atomically; returns `INVALID_CONFIRMATION` identically for unknown-token and wrong-user (contracts: must not reveal token existence)
- [X] T044 [US3] Implement precondition re-verification for `set_lineup` in `src/yahoo_fantasy_mcp/confirm.py` — compares current roster/slots against the snapshot
- [X] T045 [US3] Implement `propose_set_lineup` in `src/yahoo_fantasy_mcp/tools_write.py` per contracts, including `warnings` (e.g. bye week) surfaced pre-confirmation
- [ ] T046 [US3] 🚧 **BLOCKED ON G3 — do not implement in the mock-validated pass.** Add `set_lineup` write dispatch in `src/yahoo_fantasy_mcp/client.py` via `Team.change_positions`. The `time_frame`/`modified_lineup` shape is unverified (research R5); constitution Principle I forbids implementing against a guessed signature. Verify against a real team, then write. Until then `confirm_action` dispatches through a seam that raises `WRITE_NOT_APPROVED`
- [X] T047 [US3] Implement `confirm_action` in `src/yahoo_fantasy_mcp/tools_write.py` — the single write path; annotated `destructiveHint=true`
- [X] T048 [US3] Implement `WRITE_NOT_APPROVED` handling in `src/yahoo_fantasy_mcp/tools_write.py` — distinguishes missing Yahoo write scope from an invalid request (FR-025)

**Checkpoint**: US3 works. Run quickstart V5 and **V6 with host tool-approval prompts disabled** — that is what proves the guarantee lives in the server, not the host UI.

---

## Phase 6: User Story 4 — Add and drop players (Priority: P4) 🔒 requires G1 write approval

**Goal**: Waiver/free-agent moves on the proven confirm rail, applied atomically.

**Independent Test**: Propose an add/drop, verify no change pre-confirmation, confirm, verify both halves in Yahoo.

### Tests for User Story 4 ⚠️ write first, confirm failing

- [ ] T049 [P] [US4] Integration test in `tests/integration/test_propose_add_drop.py` — a combined move dispatches `add_and_drop_players` **exactly once**, never two separate calls (FR-022, research R5)
- [ ] T050 [P] [US4] Unit test in `tests/unit/test_confirm_add_drop_preconditions.py` — a player claimed by someone else between propose and confirm yields `PRECONDITIONS_CHANGED` **and no drop occurs** (quickstart V7)
- [ ] T051 [P] [US4] Unit test in `tests/unit/test_roster_size_warning.py` — an over-limit roster is warned about at propose time, not failed at confirm time (spec US4 sc.4)

### Implementation for User Story 4

- [ ] T052 [US4] Implement `propose_add_drop` in `src/yahoo_fantasy_mcp/tools_write.py` per contracts, including `resulting_roster_size` and `warnings`
- [ ] T053 [US4] Implement add/drop precondition snapshot and re-verification in `src/yahoo_fantasy_mcp/confirm.py` — availability of the add, rostered status of the drop
- [ ] T054 [US4] Add write dispatch in `src/yahoo_fantasy_mcp/client.py` for `add_player`, `drop_player`, and `add_and_drop_players`; route combined moves to the single-transaction call
- [ ] T055 [US4] Add optional FAAB support via `claim_player`/`claim_and_drop_players` in `src/yahoo_fantasy_mcp/client.py` when `faab_bid` is supplied

**Checkpoint**: US1–US4 work. Run quickstart V7.

---

## Phase 7: User Story 5 — Respond to trade offers (Priority: P5) 🔒 requires G1 write approval

**Goal**: Review incoming trade offers and accept or reject them, with confirmation.

**Independent Test**: With a real pending offer, list it, verify both sides are described, respond after confirmation, verify in Yahoo.

### Tests for User Story 5 ⚠️ write first, confirm failing

- [ ] T056 [P] [US5] Integration test in `tests/integration/test_trade_offers.py` — `list_trade_offers` returns both sides of each offer; accept and reject dispatch the right call
- [ ] T057 [P] [US5] Unit test in `tests/unit/test_trade_preconditions.py` — an offer withdrawn or resolved elsewhere between propose and confirm yields `PRECONDITIONS_CHANGED` (spec US5 sc.4)
- [ ] T058 [P] [US5] Unit test in `tests/unit/test_trade_initiation_refused.py` — an outbound-trade request raises `TradeInitiationNotSupportedError` with a plain-language message (spec US5 sc.5)

### Implementation for User Story 5

- [ ] T059 [P] [US5] Implement `list_trade_offers` in `src/yahoo_fantasy_mcp/tools_read.py` via `Team.proposed_trades()`
- [ ] T060 [US5] Implement `propose_trade_response` in `src/yahoo_fantasy_mcp/tools_write.py` per contracts
- [ ] T061 [US5] Implement trade precondition snapshot/re-verification in `src/yahoo_fantasy_mcp/confirm.py` — `transaction_key` + offer status
- [ ] T062 [US5] Add `accept_trade`/`reject_trade` dispatch in `src/yahoo_fantasy_mcp/client.py`; deliberately do **not** wire `propose_trade` (out of scope, spec Scope Decisions)

**Checkpoint**: All user stories functional. Run quickstart V8.

---

## Phase 8: Polish, Deployment & Cross-Cutting Concerns

- [ ] T063 [P] Full-suite secret scan test in `tests/unit/test_no_secret_leakage.py` — no credential appears in any tool output, log line, or error message across every tool (FR-026, SC-005)
- [ ] T064 [P] **Partially done, correctly left unchecked.** `README.md` was rewritten for the hosted product (connect-by-URL instructions for Claude/ChatGPT, operator-only setup with no per-user developer credentials) — those pieces of this task are done. Two pieces are NOT: **FR-013** (formal Yahoo attribution wording — the README mentions "Yahoo Fantasy Football" as context, but nobody has researched what Yahoo's actual required attribution language/notice is, so this isn't verified compliance, just incidental mention) and **FR-030** (the package/repo/product name is still `yahoo-fantasy-mcp`, which leads with "Yahoo" — exactly what FR-030 prohibits; the product name was deliberately left open earlier and has not been decided). Do not check this box until both are resolved.
- [ ] T065 [P] Add Yahoo Fantasy attribution to tool output/docs per Yahoo's branding requirements (FR-013)
- [ ] T066 Provision TLS + public hostname on the Oracle server and document it in `docs/deploy.md` (FR-029)
- [ ] T067 Add systemd unit and restart/backup runbook in `docs/deploy.md`; verify tokens survive restart and pending proposals fail closed rather than silently succeeding (quickstart operational checks)
- [ ] T068 Verify tier and usage recording end-to-end against the live DB — every tool call produces a row; confirm no limits are enforced in this release (FR-028)
- [ ] T069 Run the full quickstart V1–V10 against the deployed server with two real Yahoo accounts and record results in `specs/002-hosted-multitenant-mcp/quickstart.md`
- [ ] T070 Delete or clearly quarantine the local stdio path (`auth.py`, old `server.py` bodies) so no dead code implies a live capability (Principle IV)

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: no dependencies
- **Foundational (Phase 2)**: depends on Setup — **blocks all user stories**
- **US1 (Phase 3)**: depends on Foundational. Requires **G1 read approval** + **G2**
- **US2 (Phase 4)**: depends on Foundational. Independent of US1's tools but shares identity/league resolution
- **US3 (Phase 5)**: depends on Foundational. Requires **G1 write approval**. Builds the confirm rail US4/US5 reuse
- **US4 (Phase 6)**: depends on Foundational + **T042–T043** (confirm rail from US3)
- **US5 (Phase 7)**: depends on Foundational + **T042–T043** (confirm rail from US3)
- **Polish (Phase 8)**: depends on all desired stories

### Story Dependency Note

US4 and US5 are *not* fully independent of US3: they reuse the confirm rail (T042–T043), which US3 builds. This is deliberate — building three parallel confirmation mechanisms would be the larger risk. US3 is therefore the mandatory first write story; US4 and US5 can then proceed in parallel with each other.

### Parallel Opportunities

- All Setup tasks T002–T004 in parallel
- Foundational tests T005–T008 in parallel; then T011/T012 in parallel
- All tests within any story phase (marked [P]) in parallel
- Once the confirm rail exists, **US4 and US5 can be built simultaneously by different people**
- Polish tasks T063–T065 in parallel

---

## Parallel Example: User Story 1

```bash
# All US1 tests together (write first, confirm failing):
Task: "Contract test for OAuth metadata in tests/contract/test_oauth_metadata.py"
Task: "Integration test for check_auth in tests/integration/test_check_auth.py"
Task: "Integration test for tenant isolation in tests/integration/test_tenant_isolation.py"
Task: "Integration test for auth errors in tests/integration/test_auth_errors.py"
```

---

## Implementation Strategy

### MVP First (US1 only)

1. Phase 1 Setup → Phase 2 Foundational
2. Phase 3 US1
3. **STOP and VALIDATE**: quickstart V1, V2, V3, V10 with two real accounts
4. A user can connect and see their leagues — demo-able

### Incremental Delivery

1. Setup + Foundational → foundation ready
2. + US1 → **MVP**, connect works
3. + US2 → complete read-only product, shippable even if write approval never lands
4. + US3 → first write, confirm rail proven (run V6 adversarially)
5. + US4, US5 in parallel → full management surface
6. + Polish/Deploy → production

### Critical Sequencing Notes

- ~~**T017 (cache re-keying) is a latent data-leak fix**~~ — **WITHDRAWN**. The claimed leak does not exist; caches are per-instance and per-request construction isolates users. See T017. The genuine residual risk is rate-limit exposure from re-seeding the universe every request.
- **V9 (`WRITE_NOT_APPROVED`) must be run while write approval is still pending** — that state cannot be reproduced once approval lands.
- **V6 must be run with host approval prompts disabled.** With them enabled it proves nothing about our server's guarantee.
- **T046 has an unverified dependency** (`change_positions` signature, research R5). Verify against a real team before writing the tool, not after.

---

## Phase 9: Follow-ups from the final whole-branch review (2026-08-18)

**Not blocking** — the final review's own triage classified these as
real-but-deferrable, in scope only because the whole-branch view (not any
single task's own review) is what surfaced them. Fixed at the same time
(fix wave, commits 384dad7/7583391): the schema violation on `list_leagues`,
the dead `session.resolve_league_context` whose tests guarded unreachable
code, `check_auth`'s fabricated expiry, the `config.write_enabled`
documentation mismatch, and three test-hygiene minors. What follows is
everything the review found that was NOT part of that fix wave.

- [ ] T071 **Per-request Yahoo call amplification.** `discover_leagues` +
  `resolve_request_league_context` + `_total_expected_picks` each
  independently re-fetch league data on every call; `League.team_key()`
  costs a full teams-across-all-leagues call per discovered league;
  `get_available_players`'s universe cache never actually caches because
  the `YahooFantasyApiDataSource` instance is per-request; `YahooTokenVerifier`
  has no `cache_ttl_seconds` (FastMCP's own `GitHubTokenVerifier` offers one
  for exactly this). For a user in 3 leagues, one `get_available_players`
  call is roughly 17 upstream calls — this is the live-draft polling path,
  and the constitution requires polling/staleness to be "an explicit,
  tested part of the design." Not urgent at mock-validated tier (nothing
  calls live Yahoo yet), but should land before any real draft-day use.
  Cheapest fixes, in order: derive all team keys from one `get_teams_raw`
  during discovery instead of N `team_key()` calls; memoize discovery for
  the life of a request or a short per-`sub` TTL; add `cache_ttl_seconds`
  to `YahooTokenVerifier`.

- [ ] T072 **No exception boundary beyond `YahooFantasyError` — and this
  reframes T027.** Every tool closure in `server.py` catches only
  `YahooFantasyError`; FastMCP's `mask_error_details` defaults to `False`,
  so an unhandled exception (e.g. a malformed `changes` entry raising
  `KeyError` in `tools_write.py`) reaches the client with raw exception
  text and records no usage row. Originally this looked like a narrow gap
  (T027's note: "OAuthProxy refresh makes the revoked-token case narrower
  now"). The final review found it's actually the *dominant* unclassified
  path: `discover_leagues` runs first on every league-scoped tool and on
  `list_leagues`, and its calls go through `YahooGameFactory`, **not**
  through `YahooFantasyApiDataSource._call` — the only place that maps
  401→`AuthExpiredError` and 429/5xx→`RateLimitedError`. Fix: add a
  catch-all `except Exception -> UpstreamError` at the closure boundary
  (recording `"error"` usage), pass `mask_error_details=True` when
  constructing `FastMCP`, route discovery calls through the same
  classification `_call` uses, and validate `changes` entry shape in
  `tool_propose_set_lineup` before it reaches a `KeyError`.

- [ ] T073 **Proposal preview omits player names — FR-018.** FR-018
  requires the preview "name the specific players"; `contracts/mcp-tools.md`
  lists `player_name` in the preview shape. `tools_write.py`'s
  `propose_set_lineup` preview currently has `{player_id, from_position,
  to_position}` only — `_current_roster_positions` already fetches full
  roster data and discards the names. Fix: thread `{player_id: name}`
  alongside the position map into the preview.

- [ ] T074 **Minor cleanup batch** (each cheap, none urgent):
  - `check_auth`'s `authenticated`/`needs_reauth` logic
    (`tools_read.py:22-27`) is tautological — always `True`/`False` on the
    success path, since `_current_identity` already raises otherwise.
    Provably harmless today (bearer middleware rejects bad/expired tokens
    pre-dispatch), but worth deriving honestly if a path ever reaches this
    code with a token that could plausibly fail.
  - Auth-failure refusals record no usage row (`_record` no-ops when
    `sub is None`) — contract says every tool records usage including
    refusals; unmetered because there's no `sub` to attribute an
    unauthenticated refusal to. Needs a real design decision (a
    system-level/anonymous usage bucket?), not a quick fix.
  - `get_roster`'s `team_key` argument is unvalidated against the resolved
    league — harmless today (bounded by Yahoo's own token-based
    authorization) but outside the "membership validated on every call"
    contract statement. Cheap defense-in-depth: `team_key.startswith(f"{league_key}.t.")`.
  - `tool_confirm_action` never asserts `row.team_key == ctx.team_key` —
    equal by construction today, matters once US4/US5 add proposals that
    reference other teams.
  - Retrying a confirm after `PRECONDITIONS_CHANGED` (row now `failed`)
    reports `PROPOSAL_EXPIRED`, not what happened — imprecise but not
    incorrect (both are terminal-refusal codes).
  - `list_leagues`/`propose_set_lineup` implementations don't yet support
    the `season`/`week` optional parameters `contracts/mcp-tools.md`
    documents — implement or amend the contract.
  - No concurrency test exists (two users hitting the server at once, not
    just two sequentially-constructed identities). The final review did
    trace this by hand — `sqlite3.threadsafety == 3`, `Store` shares one
    connection, so a racing `mark_consumed`'s conditional `UPDATE` still
    holds under a shared transaction — and concluded the guarantee holds
    without a dedicated test. Worth writing one anyway for regression
    protection: N threads invoking registered closures with distinct
    `sub`s, asserting no cross-attribution in `usage_events` and exactly
    one successful confirm among racers.

---

## Notes

- [P] = different files, no dependencies
- Every task lists an exact file path
- Verify tests fail before implementing (Principle II)
- Commit after each task or logical group; reference `specs/002-hosted-multitenant-mcp/` per constitution Development Workflow
- Availability derivation in `draft.py` is untouched by design — it is the project's core correctness guarantee
