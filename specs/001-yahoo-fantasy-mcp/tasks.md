---

description: "Task list for Yahoo Fantasy MCP Server implementation"
---

# Tasks: Yahoo Fantasy MCP Server

**Input**: Design documents from `/specs/001-yahoo-fantasy-mcp/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/mcp-tools.md, quickstart.md

**Tests**: Test tasks are **REQUIRED**, not optional. Constitution Principle II
declares test-first NON-NEGOTIABLE for parsing, auth refresh, and recommendation
logic. Every test task MUST be written and observed failing before its
implementation task begins.

**Organization**: Tasks are grouped by user story to enable independent
implementation and testing of each story.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (US1, US2, US3)
- Include exact file paths in descriptions

## Path Conventions

Single project — `src/yahoo_fantasy_mcp/` and `tests/` at repository root, per
plan.md Structure Decision.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Project initialization and dependency pinning

- [X] T001 Create project structure `src/yahoo_fantasy_mcp/` and `tests/{unit,integration,fixtures}/` per plan.md
- [X] T002 Create `pyproject.toml` pinning Python 3.11, `fastmcp==3.4.7`, `yahoo_fantasy_api==2.12.3`, `yahoo_oauth==2.1.1`, `pytest` (versions from research.md R1/R7)
- [X] T003 [P] Configure `ruff` lint + format rules in `pyproject.toml`
- [X] T004 [P] Create `.env.example` in repo root with `YAHOO_CLIENT_ID`, `YAHOO_CLIENT_SECRET`, `YAHOO_LEAGUE_KEY`, `YAHOO_POLL_INTERVAL_SECONDS` as empty placeholders — **no real values** (FR-002)
- [X] T005 [P] Configure pytest (testpaths, fixture discovery) in `pyproject.toml`
- [X] T006 Verify `.gitignore` already covers `.env`, `oauth2.json`, `.yahoo_token.json` and confirm with `git check-ignore -v` (Principle III)

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Shared types, errors, config, and the Yahoo API boundary that every
user story depends on

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

- [X] T007 [P] Implement `ErrorCode` enum and typed exceptions in `src/yahoo_fantasy_mcp/errors.py` — all 7 codes from contracts/mcp-tools.md
- [X] T008 [P] Implement config loading (league key, poll interval, credential paths) in `src/yahoo_fantasy_mcp/config.py`
- [X] T009 [P] Create Yahoo JSON test fixtures in `tests/fixtures/`: `draft_predraft.json`, `draft_midraft.json`, `draft_postdraft.json`, `draft_auction.json`, `roster.json`, `standings.json`, `teams.json`, `player_details.json`
- [X] T010 [P] Write failing entity tests in `tests/unit/test_models.py` covering League, Team, Player, DraftPick, Draft, Roster per data-model.md
- [X] T011 Implement domain entities in `src/yahoo_fantasy_mcp/models.py` to pass T010 — **no `is_available` field on Player** (data-model.md Availability Invariant)
- [X] T012 Write failing test in `tests/unit/test_errors.py` asserting no tool output or log line contains a token value (FR-002, Principle III)
- [X] T013 Implement logging configuration in `src/yahoo_fantasy_mcp/errors.py` (or `logging.py`) that redacts credential values, passing T012
- [X] T014 Implement Yahoo API boundary in `src/yahoo_fantasy_mcp/client.py` — raw request wrapper returning domain models, keeping Yahoo JSON quirks out of the tool layer

**Checkpoint**: Shared types, errors, and API boundary ready — user stories can begin

---

## Phase 3: User Story 1 - Connect my Yahoo account and see my league (Priority: P1) 🎯 MVP

**Goal**: Authenticate once against Yahoo, survive token expiry without
re-login, and read league info, teams, rosters, and standings.

**Independent Test**: From zero state, complete OAuth consent, then retrieve
league list, a roster, and standings — and confirm a second call after access
token expiry succeeds with no manual re-auth (quickstart V1, V2).

### Tests for User Story 1 ⚠️ Write FIRST, observe FAILING

- [X] T015 [P] [US1] Write failing test in `tests/unit/test_auth.py` for automatic token refresh on expired access token (FR-003, US1 scenario 2)
- [X] T016 [P] [US1] Write failing test in `tests/unit/test_auth.py` asserting `AUTH_EXPIRED` and `LEAGUE_NOT_PROVISIONED` are distinct outcomes for two different 401 responses (FR-007 — both arrive as HTTP 401)
- [X] T017 [P] [US1] Write failing test in `tests/unit/test_auth.py` asserting `check_auth` output contains no token, secret, or fragment thereof (FR-002)
- [X] T018 [P] [US1] Write failing contract tests in `tests/integration/test_tools.py` for `get_league_info`, `list_teams`, `get_roster`, `get_standings` against fixtures (FR-004/005/006)

### Implementation for User Story 1

- [X] T019 [US1] Implement OAuth login flow (one-time consent, token file at gitignored path) in `src/yahoo_fantasy_mcp/auth.py` (FR-001)
- [X] T020 [US1] Implement automatic token refresh via `yahoo_oauth` in `src/yahoo_fantasy_mcp/auth.py`, passing T015 (FR-003)
- [X] T021 [US1] Implement 401/403 classification distinguishing credential-expiry from league-not-provisioned in `src/yahoo_fantasy_mcp/auth.py`, passing T016 (FR-007, research R6)
- [X] T022 [US1] Implement `check_auth` tool in `src/yahoo_fantasy_mcp/server.py` returning only booleans and duration, passing T017
- [X] T023 [P] [US1] Implement `get_league_info` tool in `src/yahoo_fantasy_mcp/server.py` (FR-004, FR-012 single configured league)
- [X] T024 [P] [US1] Implement `list_teams` tool with `is_owned_by_user` flag in `src/yahoo_fantasy_mcp/server.py` (FR-004)
- [X] T025 [P] [US1] Implement `get_roster` tool in `src/yahoo_fantasy_mcp/server.py`, defaulting to the user's own team (FR-005)
- [X] T026 [P] [US1] Implement `get_standings` tool in `src/yahoo_fantasy_mcp/server.py` (FR-006)
- [X] T027 [US1] Implement stdio entrypoint in `src/yahoo_fantasy_mcp/__main__.py` registering the FastMCP server (research R7)
- [X] T028 [US1] Write tool descriptions in `src/yahoo_fantasy_mcp/server.py` matching wired behavior only — no claimed analysis/recommendation capability (FR-011, Principle IV)

**Checkpoint**: US1 fully functional — server connects, survives refresh, reads league data. **This is the MVP.**

---

## Phase 4: User Story 2 - See draft picks as they happen (Priority: P2)

**Goal**: Return every draft pick made so far, fresh enough to act on during a
live draft, with correct pre-draft and post-draft behavior.

**Independent Test**: Against a live or completed draft, retrieve picks and
confirm they match Yahoo's own draft board, with `retrieved_at` advancing
across calls (quickstart V3, V4).

### Tests for User Story 2 ⚠️ Write FIRST, observe FAILING

- [ ] T029 [P] [US2] Write failing test in `tests/unit/test_draft.py` asserting pre-draft fixture returns `picks: []` and `draft_status: "predraft"` **without raising** (US2 scenario 3)
- [ ] T030 [P] [US2] Write failing test in `tests/unit/test_draft.py` asserting mid-draft fixture returns only picks made so far, ordered by `pick` ascending (US2 scenario 1, FR-008)
- [ ] T031 [P] [US2] Write failing test in `tests/unit/test_draft.py` asserting post-draft fixture returns complete board with `is_complete: true` (US2 scenario 2)
- [ ] T032 [P] [US2] Write failing test in `tests/unit/test_draft.py` asserting every draft-bearing response carries a populated `retrieved_at` (FR-009, data-model.md)
- [ ] T033 [P] [US2] Write failing test in `tests/unit/test_draft.py` asserting the auction fixture raises `UNSUPPORTED_DRAFT_TYPE` rather than parsing as snake (FR-013, data-model rule 1)
- [ ] T034 [P] [US2] Write failing test in `tests/unit/test_draft.py` asserting duplicate `player_id` across picks is surfaced, not silently deduplicated (data-model rule 2)

### Implementation for User Story 2

- [ ] T035 [US2] Implement `Draft` snapshot construction with required `retrieved_at` in `src/yahoo_fantasy_mcp/draft.py`, passing T032
- [ ] T036 [US2] Implement `draft_results()` parsing (pick, round, team_key, player_id) in `src/yahoo_fantasy_mcp/draft.py`, passing T029-T031 (research R2 — this endpoint is uncached, safe to poll)
- [ ] T037 [US2] Implement auction-draft guard on the `cost` field in `src/yahoo_fantasy_mcp/draft.py`, passing T033 (FR-013)
- [ ] T038 [US2] Implement duplicate-pick detection in `src/yahoo_fantasy_mcp/draft.py`, passing T034
- [ ] T039 [US2] Implement process-lifetime player identity cache (id → name/positions/nfl_team) in `src/yahoo_fantasy_mcp/client.py` — safe because identity is immutable during a draft (research R4)
- [ ] T040 [US2] Implement exponential backoff on throttle/5xx responses in `src/yahoo_fantasy_mcp/client.py`, emitting `RATE_LIMITED` (research R5)
- [ ] T041 [US2] Implement `get_draft_results` tool in `src/yahoo_fantasy_mcp/server.py` — exactly **one** Yahoo call per invocation, names served from the T039 cache (research R5)
- [ ] T042 [US2] Add contract test for `get_draft_results` response shape in `tests/integration/test_tools.py` per contracts/mcp-tools.md

**Checkpoint**: US1 and US2 both work independently — live draft picks are visible

---

## Phase 5: User Story 3 - See who's still available (Priority: P3)

**Goal**: Return undrafted players with ranking context, guaranteed never to
contradict the draft board.

**Independent Test**: Mid-draft, call `get_draft_results` and
`get_available_players` in succession and confirm the intersection of their
player IDs is empty (quickstart V5).

**⚠️ Cross-story dependency (intentional and documented)**: US3 derives
availability from the draft snapshot built in US2 (`draft.py`), per research R3.
This is a genuine dependency, not an artifact of task ordering — availability
*cannot* be computed correctly without fresh draft data. US3 is still
independently **testable** (its invariant is self-checking against fixtures),
but it is not independently **implementable** before US2.

### Tests for User Story 3 ⚠️ Write FIRST, observe FAILING

- [ ] T043 [P] [US3] Write failing test in `tests/unit/test_draft.py` asserting **the intersection of drafted IDs and available IDs is empty** for the mid-draft fixture — the machine-checkable form of SC-002 and the highest-value test in this suite (FR-010, research R3)
- [ ] T044 [P] [US3] Write failing test in `tests/unit/test_draft.py` asserting the invariant in T043 still holds after advancing to a later-stage draft fixture (catches cache-staleness bugs that only appear deep into a draft)
- [ ] T045 [P] [US3] Write failing test in `tests/unit/test_draft.py` asserting position filtering returns only players eligible at that position, with multi-eligible players appearing under each (US3 scenario 2)

### Implementation for User Story 3

- [ ] T046 [US3] Implement availability derivation as `player_universe − drafted_ids` in `src/yahoo_fantasy_mcp/draft.py`, passing T043-T044 — **MUST NOT call the library's `free_agents()` or `taken_players()`**, whose caches never expire (research R3)
- [ ] T047 [US3] Implement position filtering on eligibility in `src/yahoo_fantasy_mcp/draft.py`, passing T045
- [ ] T048 [US3] Attach ranking context (`percent_owned`, `average_pick`) to available players in `src/yahoo_fantasy_mcp/draft.py` (FR-010) — not cached across polls (data-model.md)
- [ ] T049 [US3] Implement `get_available_players` tool with `position` and `limit` params in `src/yahoo_fantasy_mcp/server.py`, sharing the same fresh draft read as `get_draft_results`
- [ ] T050 [US3] Add contract test for `get_available_players` response shape in `tests/integration/test_tools.py` per contracts/mcp-tools.md

**Checkpoint**: All three user stories independently functional

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Verification, documentation, and the pre-draft rehearsal

- [ ] T051 [P] Write `README.md` with setup instructions mirroring quickstart.md
- [ ] T052 [P] Audit `src/yahoo_fantasy_mcp/` for unwired code and verify every tool description in `src/yahoo_fantasy_mcp/server.py` matches actual behavior; delete anything unreachable from the entrypoint (FR-011, Principle IV)
- [ ] T053 Run `pytest tests/` and confirm green with no network calls (fixtures only)
- [ ] T054 Scan full git history for any token, secret, or `.env` content and confirm clean (SC-004)
- [ ] T055 Execute quickstart V1-V3 and V6-V8 manually against the real Yahoo account
- [ ] T056 **Execute quickstart V4 and V5 during a Yahoo mock draft — before draft day.** This is the only way to prove live freshness and the availability invariant under real conditions (plan.md Key Risks)
- [ ] T057 Tune the `YAHOO_POLL_INTERVAL_SECONDS` default in `src/yahoo_fantasy_mcp/config.py` and `.env.example` based on throttling observed in T056 (research R5)

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — start immediately
- **Foundational (Phase 2)**: Depends on Setup — BLOCKS all user stories
- **US1 (Phase 3)**: Depends on Foundational. No dependency on US2/US3
- **US2 (Phase 4)**: Depends on Foundational + US1 auth (needs authenticated calls)
- **US3 (Phase 5)**: Depends on US2 draft snapshot (see cross-story note above)
- **Polish (Phase 6)**: Depends on all desired stories being complete

### User Story Dependencies

```
Setup → Foundational → US1 (MVP) → US2 → US3 → Polish
                         ↑          ↑      ↑
                    independently testable at each checkpoint
