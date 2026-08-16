"""Credential-hygiene tests (FR-002, constitution Principle III).

Written before the redaction implementation exists — must fail first.
"""

from __future__ import annotations

import logging

from yahoo_fantasy_mcp.errors import (
    AuthExpiredError,
    AuthRequiredError,
    ErrorCode,
    LeagueNotAccessibleError,
    LeagueNotProvisionedError,
    RateLimitedError,
    UnsupportedDraftTypeError,
    UpstreamError,
    YahooFantasyError,
)
from yahoo_fantasy_mcp.logging_utils import get_logger, mask_secrets

# A realistic-shaped Yahoo OAuth access token (fabricated, not a real credential).
FAKE_TOKEN = (
    "JIzRgdCZ5Vup6SrkkCcziGIpdMNw4MHYGzl9uHkDkixq9Tf9A6bhSrZtKYWQDFFb"
    "wQCIFVn_DZ6suOFqBxdvStO78DU9YkQZDB7.YUUPdMflPjWbX7nD3WsXqALwQDXB"
)
FAKE_REFRESH_TOKEN = "AGK0DWlowo4txHeXTHZMt6dv4XGA~001~S7s8CjQ8_kQ7ZGnKmnRmljj2kA--"


class TestNoTokenInErrorMessages:
    """All seven error codes must be constructible with default messages that
    never contain a token value — a static regression guard."""

    def test_all_error_classes_default_messages_contain_no_token_shape(self):
        errors: list[YahooFantasyError] = [
            AuthRequiredError(),
            AuthExpiredError(),
            LeagueNotProvisionedError(),
            LeagueNotAccessibleError(),
            UnsupportedDraftTypeError(),
            RateLimitedError(),
            UpstreamError(),
        ]
        assert {e.code for e in errors} == set(ErrorCode)
        for err in errors:
            assert mask_secrets(err.message) == err.message, (
                f"{err.code}: default message looks like it contains a secret"
            )


class TestMaskSecrets:
    def test_redacts_access_token(self):
        text = f"refresh failed for token={FAKE_TOKEN}"
        assert FAKE_TOKEN not in mask_secrets(text)

    def test_redacts_refresh_token(self):
        text = f"refresh_token: {FAKE_REFRESH_TOKEN}"
        assert FAKE_REFRESH_TOKEN not in mask_secrets(text)

    def test_leaves_ordinary_text_untouched(self):
        text = "league 449.l.99001 is not yet provisioned for the 2026 season"
        assert mask_secrets(text) == text


class TestLoggerRedaction:
    def test_logged_token_is_redacted_in_output(self, caplog):
        logger = get_logger("yahoo_fantasy_mcp.test")
        with caplog.at_level(logging.INFO, logger="yahoo_fantasy_mcp.test"):
            logger.info("token refresh response: %s", FAKE_TOKEN)
        output = caplog.text
        assert FAKE_TOKEN not in output
        assert "[REDACTED]" in output
