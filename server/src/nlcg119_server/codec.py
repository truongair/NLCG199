"""Wire codec for the NLCG119 Java ME protocol.

The client uses DataInputStream/DataOutputStream semantics and a legacy
stateful XOR layer after the -27 handshake. This module keeps the transport
codec independent from command/business handlers.
"""

from __future__ import annotations

import io
import struct
from dataclasses import dataclass
from typing import BinaryIO

MAX_FRAME_PAYLOAD = 0xFFFF


class ProtocolError(Exception):
    """Raised when a frame or primitive violates protocol constraints."""


class IncompleteFrame(ProtocolError):
    """Raised when a complete frame is not available in a byte buffer."""


def _require_length(data: bytes, size: int, what: str) -> None:
    if len(data) < size:
        raise IncompleteFrame(f"need {size} bytes for {what}, got {len(data)}")


def java_modified_utf8_encode(value: str) -> bytes:
    """Encode a Python string as Java DataOutputStream modified UTF-8."""
    # Java encodes UTF-16 code units, not Unicode scalar values. surrogatepass
    # preserves unpaired surrogates in the same way as a Java String can.
    raw_utf16 = value.encode("utf-16-be", "surrogatepass")
    out = bytearray()
    for pos in range(0, len(raw_utf16), 2):
        unit = (raw_utf16[pos] << 8) | raw_utf16[pos + 1]
        if unit == 0:
            out.extend((0xC0, 0x80))
        elif unit <= 0x7F:
            out.append(unit)
        elif unit <= 0x7FF:
            out.extend((0xC0 | (unit >> 6), 0x80 | (unit & 0x3F)))
        else:
            out.extend((0xE0 | (unit >> 12), 0x80 | ((unit >> 6) & 0x3F), 0x80 | (unit & 0x3F)))
    if len(out) > MAX_FRAME_PAYLOAD:
        raise ProtocolError(f"modified UTF-8 string exceeds 65535 bytes: {len(out)}")
    return bytes(out)


def java_modified_utf8_decode(data: bytes) -> str:
    """Decode bytes produced by Java DataInputStream.readUTF."""
    units: list[int] = []
    pos = 0
    while pos < len(data):
        first = data[pos]
        pos += 1
        if first <= 0x7F:
            units.append(first)
            continue
        if (first & 0xE0) == 0xC0:
            if pos >= len(data):
                raise ProtocolError("truncated modified UTF-8 two-byte sequence")
            second = data[pos]
            pos += 1
            if (second & 0xC0) != 0x80:
                raise ProtocolError("invalid modified UTF-8 continuation byte")
            units.append(((first & 0x1F) << 6) | (second & 0x3F))
            continue
        if (first & 0xF0) == 0xE0:
            if pos + 1 >= len(data):
                raise ProtocolError("truncated modified UTF-8 three-byte sequence")
            second, third = data[pos], data[pos + 1]
            pos += 2
            if (second & 0xC0) != 0x80 or (third & 0xC0) != 0x80:
                raise ProtocolError("invalid modified UTF-8 continuation bytes")
            units.append(((first & 0x0F) << 12) | ((second & 0x3F) << 6) | (third & 0x3F))
            continue
        raise ProtocolError(f"unsupported modified UTF-8 lead byte 0x{first:02x}")
    raw_utf16 = b"".join(struct.pack(">H", unit) for unit in units)
    return raw_utf16.decode("utf-16-be", "surrogatepass")


class PacketWriter:
    """DataOutputStream-like writer for an outbound payload."""

    def __init__(self) -> None:
        self._buffer = io.BytesIO()

    def write_byte(self, value: int) -> None:
        self._buffer.write(bytes((value & 0xFF,)))

    def write_boolean(self, value: bool) -> None:
        self.write_byte(1 if value else 0)

    def write_short(self, value: int) -> None:
        self._buffer.write(struct.pack(">H", value & 0xFFFF))

    def write_int(self, value: int) -> None:
        self._buffer.write(struct.pack(">I", value & 0xFFFFFFFF))

    def write_utf(self, value: str) -> None:
        encoded = java_modified_utf8_encode(value)
        self._buffer.write(struct.pack(">H", len(encoded)))
        self._buffer.write(encoded)

    def write_bytes(self, value: bytes) -> None:
        self._buffer.write(value)

    def to_bytes(self) -> bytes:
        return self._buffer.getvalue()


