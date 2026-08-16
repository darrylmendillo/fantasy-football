"""Stdio entrypoint (research R7): `python -m yahoo_fantasy_mcp` or the
`yahoo-fantasy-mcp` console script.

No network listener, no exposed port — FastMCP's stdio transport means the
host process (e.g. Claude Code) launches this as a subprocess and speaks
JSON-RPC over stdin/stdout. Credentials never leave the machine.
"""

from __future__ import annotations

from yahoo_fantasy_mcp.client import YahooClient, YahooFantasyApiDataSource
from yahoo_fantasy_mcp.config import load_config
from yahoo_fantasy_mcp.logging_utils import get_logger
from yahoo_fantasy_mcp.server import ServerContext, mcp, register_tools

logger = get_logger(__name__)


def build_context() -> ServerContext:
    from yahoo_fantasy_api import Game

    from yahoo_fantasy_mcp import auth

    config = load_config()
    token_provider = auth.login(config.client_id, config.client_secret, config.token_path)
    game = Game(token_provider, "nfl")
    league = game.to_league(config.league_key)
    my_team_key = league.team_key()
    data_source = YahooFantasyApiDataSource(league, my_team_key)
    client = YahooClient(data_source)
    return ServerContext(client=client, token_provider=token_provider)


def main() -> None:
    logger.info("starting yahoo-fantasy-mcp (stdio)")
    ctx = build_context()
    register_tools(mcp, ctx)
    mcp.run()


if __name__ == "__main__":
    main()
