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

## ⚠️ RELEASE GATES — verify before starting Phase 3

Neither gate is code work; both are hard blockers from constitution Principle I. Phases 1–2 may proceed regardless.

- [ ] **G1** Yahoo API Access Application approved for the operator's Client ID (<https://sports.yahoo.com/developer/access/>). **Read (`fspt-r`) unblocks US1/US2. Read+write (`fspt-w`) required for US3/US4/US5.**
- [ ] **G2** Phase 1 (spec 001) validated end-to-end against a real Yahoo account — spec 001 task T055. Required by Principle I before *any* implementation of this feature.

**If G1 lands read-only**: implement through US2, stop, and run quickstart V9 (`WRITE_NOT_APPROVED` path) before write approval arrives — that state is unreproducible afterward.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Dependency and skeleton changes needed by everything downstream.

- [ ] T001 Update `pyproject.toml`: add `requests`, confirm `fastmcp>=3.4.7`, and move `yahoo_oauth` to an optional/local-only extra (research R6 removes it from the hosted path)
- [ ] T002 [P] Create empty modules with docstrings only: `src/yahoo_fantasy_mcp/auth_proxy.py`, `session.py`, `store.py`, `confirm.py`, `tools_read.py`, `tools_write.py`
- [ ] T003 [P] Rewrite `.env.example`: remove `YAHOO_LEAGUE_KEY`; add `PUBLIC_BASE_URL`, `PORT`, `DB_PATH`, `PROPOSAL_TTL_SECONDS`, `YAHOO_SCOPE`
- [ ] T004 [P] Add shared test helpers in `tests/conftest.py`: fake clock, in-memory store factory, and two fake identities (`sub_a`, `sub_b`) for isolation tests

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Multi-tenancy, auth, transport, and persistence. **No user story can begin until this is complete.**

**⚠️ CRITICAL**: This phase dismantles the single-tenant `ServerContext` singleton in `server.py`. Nothing works until it is done.

### Tests first

- [ ] T005 [P] Unit tests for server config in `tests/unit/test_config.py` — asserts no per-user/league fields, required vars named in errors, no secret values in messages
- [ ] T006 [P] Unit tests for `store.py` in `tests/unit/test_store.py` — user upsert idempotency, usage append, proposal lifecycle per data-model.md state machine
- [ ] T007 [P] Unit tests for the Yahoo session adapter in `tests/unit/test_session_adapter.py` — asserts `.session` carries the Bearer header AND that the adapter has **no** `refresh_access_token` attribute (research R6: prevents double-refresh races)
- [ ] T008 [P] Unit tests for per-user cache isolation in `tests/unit/test_client_cache_isolation.py` — two leagues/users must not share cached player identity or universe entries

### Implementation

- [ ] T009 Rewrite `src/yahoo_fantasy_mcp/config.py`: server-level `ServerConfig` only (base URL, port, client id/secret, db path, proposal TTL, scope); delete `league_key` and `token_path`
- [ ] T010 Implement SQLite schema and accessors in `src/yahoo_fantasy_mcp/store.py` per data-model.md — `users`, `usage_events`, `proposals` tables with indices on `token_hash` and `sub`
- [ ] T011 [P] Implement `YahooSessionAdapter` in `src/yahoo_fantasy_mcp/session.py` — wraps a `requests.Session` with `Authorization: Bearer <token>`; deliberately omits `refresh_access_token`
- [ ] T012 [P] Extend `src/yahoo_fantasy_mcp/errors.py` with the contract's error codes: `LeagueNotAccessibleError`, `SportNotSupportedError`, `WriteNotApprovedError`, `InvalidConfirmationError`, `ProposalExpiredError`, `ProposalAlreadyUsedError`, `PreconditionsChangedError`, `TradeInitiationNotSupportedError`
- [ ] T013 Implement `YahooTokenVerifier` in `src/yahoo_fantasy_mcp/auth_proxy.py` — validates the opaque Yahoo token via userinfo and returns `sub` (research R3/R4), modeled on FastMCP's `GitHubTokenVerifier`
- [ ] T014 Implement `build_auth_proxy()` in `src/yahoo_fantasy_mcp/auth_proxy.py` — `OAuthProxy` wired to `request_auth`/`get_token` with the configured scope (research R1)
- [ ] T015 Implement `resolve_identity()` in `src/yahoo_fantasy_mcp/session.py` — `get_access_token().token` → Yahoo token + `sub`; upserts the user row (research R2). **MUST NOT** accept any caller-supplied identity
- [ ] T016 Implement `resolve_league_context()` in `src/yahoo_fantasy_mcp/session.py` — builds `Game`/`League`/`Team` per request, validates league membership (raises `LeagueNotAccessibleError`) and football-only (raises `SportNotSupportedError`)
- [ ] T017 Re-key the caches in `src/yahoo_fantasy_mcp/client.py` to `(league_key, …)` per data-model.md; assert availability remains uncached (makes T008 pass)
- [ ] T018 Add usage recording in `src/yahoo_fantasy_mcp/server.py` — one `usage_events` row per tool call including refusals; records tool name and outcome only, never arguments (data-model.md)
- [ ] T019 Rewrite `src/yahoo_fantasy_mcp/__main__.py` — HTTP transport via `mcp.run(transport="http", …)`, auth provider attached, no `build_context()` singleton

