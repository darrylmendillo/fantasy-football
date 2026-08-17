"""SQLite persistence for application state (spec 002, data-model.md).

Scope boundary — this module owns ONLY application state:
``users``, ``usage_events``, ``proposals``. It deliberately does not touch
OAuth client registrations or upstream Yahoo tokens: those belong to
FastMCP's own encrypted store (research R2), and duplicating them here would
mean reimplementing refresh races and encryption that already work.

Nothing in this module is a credential (Principle III). The only
security-sensitive value it holds is a proposal's ``token_hash`` — the SHA-256
of a confirmation token, never the token itself, so a leaked database cannot
be used to confirm an action.
"""

from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    sub          TEXT PRIMARY KEY,
    tier         TEXT NOT NULL DEFAULT 'free',
    created_at   INTEGER NOT NULL,
    last_seen_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS usage_events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    sub         TEXT NOT NULL,
    tool_name   TEXT NOT NULL,
    occurred_at INTEGER NOT NULL,
    outcome     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_usage_sub_time ON usage_events(sub, occurred_at);

CREATE TABLE IF NOT EXISTS proposals (
    id                 TEXT PRIMARY KEY,
    token_hash         TEXT NOT NULL UNIQUE,
    sub                TEXT NOT NULL,
    league_key         TEXT NOT NULL,
    team_key           TEXT NOT NULL,
    action_type        TEXT NOT NULL,
    payload_json       TEXT NOT NULL,
    preview_json       TEXT NOT NULL,
    precondition_json  TEXT NOT NULL,
    created_at         INTEGER NOT NULL,
    expires_at         INTEGER NOT NULL,
    status             TEXT NOT NULL,
    consumed_at        INTEGER
);
CREATE INDEX IF NOT EXISTS idx_proposals_hash ON proposals(token_hash);
CREATE INDEX IF NOT EXISTS idx_proposals_sub ON proposals(sub);
"""

# Terminal states — a proposal in any of these can never be confirmed.
# See data-model.md's state machine; this is what makes replay impossible.
TERMINAL_STATUSES = ("consumed", "expired", "failed")


@dataclass(frozen=True)
class ProposalRow:
    """A stored proposal. Mirrors the `proposals` table in data-model.md."""

    id: str
    token_hash: str
    sub: str
    league_key: str
    team_key: str
    action_type: str
    payload_json: str
    preview_json: str
    precondition_json: str
    created_at: int
    expires_at: int
    status: str
    consumed_at: int | None


class Store:
    """Thin SQLite accessor. One instance per process; SQLite handles the
    concurrency this product's scale needs (research R7)."""

    def __init__(self, db_path: str = ":memory:") -> None:
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    # ---------------------------------------------------------------- users

    def upsert_user(self, sub: str, now: int | None = None) -> None:
        """Create the user on first sight, otherwise just bump last_seen_at.

        Idempotent by design: called on every authenticated request, so it
        must never fail or duplicate on the second call.
        """
        ts = int(time.time()) if now is None else now
        self._conn.execute(
            """
            INSERT INTO users (sub, tier, created_at, last_seen_at)
            VALUES (?, 'free', ?, ?)
            ON CONFLICT(sub) DO UPDATE SET last_seen_at = excluded.last_seen_at
            """,
            (sub, ts, ts),
        )
        self._conn.commit()

    def get_user(self, sub: str) -> sqlite3.Row | None:
        cur = self._conn.execute("SELECT * FROM users WHERE sub = ?", (sub,))
        return cur.fetchone()

    # ---------------------------------------------------------------- usage

    def record_usage(self, sub: str, tool_name: str, outcome: str, now: int | None = None) -> None:
        """Append a usage event (FR-028).

        Deliberately records tool NAME and outcome only — never arguments.
        Arguments carry roster and league detail; this table exists for
        future metering, not surveillance (data-model.md).
        """
        ts = int(time.time()) if now is None else now
        self._conn.execute(
            "INSERT INTO usage_events (sub, tool_name, occurred_at, outcome) VALUES (?, ?, ?, ?)",
            (sub, tool_name, ts, outcome),
        )
        self._conn.commit()

    def usage_count(self, sub: str) -> int:
        cur = self._conn.execute("SELECT COUNT(*) AS n FROM usage_events WHERE sub = ?", (sub,))
        return int(cur.fetchone()["n"])

    # ------------------------------------------------------------ proposals

    def insert_proposal(self, row: ProposalRow) -> None:
        self._conn.execute(
            """
            INSERT INTO proposals (
                id, token_hash, sub, league_key, team_key, action_type,
                payload_json, preview_json, precondition_json,
                created_at, expires_at, status, consumed_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                row.id,
                row.token_hash,
                row.sub,
                row.league_key,
                row.team_key,
                row.action_type,
                row.payload_json,
                row.preview_json,
                row.precondition_json,
                row.created_at,
                row.expires_at,
                row.status,
                row.consumed_at,
            ),
        )
        self._conn.commit()

    def get_proposal_by_hash(self, token_hash: str) -> ProposalRow | None:
        cur = self._conn.execute("SELECT * FROM proposals WHERE token_hash = ?", (token_hash,))
        r = cur.fetchone()
        return None if r is None else ProposalRow(**dict(r))

    def mark_consumed(self, proposal_id: str, now: int) -> bool:
        """Atomically claim a pending proposal.

        Returns True only if THIS call transitioned it out of 'pending'. The
        ``status = 'pending'`` predicate in the WHERE clause is what makes
        single-use hold under concurrency: two racing confirms both run this
        UPDATE, exactly one matches a row, the loser gets False.
        """
        cur = self._conn.execute(
            "UPDATE proposals SET status = 'consumed', consumed_at = ? "
            "WHERE id = ? AND status = 'pending'",
            (now, proposal_id),
        )
        self._conn.commit()
        return cur.rowcount == 1

    def mark_status(self, proposal_id: str, status: str) -> None:
        self._conn.execute("UPDATE proposals SET status = ? WHERE id = ?", (status, proposal_id))
        self._conn.commit()
