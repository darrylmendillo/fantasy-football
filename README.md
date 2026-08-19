# yahoo-fantasy-mcp

A hosted, multi-tenant [MCP](https://modelcontextprotocol.io) server for
Yahoo Fantasy Football: reads (leagues, rosters, standings, draft results,
available players) and writes (lineup changes, with more coming), usable
directly from Claude or ChatGPT over the network — no local install, no
config file, just add the server URL and sign in with Yahoo.

Full design docs, research, and requirements:

- [`specs/002-hosted-multitenant-mcp/`](specs/002-hosted-multitenant-mcp/) —
  **current.** The hosted, multi-tenant, read+write server this README
  describes. Source of truth for anything below.
- [`specs/001-yahoo-fantasy-mcp/`](specs/001-yahoo-fantasy-mcp/) — superseded.
  The original single-league, read-only, stdio proof of concept. Kept
  because the constitution requires it as a validated Phase 1 precondition
  for Phase 2 (this server); not how the server runs today.

## Status

Be precise about what's actually proven, not just built:

- **Protocol and wiring: real, tested, CI-verified.** 147 tests
  (`uv run pytest tests/`), `ruff` clean, and every push runs the real
  `@modelcontextprotocol/inspector` in its non-interactive `--cli` mode
  against a live instance of this server
  (`scripts/verify-mcp-protocol.sh`, wired into
  [`.github/workflows/ci.yml`](.github/workflows/ci.yml)). This proves the
  OAuth metadata, the auth gate, and the tool/annotation surface are wired
  correctly.
- **Functional correctness against live Yahoo data: not yet provable.**
  Everything above runs with dummy Yahoo credentials — no live account
  involved. Real verification is blocked on Yahoo's separate **Fantasy
  Sports API Access Application** approval for the operator's Client ID
  (a manual review at <https://sports.yahoo.com/developer/access/>, no
  published turnaround time). Until that clears, live calls fail with
  `additional_authorization_required` regardless of how correct the code
  is — confirmed directly against Yahoo's API, not assumed.
- **Writes are extra-gated.** Even once reads work, `confirm_action`'s
  lineup-write path is a deliberate stub (`WRITE_NOT_APPROVED`, always) until
  Yahoo write scope is confirmed granted *and* the real
  `Team.change_positions` call signature is verified against
  `yahoo_fantasy_api` (constitution Principle I forbids implementing
  against a guessed third-party signature). No write has ever been sent to
  Yahoo by this server.

See [`specs/002-hosted-multitenant-mcp/quickstart.md`](specs/002-hosted-multitenant-mcp/quickstart.md)
("Release gates") for the exact gates and validation scenarios.

## Scope

- **Multi-league.** Discovers every league the connecting Yahoo account
  belongs to, across every Yahoo fantasy sport.
- **Football-only for now.** Non-football leagues show up in `list_leagues`
  so users aren't confused by absence, but every other tool refuses them —
  extensible later, not hardcoded out.
- **Read AND write, write always confirmed.** Every write is two calls:
  `propose_*` (changes nothing, returns a preview + confirmation token) then
  `confirm_action` (the only call that actually writes). This is enforced
  **server-side** — not by trusting the host client's own tool-approval UI,
  which is inconsistent across clients and bypassable via "always allow."
- **Multi-tenant.** Every request is scoped to the calling user's own
  verified Yahoo token; nothing is cached or shared across users. See
  [`specs/002-hosted-multitenant-mcp/spec.md`](specs/002-hosted-multitenant-mcp/spec.md)
  user story US1 sc.3 — tenant isolation is the single most load-bearing
  guarantee in this codebase.

## Setup (operator)

```bash
uv sync
cp .env.example .env
```

Edit `.env` — **server-level configuration only**, nothing user-specific
(per-user Yahoo tokens come from the OAuth flow at runtime, encrypted by
FastMCP, never written to disk here):

| Variable | What it is |
|---|---|
| `YAHOO_CLIENT_ID` / `YAHOO_CLIENT_SECRET` | From a Yahoo Developer app — https://developer.yahoo.com/apps/. You also need an **approved Fantasy Sports API Access Application** for that Client ID at https://sports.yahoo.com/developer/access/ (separate review step; see Status above). |
| `PUBLIC_BASE_URL` | The public HTTPS URL this server is reachable at. MCP clients require TLS — plain HTTP will not be accepted by Claude or ChatGPT. |
| `YAHOO_SCOPE` | `fspt-w` (read/write, default) or `fspt-r` if Yahoo has only approved read access — write tools then fail cleanly with `WRITE_NOT_APPROVED` instead of failing obscurely at call time. |
| `PORT` | Optional. Default `8000`. |
| `DB_PATH` | Optional. SQLite file for users, usage history, and pending write proposals. Default `./yahoo_fantasy_mcp.db` (gitignored). |
| `PROPOSAL_TTL_SECONDS` | Optional. How long a `propose_*` confirmation token stays valid. Default `300`. |
| `YAHOO_POLL_INTERVAL_SECONDS` | Optional, currently unused by any tool — reserved for a future live-draft polling feature. Default `5`. |

`.env` is gitignored, never committed, logged, or printed — `ServerConfig.__repr__`
in `src/yahoo_fantasy_mcp/config.py` redacts both credential fields even in
tracebacks.

## Run it

```bash
uv run python -m yahoo_fantasy_mcp
```

Serves HTTP on the configured port. There is no login step for the
*operator* to run — each end user authenticates by adding the server in
their own MCP client (Claude, ChatGPT) and completing Yahoo's OAuth consent
in their browser; the server advertises OAuth metadata for the client to
discover automatically (dynamic client registration, PKCE — see
`src/yahoo_fantasy_mcp/auth_proxy.py`).

### Connect a client

**Claude**: add the server by URL in connector settings.
**ChatGPT**: add as a connector by the same URL.

Both discover the OAuth metadata, walk the Yahoo consent flow, and return
authenticated — no client-side credential entry, no config file. (There is
deliberately no `claude mcp add ... -- <stdio command>` path for this
server — that pattern belongs to the old single-user local mode in
`specs/001-yahoo-fantasy-mcp/`, not this one.)

## Tools

| Tool | What it does |
|---|---|
| `check_auth` | Whether the caller's Yahoo authorization is currently usable. Never returns a token. |
| `list_leagues` | Every Yahoo fantasy league the caller belongs to, across all sports. |
| `get_league_info` | A league's identity, season, scoring type, and draft status. |
| `list_teams` | Teams in a league, flagging the caller's own. |
| `get_roster` | A team's current roster (defaults to the caller's own team). |
| `get_standings` | Current league standings. |
| `get_draft_results` | Every pick made so far, freshest read available. |
| `get_available_players` | Undrafted players with ranking context. **Guaranteed** to never overlap with `get_draft_results` for the same read — see below. |
| `propose_set_lineup` | Preview a lineup change. Changes nothing; returns a confirmation token. |
| `confirm_action` | The only tool that writes to Yahoo. Requires a valid, unexpired, single-use, same-user confirmation token from a `propose_*` call. Currently refuses every call with `WRITE_NOT_APPROVED` (see Status above). |

