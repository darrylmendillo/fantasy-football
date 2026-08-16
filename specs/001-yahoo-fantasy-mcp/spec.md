# Feature Specification: Yahoo Fantasy MCP Server

**Feature Branch**: `001-yahoo-fantasy-mcp`

**Created**: 2026-08-16

**Status**: Draft

**Input**: User description: "A Yahoo Fantasy Sports MCP server (FastMCP-based) that authenticates with the user's Yahoo account, gives read access to their fantasy football league(s), and — critically — can see draft picks as they happen so the user can be assisted during a live draft. This is Phase 1 of a larger effort; agentic draft-recommendation skills and a full-stack app are later phases built on top of this server."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Connect my Yahoo account and see my league (Priority: P1)

As the user, I connect the MCP server to my own Yahoo account once, and can then ask
Claude (or any MCP client) basic questions about my fantasy football league — which
league(s) and team(s) I'm in, who's on my roster, and current standings — without
re-authenticating every session.

**Why this priority**: Nothing else in this feature is possible without a working,
durable connection to my real Yahoo account and league data. This is the foundation
every other story depends on.

**Independent Test**: With no prior state, connect the server to a real Yahoo account,
then successfully retrieve that account's list of fantasy football leagues, a team's
roster, and league standings — with no manual re-authentication required on a second
call.

**Acceptance Scenarios**:

1. **Given** the server has never been authenticated, **When** I run the connection
   step, **Then** I complete Yahoo's login/consent flow once and the server can make
   authenticated calls afterward.
2. **Given** the server was authenticated more than an hour ago (past Yahoo's
   short-lived access token expiry), **When** I make a new request, **Then** the
   server transparently refreshes credentials and the request succeeds without me
   re-authenticating.
3. **Given** I am in more than one Yahoo fantasy football league, **When** I ask
   which leagues/teams I have, **Then** I get an accurate list I can use to pick
   which one to query further.

---

### User Story 2 - See draft picks as they happen (Priority: P2)

As the user, during a live Yahoo fantasy draft, I can ask which players have already
been drafted (by whom, in what round/pick order) and get an accurate, current answer
I can act on while the draft is still running.

**Why this priority**: This is the specific, time-critical capability the user asked
for — "see draft picks" during a live draft. It's the feature that makes this more
than a generic season-long league viewer.

**Independent Test**: Against a league with a draft in progress (or a completed
draft, for verification), retrieve the full list of picks made so far, including
player, drafting team, and pick number/round — and confirm it matches what Yahoo's
own draft board shows at the same moment.

**Acceptance Scenarios**:

1. **Given** a draft is in progress, **When** I query draft picks, **Then** the
   response reflects picks made up to that query (see FR-009 for freshness bound)
   and does not include a player who has not actually been drafted yet.
2. **Given** a draft has just completed, **When** I query draft picks, **Then** I
   get the complete, final draft board for every team.
3. **Given** a draft has not started yet, **When** I query draft picks, **Then** I
   get an empty/not-started result rather than an error.

---

### User Story 3 - See who's still available (Priority: P3)

As the user, mid-draft, I can ask which players are still undrafted in my league,
with enough ranking/ownership context to inform who I pick next — without the server
itself deciding or recommending a pick for me.

**Why this priority**: This is the raw data a human (or a later agentic skill, per
the project constitution's Phase 2) needs to make a good pick. It depends on Story 2
(you can't compute "available" without knowing who's taken) and is explicitly scoped
to data, not strategy — recommendation/ranking logic is deferred to Phase 2.

**Independent Test**: Mid-draft, retrieve the list of available (undrafted) players
for the league, each with standard ranking/ADP/ownership data, and confirm no player
already shown as drafted (Story 2) appears in this list.

**Acceptance Scenarios**:

1. **Given** a draft in progress with some players already picked, **When** I query
   available players, **Then** every already-drafted player (per Story 2) is
   excluded from the result.
2. **Given** I filter available players by position, **When** I query, **Then** only
   players eligible at that position are returned.

---

### Edge Cases

- What happens when the user's Yahoo refresh token itself has expired or been
  revoked (not just the short-lived access token)? The server MUST fail with a
  clear, actionable error distinguishing "you need to re-authenticate" from a
  generic failure — not a raw HTTP error.
- What happens when a requested league is valid but not yet accessible for the new
  season (a real Yahoo behavior — leagues can 401 during their provisioning window
  before the season data is ready)? This MUST be surfaced distinctly from an
  expired-credential 401, per FR-007.
- What happens when the draft is paused, or a team is on autopick?
- What happens if the same player appears to be drafted twice due to a stale read
  during rapid pick activity (see FR-009 on polling/staleness)?
- What happens when the user queries a league/team they don't have access to?

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The server MUST authenticate against the Yahoo Fantasy Sports OAuth2
  API and complete the initial user consent flow exactly once per setup.
- **FR-002**: The server MUST persist OAuth tokens only in a gitignored local
  location (or equivalent local secret storage), and MUST NEVER log, print, or
  commit an access token, refresh token, or client secret in any form (constitution
  Principle III).
- **FR-003**: The server MUST automatically refresh an expired short-lived access
  token using the stored refresh token, without requiring user interaction, for as
  long as the refresh token remains valid.
- **FR-004**: The server MUST let the user list which Yahoo fantasy football
  leagues and teams are associated with their authenticated account for the
  current season.
- **FR-005**: The server MUST return the current roster for a specified team.
- **FR-006**: The server MUST return league standings for a specified league.
- **FR-007**: The server MUST distinguish a "league not yet provisioned for this
  season" failure from an "expired/invalid credential" failure, and return an
  actionable error identifying which one occurred, rather than a generic 401.
- **FR-008**: The server MUST return draft results for a specified league,
  including, for each pick made so far: the player, the drafting team, and the
  pick's round/overall position.
- **FR-009**: Draft-pick data returned during an in-progress draft MUST be no
  more than 5 seconds stale relative to Yahoo's own draft board (default polling
  interval; see Assumptions — reasonable default given Yahoo's API has no
  push/websocket mechanism for live draft events).
