"""Configuration loading for the Yahoo Fantasy MCP server.

Reads from environment variables only (populated from .env by the process
launcher, e.g. `uv run --env-file .env`). No credential value is ever
logged, printed, or included in an exception message (Principle III).
"""

from __future__ import annotations

import os
from dataclasses import dataclass

DEFAULT_POLL_INTERVAL_SECONDS = 5
DEFAULT_TOKEN_PATH = "~/.yahoo_fantasy_mcp/oauth2.json"
# Standard Yahoo NFL redraft league (starters + bench); override if yours differs.
DEFAULT_ROSTER_SIZE = 16


@dataclass(frozen=True)
class ServerConfig:
    client_id: str
    client_secret: str
    league_key: str
    poll_interval_seconds: int
    token_path: str
    # Roster spots per team, used only to compute total_expected_picks for
    # the Draft.is_complete flag (draft.py). NOT used anywhere in the
    # availability-derivation logic (FR-010/SC-002), which depends only on
    # drafted_player_ids() and is correct regardless of this value. Getting
    # this wrong makes is_complete wrong, not availability.
    roster_size: int


class MissingConfigError(RuntimeError):
    """Raised when a required environment variable is absent."""


def _require_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise MissingConfigError(f"{name} is not set. Copy .env.example to .env and fill it in.")
    return value


def load_config() -> ServerConfig:
    """Load server configuration from environment variables.

    Raises MissingConfigError (not a generic KeyError) if a required
    variable is absent — the message names the missing variable, never a
    value, so it's safe to surface directly.
    """
    poll_interval_raw = os.environ.get(
        "YAHOO_POLL_INTERVAL_SECONDS", str(DEFAULT_POLL_INTERVAL_SECONDS)
    )
    try:
        poll_interval = int(poll_interval_raw)
    except ValueError as exc:
        raise MissingConfigError(
            "YAHOO_POLL_INTERVAL_SECONDS must be an integer number of seconds."
        ) from exc

    roster_size_raw = os.environ.get("YAHOO_ROSTER_SIZE", str(DEFAULT_ROSTER_SIZE))
    try:
        roster_size = int(roster_size_raw)
    except ValueError as exc:
        raise MissingConfigError("YAHOO_ROSTER_SIZE must be an integer.") from exc

    return ServerConfig(
        client_id=_require_env("YAHOO_CLIENT_ID"),
        client_secret=_require_env("YAHOO_CLIENT_SECRET"),
        league_key=_require_env("YAHOO_LEAGUE_KEY"),
        poll_interval_seconds=poll_interval,
        token_path=os.path.expanduser(os.environ.get("YAHOO_TOKEN_PATH", DEFAULT_TOKEN_PATH)),
        roster_size=roster_size,
    )
