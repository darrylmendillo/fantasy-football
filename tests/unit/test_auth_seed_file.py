"""Tests for the token-file seeding fix in auth.login().

Real bug, found by reading yahoo_oauth's source directly rather than
assuming: OAuth2(from_file=path) calls open(path) immediately — if the
file doesn't exist yet (true on first-ever setup), it raises
FileNotFoundError instead of running the interactive consent flow. And
when from_file is set, any client_id/client_secret passed as constructor
args are silently ignored; only the file's contents are used. So the
file must be pre-seeded with {"consumer_key", "consumer_secret"} before
OAuth2() is ever constructed.
"""

from __future__ import annotations

import json

from yahoo_fantasy_mcp.auth import ensure_seed_file


class TestEnsureSeedFile:
    def test_creates_parent_directory_and_seed_file_if_missing(self, tmp_path):
        token_path = tmp_path / "nested" / "oauth2.json"
        assert not token_path.parent.exists()

        ensure_seed_file(str(token_path), client_id="cid123", client_secret="csecret456")

        assert token_path.exists()
        data = json.loads(token_path.read_text())
        assert data == {"consumer_key": "cid123", "consumer_secret": "csecret456"}

    def test_does_not_overwrite_an_existing_token_file(self, tmp_path):
        """A file that already has real tokens in it must never be
        clobbered back to a bare seed — that would force re-auth."""
        token_path = tmp_path / "oauth2.json"
        existing = {
            "consumer_key": "cid123",
            "consumer_secret": "csecret456",
            "access_token": "already-have-one",
            "refresh_token": "already-have-one-too",
        }
        token_path.write_text(json.dumps(existing))

        ensure_seed_file(str(token_path), client_id="cid123", client_secret="csecret456")

        assert json.loads(token_path.read_text()) == existing