```

Unlike a typical feature where P1/P2/P3 are fully parallel, this feature has a
real chain: you cannot know who is *available* without knowing who is *drafted*,
and you cannot read drafts without auth. The plan does not pretend otherwise.

### Within Each User Story

- Tests MUST be written and observed FAILING before implementation (Principle II)
- Models before services; services before tools
- Story complete and checkpoint-validated before moving to next priority

### Parallel Opportunities

- Setup: T003, T004, T005 in parallel
- Foundational: T007, T008, T009, T010 in parallel; T012 parallel with T011
- US1: all four test tasks (T015-T018) in parallel; then tools T023-T026 in parallel
- US2: all six test tasks (T029-T034) in parallel
- US3: all three test tasks (T043-T045) in parallel
- Polish: T051, T052 in parallel

---

## Parallel Example: User Story 2

```bash
# Write all US2 tests together, confirm all FAIL before implementing:
Task: "Pre-draft returns empty in tests/unit/test_draft.py"
Task: "Mid-draft returns partial ordered picks in tests/unit/test_draft.py"
Task: "Post-draft returns complete board in tests/unit/test_draft.py"
Task: "retrieved_at populated on every response in tests/unit/test_draft.py"
Task: "Auction fixture raises UNSUPPORTED_DRAFT_TYPE in tests/unit/test_draft.py"
Task: "Duplicate player_id surfaced in tests/unit/test_draft.py"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Setup
2. Complete Phase 2: Foundational (CRITICAL — blocks all stories)
3. Complete Phase 3: User Story 1
4. **STOP and VALIDATE**: quickstart V1 and V2 against the real account
5. You now have a working, authenticated, read-only league viewer

### Incremental Delivery

1. Setup + Foundational → foundation ready
2. US1 → validate V1/V2 → **MVP**
3. US2 → validate V3/V4 → live draft picks visible
4. US3 → validate V5/V6 → availability guaranteed consistent
5. Polish → V7/V8 + **mock-draft rehearsal (T056)**

### Draft-Day Timing

T056 (mock draft rehearsal) is the schedule-critical task. The R3 cache-staleness
class of bug does not appear at pick 5 — it appears deep into a draft. Budget a
full mock draft well before draft day; discovering this on draft day is the one
failure mode this plan cannot recover from.

---

## Notes

- [P] tasks = different files, no dependencies
- Every test task must be observed FAILING before its implementation task (Principle II)
- Commit after each task or logical group; reference `specs/001-yahoo-fantasy-mcp/`
- The single highest-value test in this suite is T043 — it is the guard against
  the exact silent-staleness failure identified in research R3