Every `league_key`-scoped tool refuses a league the caller doesn't belong to
(`LEAGUE_NOT_ACCESSIBLE`) and a non-football league (`SPORT_NOT_SUPPORTED`) —
never silently serves either. Full request/response contracts:
[`specs/002-hosted-multitenant-mcp/contracts/mcp-tools.md`](specs/002-hosted-multitenant-mcp/contracts/mcp-tools.md).

More write tools (`propose_add_drop`, `list_trade_offers`,
`propose_trade_response`) are designed in the contract but not yet
implemented — tracked as Phases 6–7 in
[`specs/002-hosted-multitenant-mcp/tasks.md`](specs/002-hosted-multitenant-mcp/tasks.md).

**Known limitation**: `average_pick` (ADP) in `get_available_players` is
always `null`. The underlying `yahoo_fantasy_api` library has no
draft-analysis endpoint. Disclosed, not silently broken.

## The one thing this server exists to get right

Yahoo's own client library caches "available players" **forever, with no
expiry**. On a server that stays running through a whole draft, that would
mean a player taken in round 3 could still show as available in round 10 —
silently, no error.

This server never uses that cache for live availability. Every
`get_available_players` call derives its answer fresh from the same draft
read `get_draft_results` uses: `available = all_players − drafted_players`,
recomputed every time, per league, per request. The empty-intersection
guarantee is enforced by tests including a check deep into a draft — that's
specifically where a regression back to the cache would surface:
`tests/unit/test_draft.py::TestAvailabilityInvariant`,
`tests/integration/test_tools.py::TestGetAvailablePlayers`,
`tests/integration/test_us2_reads.py::test_availability_invariant_holds_deep_into_draft`.
Full writeup: `specs/001-yahoo-fantasy-mcp/research.md` (R3).

## Development

```bash
uv sync --extra dev
uv run ruff check src/ tests/
uv run pytest tests/ -q       # 147 tests, fixtures only — no network, no live account needed
```

`--extra local` additionally installs `yahoo_oauth` (used only by the
legacy spec-001 code paths some tests exercise, not by the hosted server).

### CI

Runs on a **self-hosted runner** (the operator's own box, registered as
`oracle-fantasy-football-box`) rather than GitHub-hosted minutes — see
[`.github/workflows/ci.yml`](.github/workflows/ci.yml). Two jobs: `ruff` +
`pytest`, then `scripts/verify-mcp-protocol.sh` (the real MCP Inspector CLI
check described in Status above).

## Before trusting this against a real draft or lineup decision

Once Yahoo's access gates clear: run the validation scenarios in
[`specs/002-hosted-multitenant-mcp/quickstart.md`](specs/002-hosted-multitenant-mcp/quickstart.md)
against a real account — especially **V3** (tenant isolation, with two real
Yahoo accounts) and **V6** (confirmation cannot be bypassed, run with the
host's own tool-approval prompts disabled so nothing but this server's own
checks stands between a call and Yahoo). Neither is optional before this
server is trusted with real data or a real write.
