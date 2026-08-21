from __future__ import annotations

import argparse
import asyncio
import logging

from .handlers import ServerConfig
from .server import NLCG119Server


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="NLCG119 protocol-compatible Python server")
    parser.add_argument("--host", default="127.0.0.1", help="bind address; default is localhost")
    parser.add_argument("--port", type=int, default=9001, help="TCP port; default is 9001")
    parser.add_argument("--key", default="NLCG119K", help="ASCII raw handshake key")
    parser.add_argument("--no-dev-accounts", action="store_true", help="reject unknown accounts")
    parser.add_argument("--database", default="data/nlcg119.db", help="SQLite database path; default is data/nlcg119.db")
    parser.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    return parser


def main() -> None:
    args = build_parser().parse_args()
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    config = ServerConfig(
        handshake_raw_key=args.key.encode("ascii"),
        allow_dev_accounts=not args.no_dev_accounts,
        database_path=args.database,
    )
    server = NLCG119Server(args.host, args.port, config)
    try:
        asyncio.run(server.run())
    except KeyboardInterrupt:
        logging.getLogger(__name__).info("server stopped")


if __name__ == "__main__":
    main()
