"""HTTP entrypoint for the hosted multi-tenant server (spec 002, T019).

Unlike spec 001's stdio entrypoint, this builds NO per-user state at start-up.
There is no `build_context()` singleton: every user's Yahoo token arrives with
their request and every league is resolved per call. Anything cached here
would be shared across tenants.
"""

from __future__ import annotations

from yahoo_fantasy_mcp.auth_proxy import build_auth_proxy
from yahoo_fantasy_mcp.config import load_config
from yahoo_fantasy_mcp.logging_utils import get_logger
from yahoo_fantasy_mcp.server import build_server
from yahoo_fantasy_mcp.store import Store

logger = get_logger(__name__)


def main() -> None:
    config = load_config()
    store = Store(config.db_path)
    mcp_server = build_server(store, config)
    mcp_server.auth = build_auth_proxy(config)
    logger.info("starting yahoo-fantasy-mcp (http) on port %s", config.port)
    mcp_server.run(transport="http", host="0.0.0.0", port=config.port)


if __name__ == "__main__":
    main()
