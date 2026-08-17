# Feature Specification: Hosted Multi-Tenant Fantasy MCP Server

**Feature Directory**: `specs/002-hosted-multitenant-mcp`

**Created**: 2026-08-17

**Status**: Draft

**Input**: Evolve the existing single-user, single-league, read-only, locally-run Yahoo Fantasy MCP server into a hosted, multi-tenant product that any invited user can connect to from Claude or ChatGPT, covering all of their own Yahoo fantasy leagues, with both read and write capability gated behind a server-enforced confirmation step.

## Background & Motivation

The existing server (`specs/001-yahoo-fantasy-mcp`) proved the core Yahoo integration: OAuth consent, read tools, and a correctness guarantee that available-player data never goes stale mid-draft. But it runs as a local subprocess on one machine, serves exactly one person, is hardcoded to exactly one league, and can only read.

This feature turns that proof into something the owner can share. Three things change: **who** can use it (anyone the owner invites, each with their own Yahoo account, fully isolated from each other), **where** it runs (a remote server the owner hosts, reachable by AI assistants over the internet rather than launched locally), and **what** it can do (act on the user's behalf — set lineups, add and drop players — not just report).

**Why this shape**: the AI assistant *is* the product interface. There is no separate website or app to build. A user connects this server to Claude or ChatGPT once, and from then on manages their fantasy team by talking to their assistant.

**Competitive context** (informational, not requirements): existing comparable tools are either local single-user setups requiring each person to register their own developer credentials, or hosted services that are deliberately read-only. A hosted service that can actually *act* — safely, with an unavoidable confirmation step — is the differentiating capability.

**Constitutional alignment**: this is Phase 2 in the project constitution (v0.2.0). Phase 1 (the local read-only server) must be proven end-to-end against a real account before this phase's implementation begins.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Connect a Yahoo account from an AI assistant (Priority: P1)

A user adds the hosted server to Claude or ChatGPT using its address. Their assistant prompts them to sign in; they are taken to Yahoo, approve access to their fantasy data, and are returned to their assistant. From that point the assistant can see their fantasy leagues. No developer account, no credential files, no configuration — the same flow as connecting any other service.

**Why this priority**: nothing else in the product is reachable without it, and it is the entire difference between "a script I run" and "a service my friends can use." It is independently valuable: a user who connects and sees their own leagues listed has proof the product works for them.

**Independent Test**: from a fresh assistant with no prior setup, add the server, complete sign-in, and ask "what fantasy leagues am I in?" — the correct leagues for *that* user are returned.

**Acceptance Scenarios**:

1. **Given** a user who has never used the service, **When** they add the server in their assistant and complete Yahoo sign-in, **Then** their assistant can retrieve their leagues without any further setup.
2. **Given** a user who connected previously, **When** they return days later, **Then** their session still works without signing in again.
3. **Given** two different users connected at the same time, **When** each asks about their leagues, **Then** each sees only their own leagues and never any part of the other's data.
4. **Given** a user who revokes the service's access from their Yahoo account settings, **When** they next make a request, **Then** they receive a clear message that access was revoked and how to reconnect — not a confusing internal error.

---

### User Story 2 - See any of my leagues, not just one (Priority: P2)

A user in several fantasy leagues asks their assistant about any of them — standings in one, their roster in another — without the server having been preconfigured for a specific league. When the user's request is ambiguous about which league they mean, the assistant is able to determine or ask.

**Why this priority**: the single-league limitation is the most visible artifact of the old design, and most users are in more than one league. Delivers standalone value even with no write capability at all.

**Independent Test**: a user in two or more leagues asks for standings in each by name and receives correct, distinct results.

**Acceptance Scenarios**:

1. **Given** a user in three leagues, **When** they ask which leagues they are in, **Then** all three are listed with enough detail to tell them apart.
2. **Given** a user in three leagues, **When** they ask for their roster in a specific one, **Then** the roster for that league is returned.
3. **Given** a user in exactly one league, **When** they ask about "my team," **Then** it resolves without asking them to disambiguate.
4. **Given** a user asking about a league they are not a member of, **When** the request is made, **Then** it is refused clearly rather than returning another user's data.

---

### User Story 3 - Set my lineup, with confirmation (Priority: P3)

A user asks their assistant to start one player and bench another. The assistant shows exactly what will change and asks for confirmation. Only after the user explicitly confirms does the change reach Yahoo. The user then sees the change reflected in the Yahoo app.

**Why this priority**: the first genuinely new capability — the product stops being an information source and starts being a manager. Lineup changes are the highest-frequency write action and the lowest-risk place to prove the confirmation mechanism.

**Independent Test**: request a lineup change, verify nothing changes in Yahoo until confirmation is given, then confirm and verify the change appears in Yahoo.

**Acceptance Scenarios**:

1. **Given** a proposed lineup change, **When** the user has not yet confirmed, **Then** their Yahoo lineup is unchanged.
2. **Given** a proposed lineup change, **When** the user confirms, **Then** the change is applied and the result reported back.
3. **Given** a proposed lineup change, **When** the user declines or abandons it, **Then** nothing is applied and the proposal becomes unusable.
4. **Given** a proposal that has expired, **When** the user tries to confirm it, **Then** it is refused and they are told to start over.
5. **Given** a proposal made minutes ago, **When** the underlying situation has changed in the meantime (e.g. the player is no longer on the roster), **Then** confirmation is refused rather than applying a change based on stale information.
6. **Given** a proposal created by one user, **When** a different user attempts to confirm it, **Then** it is refused.

---

### User Story 4 - Add and drop players, with confirmation (Priority: P4)

A user asks their assistant to pick up an available player, dropping someone to make room. The assistant shows both sides of the move and the roster impact, and applies it only after explicit confirmation.

**Why this priority**: higher stakes than a lineup change (dropping a player can be irreversible if someone else claims them), so it comes after the confirmation mechanism is proven on lower-risk actions. Independently valuable — waiver management is a core weekly activity.

**Independent Test**: propose an add/drop, verify no change occurs pre-confirmation, confirm, and verify both the addition and the drop in Yahoo.

**Acceptance Scenarios**:

1. **Given** an add/drop proposal, **When** it is previewed, **Then** the preview names both the player being added and the player being dropped.
2. **Given** an add/drop proposal, **When** the user confirms, **Then** both halves are applied together — the user is never left with only the drop applied.
3. **Given** an add for a player who was claimed by someone else after the proposal was made, **When** the user confirms, **Then** the action fails safely with a clear explanation and no drop occurs.
4. **Given** a roster that would exceed its size limit after the add, **When** the proposal is made, **Then** the problem is surfaced before confirmation rather than as a failure after it.

---

### User Story 5 - Respond to a trade offer, with confirmation (Priority: P5)

Another manager sends the user a trade offer. The user asks their assistant what offers are pending; the assistant lays out both sides of the exchange and can help evaluate it. If the user decides to accept or reject, the assistant previews that decision and applies it only after explicit confirmation.

**Why this priority**: "should I accept this trade?" is one of the highest-value questions an assistant can answer, and responding is an immediate, self-contained action on the user's side. It comes last because it depends on the confirmation mechanism being proven by the earlier write stories.

**Independent Test**: with a real pending trade offer, list it, verify both sides are described accurately, reject or accept it after confirmation, and verify the outcome in Yahoo.

**Acceptance Scenarios**:

1. **Given** a user with pending incoming trade offers, **When** they ask what offers they have, **Then** each offer is listed with the players going each way.
2. **Given** a pending offer, **When** the user accepts and confirms, **Then** the trade is accepted in Yahoo and the result reported back.
3. **Given** a pending offer, **When** the user rejects and confirms, **Then** the offer is rejected and no roster change occurs.
4. **Given** an offer the other manager withdrew after it was previewed, **When** the user confirms their response, **Then** it is refused with a clear explanation rather than erroring confusingly.
5. **Given** a user who asks to *send* a trade offer, **When** the request is made, **Then** they are told outbound proposals are not supported yet, rather than the request failing obscurely.

---

### Edge Cases

- **Yahoo access not yet approved for write**: the operator's Yahoo API access permits reads but not writes — write attempts must fail with an explanation that distinguishes "this product cannot write yet" from "your request was invalid."
- **Yahoo is down or rate-limiting**: users receive a clear "try again shortly" message; the server does not present stale data as current.
- **Draft in progress**: the availability guarantee from Phase 1 must continue to hold — a player reported as available must never be one already drafted in that same read.
- **Two proposals outstanding at once**: confirming one must not apply the other.
- **Confirmation replay**: a confirmation used once cannot be used again to repeat the action.
- **A user's assistant retries a failed call**: a retried write must not produce a duplicate transaction.
- **User is in leagues across multiple seasons**: past-season leagues are distinguishable from the current one.
- **Assistant hallucinates a confirmation**: an assistant fabricating a confirmation value must not be able to trigger a real write.
- **A league the user is in uses an unsupported format**: unsupported cases are refused explicitly rather than silently mishandled.
- **User has non-football Yahoo leagues**: they appear in league discovery (so the user is not confused about missing leagues) but any read or write against them is refused as not-yet-supported.
- **Trade offer resolved elsewhere mid-flight**: an offer accepted, rejected, or withdrawn in the Yahoo app between preview and confirmation must not produce a misleading success.
- **User asks to send a trade**: refused clearly as out of scope for this release, not silently ignored.

## Requirements *(mandatory)*

### Functional Requirements

#### Access & Identity

- **FR-001**: The service MUST be reachable remotely by MCP-compatible AI assistants over the internet, without users installing or running anything locally.
- **FR-002**: The service MUST support the standard sign-in flow those assistants use for connected services, so that connecting requires no manual credential entry, configuration files, or developer accounts on the user's part.
- **FR-003**: Each user MUST authorize access to their own Yahoo fantasy data, and the service MUST act only within that authorization.
- **FR-004**: The service MUST keep each user's session working across days without re-authorization, refreshing access automatically until the user revokes it.
- **FR-005**: The service MUST support many distinct users concurrently, with complete data isolation: no request may ever return data derived from a different user's authorization.
- **FR-006**: The service MUST distinguish and clearly report these failure states to the user: access revoked, access expired, the operator's Yahoo permissions insufficient, and the requested league not accessible to that user.
- **FR-007**: Users MUST be able to disconnect the service, after which their stored credentials are deleted and subsequent requests require reconnecting.

#### Data Access (Read)

- **FR-008**: This release MUST support fantasy **football** leagues. The service MUST NOT hardcode football-specific assumptions (lineup cadence, roster positions, scoring periods) into its core data model in ways that would require redesign to add other Yahoo fantasy sports later. Leagues in other sports MUST be listed and then explicitly refused with a clear "not supported yet" message — never silently mishandled.
- **FR-009**: Users MUST be able to discover all of their own leagues, with enough identifying detail (name, sport, season) to distinguish them.
- **FR-010**: Every read capability MUST operate against any supported league the user belongs to, selected per request — no league may be fixed by server configuration.
- **FR-011**: The service MUST preserve all read capabilities proven in Phase 1: league information, teams, rosters, standings, draft results, and available players.
- **FR-012**: The service MUST preserve the Phase 1 correctness guarantee that available-player results never include a player already reported as drafted in the same read, including deep into a draft.
- **FR-013**: The service MUST attribute fantasy data to Yahoo Fantasy wherever it is surfaced, per Yahoo's attribution requirements.

#### Actions (Write)

- **FR-014**: Users MUST be able to set their starting lineup for a given league and time period.
- **FR-015**: Users MUST be able to add an available player, drop a rostered player, or do both as a single combined move.
- **FR-016**: Users MUST be able to review trade offers other managers have sent them, and accept or reject those offers. Initiating an outbound trade proposal is out of scope for this release (see Scope Decisions).
- **FR-017**: Every action that changes anything in Yahoo MUST require two distinct steps: a proposal that changes nothing and returns a preview, and a separate explicit confirmation that performs the change. A single request MUST NOT be able to both propose and perform an action.
- **FR-018**: The proposal preview MUST describe the exact change in terms the user can verify — naming the specific players and positions affected, and for trades both sides of the exchange — and MUST accurately reflect what confirmation will do.
- **FR-019**: The two-step guarantee MUST be enforced by the service itself and MUST NOT depend on the connected assistant's own approval prompts, which vary by platform and can be disabled by the user.
- **FR-020**: A confirmation MUST be valid only for: the exact proposal it was issued for, the user it was issued to, a single use, and a limited time window. Any other use MUST be refused.
- **FR-021**: Before performing a confirmed action, the service MUST re-verify that the conditions the proposal was based on still hold, and MUST refuse rather than act on stale assumptions.
- **FR-022**: Combined actions (such as add-plus-drop) MUST NOT leave the user in a partially-applied state.
- **FR-023**: Repeating or retrying a confirmed action MUST NOT produce duplicate changes in Yahoo.
- **FR-024**: Every capability MUST declare whether it only reads, whether it changes external state, and whether it acts on an outside system, so that assistants which offer their own confirmation prompts present them correctly. This is a supplementary safeguard, never a substitute for FR-017 through FR-021.
- **FR-025**: Write capabilities MUST fail clearly and safely when the operator's Yahoo API permissions do not yet include write access.

#### Safety, Privacy & Operations

- **FR-026**: No user's credentials or access tokens may appear in any output returned to an assistant, in logs, or in error messages.
- **FR-027**: Stored user credentials MUST be protected at rest and MUST NOT be committed to version control in any form.
- **FR-028**: The service MUST record, per user, an account tier and a timestamped history of their usage, from first release — so that usage limits and paid tiers can be introduced later without re-architecting access or data handling. No limits are enforced in this release.
- **FR-029**: The service MUST remain operable by a single operator on a single hosted server for this release, including a documented way to deploy, restart, and observe it.
- **FR-030**: The product name and presentation MUST NOT imply affiliation with or endorsement by Yahoo.

### Key Entities

- **User Account**: a person who has connected the service. Holds a stable identity derived from their Yahoo authorization, their account tier, and when they joined. Never shared across people.
- **Yahoo Authorization**: one user's granted access to their own Yahoo fantasy data, including its renewal state and expiry. Belongs to exactly one User Account; never returned to a client.
- **League**: one Yahoo fantasy league a user belongs to, identified distinctly across sports and seasons. A user may have many.
- **Pending Action Proposal**: a described-but-not-performed change, bound to one user, one league, and one specific action (lineup change, add/drop, or trade response). Carries the preview shown to the user, the conditions it assumed, a single-use confirmation value, and an expiry. Ceases to be usable once confirmed, declined, or expired.
- **Incoming Trade Offer**: a trade another manager has proposed to this user, describing the players moving each direction and its current standing. Read-only to this service except through an accept-or-reject response.
- **Usage Record**: a timestamped record that a given user made a given kind of request, retained to support future limits and tiering.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A new user with no prior setup can go from "never heard of it" to seeing their own league data in under 5 minutes, without editing any file or obtaining any developer credential.
- **SC-002**: Across a full test matrix of concurrent users, zero requests return data belonging to another user.
- **SC-003**: 100% of changes that reach Yahoo are preceded by a distinct user confirmation; no test scenario — including a deliberately misbehaving or hallucinating assistant — produces a change without one.
- **SC-004**: In 100% of proposals, what the preview described matches what was actually performed on confirmation.
- **SC-005**: Zero credentials or tokens appear in any assistant-visible output, log line, or error message across the full test suite.
- **SC-006**: Available-player results contain zero already-drafted players, verified both early and deep into a live draft.
- **SC-007**: A returning user makes a successful request after a multi-day gap without re-authorizing.
- **SC-008**: The service works from both major assistant platforms in scope, verified end-to-end on each.
- **SC-009**: No confirmed action produces a duplicate or partially-applied change under retry and interruption testing.

## Assumptions

- **Yahoo write approval is a prerequisite, not a deliverable.** Implementation of write capabilities depends on the operator's Yahoo API access application being approved for read *and* write. Read capabilities do not depend on it. Timing is outside the team's control.
- **Phase 1 must be proven first.** Per the constitution, the local read-only server must be validated end-to-end against a real Yahoo account before this phase's implementation starts. That validation is currently blocked on Yahoo API access approval.
- **Sign-in uses the assistant's built-in connected-service flow**, including whatever consent screen that flow provides. No custom-designed web frontend is in scope; a minimal sign-in/callback page is acceptable only insofar as the flow requires one.
- **Scale expectation for this release** is the operator plus invited friends — tens of users, not thousands. Hosting is a single server the operator controls.
- **Confirmation windows are short-lived** (on the order of minutes), long enough for a natural back-and-forth with an assistant but short enough that proposals do not linger.
- **Ambiguous league references are resolved by the assistant**, either from context or by asking the user; the service's responsibility is to expose enough identifying detail to make that possible, not to guess.
- **Product naming is deferred.** A name is required before public launch but is not needed to build or validate this feature.
- **Monetization is deliberately deferred.** Free/paid tiers, usage caps, new-user prioritization, differentiated service levels, and billing are all out of scope here. Only the data groundwork (FR-026) is in scope, so they can be added later without rework.
- **Also deferred to later phases**: automatically harvesting and indexing Yahoo's API documentation for agent consumption; a curated prompt/skill layer over these capabilities; support for any fantasy platform other than Yahoo; Yahoo fantasy sports other than football; initiating outbound trade proposals.
- **Reuse over rewrite**: the existing Yahoo integration logic and the availability-invariant design from Phase 1 carry forward. What changes is the assumption of a single user, a single league, and a locally-launched process.

## Scope Decisions

Resolved during specification (2026-08-17):

- **Sport scope — football now, extensible later.** This release supports fantasy football only, but the data model must not bake in football-specific assumptions that would force a redesign to add baseball, basketball, or hockey later (FR-008). The main thing to keep flexible is lineup cadence: football is weekly, whereas other Yahoo fantasy sports are daily. Other sports' leagues are discoverable but refused as unsupported. **Rationale**: keeps the shippable surface small and reuses Phase 1 directly, while paying a small design cost now to avoid a large one later.
- **Trades — respond only, don't initiate.** Accepting and rejecting incoming trade offers is in scope (FR-016, User Story 5). Sending an outbound trade proposal is deferred. **Rationale**: responding is an immediate, self-contained action that fits the existing propose/confirm model unchanged. Initiating a trade creates a *pending* outcome that depends on another person acting later — a state the confirmation model doesn't currently express, and which would need its own design.
