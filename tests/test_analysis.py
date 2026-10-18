import hashlib
import struct
import zlib

import pytest

from ezp_programmer import analysis, backups
from ezp_programmer.analysis import Block
from ezp_programmer.widgets import parse_int, parse_pattern


def test_hashes():
    h = analysis.hashes(b"abc")
    assert h["CRC32"] == f"{zlib.crc32(b'abc'):08X}"
    assert h["SHA-256"] == hashlib.sha256(b"abc").hexdigest()
    assert set(h) == {"CRC32", "MD5", "SHA-1", "SHA-256"}


def test_diff_ranges():
    a = bytearray(10000)
    b = bytearray(a)
    b[5] = 1
    b[6] = 1
    b[9000] = 7
    assert analysis.diff_ranges(bytes(a), bytes(b)) == [(5, 7), (9000, 9001)]
    assert analysis.diff_ranges(bytes(a), bytes(a)) == []
    assert analysis.diff_ranges(b"\x00" * 4, b"\x00" * 6) == [(4, 6)]
    assert analysis.diff_ranges(b"\x01\x00\x01", b"\x00\x00\x00", merge_gap=1) == [(0, 3)]


def test_usage_map_classes():
    data = b"\xff" * 4096 + b"\x00" * 4096 + b"hello w\n" * 512
    blocks = analysis.usage_map(data, 3)
    assert blocks[:2] == [Block.EMPTY, Block.ZERO]
    assert blocks[2] == Block.TEXT
    assert analysis.classify(bytes(range(256)) * 16) == Block.PACKED


def _uimage(name: bytes, size: int) -> bytes:
    hdr = bytearray(64)
    hdr[0:4] = b"\x27\x05\x19\x56"
    struct.pack_into(">I", hdr, 12, size)
    hdr[32 : 32 + len(name)] = name
    return bytes(hdr) + b"\xaa" * size


def test_scan_finds_structures():
    img = bytearray(b"\xff" * 0x20000)
    # Intel descriptor: signature at 0x10, FRBA = 0x40, BIOS region 0x10000-0x1FFFF
    img[0x10:0x14] = b"\x5a\xa5\xf0\x0f"
    struct.pack_into("<I", img, 0x14, (0x04 << 16))
    struct.pack_into("<I", img, 0x40, 0x0000_0000)  # descriptor 0x0-0xFFF
    struct.pack_into("<I", img, 0x44, (0x1F << 16) | 0x10)  # BIOS
    up = _uimage(b"Linux-5.4", 0x100)
    img[0x2000 : 0x2000 + len(up)] = up
    sq = bytearray(96)
    sq[0:4] = b"hsqs"
    struct.pack_into("<H", sq, 28, 4)
    struct.pack_into("<Q", sq, 40, 96)
    img[0x8000 : 0x8000 + 96] = sq
    img[0x9000:0x900A] = b"\x1f\x8b\x08\x00\x00\x00\x00\x00\x00\x03"

    found = {(f.offset, f.kind) for f in analysis.scan(bytes(img))}
    assert (0, "Intel flash descriptor") in found
    assert (0x10000, "Region: BIOS") in found
    assert (0x2000, "U-Boot image (uImage)") in found
    assert (0x8000, "SquashFS filesystem") in found
    assert (0x9000, "gzip data") in found
    assert analysis.scan(b"\xff" * 4096) == []


def test_backup_names(tmp_path):
    p1 = backups.save(b"abc", "W25Q64/BV", "read", tmp_path)
    p2 = backups.save(b"abc", "W25Q64/BV", "read", tmp_path)
    assert p1.read_bytes() == b"abc" and p1 != p2
    assert p1.name.startswith("W25Q64_BV_") and p1.name.endswith(f"_read_{zlib.crc32(b'abc'):08X}.bin")


@pytest.mark.parametrize("text,value", [("1000", 0x1000), ("0x20", 0x20), ("#4096", 4096), ("64K", 65536), ("1M", 1 << 20)])
def test_parse_int(text, value):
    assert parse_int(text) == value


def test_parse_pattern():
    assert parse_pattern("55 aa", "Hex") == b"\x55\xaa"
    assert parse_pattern("U-Boot", "Text") == b"U-Boot"
    with pytest.raises(ValueError):
        parse_pattern("5", "Hex")
