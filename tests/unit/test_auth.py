"""Auth tests (FR-001, FR-003, FR-007). Written before auth.py exists — must fail first."""

from __future__ import annotations

from yahoo_fantasy_mcp.errors import AuthExpiredError, LeagueNotProvisionedError


class _FakeTokenProvider:
    """Stands in for yahoo_oauth.OAuth2 for unit testing ensure_fresh()."""

    def __init__(self, expired: bool) -> None:
        self._expired = expired
        self.refresh_calls = 0

    def token_is_valid(self) -> bool:
        return not self._expired

    def refresh_access_token(self) -> None:
        self.refresh_calls += 1
        self._expired = False


class TestEnsureFresh:
    def test_refreshes_when_expired(self):
        from yahoo_fantasy_mcp.auth import ensure_fresh

        provider = _FakeTokenProvider(expired=True)
        ensure_fresh(provider)
        assert provider.refresh_calls == 1
        assert provider.token_is_valid()

    def test_does_not_refresh_when_already_valid(self):
        """FR-003: refresh only happens on actual expiry, not every call."""
        from yahoo_fantasy_mcp.auth import ensure_fresh

        provider = _FakeTokenProvider(expired=False)
        ensure_fresh(provider)
        assert provider.refresh_calls == 0


class TestClassifyAuthFailure:
    """Both failure modes arrive from Yahoo as HTTP 401 — this is the exact
    disambiguation FR-007 requires (research R6)."""

    def test_expired_token_body_raises_auth_expired(self):
        from yahoo_fantasy_mcp.auth import classify_auth_failure

        body = '{"error": "token_expired", "error_description": "oauth_problem=token_expired"}'
        try:
            classify_auth_failure(status_code=401, body=body)
            assert False, "expected AuthExpiredError"
        except AuthExpiredError:
            pass

    def test_non_token_401_raises_league_not_provisioned(self):
        from yahoo_fantasy_mcp.auth import classify_auth_failure

        body = '{"error": {"description": "This league is not yet available."}}'
        try:
            classify_auth_failure(status_code=401, body=body)
            assert False, "expected LeagueNotProvisionedError"
        except LeagueNotProvisionedError:
            pass

    def test_403_with_oauth_problem_raises_auth_expired(self):
        from yahoo_fantasy_mcp.auth import classify_auth_failure

        body = "oauth_problem=token_rejected"
        try:
            classify_auth_failure(status_code=403, body=body)
            assert False, "expected AuthExpiredError"
        except AuthExpiredError:
            pass

    def test_error_messages_never_contain_body_content(self):
        """FR-002/Principle III: the raw response body could theoretically
        contain header/token fragments in some Yahoo error payloads; the
        classified exception's message must never echo the raw body."""
        from yahoo_fantasy_mcp.auth import classify_auth_failure

        secret_looking_body = (
            '{"error":"token_expired","token":"AAABBBCCCDDDEEEFFFGGGHHHIIIJJJKKKLLLMMMNNNOOO"}'
        )
        try:
            classify_auth_failure(status_code=401, body=secret_looking_body)
            assert False, "expected AuthExpiredError"
        except AuthExpiredError as exc:
            assert "AAABBBCCCDDDEEEFFFGGGHHHIIIJJJKKKLLLMMMNNNOOO" not in exc.message


class TestCheckAuthOutput:
    def test_no_token_in_check_auth_result(self):
        from yahoo_fantasy_mcp.auth import build_check_auth_result

        provider = _FakeTokenProvider(expired=False)
        result = build_check_auth_result(provider, expires_in_seconds=3221)
        assert set(result.keys()) == {"authenticated", "expires_in_seconds", "needs_reauth"}
        assert result["authenticated"] is True
        assert result["expires_in_seconds"] == 3221
        assert result["needs_reauth"] is False
