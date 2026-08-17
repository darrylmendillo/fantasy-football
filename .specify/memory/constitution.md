<!--
Sync Impact Report
Version change: 0.2.0 → 0.3.0 (MINOR — two-tier validation added to Principle I)
  Principle I gained a "Two tiers of done" clause: external approvals no
  longer idle implementation. Work may proceed to *mock-validated* tier at
  any time; *integration-validated* remains required before anything is
  called done, working, or deployable. Added because Yahoo's API access
  review is an indefinite external block, and the alternative — waiting —
  costs weeks while teaching us nothing. The clause deliberately does NOT
  relax what "done" means; it names a lower tier honestly instead of
  letting mock-passing quietly masquerade as working.

Prior change: 1.0.0 → 0.2.0 (pre-1.0 renumbering + product pivot)
Rationale: the initial 1.0.0 ratification overstated maturity — this project
  is pre-release, nothing has shipped to real users, and the product
  direction is still in flux (as this very amendment demonstrates). The
  constitution is renumbered onto a 0.x line where breaking governance
  changes are expected and land as MINOR bumps. A 1.0.0 will be declared
  when the product direction is stable.
Modified principles:
  I. MVP-First, Phased Delivery — old 3-phase model (local read-only MCP →
     agentic skills layer → full-stack app with its own frontend) replaced
     with a 2-proven-phase + explicit-future model (prove core Yahoo
     integration → hosted multi-tenant MCP-native-OAuth read/write server).
     The full-stack-app-with-its-own-frontend goal is dropped entirely.
  II. Test-First (NON-NEGOTIABLE) — scope extended to explicitly cover
     OAuth-proxy/multi-tenancy logic and the write-confirmation flow.
  III. No Committed Credentials — scope extended from "one local token
     file" to "per-user tokens stored server-side."
Unmodified principles: IV. Honest, Wired Architecture; V. Simplicity / YAGNI
Added sections: none (structure unchanged)
Removed sections: none (Technology & Integration Constraints content
  revised in place, see below)
Modified sections:
  Technology & Integration Constraints — removed the "later full-stack
    phase: frontend served from Oracle Cloud" constraint (no frontend in
    scope); added transport (FastMCP HTTP from Phase 2), auth (FastMCP
    OAuthProxy presenting MCP-native OAuth while proxying to Yahoo's
    OAuth2), write-access and two-step confirm requirements.
Deferred TODOs: none
-->

# Fantasy Football Constitution

## Core Principles

