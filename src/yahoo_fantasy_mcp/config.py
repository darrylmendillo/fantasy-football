"""Server-level configuration for the hosted MCP server (spec 002, T009).

What is NOT here matters as much as what is. `league_key` and `token_path`
are deliberately absent: they were the single-league and single-user
assumptions of spec 001. Per-user Yahoo tokens now come from FastMCP's
OAuthProxy at request time (research R2), and the league is a per-request
argument (FR-010) — so neither can be a process-wide setting any more.

No credential value is ever logged, printed, or included in an exception
message (Principle III); `__repr__` is overridden to enforce that even in
tracebacks.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, fields

DEFAULT_PORT = 8000
DEFAULT_DB_PATH = "./yahoo_fantasy_mcp.db"
# Long enough for a natural back-and-forth with an assistant, short enough
# that proposals do not linger (spec Assumptions; research R8).
DEFAULT_PROPOSAL_TTL_SECONDS = 300
# fspt-w = Fantasy Sports read/write. Set to "fspt-r" if Yahoo has only
# approved read access — write tools then fail with WRITE_NOT_APPROVED
# (FR-025) rather than failing obscurely at call time.
DEFAULT_YAHOO_SCOPE = "fspt-w"
DEFAULT_POLL_INTERVAL_SECONDS = 5

_SECRET_FIELDS = frozenset({"client_id", "client_secret"})


@dataclass(frozen=True)
class ServerConfig:
    """Process-wide settings. Nothing user-specific belongs in here."""

    client_id: str
    client_secret: str
    public_base_url: str
    port: int
    db_path: str
    proposal_ttl_seconds: int
    yahoo_scope: str
    poll_interval_seconds: int

    def __repr__(self) -> str:
        parts = []
        for f in fields(self):
            value = "<redacted>" if f.name in _SECRET_FIELDS else getattr(self, f.name)
            parts.append(f"{f.name}={value!r}")
        return f"ServerConfig({', '.join(parts)})"

    @property
    def write_enabled(self) -> bool:
        """Whether Yahoo has granted write scope.

        Forward-looking: nothing in `src/` reads this property yet. The
        actual write gate today is the hardcoded `UnapprovedLineupWriter`
        seam in server.py's `confirm_action` closure, which refuses
        unconditionally with WRITE_NOT_APPROVED regardless of this value
        (dispatch is blocked on gate G3 — see tools_write.py). This
        property is ready for the day a real `LineupWriter` lands and
        write-vs-read selection needs to consult granted scope; it is not
        wired to anything yet, and no code should claim otherwise (see
        auth_proxy.py's build_auth_proxy docstring for the full context).
        """
        return self.yahoo_scope.strip() == "fspt-w"


class MissingConfigError(RuntimeError):
    """Raised when a required environment variable is absent or malformed."""


def _require_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise MissingConfigError(f"{name} is not set. Copy .env.example to .env and fill it in.")
    return value


def _int_env(name: str, default: int) -> int:
    raw = os.environ.get(name, str(default))
    try:
        return int(raw)
    except ValueError as exc:
        # Names the variable, never the value (Principle III).
        raise MissingConfigError(f"{name} must be an integer.") from exc


def load_config() -> ServerConfig:
    """Load server configuration from environment variables.

    Raises MissingConfigError (not KeyError/ValueError) so the message is
    always safe to surface directly to an operator.
    """
    return ServerConfig(
        client_id=_require_env("YAHOO_CLIENT_ID"),
        client_secret=_require_env("YAHOO_CLIENT_SECRET"),
        public_base_url=_require_env("PUBLIC_BASE_URL").rstrip("/"),
        port=_int_env("PORT", DEFAULT_PORT),
        db_path=os.environ.get("DB_PATH", DEFAULT_DB_PATH),
        proposal_ttl_seconds=_int_env("PROPOSAL_TTL_SECONDS", DEFAULT_PROPOSAL_TTL_SECONDS),
        yahoo_scope=os.environ.get("YAHOO_SCOPE", DEFAULT_YAHOO_SCOPE),
        poll_interval_seconds=_int_env(
            "YAHOO_POLL_INTERVAL_SECONDS", DEFAULT_POLL_INTERVAL_SECONDS
        ),
    )