**Checkpoint**: Server starts over HTTP, presents OAuth metadata, and resolves a per-request identity. User stories can begin.

---

## Phase 3: User Story 1 — Connect a Yahoo account (Priority: P1) 🎯 MVP

**Goal**: A user adds the server in Claude or ChatGPT, signs in with Yahoo, and their assistant can see their leagues — no local setup, no credential files.

**Independent Test**: From a fresh assistant, add the server URL, complete sign-in, ask "what fantasy leagues am I in?" and get that user's correct leagues.

### Tests for User Story 1 ⚠️ write first, confirm failing

- [ ] T020 [P] [US1] Contract test in `tests/contract/test_oauth_metadata.py` — OAuth discovery endpoints are served and advertise the expected scope
- [ ] T021 [P] [US1] Integration test in `tests/integration/test_check_auth.py` — returns `authenticated`/`expires_in_seconds`/`needs_reauth` and **never** a token value (FR-026)
- [ ] T022 [P] [US1] Integration test in `tests/integration/test_tenant_isolation.py` — two identities call `list_leagues`; each sees only its own, and cross-tenant `league_key` access raises `LeagueNotAccessibleError` (FR-005, quickstart V3)
- [ ] T023 [P] [US1] Integration test in `tests/integration/test_auth_errors.py` — revoked/expired upstream surfaces `AUTH_EXPIRED` with reconnect guidance, not a raw error (FR-006, quickstart V10)

### Implementation for User Story 1

- [ ] T024 [US1] Implement `check_auth` in `src/yahoo_fantasy_mcp/tools_read.py` per contracts — no token value in any field
- [ ] T025 [US1] Implement `list_leagues` in `src/yahoo_fantasy_mcp/tools_read.py` using `Game.league_ids()`, returning `league_key`/`name`/`sport`/`season`/`is_supported`/`team_key`/`team_name` (research R5)
- [ ] T026 [US1] Register both tools with `readOnlyHint=true`, `openWorldHint=true` annotations in `src/yahoo_fantasy_mcp/server.py` (FR-024)
- [ ] T027 [US1] Map upstream auth failures to `AUTH_REQUIRED`/`AUTH_EXPIRED` in `src/yahoo_fantasy_mcp/auth_proxy.py`, reusing the Phase 1 `classify_auth_failure` approach
- [ ] T028 [US1] Verify `mask_secrets` covers all new log sites in `src/yahoo_fantasy_mcp/logging_utils.py`; add a test asserting no token-shaped string appears in logs (FR-026)

**Checkpoint**: US1 fully functional. Run quickstart V1, V2, V3, V10. **This is the MVP** — a real user can connect and see their leagues.

---

## Phase 4: User Story 2 — See any of my leagues (Priority: P2)

**Goal**: All Phase 1 read capabilities work against any league the user belongs to, selected per request.

**Independent Test**: A user in ≥2 leagues requests standings in each by name and gets correct, distinct results.

### Tests for User Story 2 ⚠️ write first, confirm failing

- [ ] T029 [P] [US2] Integration tests in `tests/integration/test_reads_multi_league.py` — each read tool returns correct data for two different `league_key`s in the same session
- [ ] T030 [P] [US2] Integration test in `tests/integration/test_sport_gating.py` — a non-football league appears in `list_leagues` with `is_supported=false` but every other tool raises `SportNotSupportedError` (FR-008)
- [ ] T031 [P] [US2] Regression test in `tests/unit/test_draft_invariant_multitenant.py` — the availability invariant holds per league, **including a late-draft fixture** (FR-012; spec 001 research R3)

### Implementation for User Story 2