### I. MVP-First, Phased Delivery
Build in proven, demonstrable phases: (1) a Yahoo Fantasy Sports MCP server
(FastMCP-based, local, single-user) exposing read access, OAuth, and
draft-pick visibility; (2) evolve that into a hosted,
multi-tenant Yahoo Fantasy MCP server — MCP-native OAuth (via an
OAuth-proxy pattern in front of Yahoo's own OAuth2), multi-league,
read **and** write (Yahoo Transactions/Roster resources, gated by a
server-enforced two-step confirm), deployed on the user's own Oracle Cloud
server, reachable directly from Claude and ChatGPT as MCP clients. There is
no separate consumer-facing frontend or full-stack app in this product's
scope — the connected AI assistant is the interface. Phase 3+ (a
docs-harvesting job for agentic Yahoo API doc resources, a prompts/skill
layer on top of the tool primitives, and monetization/tiering) is
acknowledged future direction only — not designed or built until Phase 2 is
proven. Each phase MUST be independently working and verified before the
next phase's spec is written. Do not build ahead of the proven need.

**Two tiers of done (added v0.3.0).** External approvals outside our control
(e.g. Yahoo's API access review) MUST NOT idle implementation. Work is
therefore validated in two tiers, and the distinction MUST be stated
explicitly wherever status is reported:

- **Mock-validated** — logic implemented and passing against fakes, fixtures,
  and protocol-level inspection. Implementation MAY proceed to this tier at
  any time, including before external approvals land.
- **Integration-validated** — the same code exercised against the real
  external system with real credentials.

A capability is **not "done," not "working," and not deployable** on
mock-validation alone. Mocks encode *our assumptions* about a third-party
interface; a passing mock proves our code is self-consistent, never that the
external contract was understood correctly. Any interface shape not yet
verified against the live system MUST be recorded as unverified (Principle
IV) and MUST NOT be implemented against a guessed signature — verify first,
then write. Phase N+1 may be built to mock-validated tier while Phase N
awaits integration validation; neither ships until integration-validated.

### II. Test-First (NON-NEGOTIABLE)
TDD is mandatory for all non-trivial logic: Yahoo API response parsing,
OAuth token refresh handling, the OAuth-proxy/multi-tenancy layer
(per-user token issuance, storage, and refresh), the write-confirmation
flow (propose/confirm token lifecycle), draft-recommendation scoring, and
any ranking or strategy logic. Tests are written first, confirmed to fail,
then made to pass. Trivial glue code (thin handler wiring, config loading)
is exempt but MUST still be exercised by integration tests before a phase
is declared done.

### III. No Committed Credentials
Yahoo OAuth client secrets, access tokens, and refresh tokens — including
every individual user's tokens once the server is multi-tenant — MUST
NEVER be committed to version control, in any form (including "example" or
"placeholder" files that could be mistaken for real ones). `.gitignore`
MUST explicitly cover token/credential filenames used by the project
(verified to actually match, dotfiles included). Per-user tokens live only
in server-side encrypted/gitignored storage, never logged, never returned
in tool output.

### IV. Honest, Wired Architecture
No module ships as if functional unless it is actually import-reachable
from the running entrypoint and covered by a passing test. Documentation
and tool descriptions MUST NOT claim capabilities (e.g. "AI-powered",
"real-time") that the wired code path does not actually implement. Dead or
speculative code is deleted, not left in the tree implying it's live.

### V. Simplicity / YAGNI
Prefer the smallest design that satisfies the current phase's spec. No
speculative abstraction, no framework layers added ahead of a proven need.
Specs and plans stay layered and phased (per Development Workflow below)
rather than a single heavyweight upfront design.

## Technology & Integration Constraints

- MCP server layer: Python, built on **FastMCP**.
- Transport: local stdio for Phase 1; FastMCP HTTP transport from Phase 2
  onward, so the server is reachable remotely by Claude and ChatGPT.
- Auth: Phase 2 onward uses an OAuth-proxy pattern (e.g. FastMCP's
  `OAuthProxy`) that presents a spec-compliant MCP-native OAuth interface
  to MCP clients while proxying to Yahoo's own OAuth2 (consumer key/secret,
  non-DCR) underneath. Tokens are stored per authenticated user.
- Yahoo integration: Yahoo Fantasy Sports OAuth2 API. No unofficial/scraped
  data sources for anything OAuth-gated. Write access (Transactions and
  Roster resources) is in scope from Phase 2 and requires Yahoo's explicit
  read/write API access approval; every write action MUST go through a
  server-enforced two-step propose/confirm pattern whose guarantee does not
  depend on any MCP host's own tool-approval UI.
- Draft-time "live" data is polling-based (Yahoo's API has no push/websocket
  for live drafts) — polling interval and staleness handling MUST be an
  explicit, tested part of the design, not an afterthought.
- No separate frontend or full-stack app is in scope. Oracle Cloud hosts the
  MCP server itself.

## Development Workflow

- All feature work flows through Spec Kit phases in order:
  `/speckit-specify` → `/speckit-plan` → `/speckit-tasks` → `/speckit-implement`,
  with `/speckit-clarify`, `/speckit-analyze`, and `/speckit-checklist` used
  as needed to de-risk before implementation.
- Specs, plans, and research for each feature live under
  `specs/<NNN-feature-name>/` and are the source of truth — this is the
  canonical directory for design docs and research, kept in version control.
- `/speckit-converge` is used when resuming a feature or moving to the next
  phase, to reconcile the codebase against its specs before adding new work.
- Every commit implementing a spec'd feature references the spec directory
  it implements.

## Governance

This constitution supersedes ad hoc practice for this project. Amendments
are made via `/speckit-constitution`, require a version bump per semantic
versioning (MAJOR: incompatible principle removal/redefinition; MINOR: new
principle or materially expanded guidance; PATCH: clarification/wording),
and update `Last Amended` below. Compliance with Principles I-V is checked
at each `/speckit-implement` and `/speckit-converge` checkpoint; violations
block moving to the next phase rather than being deferred.

**Version**: 0.3.0 | **Ratified**: 2026-08-16 | **Last Amended**: 2026-08-17
