"""Credential-safe logging (FR-002, constitution Principle III).

Yahoo OAuth access/refresh tokens are long opaque strings using
URL-safe base64-ish characters (letters, digits, ``_``, ``-``, ``~``, ``.``),
typically 40+ characters. This module redacts anything shaped like one
before it reaches a log line, on the assumption that a future bug — not a
current one — is what this guards against: nothing here should ever log a
raw token on purpose.
"""

from __future__ import annotations

import logging
import re

_TOKEN_SHAPE = re.compile(r"[A-Za-z0-9_~.\-]{40,}")


def mask_secrets(text: str) -> str:
    """Replace any token-shaped substring (40+ url-safe-base64-ish chars)
    with a redaction marker. Safe to call on text with no secrets — it is
    a no-op in that case (see test_leaves_ordinary_text_untouched)."""
    return _TOKEN_SHAPE.sub("[REDACTED]", text)


class _RedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = mask_secrets(record.getMessage())
        record.args = ()
        return True


def get_logger(name: str) -> logging.Logger:
    """Return a logger that redacts token-shaped substrings from every
    message before it is emitted."""
    logger = logging.getLogger(name)
    if not any(isinstance(f, _RedactingFilter) for f in logger.filters):
        logger.addFilter(_RedactingFilter())
    return logger
