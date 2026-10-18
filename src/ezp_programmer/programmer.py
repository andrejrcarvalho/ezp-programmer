"""High-level programmer operations built on a Transport."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass

from . import protocol as p
from .chips import Chip, ChipType, find_by_id
from .transport import Transport, TransportError

Progress = Callable[[int, int], None]


class Cancelled(Exception):
    pass


@dataclass
class DetectResult:
    manufacturer_id: int
    device_id: int
    matches: list[Chip]


@dataclass
class VerifyResult:
    mismatches: int
    first_offset: int | None


class Programmer:
    def __init__(self, transport: Transport) -> None:
        self.t = transport
        self.cancel_requested = False

    @property
    def name(self) -> str:
        return self.t.name

    def close(self) -> None:
        self.t.close()

    # -- info -------------------------------------------------------------

    def _query(self, cmd: bytes, size: int = 512) -> bytes:
        self.t.write(cmd)
        return self.t.read(size)

    def version(self) -> str:
        return p.parse_version(self._query(p.version_cmd()))

    def serial(self) -> str:
        return p.parse_serial(self._query(p.serial_cmd()))

    def self_test(self) -> str:
        self.t.write(p.self_test_cmd())
        self.t.read(512)
        time.sleep(0.1)
        return self.t.read(512).decode("ascii", errors="replace").strip("\x00 ")

    def detect(self, chip_type: ChipType = ChipType.SPI) -> DetectResult:
        self.t.write(p.detect_cmd(chip_type))
        time.sleep(0.1)
        man, dev = p.parse_detect(self.t.read(64))
        if man in (0x00, 0xFF) and dev in (0x00, 0xFF):
            raise p.ProtocolError(
                "No chip responded. Check the chip orientation and that it sits firmly in the socket."
            )
        return DetectResult(man, dev, find_by_id(man, dev))

    # -- data -------------------------------------------------------------

    def _check_cancel(self) -> None:
        if self.cancel_requested:
            self.cancel_requested = False
            self._drain()
            raise Cancelled("Operation cancelled")

    def _drain(self) -> None:
        """Discard pending IN data so the next command starts in sync."""
        for _ in range(100_000):
            try:
                if not self.t.read(p.CHUNK, timeout_ms=300):
                    return
            except TransportError:
                return

    def read(self, chip: Chip, progress: Progress | None = None) -> bytes:
        self.t.write(p.read_cmd(chip))
        time.sleep(0.1)
        p.expect(self.t.read(p.CHUNK), p.READ_OK, "Read")
        out = bytearray()
        while len(out) < chip.size:
            chunk = self.t.read(p.CHUNK)
            out += chunk
            if progress:
                progress(min(len(out), chip.size), chip.size)
            if len(chunk) < p.CHUNK:
                break
            self._check_cancel()
        if len(out) != chip.size:
            raise p.ProtocolError(f"Read size mismatch: got {len(out)} bytes, expected {chip.size}")
        return bytes(out)

    def write(self, chip: Chip, data: bytes, progress: Progress | None = None) -> None:
        """Program ``data``; it must already be exactly ``chip.size`` bytes."""
        if len(data) != chip.size:
            raise ValueError(f"Data is {len(data)} bytes, chip is {chip.size} bytes")
        self.t.write(p.write_cmd(chip))
        time.sleep(0.1)
        p.expect(self.t.read(p.CHUNK), p.WRITE_OK, "Write")
        for off in range(0, chip.size, p.CHUNK):
            self.t.write(data[off : off + p.CHUNK])
            if progress:
                progress(min(off + p.CHUNK, chip.size), chip.size)
            # Cancelling mid-write would leave the firmware waiting for data,
            # so a write always runs to completion.

    def erase(self, progress: Progress | None = None) -> None:
        self.t.write(p.ERASE_START)
        p.expect(self.t.read(64), p.ERASE_START_OK, "Erase start")
        while True:
            self.t.write(p.ERASE_POLL)
            resp = self.t.read(64)
            if resp[:3] == p.ERASE_DONE:
                return
            p.expect(resp, p.ERASE_BUSY, "Erase")
            if progress:
                progress(0, 0)  # indeterminate
            time.sleep(0.05)

    def verify(self, chip: Chip, data: bytes, progress: Progress | None = None) -> VerifyResult:
        actual = self.read(chip, progress)
        return compare(actual, data)

    def blank_check(self, chip: Chip, progress: Progress | None = None) -> VerifyResult:
        return self.verify(chip, b"\xff" * chip.size, progress)


def compare(actual: bytes, expected: bytes) -> VerifyResult:
    n = min(len(actual), len(expected))
    mismatches = abs(len(actual) - len(expected))
    first = None if not mismatches else n
    if actual[:n] != expected[:n]:
        for i in range(n):
            if actual[i] != expected[i]:
                mismatches += 1
                if first is None or i < first:
                    first = i
    return VerifyResult(mismatches, first)


def fit_to_chip(data: bytes, chip: Chip) -> bytes:
    """Pad with 0xFF or truncate so the image matches the chip size."""
    if len(data) >= chip.size:
        return bytes(data[: chip.size])
    return bytes(data) + b"\xff" * (chip.size - len(data))
