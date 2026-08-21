#!/usr/bin/env python3
import asyncio
import sys

sys.path.insert(0, "/home/ubuntu/work/NLCG199/server/src")
from nlcg119_server.codec import PacketReader, PacketWriter, XorCursor, build_frame, derive_xor_key, read_frame
from nlcg119_server.protocol import Command


async def read_one(reader, rx, label):
    command, payload = await asyncio.wait_for(read_frame(reader, rx), timeout=3)
    print(f"{label}: command={command} payload={len(payload)}", flush=True)
    return command, payload


async def send_action(writer, tx, command, payload, label):
    writer.write(build_frame(command, payload, tx))
    await writer.drain()
    print(f"send {label}: command={command} payload={len(payload)}", flush=True)


async def main():
    reader, writer = await asyncio.open_connection("127.0.0.1", 9011)
    writer.write(build_frame(Command.HANDSHAKE, b""))
    await writer.drain()
    command, handshake = await asyncio.wait_for(read_frame(reader), timeout=3)
    assert command == Command.HANDSHAKE
    key = derive_xor_key(handshake[1:])
    tx, rx = XorCursor(key), XorCursor(key)

    login = PacketWriter()
    for value in ("smokeuser", "pw", "1.0"):
        login.write_utf(value)
    login.write_short(240)
    login.write_short(320)
    login.write_byte(1)
    await send_action(writer, tx, Command.LOGIN, login.to_bytes(), "login")
    for index in range(7):
        await read_one(reader, rx, f"bootstrap[{index}]")

    # Plot 0 is empty and receives the seed/fertilizer lifecycle. Plot 1 is
    # already mature in the fixture, so harvest is valid there. Plot 2 has a
    # crop and is a valid destroy target. This mirrors a real player choosing
    # available actions rather than expecting ignored invalid requests to reply.
    actions = [
        ("sow_plot0", bytes((0, 2, 0)), 1),
        ("fertilize_plot0", bytes((0, 3, 1)), 2),
        ("water_plot0", bytes((0, 1)), 2),
        ("harvest_plot1", bytes((1, 4)), 2),
        ("destroy_plot2", bytes((2, 5)), 1),
    ]
    for label, payload, response_count in actions:
        await send_action(writer, tx, Command.FARM_EVENT, payload, label)
        for index in range(response_count):
            await read_one(reader, rx, f"{label}.response[{index}]")

    writer.close()
    await writer.wait_closed()
    print("player gameplay sequence completed", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
