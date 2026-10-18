"""Dump analysis: content signatures, usage map, diffs and hashes (no Qt)."""

from __future__ import annotations

import hashlib
import math
import struct
import zlib
from collections import Counter
from dataclasses import dataclass
from enum import Enum


# ---------------------------------------------------------------- hashes


def hashes(data: bytes) -> dict[str, str]:
    return {
        "CRC32": f"{zlib.crc32(data):08X}",
        "MD5": hashlib.md5(data).hexdigest(),
        "SHA-1": hashlib.sha1(data).hexdigest(),
        "SHA-256": hashlib.sha256(data).hexdigest(),
    }


# ---------------------------------------------------------------- diffs


def diff_ranges(a: bytes, b: bytes, merge_gap: int = 0) -> list[tuple[int, int]]:
    """Half-open ``(start, end)`` ranges where ``a`` and ``b`` differ.

    Bytes past the end of the shorter input count as different. Ranges
    separated by at most ``merge_gap`` equal bytes are merged.
    """
    n = min(len(a), len(b))
    ranges: list[tuple[int, int]] = []
    block = 4096
    for base in range(0, n, block):
        end = min(base + block, n)
        if a[base:end] == b[base:end]:
            continue
        for i in range(base, end):
            if a[i] != b[i]:
                if ranges and i - ranges[-1][1] <= merge_gap:
                    ranges[-1] = (ranges[-1][0], i + 1)
                else:
                    ranges.append((i, i + 1))
    if len(a) != len(b):
        tail = (n, max(len(a), len(b)))
        if ranges and tail[0] - ranges[-1][1] <= merge_gap:
            ranges[-1] = (ranges[-1][0], tail[1])
        else:
            ranges.append(tail)
    return ranges


# ---------------------------------------------------------------- usage map


class Block(Enum):
    EMPTY = "Empty (FF)"
    ZERO = "Zeros (00)"
    TEXT = "Text"
    DATA = "Data / code"
    PACKED = "Compressed / encrypted"


_PRINTABLE = bytes(range(0x20, 0x7F)) + b"\t\n\r"


def _entropy(chunk: bytes) -> float:
    n = len(chunk)
    return -sum(c / n * math.log2(c / n) for c in Counter(chunk).values())


def classify(chunk: bytes) -> Block:
    if not chunk or chunk.count(0xFF) == len(chunk):
        return Block.EMPTY
    if chunk.count(0) == len(chunk):
        return Block.ZERO
    sample = chunk[:4096]
    printable = len(sample) - len(sample.translate(None, _PRINTABLE))
    if printable / len(sample) > 0.9:
        return Block.TEXT
    return Block.PACKED if _entropy(sample) > 7.5 else Block.DATA


