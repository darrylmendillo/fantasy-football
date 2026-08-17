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
    # --- spec 002 additions (contracts/mcp-tools.md) ---
    SPORT_NOT_SUPPORTED = "SPORT_NOT_SUPPORTED"
    WRITE_NOT_APPROVED = "WRITE_NOT_APPROVED"
    INVALID_CONFIRMATION = "INVALID_CONFIRMATION"
    PROPOSAL_EXPIRED = "PROPOSAL_EXPIRED"
    PROPOSAL_ALREADY_USED = "PROPOSAL_ALREADY_USED"
    PRECONDITIONS_CHANGED = "PRECONDITIONS_CHANGED"
    TRADE_INITIATION_NOT_SUPPORTED = "TRADE_INITIATION_NOT_SUPPORTED"


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


# --------------------------------------------------------------------------
# spec 002 additions. See contracts/mcp-tools.md for the full error table.
# --------------------------------------------------------------------------


class SportNotSupportedError(YahooFantasyError):
    def __init__(
        self,
        message: str = "This server currently supports fantasy football only.",
    ) -> None:
        super().__init__(ErrorCode.SPORT_NOT_SUPPORTED, message)


class WriteNotApprovedError(YahooFantasyError):
    """Raised when Yahoo has not granted this deployment write access (FR-025).

    Deliberately distinct from a validation error: the user's request was
    fine, the product simply cannot write yet.
    """

    def __init__(
        self,
        message: str = (
            "This server does not yet have Yahoo write access approved, so no changes "
            "can be made. Reading your league data still works."
        ),
    ) -> None:
        super().__init__(ErrorCode.WRITE_NOT_APPROVED, message)


class InvalidConfirmationError(YahooFantasyError):
    """Unknown token OR wrong user — deliberately indistinguishable.

    contracts/mcp-tools.md: the response must not reveal whether a given
    confirmation token exists.
    """

    def __init__(
        self,
        message: str = "That confirmation is not valid. Start the action again to get a new one.",
    ) -> None:
        super().__init__(ErrorCode.INVALID_CONFIRMATION, message)


class ProposalExpiredError(YahooFantasyError):
    def __init__(
        self,
        message: str = "That confirmation has expired. Start the action again.",
    ) -> None:
        super().__init__(ErrorCode.PROPOSAL_EXPIRED, message)


class ProposalAlreadyUsedError(YahooFantasyError):
    def __init__(
        self,
        message: str = "That confirmation was already used. Start the action again.",
    ) -> None:
        super().__init__(ErrorCode.PROPOSAL_ALREADY_USED, message)


class PreconditionsChangedError(YahooFantasyError):
    """The world moved between propose and confirm (FR-021)."""

    def __init__(
        self,
        message: str = (
            "The situation changed since this was proposed, so it was not applied. "
            "Review the current state and start again."
        ),
    ) -> None:
        super().__init__(ErrorCode.PRECONDITIONS_CHANGED, message)


class TradeInitiationNotSupportedError(YahooFantasyError):
    def __init__(
        self,
        message: str = (
            "Sending new trade offers is not supported yet. You can review, accept, "
            "and reject offers other managers send you."
        ),
    ) -> None:
        super().__init__(ErrorCode.TRADE_INITIATION_NOT_SUPPORTED, message)
