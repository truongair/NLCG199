import unittest

from nlcg119_server.codec import (
    PacketReader,
    PacketWriter,
    ProtocolError,
    XorCursor,
    build_frame,
    decode_frame_from_bytes,
    derive_xor_key,
    java_modified_utf8_decode,
    java_modified_utf8_encode,
)


class CodecTests(unittest.TestCase):
    def test_modified_utf_round_trip(self):
        values = ["", "demo", "Xin chào", "a\x00b", "\U0001F600"]
        for value in values:
            with self.subTest(value=value):
                self.assertEqual(java_modified_utf8_decode(java_modified_utf8_encode(value)), value)

    def test_java_primitive_order(self):
        writer = PacketWriter()
        writer.write_byte(-1)
        writer.write_boolean(True)
        writer.write_short(-2)
        writer.write_int(0x10203040)
        writer.write_utf("demo")
        reader = PacketReader(writer.to_bytes())
        self.assertEqual(reader.read_byte(), -1)
        self.assertTrue(reader.read_boolean())
        self.assertEqual(reader.read_short(), -2)
        self.assertEqual(reader.read_int(), 0x10203040)
        self.assertEqual(reader.read_utf(), "demo")
        self.assertEqual(reader.remaining(), 0)

    def test_derived_key(self):
        self.assertEqual(derive_xor_key(bytes([1, 2, 4])), bytes([1, 3, 7]))

    def test_plain_frame(self):
        frame = build_frame(-3, b"abc")
        self.assertEqual(frame[:3], bytes([0xFD, 0, 3]))
        command, payload, consumed = decode_frame_from_bytes(frame)
        self.assertEqual((command, payload, consumed), (-3, b"abc", len(frame)))

    def test_stateful_xor_frame_round_trip(self):
        key = derive_xor_key(b"KEY")
        tx = XorCursor(key)
        rx = XorCursor(key)
        first = build_frame(-1, b"hello", tx)
        second = build_frame(-3, b"world", tx)
        self.assertNotEqual(first, bytes([0xFF, 0, 5]) + b"hello")
        command, payload, consumed = decode_frame_from_bytes(first, rx)
        self.assertEqual((command, payload, consumed), (-1, b"hello", len(first)))
        command, payload, consumed = decode_frame_from_bytes(second, rx)
        self.assertEqual((command, payload, consumed), (-3, b"world", len(second)))

    def test_invalid_utf_continuation(self):
        with self.assertRaises(ProtocolError):
            java_modified_utf8_decode(bytes([0xC2, 0x20]))
