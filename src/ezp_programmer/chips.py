"""Chip database for the EZP2010/EZP2012/EZP2013 programmer family.

The bundled ``data/chips.json`` comes from the hsorbo/ezp2010 project
(GPL-2.0), which extracted it from the vendor software's database.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import IntEnum
from functools import cache
from importlib import resources


class ChipType(IntEnum):
    """Chip family as the programmer firmware encodes it on the wire."""

    SPI = 0x01
    EE24 = 0x02
    EE25 = 0x03
    EE93 = 0x04

    @property
    def label(self) -> str:
        return {
            ChipType.SPI: "SPI Flash (25xx)",
            ChipType.EE24: "I2C EEPROM (24xx)",
            ChipType.EE25: "SPI EEPROM (25xx)",
            ChipType.EE93: "Microwire EEPROM (93xx)",
        }[self]


# The JSON database uses a zero-based enum (protobuf RomType).
_DB_TYPE = {0: ChipType.SPI, 1: ChipType.EE24, 2: ChipType.EE25, 3: ChipType.EE93}


@dataclass(frozen=True)
class Chip:
    chip_type: ChipType
    name: str
    vendor: str
    size: int
    voltage: int  # tenths of a volt (36 = 3.6 V, 55 = 5.5 V)
    manufacturer_id: int
    device_id: int
    ee93_unk: int
    ee93_bits: int
    write_flag: int | None

    @property
    def is_5v(self) -> bool:
        return self.voltage > 0x28

    @property
    def flags(self) -> int:
        """Per-family configuration word sent with read/write commands."""
        match self.chip_type:
            case ChipType.SPI:
                return 0x0300
            case ChipType.EE24:
                return 0x2400 if self.size > 0x800 else 0x1400
            case ChipType.EE25:
                return 0x1100 if self.size > 0x200 else 0x0100
            case ChipType.EE93:
                hi = (0x10 * self.ee93_unk) | 0x08
                lo = 0x03 if self.ee93_bits == 0x08 else 0x01
                return ((hi & 0xFF) << 8) | lo

    @property
    def voltage_label(self) -> str:
        return "5 V" if self.is_5v else "3.3 V"

    @property
    def has_id(self) -> bool:
        return not (self.manufacturer_id == 0xFF and self.device_id == 0xFF)

    def __str__(self) -> str:
        return f"{self.vendor} {self.name}"


def format_size(n: int) -> str:
    if n >= 1024 * 1024 and n % (1024 * 1024) == 0:
        return f"{n // (1024 * 1024)} MiB"
    if n >= 1024 and n % 1024 == 0:
        return f"{n // 1024} KiB"
    return f"{n} B"


@cache
def load_chips() -> tuple[Chip, ...]:
    raw = json.loads(
        resources.files("ezp_programmer").joinpath("data/chips.json").read_text("utf-8")
    )
    chips = [
        Chip(
            chip_type=_DB_TYPE[e["type"]],
            name=e["device_name"],
            vendor=e["manufacturer_name"],
            size=e["size"],
            voltage=e["voltage"],
            manufacturer_id=e["manufacturer_id"],
            device_id=e["device_id"],
            ee93_unk=e["ee93_unk"],
            ee93_bits=e["ee93_bits"],
            write_flag=e["write_2"] if e["write_1"] else None,
        )
        for e in raw
    ]
    chips.sort(key=lambda c: (c.chip_type, c.vendor.upper(), c.name.upper()))
    return tuple(chips)


def find_by_id(manufacturer_id: int, device_id: int) -> list[Chip]:
    return [
        c
        for c in load_chips()
        if c.chip_type == ChipType.SPI
        and c.manufacturer_id == manufacturer_id
        and c.device_id == device_id
    ]


def find_by_name(name: str) -> Chip | None:
    return next((c for c in load_chips() if c.name == name), None)