def usage_map(data: bytes, blocks: int = 256) -> list[Block]:
    if not data:
        return []
    size = max(1, -(-len(data) // blocks))
    return [classify(data[i : i + size]) for i in range(0, len(data), size)]


# ---------------------------------------------------------------- signatures


@dataclass(frozen=True)
class Finding:
    offset: int
    kind: str
    detail: str = ""
    end: int | None = None  # exclusive, when the extent is known


MAX_PER_KIND = 64


def _find_all(data: bytes, magic: bytes, align: int = 1, limit: int = MAX_PER_KIND):
    found = 0
    i = data.find(magic)
    while i != -1 and found < limit:
        if i % align == 0:
            found += 1
            yield i
        i = data.find(magic, i + 1)


def _cstr(raw: bytes) -> str:
    return raw.split(b"\0", 1)[0].decode("ascii", "replace").strip()


def _intel_descriptor(data: bytes) -> list[Finding]:
    """Intel flash descriptor and its region table (BIOS, ME, GbE…)."""
    for sig_off in (0x10, 0x00):
        if data[sig_off : sig_off + 4] == b"\x5a\xa5\xf0\x0f":
            break
    else:
        return []
    out = [Finding(0, "Intel flash descriptor", "Region table follows")]
    (flmap0,) = struct.unpack_from("<I", data, sig_off + 4)
    frba = ((flmap0 >> 16) & 0xFF) << 4
    names = ["Descriptor", "BIOS", "Intel ME", "GbE (Ethernet)", "Platform data", "Region 5", "Region 6", "Region 7", "EC"]
    for i, name in enumerate(names):
        off = frba + 4 * i
        if off + 4 > len(data):
            break
        (reg,) = struct.unpack_from("<I", data, off)
        base, limit = (reg & 0x7FFF) << 12, ((reg >> 16) & 0x7FFF) << 12 | 0xFFF
        if reg in (0, 0xFFFFFFFF) or limit < base or base >= len(data):
            continue
        out.append(Finding(base, f"Region: {name}", f"{base:#x}–{limit:#x}", min(limit + 1, len(data))))
    return out


def scan(data: bytes) -> list[Finding]:
    """Find well-known firmware structures. Fast: uses bytes.find per magic."""
    data = bytes(data)
    out: list[Finding] = []
    out += _intel_descriptor(data)

    for i in _find_all(data, b"_FVH"):
        fv = i - 0x28
        if fv >= 0 and fv % 8 == 0:
            (length,) = struct.unpack_from("<Q", data, fv + 0x20)
            if 0 < length <= len(data) - fv:
                out.append(Finding(fv, "UEFI firmware volume", f"{length:,} bytes", fv + length))

    for i in _find_all(data, b"\x27\x05\x19\x56", align=4):
        if i + 64 <= len(data):
            size = struct.unpack_from(">I", data, i + 12)[0]
            name = _cstr(data[i + 32 : i + 64])
            if size and i + 64 + size <= len(data) + 64:
                out.append(Finding(i, "U-Boot image (uImage)", f"'{name}', {size:,} bytes", min(i + 64 + size, len(data))))

    for i in _find_all(data, b"\xd0\x0d\xfe\xed", align=4):
        if i + 8 <= len(data):
            size = struct.unpack_from(">I", data, i + 4)[0]
            if 0x40 < size <= len(data) - i:
                out.append(Finding(i, "Device tree / FIT (DTB)", f"{size:,} bytes", i + size))

    for magic, endian in ((b"hsqs", "<"), (b"sqsh", ">")):
        for i in _find_all(data, magic, align=4):
            if i + 48 <= len(data):
                size = struct.unpack_from(endian + "Q", data, i + 40)[0]
                if 0 < size <= len(data) - i:
                    major = struct.unpack_from(endian + "H", data, i + 28)[0]
                    out.append(Finding(i, "SquashFS filesystem", f"v{major}, {size:,} bytes", i + size))

    for i in _find_all(data, b"\x45\x3d\xcd\x28", align=4):
        out.append(Finding(i, "CramFS filesystem"))
    for i in _find_all(data, b"UBI#", align=4, limit=1):
        out.append(Finding(i, "UBI volume", "first erase block"))
    for i in _find_all(data, b"\x85\x19\x03\x20", align=4, limit=1):
        out.append(Finding(i, "JFFS2 filesystem", "first node"))
    for i in _find_all(data, b"HDR0", align=4):
        if i + 8 <= len(data):
            size = struct.unpack_from("<I", data, i + 4)[0]
            if 0 < size <= len(data) - i:
                out.append(Finding(i, "TRX firmware (Broadcom)", f"{size:,} bytes", i + size))
    for i in _find_all(data, b"ANDROID!", align=4):
        out.append(Finding(i, "Android boot image"))
    for i in _find_all(data, b"\x7fELF", align=4):
        out.append(Finding(i, "ELF executable"))
    for i in _find_all(data, b"\x1f\x8b\x08"):
        if i + 10 <= len(data) and data[i + 3] & 0xE0 == 0:
            out.append(Finding(i, "gzip data"))
    for i in _find_all(data, b"\xfd7zXZ\x00"):
        out.append(Finding(i, "xz data"))
    for i in _find_all(data, b"$IBIOSI$", limit=4):
        out.append(Finding(i, "Intel BIOS ID", _cstr(data[i + 8 : i + 8 + 64].replace(b"\0", b""))[:40]))
    for i in _find_all(data, b"U-Boot 20", limit=4):
        out.append(Finding(i, "U-Boot version string", _cstr(data[i : i + 64])))
    for i in _find_all(data, b"Linux version ", limit=4):
        out.append(Finding(i, "Linux kernel version", _cstr(data[i : i + 96])))

    out.sort(key=lambda f: (f.offset, f.kind))
    return out


def summary(data: bytes) -> dict[Block, float]:
    """Share of the image per block class."""
    blocks = usage_map(data, 1024)
    return {k: v / len(blocks) for k, v in Counter(blocks).items()} if blocks else {}