- **FR-010**: The server MUST return the set of currently undrafted/available
  players for a specified league, each with standard ranking/ADP/ownership data,
  excluding every player already returned by FR-008 for that league.
- **FR-011**: The server MUST expose its capabilities as MCP tools with
  descriptions that accurately reflect only what is actually implemented and
  wired to a running code path (constitution Principle IV — no describing
  unimplemented "AI-powered" behavior).
- **FR-012**: The server MUST be scoped to a single, user-specified Yahoo fantasy
  football league for this draft season, not all of the user's leagues. Support
  for multiple leagues is out of scope for this spec (see Assumptions).
- **FR-013**: The server MUST support standard live "snake" (turn-order) drafts
  only. Yahoo auction drafts (nomination-and-bidding) are out of scope for this
  spec.
- **FR-014**: The server MUST be strictly read-only/advisory with respect to
  drafting: it MUST NOT submit, modify, or cancel a draft pick via the Yahoo API
  under any circumstance. The user makes the actual pick in Yahoo's own UI; the
  server only ever reads and reports draft/roster/player state.

### Key Entities

- **League**: A Yahoo fantasy football league the user belongs to for a given
  season. Has settings (scoring type, number of teams), a set of teams, and a
  draft.
- **Team**: A team within a league — either the user's own or an opponent's. Has
  a roster of players and standings record.
- **Player**: An NFL player as represented in Yahoo's fantasy data, with position
  eligibility and ranking/ownership metadata.
- **Draft**: The draft event for a league — an ordered sequence of picks, each
  associating a player with the team that selected them and the pick's
  round/overall number. Draft type (snake vs. auction) affects this entity's
  shape (see FR-013).
- **Roster**: The set of players currently owned by a team.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: The user can complete initial Yahoo authentication in under 2
  minutes and never has to manually re-authenticate again during normal use
  (barring explicit revocation).
- **SC-002**: During a live draft, a query for "who's been drafted" reflects
  reality closely enough that the user never sees an already-drafted player
  offered as available (zero false-availability incidents observed in a full
  mock or live draft).
- **SC-003**: A first-time user can go from "server not yet connected" to
  "successfully viewing my league's current draft board" without needing outside
  help beyond the setup instructions.
- **SC-004**: No credential (token or secret) is ever found in the project's git
  history at any point (verifiable via a repo history scan).

## Assumptions

- Yahoo Fantasy **Football** is the only sport in scope for this MVP; other Yahoo
  fantasy sports (baseball, hockey, basketball) are out of scope until explicitly
  requested.
- This is a single-user tool: it authenticates and operates as the one Yahoo
  account belonging to the project owner, not a multi-tenant service for other
  people's credentials.
- Scoped to one league at a time (FR-012) and standard snake drafts only
  (FR-013); multi-league support and auction-draft support are candidate
  Phase 2+ extensions once the single-league snake-draft MVP is proven.
- The server never writes to Yahoo (FR-014, constitution-aligned safety
  boundary): it is a data/visibility layer only. Any future "make a pick for
  me" capability would need its own spec and explicit opt-in, not an
  extension of this one.
- Draft-pick visibility (FR-008/FR-009) is necessarily polling-based, since
  Yahoo's Fantasy Sports API has no push/websocket mechanism for live draft
  events (per the project constitution's Technology & Integration Constraints).
  A 5-second poll interval (FR-009) is assumed as a reasonable default — fast
  enough to act on within a typical draft pick clock, without hammering Yahoo's
  API. This can be revisited in `/speckit-plan` if rate limits require it.
- Recommendation/strategy logic (deciding *who* to pick, not just *who's
  available*) is explicitly out of scope for this spec — it belongs to the
  Phase 2 agentic skills layer described in the project constitution, which
  will consume this server's data rather than duplicate it.
- The full-stack frontend and Oracle Cloud deployment described in the project
  constitution are out of scope for this spec and will get their own spec once
  Phase 1 (this server) and Phase 2 (agentic skills) are proven.
