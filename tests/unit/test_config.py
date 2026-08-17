"""T005 — server config for the hosted server.

The load-bearing assertion here is a NEGATIVE one: `ServerConfig` must no
longer carry `league_key` or `token_path`. Those two fields ARE the
single-tenant assumption (spec 002 background); if they survive the rewrite,
multi-tenancy is not real no matter what the rest of the code does.
"""

from __future__ import annotations

import dataclasses

import pytest

from yahoo_fantasy_mcp.config import MissingConfigError, ServerConfig, load_config

_REQUIRED = {
    "YAHOO_CLIENT_ID": "client-id-value",
    "YAHOO_CLIENT_SECRET": "client-secret-value",
    "PUBLIC_BASE_URL": "https://example.test",
}


@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    for var in (
        "YAHOO_CLIENT_ID",
        "YAHOO_CLIENT_SECRET",
        "PUBLIC_BASE_URL",
        "YAHOO_LEAGUE_KEY",
        "YAHOO_TOKEN_PATH",
        "PORT",
        "DB_PATH",
        "PROPOSAL_TTL_SECONDS",
        "YAHOO_SCOPE",
    ):
        monkeypatch.delenv(var, raising=False)
    return monkeypatch


class TestSingleTenantFieldsAreGone:
    def test_config_has_no_league_key_or_token_path(self) -> None:
        fields = {f.name for f in dataclasses.fields(ServerConfig)}
        assert "league_key" not in fields, "league_key is the single-league assumption"
        assert "token_path" not in fields, "token_path is the single-user assumption"

    def test_league_key_env_var_is_ignored(self, clean_env: pytest.MonkeyPatch) -> None:
        """A leftover YAHOO_LEAGUE_KEY in someone's .env must not silently
        re-pin the server to one league."""
        for k, v in _REQUIRED.items():
            clean_env.setenv(k, v)
        clean_env.setenv("YAHOO_LEAGUE_KEY", "461.l.99999")
        cfg = load_config()
        assert "461.l.99999" not in repr(cfg)


class TestRequiredVars:
    @pytest.mark.parametrize("missing", sorted(_REQUIRED))
    def test_missing_required_var_is_named(
        self, clean_env: pytest.MonkeyPatch, missing: str
    ) -> None:
        for k, v in _REQUIRED.items():
            if k != missing:
                clean_env.setenv(k, v)
        with pytest.raises(MissingConfigError) as exc:
            load_config()
        assert missing in str(exc.value)

    def test_error_never_leaks_a_secret_value(self, clean_env: pytest.MonkeyPatch) -> None:
        """Principle III: the message names the variable, never its value."""
        clean_env.setenv("YAHOO_CLIENT_ID", "super-secret-id")
        clean_env.setenv("PUBLIC_BASE_URL", "https://example.test")
        with pytest.raises(MissingConfigError) as exc:
            load_config()
        assert "super-secret-id" not in str(exc.value)


class TestDefaults:
    def test_sensible_defaults_applied(self, clean_env: pytest.MonkeyPatch) -> None:
        for k, v in _REQUIRED.items():
            clean_env.setenv(k, v)
        cfg = load_config()
        assert cfg.port > 0
        assert cfg.proposal_ttl_seconds > 0
        assert cfg.db_path
        assert cfg.yahoo_scope

    def test_non_integer_port_is_rejected_clearly(self, clean_env: pytest.MonkeyPatch) -> None:
        for k, v in _REQUIRED.items():
            clean_env.setenv(k, v)
        clean_env.setenv("PORT", "not-a-number")
        with pytest.raises(MissingConfigError):
            load_config()

    def test_proposal_ttl_is_overridable(self, clean_env: pytest.MonkeyPatch) -> None:
        for k, v in _REQUIRED.items():
            clean_env.setenv(k, v)
        clean_env.setenv("PROPOSAL_TTL_SECONDS", "60")
        assert load_config().proposal_ttl_seconds == 60
