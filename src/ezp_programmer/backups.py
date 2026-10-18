"""Automatic, timestamped chip backups."""

from __future__ import annotations

import re
import time
import zlib
from pathlib import Path


def default_dir() -> Path:
    return Path.home() / "Documents" / "EZP Programmer" / "backups"


def _safe(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", text).strip("_") or "chip"


def save(data: bytes, chip_name: str, reason: str, folder: Path) -> Path:
    """Write ``data`` as ``<chip>_<timestamp>_<reason>_<crc32>.bin`` in ``folder``."""
    folder.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y-%m-%d_%H%M%S")
    name = f"{_safe(chip_name)}_{stamp}_{_safe(reason)}_{zlib.crc32(data):08X}.bin"
    path = folder / name
    n = 1
    while path.exists():  # two backups in the same second
        n += 1
        path = folder / name.replace(".bin", f"_{n}.bin")
    path.write_bytes(data)
    return path
