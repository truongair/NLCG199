"""Asyncio TCP server entry point."""

from __future__ import annotations

import asyncio
import logging

from .handlers import ServerConfig, serve_session

log = logging.getLogger(__name__)


class NLCG119Server:
    def __init__(self, host: str = "127.0.0.1", port: int = 9001, config: ServerConfig | None = None):
        self.host = host
        self.port = port
        self.config = config or ServerConfig()
        self._server: asyncio.AbstractServer | None = None

    async def start(self) -> None:
        self._server = await asyncio.start_server(
            lambda reader, writer: serve_session(reader, writer, self.config),
            host=self.host,
            port=self.port,
            limit=65536,
        )
        sockets = self._server.sockets or []
        addresses = ", ".join(str(sock.getsockname()) for sock in sockets)
        log.info("NLCG119 server listening on %s", addresses)

    async def run(self) -> None:
        await self.start()
        assert self._server is not None
        async with self._server:
            await self._server.serve_forever()

    async def close(self) -> None:
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None
