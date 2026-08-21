#!/usr/bin/env python3
import asyncio
import sys
sys.path.insert(0, "/home/ubuntu/work/NLCG199/server/src")
from nlcg119_server.codec import PacketWriter, XorCursor, build_frame, derive_xor_key, read_frame
from nlcg119_server.protocol import Command

async def receive(reader, rx, label):
    command, payload = await asyncio.wait_for(read_frame(reader, rx), timeout=3)
    print(f"{label}: command={command} payload={len(payload)}", flush=True)
    return command, payload

async def main():
    reader, writer = await asyncio.open_connection("127.0.0.1", 9011)
    writer.write(build_frame(Command.HANDSHAKE, b""))
    await writer.drain()
    command, handshake = await receive(reader, None, "handshake")
    assert command == Command.HANDSHAKE
    key = derive_xor_key(handshake[1:])
    tx, rx = XorCursor(key), XorCursor(key)
    login = PacketWriter()
    for value in ("smokeuser", "pw", "1.0"):
        login.write_utf(value)
    login.write_short(240); login.write_short(320); login.write_byte(1)
    writer.write(build_frame(Command.LOGIN, login.to_bytes(), tx)); await writer.drain()
    print("send login", flush=True)
    for i in range(7): await receive(reader, rx, f"bootstrap[{i}]")

    # JAR sq.a(byte,int): -9 payload = subcase 0, object id 21.
    writer.write(build_frame(Command.NPC_EVENT, bytes((0, 21)), tx)); await writer.drain()
    print("send npc_open object=21", flush=True)
    await receive(reader, rx, "npc_open.response")

    # JAR sq.c(boolean): -22 payload = subcase 0, boolean false.
    writer.write(build_frame(Command.SHOP_EVENT, bytes((0, 0)), tx)); await writer.drain()
    print("send shop_open tab=0", flush=True)
    await receive(reader, rx, "shop_open.response")

    writer.close(); await writer.wait_closed()
    print("player shop sequence completed", flush=True)

if __name__ == "__main__": asyncio.run(main())
