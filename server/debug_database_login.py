from __future__ import annotations

import asyncio
import logging

from nlcg119_server.codec import PacketReader, PacketWriter, XorCursor, build_frame, derive_xor_key, read_frame
from nlcg119_server.handlers import ServerConfig, serve_session
from nlcg119_server.model import Account, CharacterState, InventoryItem
from nlcg119_server.protocol import Command

logging.basicConfig(level=logging.DEBUG)


def login_payload() -> bytes:
    writer = PacketWriter()
    writer.write_utf("existing")
    writer.write_utf("pw")
    writer.write_utf("1.0")
    writer.write_short(240)
    writer.write_short(320)
    writer.write_byte(1)
    return writer.to_bytes()


async def main() -> None:
    character = CharacterState(character_id=42, name="existing", gold=1000, premium=100, inventory_items=[InventoryItem()])
    config = ServerConfig(handshake_raw_key=b"KEY", accounts={"existing": Account("existing", "pw", character=character)})
    server = await asyncio.start_server(lambda r, w: serve_session(r, w, config), "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    print("listening", port, flush=True)
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    writer.write(build_frame(Command.HANDSHAKE, b""))
    await writer.drain()
    command, handshake = await asyncio.wait_for(read_frame(reader), 2)
    print("handshake", command, len(handshake), flush=True)
    key = derive_xor_key(handshake[1:])
    tx = XorCursor(key)
    rx = XorCursor(key)
    writer.write(build_frame(Command.LOGIN, login_payload(), tx))
    await writer.drain()
    for i in range(7):
        command, payload = await asyncio.wait_for(read_frame(reader, rx), 2)
        print("frame", i, command, len(payload), flush=True)
    writer.close()
    await writer.wait_closed()
    server.close()
    await server.wait_closed()


if __name__ == "__main__":
    asyncio.run(main())
