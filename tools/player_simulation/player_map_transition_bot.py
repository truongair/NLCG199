#!/usr/bin/env python3
import asyncio, sys
sys.path.insert(0, '/home/ubuntu/work/NLCG199/server/src')
from nlcg119_server.codec import PacketWriter, XorCursor, build_frame, derive_xor_key, read_frame
from nlcg119_server.protocol import Command

async def recv(reader, rx, label):
    command, payload = await asyncio.wait_for(read_frame(reader, rx), 3)
    print(f'{label}: command={command} payload={len(payload)}', flush=True)
    return command, payload

async def main():
    reader, writer = await asyncio.open_connection('127.0.0.1', 9011)
    writer.write(build_frame(Command.HANDSHAKE, b'')); await writer.drain()
    _, h = await recv(reader, None, 'handshake')
    key = derive_xor_key(h[1:]); tx, rx = XorCursor(key), XorCursor(key)
    p = PacketWriter()
    for v in ('smokeuser','pw','1.0'): p.write_utf(v)
    p.write_short(240); p.write_short(320); p.write_byte(1)
    writer.write(build_frame(Command.LOGIN, p.to_bytes(), tx)); await writer.drain()
    for i in range(7): await recv(reader, rx, f'bootstrap[{i}]')
    writer.write(build_frame(Command.MAP_ACTION, bytes((1,)), tx)); await writer.drain()
    print('send transition map1', flush=True)
    await recv(reader, rx, 'map1.handoff'); await recv(reader, rx, 'map1.snapshot')
    p = PacketWriter(); p.write_byte(0); p.write_int(18296)
    writer.write(build_frame(Command.MAP_ACTION, p.to_bytes(), tx)); await writer.drain()
    print('send transition map0 owner=18296', flush=True)
    await recv(reader, rx, 'map0.handoff'); await recv(reader, rx, 'map0.snapshot')
    writer.close(); await writer.wait_closed(); print('player map sequence completed', flush=True)

asyncio.run(main())
