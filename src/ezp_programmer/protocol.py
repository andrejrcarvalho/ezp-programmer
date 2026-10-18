"""Wire protocol of the EZP2010/EZP2012/EZP2013 programmers.

Command layout follows the reverse engineering done in hsorbo/ezp2010.
All multi-byte fields are big-endian. Every command and response travels
over a single pair of bulk endpoints.
"""

from __future__ import annotations

import struct

from .chips import Chip, ChipType

CHUNK = 4096  # bulk transfer size used for data streams

CMD_READ = 0x11
CMD_WRITE = 0x12
CMD_ERASE_POLL = 0x13
CMD_ERASE_START = 0x14
CMD_DETECT = 0x15
CMD_VERSION = 0x17
CMD_SERIAL = 0x18
CMD_SELF_TEST = 0xF3

READ_OK = bytes([CMD_READ, 0x01, 0x00])
WRITE_OK = bytes([CMD_WRITE, 0x01, 0x01])
ERASE_START = bytes([CMD_ERASE_START, 0x01, 0x01])
ERASE_START_OK = bytes([CMD_ERASE_START, 0x01, 0x01])
ERASE_POLL = bytes([CMD_ERASE_POLL, 0x00, 0x01])
ERASE_BUSY = bytes([CMD_ERASE_POLL, 0x01, 0x01])
ERASE_DONE = bytes([CMD_ERASE_POLL, 0x01, 0x00])


class ProtocolError(Exception):
    pass


def read_cmd(chip: Chip) -> bytes:
    return (
        bytes([CMD_READ, 0x0A, chip.chip_type, 0, 0, 0, 0])
        + struct.pack(">IH", chip.size, chip.flags)
        + bytes([1 if chip.is_5v else 0, 0])
    )


def write_cmd(chip: Chip) -> bytes:
    write_flag = chip.write_flag if chip.write_flag is not None else 0x01
    return (
        bytes([CMD_WRITE, 0x0C, chip.chip_type, 0, 0, 0, 0])
        + struct.pack(">IHH", chip.size, write_flag, chip.flags)
        + bytes([1 if chip.is_5v else 0, 0])
    )


def detect_cmd(chip_type: ChipType = ChipType.SPI) -> bytes:
    return bytes([CMD_DETECT, 0x00, chip_type])


def version_cmd() -> bytes:
    return bytes([CMD_VERSION, 0x00])


def serial_cmd() -> bytes:
    return bytes([CMD_SERIAL, 0x00])


def self_test_cmd() -> bytes:
    return bytes([CMD_SELF_TEST, 0x00])


def expect(resp: bytes, ok: bytes, what: str) -> None:
    if bytes(resp[: len(ok)]) != ok:
        raise ProtocolError(f"{what}: unexpected response {bytes(resp).hex(' ')}")


def parse_detect(resp: bytes) -> tuple[int, int]:
    """Return (manufacturer_id, device_id) from a detect response."""
    if len(resp) < 4 or resp[0] != CMD_DETECT or resp[1] != 0x02:
        raise ProtocolError(f"Detect failed: response {bytes(resp).hex(' ')}")
    return resp[2], resp[3]


def _cstr(data: bytes) -> str:
    data = bytes(data).split(b"\x00", 1)[0]
    return data.decode("ascii", errors="replace").strip()


def parse_version(resp: bytes) -> str:
    if len(resp) < 2 or resp[0] != CMD_VERSION:
        raise ProtocolError(f"Version: unexpected response {bytes(resp).hex(' ')}")
    return _cstr(resp[2 : 2 + resp[1]])


def parse_serial(resp: bytes) -> str:
    if len(resp) < 2 or resp[0] != CMD_SERIAL:
        raise ProtocolError(f"Serial: unexpected response {bytes(resp).hex(' ')}")
    # The serial field is 16 bytes, padded with 0xFF.
    return _cstr(bytes(resp[2 : 2 + resp[1]]).rstrip(b"\xff"))
