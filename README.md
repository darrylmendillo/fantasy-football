# yahoo-fantasy-mcp

A read-only [MCP](https://modelcontextprotocol.io) server for Yahoo Fantasy
Football: league info, rosters, standings, and — the reason this exists —
live draft-pick visibility during your draft.

Full design docs, research, and requirements live in
[`specs/001-yahoo-fantasy-mcp/`](specs/001-yahoo-fantasy-mcp/). This README is
the short version; that directory is the source of truth.

## Scope

- **Read-only.** This server never submits a pick to Yahoo. You draft in
  Yahoo's own UI; this just tells you what's happened and what's left.
- **One league.** Configured to a single Yahoo fantasy football league.
- **Snake drafts only.** Auction leagues are explicitly rejected, not
  silently mishandled.

See [`specs/001-yahoo-fantasy-mcp/spec.md`](specs/001-yahoo-fantasy-mcp/spec.md)
for the full requirements and rationale.

## Setup

Two ways to run this. Pick one.

### Option A: locally on your own machine

```bash
uv sync
cp .env.example .env
```

Edit `.env`:

| Variable | What it is |
|---|---|
| `YAHOO_CLIENT_ID` / `YAHOO_CLIENT_SECRET` | From a Yahoo Developer app — https://developer.yahoo.com/apps/. You also need an **approved Fantasy Sports API Access Application** for that Client ID at https://sports.yahoo.com/developer/access/ (a separate review step from app creation; no published turnaround time). Without it, calls fail with `additional_authorization_required` even with a valid token. Request Read only; this server doesn't need or use write scope. |
| `YAHOO_LEAGUE_KEY` | The single league this server serves, e.g. `449.l.99001`. |
| `YAHOO_POLL_INTERVAL_SECONDS` | How often to poll during a live draft. Default `5`. |
| `YAHOO_ROSTER_SIZE` | Roster spots per team in your league. Only affects the `is_complete` flag on draft results, not correctness of who's available. Default `16`. |

`.env` is gitignored. It is never committed, logged, or printed — see
`specs/001-yahoo-fantasy-mcp/data-model.md` validation rule 4 and
`src/yahoo_fantasy_mcp/logging_utils.py`.

### Option B: GitHub Codespaces

`.devcontainer/devcontainer.json` provisions Python 3.11 + `uv` and runs
`uv sync` automatically when the Codespace builds. No local install needed.

Codespaces secrets become environment variables automatically inside the
Codespace terminal — the same `config.py` reads either way, no code branch
for "am I in a Codespace." **The secret names must match exactly** what
`config.py` looks up (`os.environ.get`) — GitHub secret names do not get a
`YAHOO_` prefix added automatically:

| Codespaces secret name (GitHub Settings → Secrets and variables → Codespaces) | Value |
|---|---|
| `YAHOO_CLIENT_ID` | Your Yahoo app's Client ID |
| `YAHOO_CLIENT_SECRET` | Your Yahoo app's Client Secret |
| `YAHOO_LEAGUE_KEY` | Your league key, e.g. `449.l.99001` |

If you already added secrets named `CLIENT_ID`/`CLIENT_SECRET` (without the
`YAHOO_` prefix) — rename them to the names above; `config.py` won't find
them otherwise. `APP_ID` isn't used by this server (the OAuth flow only
needs Client ID + Secret) — harmless to leave it, just inert.

`YAHOO_POLL_INTERVAL_SECONDS` and `YAHOO_ROSTER_SIZE` have safe defaults
(`5`, `16`) — only add them as secrets if you want to override those.

Once the secrets are named correctly and the Codespace rebuilds, `uv run
python -m yahoo_fantasy_mcp` should find them exactly like a local `.env`
would.

**First login in a Codespace looks different than local**: there's no GUI
browser in the container, so instead of a browser window opening, the
terminal prints a Yahoo authorization URL directly and waits for you to
paste back a verifier code — open the printed URL yourself (in your actual
browser, on your own machine), approve access, and paste the code shown
back into the Codespace terminal.

## Run it

```bash
uv run python -m yahoo_fantasy_mcp
```

First run opens a browser for a one-time Yahoo OAuth consent. After that,
tokens refresh automatically — you shouldn't need to log in again.

### Register with Claude Code

```bash
claude mcp add yahoo-fantasy -- uv run python -m yahoo_fantasy_mcp
```

Transport is stdio — no network listener, no exposed port. Credentials never
leave the machine.

## Tools

| Tool | What it does |
|---|---|
| `check_auth` | Whether credentials are valid, and for how long. Never returns a token. |
| `get_league_info` | The configured league's identity and draft status. |
| `list_teams` | Teams in the league, flagging your own. |
| `get_roster` | A team's current roster (defaults to yours). |
| `get_standings` | Current league standings. |
| `get_draft_results` | Every pick made so far, freshest read available. Empty pre-draft, complete post-draft. |
| `get_available_players` | Undrafted players with ranking context. **Guaranteed** to never overlap with `get_draft_results` for the same read — see below. |

Full request/response contracts:
[`specs/001-yahoo-fantasy-mcp/contracts/mcp-tools.md`](specs/001-yahoo-fantasy-mcp/contracts/mcp-tools.md).

**Known limitation**: `average_pick` (ADP) in `get_available_players` is
currently always `null`. The underlying `yahoo_fantasy_api` library has no
draft-analysis endpoint — `percent_owned` is real, ADP needs a future
supplementary data source. Disclosed, not silently broken.

## The one thing this server exists to get right

Yahoo's own client library caches "available players" **forever, with no
expiry**. On a server that stays running through your whole draft, that
would mean a player taken in round 3 could still show as available in round
10 — silently, no error.

This server never uses that cache for live availability. Every
`get_available_players` call derives its answer fresh from the same draft
read `get_draft_results` uses: `available = all_players − drafted_players`,
recomputed every time. The empty-intersection guarantee between those two
tools is enforced by tests (`tests/unit/test_draft.py::TestAvailabilityInvariant`,
`tests/integration/test_tools.py::TestGetAvailablePlayers`), including a
check at a *later* draft stage — that's specifically where a regression back
to the cache would surface. Full writeup:
[`specs/001-yahoo-fantasy-mcp/research.md`](specs/001-yahoo-fantasy-mcp/research.md) (R3).

## Development

```bash
uv sync
.venv/bin/pytest tests/       # 57 tests, fixtures only — no network, no live account needed
.venv/bin/ruff check src/ tests/
```

## Before your actual draft

Run a **Yahoo mock draft** first. `get_draft_results` and
`get_available_players` are the two tools that matter live, and the failure
mode they guard against (stale availability) doesn't show up in the first
few picks — it shows up deep into a draft. See
[`specs/001-yahoo-fantasy-mcp/quickstart.md`](specs/001-yahoo-fantasy-mcp/quickstart.md)
scenarios V4/V5 for exactly what to check.