- [ ] T032 [P] [US2] Port `get_league_info` and `list_teams` to `src/yahoo_fantasy_mcp/tools_read.py`, parameterized by `league_key`
- [ ] T033 [P] [US2] Port `get_roster` and `get_standings` to `src/yahoo_fantasy_mcp/tools_read.py` (`team_key` optional, defaults to caller's team)
- [ ] T034 [US2] Port `get_draft_results` and `get_available_players` to `src/yahoo_fantasy_mcp/tools_read.py`, deriving `total_expected_picks` from league settings rather than a global env var
- [ ] T035 [US2] Register all read tools with correct annotations in `src/yahoo_fantasy_mcp/server.py`
- [ ] T036 [US2] Delete the now-unused single-tenant tool bodies and `ServerContext` from `src/yahoo_fantasy_mcp/server.py` (Principle IV — no dead code implying it's live)

**Checkpoint**: US1 + US2 both work. Run quickstart V4. Read-only product is complete and shippable.

---

## Phase 5: User Story 3 — Set my lineup, with confirmation (Priority: P3) 🔒 requires G1 write approval

**Goal**: Lineup changes reach Yahoo only after an explicit, server-enforced confirmation.

**Independent Test**: Propose a lineup change, verify Yahoo is unchanged, confirm, verify it applied.

### Tests for User Story 3 ⚠️ write first, confirm failing

- [ ] T037 [P] [US3] Unit tests for the confirm rail in `tests/unit/test_confirm.py` — covers all five refusals from quickstart V6: unknown token, replay, expiry, wrong user, precondition drift (FR-020, FR-021, FR-023)
- [ ] T038 [P] [US3] Unit test in `tests/unit/test_confirm_storage.py` — only the token **hash** is persisted; the raw token never appears in the DB (data-model.md)
- [ ] T039 [P] [US3] Unit test in `tests/unit/test_confirm_atomicity.py` — consumption and dispatch share one transaction; a simulated crash mid-write leaves the token unusable, never reusable
- [ ] T040 [P] [US3] Integration test in `tests/integration/test_propose_lineup.py` — propose issues no write; confirm dispatches exactly one `change_positions` call
- [ ] T041 [P] [US3] Contract test in `tests/contract/test_tool_annotations.py` — asserts the full annotation matrix: reads and `propose_*` non-destructive, `confirm_action` destructive (FR-024, research R9)

### Implementation for User Story 3

- [ ] T042 [US3] Implement proposal creation in `src/yahoo_fantasy_mcp/confirm.py` — `secrets.token_urlsafe(32)`, store SHA-256 hash, TTL from config, snapshot preconditions
- [ ] T043 [US3] Implement `verify_and_consume()` in `src/yahoo_fantasy_mcp/confirm.py` — enforces the six checks from data-model.md atomically; returns `INVALID_CONFIRMATION` identically for unknown-token and wrong-user (contracts: must not reveal token existence)
- [ ] T044 [US3] Implement precondition re-verification for `set_lineup` in `src/yahoo_fantasy_mcp/confirm.py` — compares current roster/slots against the snapshot
- [ ] T045 [US3] Implement `propose_set_lineup` in `src/yahoo_fantasy_mcp/tools_write.py` per contracts, including `warnings` (e.g. bye week) surfaced pre-confirmation
- [ ] T046 [US3] Add `set_lineup` write dispatch in `src/yahoo_fantasy_mcp/client.py` via `Team.change_positions` — **verify `time_frame`/`modified_lineup` shape against a real team first** (research R5 flags this unverified)
- [ ] T047 [US3] Implement `confirm_action` in `src/yahoo_fantasy_mcp/tools_write.py` — the single write path; annotated `destructiveHint=true`
- [ ] T048 [US3] Implement `WRITE_NOT_APPROVED` handling in `src/yahoo_fantasy_mcp/tools_write.py` — distinguishes missing Yahoo write scope from an invalid request (FR-025)

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
- [ ] T064 [P] Rewrite `README.md` for the hosted product: connect-by-URL instructions for Claude and ChatGPT, no per-user developer credentials, Yahoo attribution (FR-013), and no name implying Yahoo affiliation (FR-030)
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

- **T017 (cache re-keying) is a latent data-leak fix**, not a refactor. It must land in Foundational, before any read story serves two users.
- **V9 (`WRITE_NOT_APPROVED`) must be run while write approval is still pending** — that state cannot be reproduced once approval lands.
- **V6 must be run with host approval prompts disabled.** With them enabled it proves nothing about our server's guarantee.
- **T046 has an unverified dependency** (`change_positions` signature, research R5). Verify against a real team before writing the tool, not after.

---

## Notes

- [P] = different files, no dependencies
- Every task lists an exact file path
- Verify tests fail before implementing (Principle II)
- Commit after each task or logical group; reference `specs/002-hosted-multitenant-mcp/` per constitution Development Workflow
- Availability derivation in `draft.py` is untouched by design — it is the project's core correctness guarantee
