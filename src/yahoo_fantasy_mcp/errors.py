"""Typed error surface for the Yahoo Fantasy MCP server.

Per contracts/mcp-tools.md: every tool failure MUST map to one of these
codes, never a raw HTTP status, stack trace, or credential value
(constitution Principle III).
"""

from __future__ import annotations

import enum


class ErrorCode(enum.Enum):
    """Stable error codes surfaced to MCP clients. See contracts/mcp-tools.md."""

    AUTH_REQUIRED = "AUTH_REQUIRED"
    AUTH_EXPIRED = "AUTH_EXPIRED"
    LEAGUE_NOT_PROVISIONED = "LEAGUE_NOT_PROVISIONED"
    LEAGUE_NOT_ACCESSIBLE = "LEAGUE_NOT_ACCESSIBLE"
    UNSUPPORTED_DRAFT_TYPE = "UNSUPPORTED_DRAFT_TYPE"
    RATE_LIMITED = "RATE_LIMITED"
    UPSTREAM_ERROR = "UPSTREAM_ERROR"


class YahooFantasyError(Exception):
    """Base exception for all typed server errors.

    ``message`` must describe the *condition*, never include a token,
    secret, or credential fragment (Principle III) — this is enforced by
    tests/unit/test_errors.py, not just convention.
    """

    def __init__(self, code: ErrorCode, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(f"{code.value}: {message}")

    def to_dict(self) -> dict:
        return {"error_code": self.code.value, "message": self.message}


class AuthRequiredError(YahooFantasyError):
    def __init__(
        self, message: str = "No credentials found; run the one-time OAuth setup."
    ) -> None:
        super().__init__(ErrorCode.AUTH_REQUIRED, message)


class AuthExpiredError(YahooFantasyError):
    def __init__(
        self, message: str = "Yahoo credentials have expired or been revoked; re-authenticate."
    ) -> None:
        super().__init__(ErrorCode.AUTH_EXPIRED, message)


class LeagueNotProvisionedError(YahooFantasyError):
    def __init__(
        self,
        message: str = (
            "League is not yet provisioned for this season; try again once Yahoo opens it."
        ),
    ) -> None:
        super().__init__(ErrorCode.LEAGUE_NOT_PROVISIONED, message)


class LeagueNotAccessibleError(YahooFantasyError):
    def __init__(
        self, message: str = "This account cannot access the requested league/team."
    ) -> None:
        super().__init__(ErrorCode.LEAGUE_NOT_ACCESSIBLE, message)


class UnsupportedDraftTypeError(YahooFantasyError):
    def __init__(
        self,
        message: str = (
            "Auction drafts are not supported; this server only models standard snake drafts."
        ),
    ) -> None:
        super().__init__(ErrorCode.UNSUPPORTED_DRAFT_TYPE, message)


class RateLimitedError(YahooFantasyError):
    def __init__(self, message: str = "Yahoo is throttling requests; backing off.") -> None:
        super().__init__(ErrorCode.RATE_LIMITED, message)


class UpstreamError(YahooFantasyError):
    def __init__(self, message: str = "Yahoo returned an unexpected error.") -> None:
        super().__init__(ErrorCode.UPSTREAM_ERROR, message)
