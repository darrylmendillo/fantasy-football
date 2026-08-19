# Quickstart & Validation: Hosted Multi-Tenant Fantasy MCP Server

**Feature**: `002-hosted-multitenant-mcp` | **Date**: 2026-08-17

How to run the hosted server and prove it works. Scenarios map to spec
acceptance criteria and are the manual counterpart to the automated tests, not
a substitute for them.

---

## Release gates

Neither is under our control; both block implementation, not planning.

1. **Yahoo API Access Application approved** for the operator's Client ID at
   <https://sports.yahoo.com/developer/access/>. **Read+write (`fspt-w`)** is
   required for V5–V9; read-only (`fspt-r`) still permits V1–V4.
2. **Phase 1 validated end-to-end** (spec 001, T055) — required by constitution
   Principle I before this phase's implementation begins.

---

## MCP Inspector verification (mock-validated)

Performed 2026-08-18, at the end of the mock-validated implementation pass
(T013–T048). **No Yahoo account was involved anywhere in this section** —
`YAHOO_CLIENT_ID`/`YAHOO_CLIENT_SECRET` were the literal string `dummy`.
Everything below is a protocol/wiring check, not a functional one; G1/G2/G3
(above) remain the gates for anything claiming to actually work against
Yahoo.

`@modelcontextprotocol/inspector`'s default `--web` mode opens an interactive
browser UI, which isn't drivable in this (headless, non-interactive)
environment. The first pass below substituted direct HTTP/Python
verification against the real running server for that. A later pass (see
"Genuine MCP Inspector CLI run" further down) used the package's actual
`--cli` mode instead — the real Anthropic tool, not a substitute — once it
was confirmed that mode exists and runs non-interactively.

**Server started** exactly per this doc's Step 1 command
(`YAHOO_CLIENT_ID=dummy YAHOO_CLIENT_SECRET=dummy PUBLIC_BASE_URL=http://localhost:8000
DB_PATH=/tmp/inspect.db .venv/bin/python -m yahoo_fantasy_mcp`) — started clean,
no errors, `Uvicorn running on http://0.0.0.0:8000`.

**OAuth metadata, verified live via `curl` against the running server:**

- `GET /.well-known/oauth-authorization-server` → 200, advertises
  `authorization_endpoint`, `token_endpoint`, `registration_endpoint`
  (dynamic client registration is live), `scopes_supported: ["fspt-w"]`
  (matches configured `YAHOO_SCOPE`), `code_challenge_methods_supported: ["S256"]`
  (PKCE), `client_id_metadata_document_supported: true`.
- `GET /.well-known/oauth-protected-resource` → 404 (expected — metadata is
  per-resource, not global). `GET /.well-known/oauth-protected-resource/mcp`
  → 200, correctly scoped: `resource: "http://localhost:8000/mcp"`,
  `authorization_servers: ["http://localhost:8000/"]`, matching `scopes_supported`.
- `POST /mcp` with **no** bearer token → **401 Unauthorized**, with
  `WWW-Authenticate: Bearer resource_metadata="http://localhost:8000/.well-known/oauth-protected-resource/mcp"`
  — the exact discovery flow the MCP OAuth spec requires: an unauthenticated
  client is told precisely where to find out how to authenticate. This is
  live proof the whole auth stack (Tasks 1, 2, 4) is wired correctly at the
  protocol level, not just unit-tested in isolation.

**Tool list and annotations, verified live via `build_server()` against this
exact running config** (in-process call, same product code the HTTP server
uses — listing tools over the wire would require a real Yahoo session,
which dummy credentials can't provide; this is the same limitation Step 2
already anticipated):

10 tools registered, exactly: `check_auth`, `list_leagues`, `get_league_info`,
`list_teams`, `get_roster`, `get_standings`, `get_draft_results`,
`get_available_players`, `propose_set_lineup` — all `readOnlyHint=True,
destructiveHint=False, openWorldHint=True` — and `confirm_action`, the
**only** tool with `destructiveHint=True` (`readOnlyHint=False`). Matches
`contracts/mcp-tools.md` exactly for the tools this pass covers.
`propose_add_drop`/`list_trade_offers`/`propose_trade_response` (documented
in the contract for US4/US5) are correctly absent — those tasks (T049–T062)
were not part of this execution pass's scope.

**Conclusion**: the protocol surface is real and correctly wired. What
remains unverified, because it requires an actual Yahoo account and
approved API access (gates G1–G3, tasks.md), is whether the *content* of
what these tools return is correct against live data — that's what V1–V9
above are for, once the gates clear.