class PacketReader:
    """DataInputStream-like reader for an inbound payload."""

    def __init__(self, payload: bytes):
        self._buffer = io.BytesIO(payload)

    def _read(self, size: int, what: str) -> bytes:
        value = self._buffer.read(size)
        if len(value) != size:
            raise ProtocolError(f"truncated {what}: need {size}, got {len(value)}")
        return value

    def read_byte(self) -> int:
        value = self._read(1, "byte")[0]
        return value - 256 if value >= 128 else value

    def read_unsigned_byte(self) -> int:
        return self._read(1, "unsigned byte")[0]

    def read_boolean(self) -> bool:
        return self.read_byte() != 0

    def read_short(self) -> int:
        return struct.unpack(">h", self._read(2, "short"))[0]

    def read_unsigned_short(self) -> int:
        return struct.unpack(">H", self._read(2, "unsigned short"))[0]

    def read_int(self) -> int:
        return struct.unpack(">i", self._read(4, "int"))[0]

    def read_utf(self) -> str:
        length = self.read_unsigned_short()
        return java_modified_utf8_decode(self._read(length, "modified UTF-8 string"))

    def read_bytes(self, size: int) -> bytes:
        return self._read(size, "byte array")

    def remaining(self) -> int:
        current = self._buffer.tell()
        self._buffer.seek(0, io.SEEK_END)
        end = self._buffer.tell()
        self._buffer.seek(current)
        return end - current

    def remaining_bytes(self) -> bytes:
        return self._buffer.read()


@dataclass
class XorCursor:
    """Connection-local rolling XOR cursor."""

    key: bytes
    offset: int = 0

    def __post_init__(self) -> None:
        if not self.key:
            raise ProtocolError("XOR key must not be empty")
        self.offset %= len(self.key)

    def crypt(self, data: bytes) -> bytes:
        out = bytearray(len(data))
        for index, value in enumerate(data):
            out[index] = value ^ self.key[self.offset]
            self.offset = (self.offset + 1) % len(self.key)
        return bytes(out)


def derive_xor_key(raw_key: bytes) -> bytes:
    """Apply the client's in-place cumulative XOR key transformation."""
    if not raw_key:
        raise ProtocolError("handshake key must not be empty")
    derived = bytearray(raw_key)
    for index in range(1, len(derived)):
        derived[index] ^= derived[index - 1]
    return bytes(derived)


def build_frame(command: int, payload: bytes = b"", cursor: XorCursor | None = None) -> bytes:
    """Build one complete frame, advancing cursor over command/header/body."""
    if len(payload) > MAX_FRAME_PAYLOAD:
        raise ProtocolError(f"payload exceeds 65535 bytes: {len(payload)}")
    plain = bytes((command & 0xFF,)) + struct.pack(">H", len(payload)) + payload
    return cursor.crypt(plain) if cursor is not None else plain


def decode_frame_from_bytes(data: bytes, cursor: XorCursor | None = None) -> tuple[int, bytes, int]:
    """Decode one frame from a buffer and return command, payload, consumed bytes."""
    if len(data) < 3:
        raise IncompleteFrame("need at least 3 frame-header bytes")
    header = cursor.crypt(data[:3]) if cursor is not None else data[:3]
    command = header[0] - 256 if header[0] >= 128 else header[0]
    length = struct.unpack(">H", header[1:3])[0]
    total = 3 + length
    if len(data) < total:
        raise IncompleteFrame(f"need full frame of {total} bytes, got {len(data)}")
    body = data[3:total]
    payload = cursor.crypt(body) if cursor is not None else body
    return command, payload, total


async def read_exact(stream: BinaryIO, size: int) -> bytes:
    """Read exactly size bytes from an asyncio StreamReader-like object."""
    value = await stream.readexactly(size)  # type: ignore[attr-defined]
    return value


async def read_frame(stream: BinaryIO, cursor: XorCursor | None = None) -> tuple[int, bytes]:
    """Read and decode exactly one frame from an asyncio stream."""
    raw_header = await read_exact(stream, 3)
    header = cursor.crypt(raw_header) if cursor is not None else raw_header
    command = header[0] - 256 if header[0] >= 128 else header[0]
    length = struct.unpack(">H", header[1:3])[0]
    raw_payload = await read_exact(stream, length)
    payload = cursor.crypt(raw_payload) if cursor is not None else raw_payload
    return command, payload
