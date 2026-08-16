<!--
Sync Impact Report
Version change: none → 1.0.0 (initial ratification)
Modified principles: n/a (initial version)
Added sections: Core Principles (I-V), Technology & Integration Constraints,
  Development Workflow, Governance
Removed sections: none
Deferred TODOs: none
-->

# Fantasy Football Constitution

## Core Principles

### I. MVP-First, Phased Delivery
Build in proven, demonstrable phases: (1) a Yahoo Fantasy Sports MCP server
(FastMCP-based) exposing read access and draft-pick visibility, (2) agentic
skills for draft research and live recommendations on top of it, (3) only
once phases 1-2 are proven working end-to-end, a full-stack app with its own
frontend. Each phase MUST be independently working and verified before the
next phase's spec is written. Do not build ahead of the proven need.

### II. Test-First (NON-NEGOTIABLE)
TDD is mandatory for all non-trivial logic: Yahoo API response parsing,
OAuth token refresh handling, draft-recommendation scoring, and any ranking
or strategy logic. Tests are written first, confirmed to fail, then made to
pass. Trivial glue code (thin handler wiring, config loading) is exempt but
MUST still be exercised by integration tests before a phase is declared
done.

### III. No Committed Credentials
Yahoo OAuth client secrets, access tokens, and refresh tokens MUST NEVER be
committed to version control, in any form (including "example" or
"placeholder" files that could be mistaken for real ones). `.gitignore`
MUST explicitly cover token/credential filenames used by the project
(verified to actually match, dotfiles included). Tokens live only in
gitignored local files or environment variables, never logged.

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
- Yahoo integration: Yahoo Fantasy Sports OAuth2 API. No unofficial/scraped
  data sources for anything OAuth-gated.
- Draft-time "live" data is polling-based (Yahoo's API has no push/websocket
  for live drafts) — polling interval and staleness handling MUST be an
  explicit, tested part of the design, not an afterthought.
- Later full-stack phase: frontend to be served from the user's own Oracle
  Cloud infrastructure. No frontend/deployment work begins before the MCP
  server + agentic skills phases are proven.

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

**Version**: 1.0.0 | **Ratified**: 2026-08-16 | **Last Amended**: 2026-08-16