### Genuine MCP Inspector CLI run (2026-08-19)

Ran the real `@modelcontextprotocol/inspector` package (v2.2.0, fetched live
via `npx -y @modelcontextprotocol/inspector`) in its `--cli` mode — a
non-interactive mode the package documents explicitly for CI use
(`--stored-auth-only`: "Never start interactive OAuth... Preferred for
CI/non-interactive runs"). This supersedes nothing above; it adds a second,
independent confirmation from the actual Anthropic tool rather than a
hand-rolled equivalent.

Server started identically to the 2026-08-18 run (dummy Yahoo credentials,
same command). Command run against it:

```bash
npx -y @modelcontextprotocol/inspector --cli \
  --server-url http://localhost:8000/mcp --transport http \
  --method tools/list --stored-auth-only --format json
```

**Output:**
```json
{"error":{"code":"auth_required","message":"Error POSTing to endpoint: "}}
```
Exit code 3.

This is the real inspector tool independently reaching the same conclusion
the curl-based check above did: `tools/list` cannot proceed without a valid
OAuth token, and the tool refuses to silently continue or fake one. It does
**not** go further than the curl-based check — `tools/list` still cannot
actually be listed over the wire, because that requires a real Yahoo
consent flow, which dummy credentials cannot complete (same gate G1–G3
limitation noted throughout this document). Getting an authenticated
`tools/list` via this same command is the natural first live check once
gate G1 clears — swap `--stored-auth-only` for a real interactive login
(drop that flag, add `--client-id`/`--client-secret` if using a static
client) and rerun.

Repeatable as `scripts/verify-mcp-protocol.sh` — starts the server with
dummy credentials, re-runs every check above (OAuth metadata, unauthenticated
401, and the real inspector `--cli` `auth_required` check), and tears the
server down on exit.

## Prerequisites

- Python 3.11+, `uv`.
- The operator's Yahoo Developer app (Client ID + Secret) with approved access.
- A public HTTPS hostname pointing at the Oracle server. MCP clients require
  TLS; plain HTTP will not be accepted by Claude or ChatGPT.
- At least **two** Yahoo accounts in at least one fantasy football league each
  — one account cannot demonstrate the isolation guarantee (V3).

## Setup

```bash
uv sync
cp .env.example .env
$EDITOR .env    # server credentials + public base URL; NO league key, NO user tokens
```

Server-level configuration only. Per-user Yahoo tokens are obtained through the
OAuth flow at runtime and stored encrypted by FastMCP — never in `.env`.

```bash
uv run python -m yahoo_fantasy_mcp        # serves HTTP on the configured port
```

**Verify nothing secret is tracked** before any commit:

```bash
git status --porcelain          # expect: no .env, no token store, no *.db
git check-ignore -v .env
```

## Connect a client

**Claude**: add the server by URL in connector settings.
**ChatGPT**: add as a connector by the same URL.

Both should discover the OAuth metadata, walk the Yahoo consent flow, and
return authenticated. No client-side credential entry, no config file.

---

## Validation scenarios

### V1 — First-time connection (US1, FR-001–003)

1. From a client with no prior setup, add the server URL.
2. Complete Yahoo sign-in when prompted.
3. Ask: "what fantasy leagues am I in?"

**Expected**: correct leagues for that account. No manual credential step
anywhere. **No token value appears in any output.**

---

### V2 — Session survives (US1 sc.2, FR-004)

Return ≥1 day later (or fast-forward the stored upstream expiry) and issue any
read.

**Expected**: succeeds with no re-consent. Refresh happened transparently.

---

### V3 — Tenant isolation (US1 sc.3, FR-005) ⭐

The single most important scenario in this feature.

1. Connect account A in one client; connect account B in another.
2. Interleave requests: A lists leagues, B lists leagues, A reads a roster, B
   reads a roster.
3. Attempt the cross-tenant case: ask A for a `league_key` belonging only to B.

**Expected**: each sees only their own leagues and rosters; step 3 is refused
with `LEAGUE_NOT_ACCESSIBLE`. **Any leakage here is a release blocker**, not a
bug to file.

---

### V4 — Multi-league reads and the availability invariant (US2, FR-008–012)

1. With an account in ≥2 leagues, request standings in each by name.
2. Ask about a non-football league.
3. During a live or mock draft, call `get_draft_results` and
   `get_available_players` repeatedly, **including deep into the draft**.

**Expected**: correct distinct results per league; non-football refused with
`SPORT_NOT_SUPPORTED` while still appearing in `list_leagues`; and **zero
overlap** between drafted and available players at every point. Late-draft
checks matter most — that is where a regression to cached availability shows up
(spec 001 research R3).

---

### V5 — Lineup change requires confirmation (US3, FR-014–021) 🔒 write

1. Ask to start one player and bench another.
2. **Before confirming**, check the lineup in the Yahoo app.
3. Confirm.
4. Check Yahoo again.

**Expected**: unchanged at step 2; applied at step 4; preview at step 1 named
exactly the players and slots that changed (FR-018).

---

### V6 — Confirmation cannot be bypassed (FR-019, FR-020, FR-023) 🔒 write

Adversarial. Attempt each, expecting refusal:

| Attempt | Expected |
|---|---|
| Call `confirm_action` with a made-up token | `INVALID_CONFIRMATION` |
| Reuse a token that already succeeded | `PROPOSAL_ALREADY_USED` |
| Confirm after the TTL elapses | `PROPOSAL_EXPIRED` |
| Confirm user A's token while authenticated as B | `INVALID_CONFIRMATION` |
| Propose, change the roster in the Yahoo app, then confirm | `PRECONDITIONS_CHANGED` |

**Expected**: five refusals, zero writes. This scenario is what proves the
guarantee lives in the server rather than the host UI — run it in a client with
tool-approval prompts **disabled** so nothing but our own checks stands between
the call and Yahoo.

---

### V7 — Add/drop is atomic (US4, FR-015, FR-022) 🔒 write

1. Propose adding an available player and dropping a rostered one.
2. Confirm; verify both halves in Yahoo.
3. Repeat, but have the target player claimed by someone else between propose
   and confirm.

**Expected**: step 2 applies both together; step 3 refuses with
`PRECONDITIONS_CHANGED` and — critically — **the drop does not happen**.

---

### V8 — Trade responses (US5, FR-016) 🔒 write

1. Have another manager send an offer; call `list_trade_offers`.
2. Reject one after confirmation; accept another after confirmation.
3. Ask the assistant to *send* a new trade offer.

**Expected**: both sides of each offer described accurately; responses applied;
step 3 refused with `TRADE_INITIATION_NOT_SUPPORTED` and a plain explanation.

---

### V9 — Write access not approved (FR-025) 🔒

Only runnable while write approval is pending — do it *before* approval lands,
because the state is unreproducible afterward.

**Expected**: write attempts fail with `WRITE_NOT_APPROVED` explaining the
product cannot write yet — clearly distinct from "your request was invalid."
Reads unaffected.

---

### V10 — Revocation (US1 sc.4, FR-006–007)

Revoke the app's access from Yahoo account settings, then issue any request.

**Expected**: clear `AUTH_EXPIRED` with reconnection guidance — not a stack
trace, not a confusing internal error.

---

## Operational checks (FR-029)

```bash
systemctl status <service>     # running under process supervision
curl -sI https://<host>/       # valid TLS, expected status
sqlite3 <db> ".tables"         # users, usage_events, proposals present
```

Confirm: restart preserves connected users (tokens survive); pending proposals
either survive restart or fail closed as expired — **never** silently succeed
after a restart; logs contain no token-shaped strings.

### ⚠️ Do not rotate `YAHOO_CLIENT_SECRET` without a re-auth plan

FastMCP's `OAuthProxy` stores every user's Yahoo token in an encrypted store
whose location/encryption key is derived from `YAHOO_CLIENT_SECRET`. Rotating
that secret therefore silently orphans every currently-stored session at
once — nobody is notified, and affected users will simply start seeing
`AUTH_REQUIRED`/`AUTH_EXPIRED` the next time they call a tool, with no
indication that a server-side secret rotation was the cause. Do not rotate
`YAHOO_CLIENT_SECRET` unless you are prepared for every connected user to
re-authenticate from scratch.

---

## Automated coverage expectation

Manual scenarios above complement, never replace, the suite. Per constitution
Principle II, these MUST be covered by tests that need no live account:

- Confirm-flow logic: expiry, single-use, wrong-user, precondition drift
  (V6 in full, against a fake clock and store).
- Tenant isolation at the resolution layer: two fake identities, asserting no
  cross-access (V3's logic).
- Tool annotations present and correct on every tool (FR-024).
- Availability invariant, including a late-draft fixture (carried from Phase 1).
- Write dispatch: assert `add_and_drop_players` is called once for a combined
  move, never as two calls (FR-022).
